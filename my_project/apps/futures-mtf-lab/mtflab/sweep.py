"""تحلیل حساسیت به هزینه و کیفیت اجرا: آیا هزینه کشنده است یا سیگنال؟

**سؤال:** در اجرای ۴ ساعته، `trend` روی ۲۰ نماد میانهٔ PF ۱.۱۵ داشت و در
۱۵ دقیقه ۰.۸۹. ادعا کردیم «هزینه» علت است. این ماژول آن ادعا را می‌سنجد:

    همان داده، همان سیگنال، فقط سیاست اجرا عوض می‌شود.

چرا این قبل از هر طرح اجرایی دیگری لازم است؟

هر بهبود اجرا (سفارش محدود، کارمزد میکر، صفر کردن اسلیپیج) فقط **یک** کار
می‌کند: هزینهٔ رفت‌وبرگشت را کم می‌کند. پس بالاترین چیزی که می‌تواند به دست
آورد، همان حالت «هزینهٔ صفر» است. اگر با هزینهٔ صفر هم سوددهی نبود، هیچ
اجراگذاری نجاتش نمی‌دهد.

پس این تحلیل یک **حد بالا** است، نه پیش‌بینی. و چون سیاست‌ها روی **همان**
لایه‌ها اجرا می‌شوند (لایه‌ها یک‌بار ساخته می‌شوند)، مقایسه کنترل‌شده است.

سیاست پیش‌فرض «TP با میکر» واقع‌بینانه‌ترین حالت است: در معاملهٔ الگوریتمی
معمولاً ورود و حد ضرر سفارش بازارند (تیکر + اسلیپیج)، ولی حد سود یک سفارش
محدودِ نشسته است (میکر، بدون اسلیپیج). مدل قبلی پروژه هر دو پا را تیکر
می‌گرفت — یعنی **بدبینانه‌تر از واقعیت** بود.
"""
from __future__ import annotations

import json
import os
import statistics as st
import time
from typing import Dict, List, Optional, Sequence, Tuple

#: سیاست‌های اجرا: (کلید، کارمزد تیکر bps، اسلیپیج٪، خروج محدود؟، کارمزد میکر bps)
POLICIES: List[Tuple[str, float, float, bool, float]] = [
    ("taker", 5.5, 0.02, False, 2.0),        # قرارداد فعلی پروژه (مبنا)
    ("taker_noslip", 5.5, 0.0, False, 2.0),  # همان کارمزد، بدون اسلیپیج
    ("maker_tp", 5.5, 0.02, True, 2.0),      # **واقع‌بینانه**: TP با میکر
    ("all_maker", 2.0, 0.0, True, 2.0),      # همهٔ سفارش‌ها میکر (خوش‌بینانه)
    ("zero", 0.0, 0.0, False, 0.0),          # سود ناخالص (حد بالا)
]

#: توضیح فارسی هر سیاست برای گزارش
POLICY_FA = {
    "taker": "تیکر (فعلی)",
    "taker_noslip": "تیکر بی‌اسلیپیج",
    "maker_tp": "TP با میکر ★",
    "all_maker": "همه میکر (خوش‌بینانه)",
    "zero": "صفر (سود ناخالص)",
}


def effective_round_trip_bps(policy: Tuple[str, float, float, bool, float]) -> float:
    """هزینهٔ مؤثر رفت‌وبرگشت روی نوشنال (bps). ورود همیشه بازار فرض می‌شود."""
    _name, fee, slip, limit_exit, maker = policy
    entry = fee + slip * 100.0
    exit_ = maker if limit_exit else fee + slip * 100.0
    return round(entry + exit_, 3)


# ---------------------------------------------------------------------------
# داده
# ---------------------------------------------------------------------------
def load_cached(data_dir: str, tf: str) -> Dict[str, list]:
    """همهٔ بسته‌های `<symbol>_<tf>.json` را می‌خواند (خروجی autoscan)."""
    from .autoscan import candles_from_json

    folder = os.path.join(data_dir, "json")
    out: Dict[str, list] = {}
    if not os.path.isdir(folder):
        return out
    suffix = f"_{tf}.json"
    for name in sorted(os.listdir(folder)):
        if not name.endswith(suffix):
            continue
        sym = name[: -len(suffix)].upper()
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                cs = candles_from_json(json.load(f))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if len(cs) > 100:
            out[sym] = cs
    return out


# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------
def run_policy(cfg, trig: Sequence, tf_trigger: str, tf_filter: str, tf_bias: str,
               policy: Tuple[str, float, float, bool, float],
               variants: Sequence[Tuple[str, str, dict]],
               layers_cache: dict) -> Dict[str, dict]:
    """همهٔ نسخه‌ها را با یک سیاست اجرا روی یک نماد اجرا می‌کند.

    لایه‌ها **یک‌بار** ساخته و دوباره استفاده می‌شوند؛ تنها سیاست اجرا عوض
    می‌شود. این شرط یک مقایسهٔ کنترل‌شده است.
    """
    from dataclasses import replace
    from .autoscan import build_layers, run_variant

    key = (id(trig), tf_trigger, tf_filter, tf_bias)
    layers = layers_cache.get(key)
    if layers is None:
        layers = build_layers(trig, tf_trigger, tf_filter, tf_bias, bias_enabled=True)
        layers_cache[key] = layers

    _name, fee_bps, slippage_pct, limit_exits, maker_bps = policy
    out: Dict[str, dict] = {}
    for vid, _label, over in variants:
        c = replace(cfg, verbose=False, forensics=False, run_id="",
                    fee_bps=fee_bps, slippage_pct=slippage_pct,
                    limit_exits=limit_exits, maker_fee_bps=maker_bps, **over)
        try:
            out[vid] = run_variant(c, layers, {})
        except Exception as e:                                  # noqa: BLE001
            out[vid] = {"error": str(e)[:80]}
    return out


# ---------------------------------------------------------------------------
# سربه‌سر
# ---------------------------------------------------------------------------
def breakeven_cost(points: Sequence[Tuple[float, float]]) -> Optional[float]:
    """هزینه‌ای (bps) که در آن expectancy = 0 می‌شود (درون‌یابی خطی).

    :param points: [(round_trip_bps, expectancy), ...]
    """
    pts = sorted(points)
    for (f0, e0), (f1, e1) in zip(pts, pts[1:]):
        if e0 == 0:
            return f0
        if (e0 > 0) != (e1 > 0):            # عبور از صفر
            if e1 == e0:
                return f0
            return round(f0 + (0 - e0) * (f1 - f0) / (e1 - e0), 3)
    return None


#: دلیل‌های خروجی که می‌توانند «سفارش محدود» باشند (کارمزد میکر، بدون اسلیپیج)
LIMIT_REASONS = ("take_profit", "partial_take")


def limit_fill_share(rows: Sequence[dict]) -> Optional[float]:
    """سهم معاملاتی که خروجشان می‌تواند محدود باشد (۰..۱)."""
    legs = sum(r.get("n_legs", 0) for r in rows)
    if not legs:
        return None
    hits = 0
    for r in rows:
        ex = r.get("exit_reasons") or {}
        hits += sum(int(ex.get(k, 0)) for k in LIMIT_REASONS)
    return round(hits / legs, 4)


def exit_structure(rows: Sequence[dict]) -> Dict[str, float]:
    """توزیع درصدی دلیل خروج روی همهٔ نمادها."""
    tot: Dict[str, int] = {}
    for r in rows:
        for k, v in (r.get("exit_reasons") or {}).items():
            tot[k] = tot.get(k, 0) + int(v)
    n = sum(tot.values())
    if not n:
        return {}
    return {k: round(v * 100.0 / n, 1) for k, v in
            sorted(tot.items(), key=lambda kv: -kv[1])}


# ---------------------------------------------------------------------------
# اجرای کامل
# ---------------------------------------------------------------------------
def sweep(cfg, data: Dict[str, list], tf_trigger: str, tf_filter: str,
          tf_bias: str, variants: Sequence[Tuple[str, str, dict]],
          policies: Sequence[Tuple[str, float, float, bool, float]] = POLICIES,
          progress: bool = True) -> dict:
    t0 = time.time()
    layers_cache: dict = {}
    vids = [v[0] for v in variants]
    names = [p[0] for p in policies]

    results: Dict[str, Dict[str, Dict[str, dict]]] = {
        v: {n: {} for n in names} for v in vids}

    for i, (sym, trig) in enumerate(sorted(data.items()), 1):
        if progress:
            print(f"[{i}/{len(data)}] {sym}", flush=True)
        for pol in policies:
            per = run_policy(cfg, trig, tf_trigger, tf_filter, tf_bias, pol,
                             variants, layers_cache)
            for vid, m in per.items():
                results[vid][pol[0]][sym] = m

    summary: Dict[str, dict] = {}
    for vid in vids:
        summary[vid] = {}
        for pol in policies:
            name = pol[0]
            rows = [m for m in results[vid][name].values() if "error" not in m]
            if not rows:
                summary[vid][name] = {"ok": False}
                continue
            pfs = sorted(r["profit_factor"] for r in rows if r["profit_factor"] is not None)
            exps = [r["expectancy"] for r in rows]
            summary[vid][name] = {
                "ok": True,
                "fee_bps": pol[1], "slippage_pct": pol[2],
                "limit_exits": pol[3], "maker_fee_bps": pol[4],
                "round_trip_bps": effective_round_trip_bps(pol),
                "n_symbols": len(rows),
                "trades": sum(r["n"] for r in rows),
                "median_pf": round(st.median(pfs), 4) if pfs else None,
                "median_expectancy": round(st.median(exps), 4),
                "total_pnl": round(sum(r["pnl"] for r in rows), 2),
                "symbols_pf_above_1": sum(1 for x in pfs if x > 1.0),
                "median_fees_paid": round(st.median([r["total_fees"] for r in rows]), 2),
                "limit_fill_share": limit_fill_share(rows),
            }

        be: Dict[str, float] = {}
        for sym in data:
            pts = []
            for pol in policies:
                m = results[vid][pol[0]].get(sym) or {}
                if "error" not in m and "expectancy" in m:
                    pts.append((effective_round_trip_bps(pol), m["expectancy"]))
            b = breakeven_cost(pts)
            if b is not None:
                be[sym] = b
        ref_rows = [m for m in results[vid]["taker"].values() if "error" not in m]
        summary[vid]["exit_structure"] = exit_structure(ref_rows)
        summary[vid]["breakeven"] = {
            "n": len(be),
            "median_round_trip_bps": round(st.median(be.values()), 3) if be else None,
            "per_symbol": dict(sorted(be.items())),
            "of_symbols": len(data),
        }

    return {
        "version": "1.1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "settings": {
            "tf_trigger": tf_trigger, "tf_filter": tf_filter, "tf_bias": tf_bias,
            "symbols": sorted(data), "n_symbols": len(data),
            "bars_per_symbol": {s: len(c) for s, c in sorted(data.items())},
            "variants": list(vids),
            "policies": [{"name": n, "fee_bps": f, "slippage_pct": sl,
                          "limit_exits": le, "maker_fee_bps": mf,
                          "round_trip_bps": effective_round_trip_bps((n, f, sl, le, mf))}
                         for n, f, sl, le, mf in policies],
        },
        "summary": summary,
        "detail": results,
    }


def verdict(d: dict, lang: str = "fa") -> str:
    """حکم یک نسخه: آیا اصلاً لبه‌ای هست و اجرا می‌تواند نجاتش دهد؟

    سه پرسش، به ترتیب هزینه:
      ۱) با هزینهٔ صفر سودده است؟ (اگر نه، هیچ اجرایی نجاتش نمی‌دهد)
      ۲) با «TP محدود» (واقع‌بینانه) سودده است؟ (اگر بله، طرح میکر ارزش ساخت دارد)
      ۳) فقط با فرضِ غیرواقعیِ «همه میکر» سودده می‌شود؟ (اگر بله، نسازید)
    """
    def pf(name):
        m = d.get(name) or {}
        return m.get("median_pf") if m.get("ok") else None

    z, mt, am, tk = pf("zero"), pf("maker_tp"), pf("all_maker"), pf("taker")
    be = (d.get("breakeven") or {}).get("median_round_trip_bps")
    if z is None:
        return "نامشخص" if lang == "fa" else "unknown"

    if z <= 1.0:
        return ("❌ **رها کنید** — حتی با هزینهٔ صفر هم PF ≤ ۱ است؛ "
                "مشکل سیگنال است نه اجرا" if lang == "fa" else
                "❌ **Abandon** — PF ≤ 1 even at zero cost; the signal, not "
                "execution, is the problem")

    if mt is not None and mt > 1.0:
        return ("✅ **طرح میکر ارزش ساخت دارد** — با TP محدود (واقع‌بینانه) هم "
                "PF > ۱ می‌ماند" if lang == "fa" else
                "✅ **Maker scheme worth building** — PF stays >1 with realistic "
                "limit-TP exits")

    if am is not None and am > 1.0:
        return ("⚠️ **مرزی** — فقط با فرضِ غیرواقعیِ «همه سفارش‌ها میکر» بالای ۱ "
                "می‌رود (حد ضرر را نمی‌شود محدود گذاشت)" if lang == "fa" else
                "⚠️ **Borderline** — only clears 1 under the unrealistic "
                "'everything maker' assumption; stops cannot be limit orders")

    if be is not None:
        return ("❌ **رها کنید** — سربه‌سر در "
                f"{be} bps است، کمتر از کارمزد میکرِ قابل‌دستیابی" if lang == "fa"
                else f"❌ **Abandon** — break-even at {be} bps, below achievable maker cost")

    return ("❌ **رها کنید** — با هیچ سطح هزینه‌ای PF بالای ۱ نمی‌رود" if lang == "fa"
            else "❌ **Abandon** — PF never clears 1 at any cost level")


def _structure_block(d: dict, lang: str = "fa") -> str:
    """«چرا میکر بی‌اثر است» را با داده نشان می‌دهد.

    فقط خروجی‌هایی می‌توانند سفارش محدود باشند که از قبل روی دفتر نشسته‌اند
    (حد سود و برداشت جزئی). حد ضرر و تریلینگ **باید** بازار باشند.
    """
    ex = d.get("exit_structure") or {}
    share = (d.get("taker") or {}).get("limit_fill_share")
    if not ex:
        return ""
    lines = []
    if lang == "en":
        lines.append("**How trades actually exit** (taker policy):")
        lines.append("")
        for k, v in ex.items():
            lines.append(f"- `{k}` — {v}%")
        lines.append("")
        if share is not None:
            lines.append(f"Only **{share * 100:.1f}%** of exits could ever be "
                         f"limit/maker fills (`take_profit`, `partial_take`). "
                         f"The rest are stop/trail/time exits, which are **market "
                         f"orders by nature** — no maker scheme can touch them.\n")
    else:
        lines.append("**معامله‌ها واقعاً چطور بسته می‌شوند** (سیاست تیکر):")
        lines.append("")
        for k, v in ex.items():
            lines.append(f"- `{k}` — {v}٪")
        lines.append("")
        if share is not None:
            lines.append(f"فقط **{share * 100:.1f}٪** خروج‌ها می‌توانند سفارش محدود "
                         f"باشند (`take_profit`, `partial_take`). بقیه حد ضرر/تریلینگ/"
                         f"زمانی‌اند و **ماهیتاً سفارش بازارند** — هیچ طرح میکری "
                         f"به آن‌ها دست نمی‌زند.\n")
            if share < 0.10:
                lines.append("⚠️ **این یعنی ستون «TP با میکر» عملاً همان تیکر است.** "
                             "هر سودی که در «همه میکر» می‌بینید از فرضِ پرشدن حد ضرر "
                             "به‌صورت محدود می‌آید که در بازار واقعی ممکن نیست.\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# گزارش
# ---------------------------------------------------------------------------
def render_report(res: dict, lang: str = "fa") -> str:
    s = res["settings"]
    L: List[str] = []
    w = L.append

    if lang == "en":
        w("# Cost and execution quality — is cost the killer, or the signal?\n")
        w(f"*{res['generated_at']} · runtime {res['elapsed_s']}s · {s['n_symbols']} "
          f"symbols · trigger `{s['tf_trigger']}` / filter `{s['tf_filter']}` / "
          f"bias `{s['tf_bias']}`*\n")
        w("Same data, same signal, **only the execution policy changes**. "
          "`zero` is the upper bound any execution scheme can ever reach.\n")
        w("## Verdict\n")
        for vid in s["variants"]:
            w(f"- `{vid}`: {verdict(res['summary'][vid], lang='en')}")
        w("")
        for vid in s["variants"]:
            d = res["summary"][vid]
            w(f"## Variant `{vid}`\n")
            w("| policy | round-trip bps | trades | median PF | median exp | PF>1 | "
              "total PnL |")
            w("|---|---:|---:|---:|---:|---:|---:|")
            for pol in s["policies"]:
                m = d.get(pol["name"]) or {}
                if not m.get("ok"):
                    continue
                w(f"| `{pol['name']}` | {m['round_trip_bps']} | {m['trades']} | "
                  f"{m['median_pf']} | {m['median_expectancy']:+}$ | "
                  f"{m['symbols_pf_above_1']}/{m['n_symbols']} | {m['total_pnl']:+}$ |")
            be = d.get("breakeven") or {}
            w("")
            if be.get("median_round_trip_bps") is not None:
                if be["n"] * 2 < be["of_symbols"]:
                    w(f"**Break-even exists on only {be['n']}/{be['of_symbols']} "
                      f"symbols** (median {be['median_round_trip_bps']} bps) — most "
                      f"symbols never turn positive at any cost.\n")
                else:
                    w(f"**Break-even cost (median): {be['median_round_trip_bps']} bps "
                      f"round-trip** on {be['n']}/{be['of_symbols']} symbols.\n")
            else:
                w("**Break-even: unreachable** — expectancy stays negative even at "
                  "zero cost, i.e. the signal has no gross edge.\n")
            zero = d.get("zero") or {}
            mk = d.get("maker_tp") or {}
            base = d.get("taker") or {}
            if zero.get("ok"):
                w(f"Gross PF (zero cost) **{zero['median_pf']}** ⇒ "
                  f"{'gross edge EXISTS' if (zero['median_pf'] or 0) > 1 else 'NO gross edge even at zero cost'}.\n")
            if mk.get("ok") and base.get("ok"):
                w(f"Realistic maker-TP vs current taker: median PF "
                  f"{base['median_pf']} → **{mk['median_pf']}** "
                  f"(cost {base['round_trip_bps']} → {mk['round_trip_bps']} bps).\n")
            w(_structure_block(d, lang="en"))
        w("> **Reading this:** if PF at zero cost is not clearly above 1, no execution "
          "improvement can save the strategy. The gap between zero-cost PF and the "
          "current one is the **maximum** any make-order scheme could recover.\n")
        return "\n".join(L) + "\n"

    w("# حساسیت به هزینه و کیفیت اجرا — آیا هزینه کشنده است یا سیگنال؟\n")
    w(f"*{res['generated_at']} · زمان اجرا {res['elapsed_s']} ثانیه · "
      f"{s['n_symbols']} نماد · تریگر `{s['tf_trigger']}` / فیلتر "
      f"`{s['tf_filter']}` / بایاس `{s['tf_bias']}`*\n")
    w("همان داده، همان سیگنال، **فقط سیاست اجرا عوض می‌شود**. سیاست «صفر» "
      "بالاترین چیزی است که هر اجراگذاری می‌تواند به آن برسد — یک **حد بالا**، "
      "نه پیش‌بینی.\n")
    w("## حکم\n")
    for vid in s["variants"]:
        w(f"- `{vid}`: {verdict(res['summary'][vid], lang='fa')}")
    w("")

    for vid in s["variants"]:
        d = res["summary"][vid]
        w(f"## نسخهٔ `{vid}`\n")
        w("| سیاست اجرا | هزینهٔ رفت‌وبرگشت (bps) | معاملات | میانهٔ PF | میانهٔ exp | "
          "PF>1 | جمع PnL |")
        w("|---|---:|---:|---:|---:|---:|---:|")
        for pol in s["policies"]:
            m = d.get(pol["name"]) or {}
            if not m.get("ok"):
                continue
            fa = POLICY_FA.get(pol["name"], pol["name"])
            w(f"| {fa} `{pol['name']}` | {m['round_trip_bps']} | {m['trades']} | "
              f"{m['median_pf']} | {m['median_expectancy']:+}$ | "
              f"{m['symbols_pf_above_1']}/{m['n_symbols']} | {m['total_pnl']:+}$ |")
        be = d.get("breakeven") or {}
        w("")
        if be.get("median_round_trip_bps") is not None:
            if be["n"] * 2 < be["of_symbols"]:
                w(f"**سربه‌سر فقط روی {be['n']} از {be['of_symbols']} نماد وجود دارد** "
                  f"(میانهٔ همان‌ها {be['median_round_trip_bps']} bps). یعنی بیشترِ "
                  f"نمادها با هیچ هزینه‌ای سودده نمی‌شوند.\n")
            else:
                w(f"**هزینهٔ سربه‌سر (میانهٔ نمادها): {be['median_round_trip_bps']} bps "
                  f"رفت‌وبرگشت** — روی {be['n']} از {be['of_symbols']} نماد.\n")
        else:
            w("**سربه‌سر: دست‌نیافتنی** — expectancy حتی با هزینهٔ صفر هم منفی "
              "می‌ماند، یعنی خودِ سیگنال سود ناخالص ندارد.\n")

        zero = d.get("zero") or {}
        mk = d.get("maker_tp") or {}
        base = d.get("taker") or {}
        if zero.get("ok"):
            ok = (zero["median_pf"] or 0) > 1.0
            w(f"با هزینهٔ صفر، میانهٔ PF = **{zero['median_pf']}** ⇒ "
              f"{'سود ناخالص **وجود دارد**' if ok else 'سود ناخالص هم **وجود ندارد**'}.\n")
        if mk.get("ok") and base.get("ok"):
            w(f"«TP با میکر» در برابر «تیکر فعلی»: میانهٔ PF از {base['median_pf']} "
              f"به **{mk['median_pf']}** (هزینه {base['round_trip_bps']} → "
              f"{mk['round_trip_bps']} bps).\n")
        w(_structure_block(d, lang="fa"))

    w("> **چطور بخوانیم:** اگر PF در هزینهٔ صفر هم روشن بالای ۱ نباشد، هیچ بهبود "
      "اجرایی نجاتش نمی‌دهد. فاصلهٔ PF فعلی با PF هزینهٔ صفر، **بیشترین** چیزی "
      "است که یک طرح میکر می‌تواند برگرداند.\n")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def sweep_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .config import load_config
    from .autoscan import variants_for, set_lang, _t

    p = argparse.ArgumentParser(
        prog="mtflab sweep",
        description="حساسیت به هزینه/اجرا روی دادهٔ ذخیره‌شده (بدون دانلود)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h", help="تایم‌فریم تریگر (باید در کش باشد)")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--variants", nargs="+", default=["trend"],
                   help="کدام نسخه‌ها (پیش‌فرض: trend)")
    p.add_argument("--symbols", nargs="+", default=None,
                   help="محدود کردن به چند نماد (برای تست سریع)")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--tag", default="")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)
    set_lang(a.lang)

    data = load_cached(a.data_dir, a.tf)
    if not data:
        print(_t(f"❌ در {a.data_dir}/json هیچ بستهٔ {a.tf} نیست.",
                 f"❌ no cached {a.tf} bundles in {a.data_dir}/json"))
        print(_t("   یک‌بار اسکنر را روی همین تایم‌فریم اجرا کنید.",
                 "   run the scanner once on that timeframe."))
        return 2
    if a.symbols:
        keep = {x.upper() for x in a.symbols}
        data = {k: v for k, v in data.items() if k in keep}
        if not data:
            print(_t("❌ هیچ‌کدام از نمادهای داده‌شده در کش نیست.",
                     "❌ none of the given symbols are cached."))
            return 2

    by_id = {v[0]: v for v in variants_for(a.tf, a.tf_filter, a.tf_bias)}
    variants = [by_id[x] for x in a.variants if x in by_id]
    if not variants:
        print(_t(f"❌ نسخهٔ ناشناخته. مجاز: {', '.join(by_id)}",
                 f"❌ unknown variant. allowed: {', '.join(by_id)}"))
        return 2

    cfg = load_config(["--data", "synthetic", "--quiet"])
    print("=" * 70)
    print(_t(f"تحلیل هزینه — {len(data)} نماد · {a.tf}/{a.tf_filter}/{a.tf_bias} · "
             f"نسخه‌ها: {', '.join(v[0] for v in variants)}",
             f"COST SWEEP — {len(data)} symbols · {a.tf}/{a.tf_filter}/{a.tf_bias} · "
             f"variants: {', '.join(v[0] for v in variants)}"))
    print("=" * 70)

    res = sweep(cfg, data, a.tf, a.tf_filter, a.tf_bias, variants)
    os.makedirs(a.out_dir, exist_ok=True)
    tag = f"_{a.tag}" if a.tag else ""
    md = os.path.join(a.out_dir, f"cost_sweep{tag}.md")
    js = os.path.join(a.out_dir, f"cost_sweep{tag}.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(render_report(res, lang=a.lang))
    with open(js, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)

    print("\n" + "=" * 70)
    for vid in res["settings"]["variants"]:
        d = res["summary"][vid]
        print(f"\n📊 {vid}")
        for pol in res["settings"]["policies"]:
            m = d.get(pol["name"]) or {}
            if not m.get("ok"):
                continue
            print(f"  {pol['name']:14s} rt={m['round_trip_bps']:5.1f}bps "
                  f"trades={m['trades']:5d} medPF={m['median_pf']} "
                  f"exp={m['median_expectancy']:+7.2f}$")
        be = d.get("breakeven") or {}
        if be.get("median_round_trip_bps") is not None:
            print(_t(f"  ↳ سربه‌سر: {be['median_round_trip_bps']} bps رفت‌وبرگشت "
                     f"({be['n']}/{be['of_symbols']} نماد)",
                     f"  -> break-even: {be['median_round_trip_bps']} bps round-trip "
                     f"({be['n']}/{be['of_symbols']} symbols)"))
        else:
            print(_t("  ↳ سربه‌سر: دست‌نیافتنی (حتی با هزینهٔ صفر منفی)",
                     "  -> break-even: unreachable (negative even at zero cost)"))
        print("  " + verdict(d, lang=a.lang))

    print(f"\n📄 {md}\n🗂 {js}")
    print("=" * 70)
    print(_t("👉 این دو فایل را بفرستید.", "👉 send these two files back."))
    return 0
