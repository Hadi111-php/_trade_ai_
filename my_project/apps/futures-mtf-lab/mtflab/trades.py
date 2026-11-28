"""برون‌بری معاملات + دو آزمون آماری روی همان فایل.

**چرا این ماژول؟** دو سؤالی که کاربر پرسید (جایگاه قیمت میان قله/دره، و
«بعد از سود، سود را پس می‌گیرند») هر دو به **فهرست معاملات** نیاز دارند — و
`run_variant` آن‌ها را دور می‌ریخت. یک‌بار برون‌بری، بعد چند آزمون، بدون
اجرای دوبارهٔ گران.

خروجی برون‌بری عمداً «کامل ولی کوچک» است: هر معامله فقط فیلدهایی که برای
آزمون لازم است، به‌علاوهٔ یک سری کوچک از تغییرهای ساختار بازار هر نماد
(برای قاعدهٔ «تا وقتی ساختار عوض شود»).
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics as st
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .autoscan import build_layers, variants_for
from .data import tf_to_minutes
from .indicators import market_structure, swings

#: دروازه‌های از پیش قفل‌شده — **قبل** از دیدن نتیجه نوشته شده‌اند.
GATE = {
    # قاعدهٔ «بعد از سود استراحت کن»: بهبود expectancy باید از باند نویز بیرون بزند
    "cluster_gain_min_r": 0.06,
    # ویژگی قله/دره: اختلاف پنجک بالا و پایین باید از این بیشتر باشد
    "quintile_spread_min_r": 0.31,
    # حداقل معامله در هر پنجک تا نتیجه معنا داشته باشد
    "min_trades_per_quintile": 60,
}


# ---------------------------------------------------------------------------
# ۱) برون‌بری
# ---------------------------------------------------------------------------
def _compact(t: dict) -> dict:
    """فقط فیلدهایی که در آزمون لازم است."""
    return {
        "ts": t.get("ts"),
        "dir": t.get("side"),
        "pnl": round(t.get("pnl") or 0.0, 4),
        "r": round(t.get("r_multiple") or 0.0, 4),
        "mfe": round(t.get("mfe_pct") or 0.0, 4),
        "mae": round(t.get("mae_pct") or 0.0, 4),
        "reason": t.get("reason"),
        "mode": t.get("trigger_mode"),
        "bars": t.get("bars_held"),
        "don_pos": (t.get("indicators_entry") or {}).get("don_pos"),
        "regime": t.get("regime_entry"),
        "rsi": (t.get("indicators_entry") or {}).get("rsi"),
        "adx": (t.get("indicators_entry") or {}).get("adx"),
        "win": bool(t.get("is_win")),
    }


def _structure_series(candles: Sequence, k: int) -> List[List[int]]:
    """نقاط تغییر ساختار بازار: [[ts, dir], ...] — فشرده."""
    ms = market_structure(candles, 20)
    out: List[List[int]] = []
    last = 0
    for c, m in zip(candles, ms):
        d = m.get("direction", 0)
        if d != last:
            out.append([c.open_time_ms, d])
            last = d
    return out


def export(data_dir: str, tf: str, tf_filter: str, tf_bias: str,
           variants: Sequence[str], swing_k: int = 3,
           progress: bool = True) -> dict:
    """همهٔ معاملات نسخه‌های خواسته‌شده را روی کش می‌سازد و برمی‌گرداند."""
    from .config import load_config
    from .sweep import load_cached

    data = load_cached(data_dir, tf)
    if not data:
        return {"error": f"no cached {tf} bundles"}
    cfg = load_config(["--data", "synthetic", "--quiet"])
    by_id = {v[0]: v for v in variants_for(tf, tf_filter, tf_bias)}
    picked = [by_id[x] for x in variants if x in by_id]
    if not picked:
        return {"error": f"unknown variants; allowed: {sorted(by_id)}"}

    t0 = time.time()
    symbols: Dict[str, dict] = {}
    total = 0
    for n, (sym, cs) in enumerate(sorted(data.items()), 1):
        if progress:
            print(f"[{n}/{len(data)}] {sym}", flush=True)
        layers = build_layers(cs, tf, tf_filter, tf_bias, bias_enabled=True)
        sw = swings(cs, swing_k)
        entry: Dict[str, list] = {}
        for vid, _label, over in picked:
            c = replace(cfg, verbose=False, forensics=False, run_id="", **over)
            # run_variant آمار می‌دهد نه خودِ معاملات؛ اینجا فهرست معاملات لازم است
            from .engine import run_backtest
            try:
                raw = run_backtest(c, layers)
            except Exception:                                        # noqa: BLE001
                continue
            rows = []
            for t in raw["trades"]:
                row = _compact(t)
                idx = _bar_index(cs, t.get("ts"))
                if idx is not None and idx < len(sw) and sw[idx]["peak"] is not None:
                    row["swing"] = swing_ratio_from(sw[idx], cs[idx].close)
                rows.append(row)
            entry[vid] = rows
            total += len(rows)
        symbols[sym] = {
            "trades": entry,
            "structure": _structure_series(cs, swing_k),
            "bars": len(cs),
            "first_ms": cs[0].open_time_ms,
            "bar_ms": tf_to_minutes(tf) * 60_000,
        }

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "settings": {"tf": tf, "tf_filter": tf_filter, "tf_bias": tf_bias,
                     "variants": [v[0] for v in picked], "swing_k": swing_k,
                     "symbols": sorted(data), "n_trades": total},
        "gate": GATE,
        "symbols": symbols,
    }


def swing_ratio_from(sw: dict, close: float) -> Optional[float]:
    """نسبت جایگاه close میان قله/درهٔ تأییدشده (بدون نگاه به آینده)."""
    peak, trough = sw.get("peak"), sw.get("trough")
    if peak is None or trough is None:
        return None
    span = peak - trough
    if span <= 0:
        return None
    return round((close - trough) / span, 4)


def _bar_index(candles: Sequence, ts) -> Optional[int]:
    """ایندکس کندلی که این معامله در آن بسته شده (با جست‌وجوی دودویی)."""
    if not isinstance(ts, (int, float)) or not candles:
        return None
    lo, hi = 0, len(candles) - 1
    if ts < candles[0].open_time_ms:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if candles[mid].open_time_ms <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------------------
# ۲) آزمون قله/دره — پنجک‌بندی، بدون جست‌وجوی آستانه
# ---------------------------------------------------------------------------
def _mean(xs: Sequence[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def _se(xs: Sequence[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    return round(st.pstdev(xs) / math.sqrt(len(xs)), 4)


def _quintiles(rows: Sequence[dict]) -> List[dict]:
    """۵ گروه بر اساس نسبت؛ جدا محاسبه می‌شود که آستانه جست‌وجو نشود."""
    pts = [(r["swing"], r["r"]) for r in rows
           if r.get("swing") is not None and r.get("r") is not None]
    if len(pts) < 5 * GATE["min_trades_per_quintile"]:
        return []
    pts.sort(key=lambda x: x[0])
    out = []
    n = len(pts)
    for q in range(5):
        seg = pts[q * n // 5:(q + 1) * n // 5]
        if not seg:
            continue
        rs = [x[1] for x in seg]
        out.append({
            "q": q + 1, "n": len(seg),
            "lo": round(seg[0][0], 3), "hi": round(seg[-1][0], 3),
            "mean_r": _mean(rs), "se": _se(rs),
            "win_rate": round(sum(1 for x in rs if x > 0) / len(rs), 4),
        })
    return out


def analysis_peakvalley(trades: Sequence[dict], label: str = "") -> dict:
    """آیا جایگاه قیمت میان قله و دره، نتیجه را پیش‌بینی می‌کند؟

    دو مسیر جدا: `don_pos` (کانال ۲۰ کندلی، همان چیزی که موتور دارد) و
    `swing` (قله/درهٔ تأییدشدهٔ تطبیقی، ایدهٔ کاربر). هر کدام پنجک‌بندی مستقل.
    """
    out: Dict[str, object] = {"label": label, "n": len(trades)}
    for key in ("don_pos", "swing"):
        q = _quintiles([{"swing": t.get(key), "r": t.get("r")} for t in trades])
        out[key] = {"quintiles": q}
        if len(q) >= 2:
            top, bot = q[-1], q[0]
            spread = (top["mean_r"] or 0) - (bot["mean_r"] or 0)
            se = math.sqrt((top["se"] or 0) ** 2 + (bot["se"] or 0) ** 2)
            out[key]["spread_r"] = round(spread, 4)
            out[key]["spread_se"] = round(se, 4)
            out[key]["t"] = round(spread / se, 2) if se else None
            out[key]["monotone"] = _is_monotone([x["mean_r"] for x in q])
            out[key]["passes"] = bool(abs(spread) >= GATE["quintile_spread_min_r"]
                                      and abs(spread / se) >= 2.0) if se else False
    # جدا به‌تفکیک نوع ورود: ویژگی در breakout خودِ سیگنال است
    for mode in ("breakout", "pullback"):
        sub = [t for t in trades if t.get("mode") == mode]
        out[f"mode_{mode}"] = {"n": len(sub),
                               "quintiles": _quintiles(
                                   [{"swing": t.get("swing"), "r": t.get("r")}
                                    for t in sub])}
    return out


def _is_monotone(xs: Sequence[Optional[float]]) -> bool:
    v = [x for x in xs if x is not None]
    if len(v) < 3:
        return False
    up = all(b >= a for a, b in zip(v, v[1:]))
    down = all(b <= a for a, b in zip(v, v[1:]))
    return up or down


# ---------------------------------------------------------------------------
# ۳) آزمون «بعد از سود، استراحت» — قاعدهٔ ترکیبی (N کندل **و** تغییر ساختار)
# ---------------------------------------------------------------------------
def _structure_at(series: Sequence[Sequence[int]], ts: int) -> int:
    d = 0
    for s_ts, s_d in series:
        if s_ts <= ts:
            d = s_d
        else:
            break
    return d


def cluster_sim(symbols: dict, N: int = 4, need_structure: bool = True,
                mode: str = "bars") -> dict:
    """قاعدهٔ استراحت بعد از **برد** روی همان نماد، به دو شکل:

    - `mode="bars"`: تا N کندل بلاک. (روی ۴ ساعته یعنی ۱۶ ساعت)
    - `mode="next"`: معاملهٔ **بعدی** همان نماد را رد کن — عملاً همان «یک مرحله»
      که وقتی فاصلهٔ معاملات هفته‌هاست، معنای واقعی‌تری دارد.

    و `need_structure=True` شرط دوم را اضافه می‌کند: اگر ساختار بازار از زمان
    برد عوض شده باشد، بلاک برداشته می‌شود (هر دو شرط با هم، خواستهٔ کاربر).
    """
    kept, dropped = [], []
    for sym, box in symbols.items():
        bar_ms = box.get("bar_ms") or 1
        struct = box.get("structure") or []
        rows = sorted(box["trades"], key=lambda t: t.get("ts") or 0)
        block_until = -1e18
        block_dir = 0
        skip_next = False
        for t in rows:
            ts = t.get("ts") or 0
            blocked = False
            if mode == "next":
                blocked = skip_next
            elif ts <= block_until:
                blocked = True
            if blocked and need_structure:
                cur = _structure_at(struct, ts)
                if cur != block_dir and cur != 0:
                    blocked = False            # ساختار عوض شد ⇒ آزاد
            (dropped if blocked else kept).append(t)
            skip_next = False
            if t.get("win"):
                if mode == "next":
                    skip_next = True
                else:
                    block_until = max(block_until, ts + N * bar_ms)
                block_dir = _structure_at(struct, ts)
    return {"kept": kept, "dropped": dropped, "N": N, "mode": mode,
            "need_structure": need_structure}


def _bootstrap_gain(symbols: dict, N: int, need_structure: bool,
                    mode: str = "bars", sims: int = 2000, seed: int = 7) -> dict:
    """باند نویز: همان قاعده روی داده‌ای که در آن اثر وجود ندارد.

    روش: برچسب برد/باخت را **درون هر نماد** جابه‌جا می‌کنیم (permutation)،
    پس ترتیب زمانی معاملات می‌ماند ولی «کدام برد بود» تصادفی می‌شود.
    """
    rng = random.Random(seed)
    base = cluster_sim(symbols, N, need_structure, mode)
    obs = (_mean([t["r"] for t in base["kept"]])
           - _mean([t["r"] for b in symbols.values() for t in b["trades"]]))

    gains = []
    for _ in range(sims):
        perm = {}
        for sym, box in symbols.items():
            rows = [dict(t) for t in box["trades"]]
            flags = [t.get("win") for t in rows]
            rng.shuffle(flags)
            for t, f in zip(rows, flags):
                t["win"] = f
            perm[sym] = {**box, "trades": rows}
        sim = cluster_sim(perm, N, need_structure, mode)
        g = (_mean([t["r"] for t in sim["kept"]])
             - _mean([t["r"] for b in symbols.values() for t in b["trades"]]))
        if g is not None:
            gains.append(g)
    gains.sort()
    lo = gains[int(0.025 * len(gains))] if gains else None
    hi = gains[int(0.975 * len(gains))] if gains else None
    return {"observed_gain_r": round(obs, 4) if obs is not None else None,
            "noise_lo": round(lo, 4) if lo is not None else None,
            "noise_hi": round(hi, 4) if hi is not None else None, "sims": len(gains),
            "n_kept": len(base["kept"]), "n_dropped": len(base["dropped"]),
            "passes": bool(obs is not None and hi is not None
                           and obs >= GATE["cluster_gain_min_r"] and obs > hi)}


def flatten_symbols(symbols: dict, variant: Optional[str] = None) -> dict:
    """`{sym: {trades: {vid: [...]}, structure, bars, bar_ms}}` → `{sym: {...}}`
    با یک فهرست تخت از معاملات (یک نسخه یا همه با هم)."""
    out = {}
    for sym, box in symbols.items():
        per = box.get("trades") or {}
        rows = per.get(variant) if variant else [t for v in per.values() for t in v]
        out[sym] = {"trades": rows or [], "structure": box.get("structure") or [],
                    "bars": box.get("bars"), "bar_ms": box.get("bar_ms")}
    return out


#: (N, شرط ساختار, حالت) — از پیش تعیین‌شده
CLUSTER_SETTINGS: Sequence[Tuple[int, bool, str]] = (
    (4, False, "bars"),      # خام: N کندل، بدون شرط ساختار
    (4, True, "bars"),       # N کندل + تغییر ساختار
    (20, True, "bars"),      # پنج کندلِ ۴ساعته (≈۳ روز) + تغییر ساختار
    (1, False, "next"),      # «یک مرحله»: معاملهٔ بعدیِ همان نماد را رد کن
    (1, True, "next"),       # همان + اگر ساختار عوض شد، رد نکن
)


def analysis_cluster(symbols: dict,
                     settings: Sequence[Tuple[int, bool, str]] = CLUSTER_SETTINGS) -> dict:
    out = {"variants": []}
    for N, need_struct, mode in settings:
        r = _bootstrap_gain(symbols, N, need_struct, mode)
        r["need_structure"] = need_struct
        r["mode"] = mode
        if mode == "next":
            r["label"] = "next" + ("+struct" if need_struct else "")
        else:
            r["label"] = f"bars{N}" + ("+struct" if need_struct else "")
        if not r["n_dropped"]:
            r["inert"] = True
        out["variants"].append(r)
    return out


# ---------------------------------------------------------------------------
# ۳.۵) ساختار پاداش: آیا لبه «قرعه‌کشی» است یا جریان؟
# ---------------------------------------------------------------------------
def _events(rows: Sequence[dict], window_days: int = 45) -> int:
    """چند **رویداد مستقل**؟ معاملات بزرگِ هم‌زمان روی چند سکه، یک رویدادند."""
    rows = sorted(rows, key=lambda t: t.get("ts") or 0)
    groups, cur = 0, None
    for t in rows:
        ts = t.get("ts") or 0
        if cur is None or ts - cur > window_days * 86_400_000:
            groups += 1
            cur = ts
    return groups


def analysis_payoff(trades: Sequence[dict], window_days: int = 45) -> dict:
    """کل سود از چند معامله می‌آید؟ و چند «رویداد مستقل» پشت آن است؟

    این مهم‌ترین سنجهٔ ساختاری است و اکثر آزمون‌ها آن را نمی‌بینند: اگر ۸۰٪ سود
    از ۵ معامله بیاید، هر قاعده‌ای که برنده‌ها را کوتاه کند فاجعه است، و هر
    آماره‌ای که «میانگین» را می‌سنجد عملاً چند مشاهده دارد نه هزار تا.
    """
    rs = sorted((t.get("r") or 0.0 for t in trades), reverse=True)
    tot = sum(rs)
    if not rs or tot == 0:
        return {"ok": False}
    n = len(rs)
    top = {str(k): round(sum(rs[:k]), 2) for k in (1, 3, 5, 10, 20) if k <= n}
    # سهم فقط وقتی معنا دارد که مجموع مثبت باشد؛ با مجموع منفی «۱۲۰٪» بی‌معنی است
    share = ({k: round(v / tot, 4) for k, v in top.items()} if tot > 0
             else {k: None for k in top})
    gains = sum(r for r in rs if r > 0)
    top_of_gains = {str(k): (round(sum(rs[:k]) / gains, 4) if gains > 0 else None)
                    for k in (5, 10) if k <= n}
    # مرز «برندهٔ بزرگ»: mfe ≥ ۲۰٪
    big = [t for t in trades if (t.get("mfe") or 0) >= 20]
    horizon = {k: {"n": len(v), "share": round(len(v) / n, 4),
                   "mean_r": round(sum(x["r"] for x in v) / len(v), 3)
                   if v else None}
               for k, v in (("0-2", [t for t in trades if (t.get("mfe") or 0) < 2]),
                            ("2-5", [t for t in trades if 2 <= (t.get("mfe") or 0) < 5]),
                            ("5-10", [t for t in trades if 5 <= (t.get("mfe") or 0) < 10]),
                            ("10-20", [t for t in trades if 10 <= (t.get("mfe") or 0) < 20]),
                            (">20", big))}
    return {
        "ok": True, "n": n, "total_r": round(tot, 2),
        "top_r": top, "top_share": share, "top_of_gains": top_of_gains,
        "median_r": round(st.median(rs), 3), "mean_r": round(sum(rs) / n, 3),
        "big_movers": len(big),
        "big_mover_rate": round(len(big) / n, 4),
        "independent_events_45d": _events(
            sorted([t for t in trades if (t.get("r") or 0) > 0],
                   key=lambda t: -(t.get("r") or 0))[:15],
            window_days),
        "by_horizon": horizon,
        "lottery": bool(tot > 0 and (share.get("5") or 0.0) >= 0.60),
    }


# ---------------------------------------------------------------------------
# ۴) گزارش
# ---------------------------------------------------------------------------
def _arm_label(key: str, fa: bool) -> str:
    """برچسب قاعده را به زبان گزارش برمی‌گرداند."""
    table_fa = {"bars4": "۴ کندل صبر", "bars4+struct": "۴ کندل + تغییر ساختار",
                "bars20+struct": "۲۰ کندل + تغییر ساختار",
                "next": "معاملهٔ بعدی صبر", "next+struct": "معاملهٔ بعدی + تغییر ساختار"}
    table_en = {"bars4": "wait 4 bars", "bars4+struct": "4 bars + structure change",
                "bars20+struct": "20 bars + structure change",
                "next": "skip next trade", "next+struct": "skip next + structure change"}
    return (table_fa if fa else table_en).get(key, key)


def render(res: dict, lang: str = "fa") -> str:
    fa = lang != "en"
    s = res["export"]["settings"]
    L: List[str] = []
    w = L.append

    if fa:
        w("# آزمایش قله/دره و «استراحت بعد از سود»\n")
        w(f"*{res['export']['generated_at']} · {s['n_trades']} معامله · "
          f"{len(s['symbols'])} نماد · نسخه‌های {', '.join(s['variants'])} · "
          f"`{s['tf']}`*\n")
        w("دو آزمون مستقل، هر دو با دروازهٔ **از پیش قفل‌شده**. هیچ آستانه‌ای "
          "جست‌وجو نشده است.\n")
    else:
        w("# Swing position and post-win rest — two tests\n")
        w(f"*{res['export']['generated_at']} · {s['n_trades']} trades · "
          f"{len(s['symbols'])} symbols · {', '.join(s['variants'])} · "
          f"`{s['tf']}`*\n")

    g = res["export"]["gate"]
    # ── آزمون ۱
    pv = res["peakvalley"]
    w("## ۱) جایگاه قیمت میان قله و دره\n" if fa else "## 1) Position between last peak and trough\n")
    if fa:
        w("۰ = روی دره · ۱ = روی قله · بیرون بازه = شکست محدوده.\n")
    for key, name in (("swing", "قله/درهٔ تأییدشده" if fa else "confirmed swings"),
                      ("don_pos", "کانال ۲۰ کندلی" if fa else "20-bar channel")):
        blk = pv.get(key) or {}
        q = blk.get("quintiles") or []
        if not q:
            w(f"- **{name}**: داده کافی نبود (حداقل {g['min_trades_per_quintile']} "
              f"معامله در هر پنجک).\n" if fa else f"- **{name}**: not enough trades.\n")
            continue
        w(f"**{name}**\n")
        w("| پنجک | بازه | معاملات | میانگین R | خطا | نرخ برد |" if fa else
          "| quintile | range | trades | mean R | SE | win rate |")
        w("|---|---|---:|---:|---:|---:|")
        for x in q:
            w(f"| {x['q']} | {x['lo']} … {x['hi']} | {x['n']} | {x['mean_r']:+} | "
              f"{x['se']} | {x['win_rate'] * 100:.0f}% |")
        t = blk.get("t")
        w("")
        verdict = ("✅ **لبه دارد**" if blk.get("passes") else "❌ **لبه ندارد**") if fa \
            else ("✅ **has an edge**" if blk.get("passes") else "❌ **no edge**")
        w((f"اختلاف پنجک ۱ و ۵: **{blk.get('spread_r'):+}R** (t = {t}) · "
           f"یکنوا: {'بله' if blk.get('monotone') else 'نه'} ⇒ {verdict}\n") if fa else
          (f"Top-vs-bottom spread: **{blk.get('spread_r'):+}R** (t = {t}) · "
           f"monotone: {blk.get('monotone')} ⇒ {verdict}\n"))
        if fa:
            w(f"دروازه: |اختلاف| ≥ {g['quintile_spread_min_r']}R **و** |t| ≥ ۲\n")
    for mode in ("breakout", "pullback"):
        blk = pv.get(f"mode_{mode}") or {}
        q = blk.get("quintiles") or []
        if q:
            w((f"- `{mode}` ({blk['n']} معامله): پنجک ۱ = {q[0]['mean_r']:+}R · "
               f"پنجک ۵ = {q[-1]['mean_r']:+}R") if fa else
              (f"- `{mode}` ({blk['n']} trades): Q1 {q[0]['mean_r']:+}R · "
               f"Q5 {q[-1]['mean_r']:+}R"))
    w("")

    # ── ساختار پاداش
    po = res.get("payoff") or {}
    if po.get("ok"):
        w("## ۰) ساختار پاداش — سود از کجا می‌آید؟\n" if fa else
          "## 0) Payoff structure — where does the money come from?\n")
        if fa:
            w(f"میانهٔ R = **{po['median_r']:+.2f}** · میانگین = **{po['mean_r']:+.2f}** "
              f"· برندهٔ بزرگ (حرکت ≥۲۰٪): {po['big_movers']} از {po['n']} "
              f"({po['big_mover_rate'] * 100:.1f}٪)\n")
            if po["top_share"].get("5") is not None:
                w("| چند معاملهٔ بزرگ | جمع R | سهم از کل سود |")
                w("|---|---:|---:|")
                for k, v in po["top_r"].items():
                    w(f"| {k} | {v:+} | **{po['top_share'][k] * 100:.0f}٪** |")
            else:
                w("⚠️ مجموع R منفی است ⇒ «سهم از سود» بی‌معنی می‌شود؛ "
                  "این نسخه در کل بازنده است و ساختار پاداش ارزش خواندن ندارد.")
            w("")
            w(f"این معاملات از **{po['independent_events_45d']} رویداد مستقل** آمده‌اند "
              f"(پنجرهٔ {45} روزه) — یعنی نمونهٔ مؤثر از تعداد معاملات خیلی کمتر است.\n")
            if po.get("lottery"):
                w("⚠️ **ساختار قرعه‌کشی:** بیش از ۶۰٪ سود از ۵ معامله می‌آید. هر "
                  "قاعده‌ای که برنده‌ها را کوتاه کند کل سود را می‌کشد، حتی اگر نرخ "
                  "برد را بالا ببرد.\n")
            w("**پاداش بر حسب اندازهٔ حرکت:**\n")
            w("| حرکت (mfe) | سهم معاملات | میانگین R |")
            w("|---|---:|---:|")
            for k, v in po["by_horizon"].items():
                if v["n"]:
                    w(f"| {k}٪ | {v['share'] * 100:.1f}٪ | {v['mean_r']:+.2f} |")
            w("")
    # ── آزمون ۲
    cl = res["cluster"]
    w("## ۲) استراحت بعد از سود\n" if fa else "## 2) Rest after a win\n")
    if fa:
        w("قاعدهٔ ترکیبی: بعد از هر **برد**، آن نماد تا **N کندل** و **تا تغییر "
          "ساختار بازار** از فهرست بیرون می‌ماند (هر دو شرط باید برطرف شوند).\n")
        w("| قاعده | معاملات مانده | حذف | بهبود expectancy | باند نویز ۹۵٪ | حکم |")
        w("|---|---:|---:|---:|---|---|")
    else:
        w("| rule | kept | dropped | gain | noise band | verdict |")
        w("|---|---:|---:|---:|---|---|")
    for v in cl["variants"]:
        if v.get("inert"):
            ok = "⚪ بی‌اثر (هیچ معامله‌ای حذف نشد)" if fa else "⚪ inert (nothing dropped)"
        elif v["passes"]:
            ok = "✅ **اثر واقعی**" if fa else "✅ **real**"
        else:
            ok = "❌ نویز" if fa else "❌ noise"
        lab = _arm_label(v["label"], fa)
        lo = "—" if v["noise_lo"] is None else f"{v['noise_lo']:+}"
        hi = "—" if v["noise_hi"] is None else f"{v['noise_hi']:+}"
        gain = "—" if v["observed_gain_r"] is None else f"{v['observed_gain_r']:+}"
        w(f"| {lab} | {v['n_kept']} | {v['n_dropped']} | {gain}R | "
          f"[{lo}, {hi}] | {ok} |")
    w("")
    if fa:
        w(f"دروازه: بهبود ≥ **{g['cluster_gain_min_r']}R** **و** بالاتر از باند نویز.\n")
        w("> باند نویز با جابه‌جایی تصادفی برچسب برد/باخت **درون هر نماد** ساخته "
          "شده — ترتیب زمانی حفظ می‌شود، فقط «کدام معامله برد بود» تصادفی می‌شود.\n")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# ۵) CLI
# ---------------------------------------------------------------------------
def lab_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .autoscan import set_lang, _t
    from .sweep import deliver

    p = argparse.ArgumentParser(
        prog="mtflab trade-lab",
        description="برون‌بری معاملات + آزمون قله/دره + آزمون استراحت بعد از سود")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--variants", nargs="+", default=["trend"])
    p.add_argument("--swing-k", type=int, default=3)
    p.add_argument("--sims", type=int, default=600)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--tag", default="")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)
    set_lang(a.lang)

    print("=" * 70)
    print(_t(f"آزمایش معاملات — {a.tf} · نسخه‌های {', '.join(a.variants)}",
             f"trade lab — {a.tf} · variants {', '.join(a.variants)}"))
    print("=" * 70)

    ex = export(a.data_dir, a.tf, a.tf_filter, a.tf_bias, a.variants, a.swing_k)
    if ex.get("error"):
        print(_t(f"❌ {ex['error']}", f"❌ {ex['error']}"))
        return 2

    all_trades = [t for box in ex["symbols"].values()
                  for rows in box["trades"].values() for t in rows]
    pv = analysis_peakvalley(all_trades, label=", ".join(a.variants))
    po = analysis_payoff(all_trades)
    cl = analysis_cluster(flatten_symbols(ex["symbols"],
                                           a.variants[0] if a.variants else None))
    res = {"export": ex, "payoff": po, "peakvalley": pv, "cluster": cl}
    _ = a.sims

    os.makedirs(a.out_dir, exist_ok=True)
    tag = f"_{a.tag}" if a.tag else ""
    paths = {"json": os.path.join(a.out_dir, f"trade_lab{tag}.json"),
             "md": os.path.join(a.out_dir, f"trade_lab{tag}.md"),
             "export": os.path.join(a.out_dir, f"trades_export{tag}.json")}
    with open(paths["json"], "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    with open(paths["md"], "w", encoding="utf-8") as f:
        f.write(render(res, lang=a.lang))
    with open(paths["export"], "w", encoding="utf-8") as f:
        json.dump(ex, f, ensure_ascii=False, separators=(",", ":"))

    print("\n" + "=" * 70)
    if po.get("ok"):
        print(_t(f"  ساختار پاداش: میانه {po['median_r']:+.2f}R · "
                 f"میانگین {po['mean_r']:+.2f}R · "
                 f"۵ معاملهٔ بزرگ = {(po['top_share'].get(5) or 0) * 100:.0f}٪ سود · "
                 f"{po['independent_events_45d']} رویداد مستقل",
                 f"  payoff: median {po['median_r']:+.2f}R · mean {po['mean_r']:+.2f}R "
                 f"· top-5 = {(po['top_share'].get(5) or 0) * 100:.0f}% · "
                 f"{po['independent_events_45d']} independent events"))
        if po.get("lottery"):
            print(_t("  ⚠️ ساختار قرعه‌کشی — کوتاه کردن برنده‌ها فاجعه است",
                     "  ⚠️ lottery profile — cutting winners is fatal"))
    for key, name in (("swing", _t("قله/دره", "swings")),
                      ("don_pos", _t("کانال", "channel"))):
        blk = pv.get(key) or {}
        if blk.get("spread_r") is None:
            print(f"  {name:10s} " + _t("دادهٔ کافی نبود", "not enough data"))
        else:
            print(f"  {name:10s} spread={blk['spread_r']:+7.3f}R "
                  f"t={blk['t']:5.2f} monotone={blk['monotone']} "
                  f"{'✅' if blk['passes'] else '❌'}")
    print("")
    for v in cl["variants"]:
        if v.get("inert"):
            print(f"  {_arm_label(v['label'], a.lang == 'fa'):26s} "
                  + _t("بی‌اثر — هیچ معامله‌ای حذف نشد", "inert — nothing dropped"))
            continue
        print(f"  {_arm_label(v['label'], a.lang == 'fa'):26s} "
              f"kept={v['n_kept']:5d} gain={v['observed_gain_r']:+7.4f}R "
              f"noise=[{v['noise_lo']:+.3f},{v['noise_hi']:+.3f}] "
              f"{'✅' if v['passes'] else '❌'}")

    print(f"\n📄 {os.path.abspath(paths['md'])}\n🗂 {os.path.abspath(paths['json'])}")
    print(_t("👉 هر سه فایل را بفرستید.", "👉 send all three files back."))
    deliver([paths["md"], paths["json"], paths["export"]], a.out_dir, lang=a.lang)
    return 0
