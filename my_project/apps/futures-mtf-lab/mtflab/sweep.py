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
import shutil
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


def breakeven_status(points: Sequence[Tuple[float, float]]) -> Tuple[str, Optional[float]]:
    """وضعیت سربه‌سر یک نماد: (`never` | `above` | `cross`, مقدار bps).

    - `never` : حتی با هزینهٔ صفر هم منفی است ⇒ هیچ اجراگذاری نجاتش نمی‌دهد
    - `above` : با **گران‌ترین** هزینهٔ آزمون‌شده هم مثبت است ⇒ سربه‌سرش بالاتر
                از بازهٔ آزمون است، یعنی لبه حاشیهٔ امن دارد
    - `cross` : جایی داخل بازه از صفر می‌گذرد ⇒ عدد دقیق درون‌یابی می‌شود

    تفکیک `above` از `never` حیاتی است: هر دو در نسخهٔ اول `None` می‌شدند و
    گزارش «سربه‌سر روی ۱ از ۲۰ نماد» می‌نوشت، در حالی که ۱۹ نماد **در گران‌ترین
    حالت هم سودده** بودند — پیام دقیقاً برعکسِ واقعیت.
    """
    pts = sorted(points)
    if not pts:
        return "never", None
    be = breakeven_cost(pts)
    if be is not None:
        return "cross", be
    if all(e > 0 for _f, e in pts):
        return "above", None
    return "never", None


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

        status: Dict[str, str] = {}
        crossing: Dict[str, float] = {}
        for sym in data:
            pts = []
            for pol in policies:
                m = results[vid][pol[0]].get(sym) or {}
                if "error" not in m and "expectancy" in m:
                    pts.append((effective_round_trip_bps(pol), m["expectancy"]))
            st_, val = breakeven_status(pts)
            status[sym] = st_
            if val is not None:
                crossing[sym] = val
        ref_rows = [m for m in results[vid]["taker"].values() if "error" not in m]
        summary[vid]["exit_structure"] = exit_structure(ref_rows)
        summary[vid]["breakeven"] = {
            "n": len(crossing),                       # سازگاری با نسخهٔ قبل
            "median_round_trip_bps": (round(st.median(crossing.values()), 3)
                                      if crossing else None),
            "cross": len(crossing),
            "above_max": sum(1 for v in status.values() if v == "above"),
            "never": sum(1 for v in status.values() if v == "never"),
            "max_tested_bps": max((effective_round_trip_bps(pp) for pp in policies),
                                  default=0.0),
            "per_symbol": dict(sorted(status.items())),
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
    """حکم یک نسخه — به ترتیب، سه پرسشِ هزینه:

      ۱) با هزینهٔ صفر سودده است؟ (اگر نه، هیچ اجراگذاری نجاتش نمی‌دهد)
      ۲) با هزینهٔ **فعلی (تیکر)** سودده است؟ (اگر بله، مشکل اجرا نیست)
      ۳) با «TP محدود» سودده می‌شود، در حالی که با تیکر نمی‌شد؟
         (تنها حالتی که ساختنِ اجراگذاری میکر توجیه دارد)

    نسخهٔ اول این تابع فقط PF>1 را می‌دید و در نتیجه وقتی لبه **با هزینهٔ فعلی
    هم زنده** بود، بی‌دلیل می‌نوشت «طرح میکر ارزش ساخت دارد». هزینه بهینه‌سازی
    فقط وقتی ارزش دارد که هزینه **مانع** باشد، نه وقتی فقط سود را کم کند.
    """
    def pf(name):
        m = d.get(name) or {}
        return m.get("median_pf") if m.get("ok") else None

    def ex(name):
        m = d.get(name) or {}
        return m.get("median_expectancy") if m.get("ok") else None

    z, tk, mt, am = pf("zero"), pf("taker"), pf("maker_tp"), pf("all_maker")
    ez, etk, emt = ex("zero"), ex("taker"), ex("maker_tp")
    be = d.get("breakeven") or {}
    if z is None or tk is None:
        return "نامشخص" if lang == "fa" else "unknown"

    # ۱) هیچ لبهٔ ناخالصی نیست
    if z <= 1.0:
        msg = ("❌ **رها کنید** — حتی با هزینهٔ صفر هم PF ≤ ۱ است؛ "
               "مشکل سیگنال است نه اجرا")
        return msg if lang == "fa" else (
            "❌ **Abandon** — PF ≤ 1 even at zero cost; the signal, not "
            "execution, is the problem")

    # ۲) لبه با هزینهٔ فعلی هم زنده است ⇒ هزینه مانع نیست
    if tk > 1.0:
        gain = (emt - etk) / abs(etk) if (etk and emt is not None and etk != 0) else 0.0
        if lang == "fa":
            return (f"✅ **لبه با هزینهٔ فعلی زنده است** (PF {tk} > ۱) — "
                    f"مشکل اجرا **نیست**. سودِ اضافه از میکر: {gain * 100:+.0f}٪ "
                    f"(‏{etk:+.2f}$ → {emt:+.2f}$). پس اجراگذاری را نسازید؛ "
                    f"مسئله «بُرد» نیست، «تکرارپذیری» است")
        return (f"✅ **Edge survives current cost** (PF {tk} > 1) — execution is "
                f"**not** the problem. Maker would add {gain * 100:+.0f}% "
                f"({etk:+.2f}$ → {emt:+.2f}$). Do not build execution; the issue "
                f"is repeatability, not cost")

    # ۳) هزینه مانع است: آیا اجرای محدود نجاتش می‌دهد؟
    if mt is not None and mt > 1.0:
        if lang == "fa":
            return ("✅ **طرح میکر ارزش ساخت دارد** — با هزینهٔ فعلی منفی است ولی "
                    "با TP محدود (واقع‌بینانه) بالای ۱ می‌رود")
        return ("✅ **Maker scheme worth building** — negative at current cost, "
                "but clears 1 with realistic limit-TP exits")

    if be.get("cross"):
        n = be["cross"]
        if lang == "fa":
            return (f"⚠️ **مرزی** — فقط اگر هزینهٔ رفت‌وبرگشت زیر "
                    f"{be['median_round_trip_bps']} bps بیاید سودده می‌شود "
                    f"({n} نماد از {be['of_symbols']})")
        return (f"⚠️ **Borderline** — only profitable with round-trip cost below "
                f"{be['median_round_trip_bps']} bps ({n}/{be['of_symbols']} symbols)")

    if am is not None and am > 1.0:
        if lang == "fa":
            return ("⚠️ **سراب** — فقط با فرضِ غیرواقعیِ «همه سفارش‌ها میکر» بالای ۱ "
                    "می‌رود؛ حد ضرر را نمی‌شود محدود گذاشت")
        return ("⚠️ **Mirage** — only clears 1 under the unrealistic "
                "'everything maker' assumption; stops cannot be limit orders")

    if lang == "fa":
        return "❌ **رها کنید** — با هیچ سطح هزینه‌ای PF بالای ۱ نمی‌رود"
    return "❌ **Abandon** — PF never clears 1 at any cost level"


def _breakeven_block(be: dict, lang: str = "fa") -> str:
    """سه وضعیت سربه‌سر را جدا نشان می‌دهد — نه یک عدد گمراه‌کننده.

    عدد میانه فقط روی نمادهایی معنا دارد که **واقعاً** عبور کرده‌اند. دو دستهٔ
    دیگر باید جدا شمرده شوند، وگرنه «۱ از ۲۰» خوانده می‌شود در حالی که ۱۹ نماد
    در گران‌ترین حالت هم سودده‌اند.
    """
    n, tot = be.get("cross", 0), be.get("of_symbols", 0)
    above, never = be.get("above_max", 0), be.get("never", 0)
    mx = be.get("max_tested_bps", 0.0)
    if not tot:
        return ""
    if lang == "en":
        out = [f"**Break-even:** {above}/{tot} symbols stay profitable even at the "
               f"highest tested cost ({mx} bps) — their break-even is *above* that; "
               f"{never}/{tot} are negative even at **zero** cost."]
        if n:
            out.append(f"{n}/{tot} cross zero inside the range: median "
                       f"**{be['median_round_trip_bps']} bps** round-trip.")
        return "\n\n".join(out) + "\n"
    out = [f"**سربه‌سر:** {above} از {tot} نماد حتی با گران‌ترین هزینهٔ آزمون‌شده "
           f"({mx} bps) هم سودده می‌مانند — سربه‌سرشان *بالاتر* از این بازه است. "
           f"{never} از {tot} حتی با **هزینهٔ صفر** هم منفی‌اند."]
    if n:
        out.append(f"{n} از {tot} داخل بازه از صفر می‌گذرند: میانه "
                   f"**{be['median_round_trip_bps']} bps** رفت‌وبرگشت.")
    return "\n\n".join(out) + "\n"


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
            w(_breakeven_block(be, lang="en"))

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
        w(_breakeven_block(be, lang="fa"))

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
# تحویل فایل به گوشی
# ---------------------------------------------------------------------------
def download_dir() -> Optional[str]:
    """پوشهٔ Download گوشی، اگر در دسترس باشد (Termux)."""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "storage", "downloads"), "/sdcard/Download"):
        if os.path.isdir(cand):
            return cand
    return None


def deliver(paths: Sequence[str], out_dir: str, lang: str = "fa") -> None:
    """فایل‌ها را به Download کپی می‌کند و مسیرشان را صریح چاپ می‌کند.

    چرا داخل پایتون و نه در اسکریپت شل: اسکریپت مسیر خروجی را حدس می‌زد
    (`results/cost_sweep*`)، پس اگر کاربر `--out-dir` می‌داد، کپی بی‌صدا شکست
    می‌خورد. اینجا مسیر واقعیِ همان فایل‌هایی که نوشتیم معلوم است.
    """
    from .autoscan import _t

    dest = download_dir()
    copied = 0
    if dest:
        for p_ in paths:
            try:
                shutil.copy2(p_, dest)
                copied += 1
            except OSError:
                pass
    print("")
    if copied:
        print(_t(f"✅ کپی شد به پوشهٔ Download گوشی: {dest}/",
                 f"✅ copied to the phone Download folder: {dest}/"))
        print(_t("   از همان‌جا در فایل‌منیجر یا چت انتخاب و ارسال کنید.",
                 "   pick them there in your file manager / chat app."))
        return
    print(_t("⚠️  پوشهٔ Download در دسترس نبود — فایل‌ها اینجا هستند:",
             "⚠️  Download folder not accessible — the files are here:"))
    print(f"   {os.path.abspath(out_dir)}/")
    print(_t("   یک‌بار `termux-setup-storage` را بزنید، یا همین حالا کپی کنید:",
             "   run `termux-setup-storage` once, or copy them right now:"))
    print(f"   cp {os.path.abspath(out_dir)}/cost_sweep*.\* ~/storage/downloads/")


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
    p.add_argument("--variants", nargs="+", default=["trend", "base"],
                   help="کدام نسخه‌ها (پیش‌فرض: trend base)")
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
        if be.get("of_symbols"):
            print(_t(f"  ↳ سربه‌سر: {be.get('above_max', 0)}/{be['of_symbols']} نماد "
                     f"حتی با {be.get('max_tested_bps')}bps هم سودده · "
                     f"{be.get('never', 0)} حتی با صفر منفی",
                     f"  -> break-even: {be.get('above_max', 0)}/{be['of_symbols']} "
                     f"profitable even at {be.get('max_tested_bps')}bps · "
                     f"{be.get('never', 0)} negative even at zero"))
        print("  " + verdict(d, lang=a.lang))

    # مسیر **مطلق**: کاربر نباید حدس بزند فایل کجاست. یک‌بار مسیر نسبی چاپ شد
    # و فایل‌ها «تولید نشده» به نظر رسیدند.
    print(f"\n📄 {os.path.abspath(md)}\n🗂 {os.path.abspath(js)}")
    print("=" * 70)
    print(_t("👉 این دو فایل را بفرستید.", "👉 send these two files back."))
    deliver([md, js], a.out_dir, lang=a.lang)
    return 0
