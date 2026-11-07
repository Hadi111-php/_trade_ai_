"""پامپ و دامپ — تشخیص رویداد و اندازه‌گیری صادقانهٔ واکنش قیمت.

**این ماژول عمداً از موتور اتوترید مستقل است.** نه `engine` را import می‌کند، نه
`signals`، نه `live`. دلیلش در `docs/PUMPDUMP_PLAN_FA.md` آمده: مکانیزم این پدیده
با روندکاوی ۴ساعته فرق دارد (انفجار حجم/دامنه در چند دقیقه، ریسک لغزش، تعداد
رویداد کم). استفادهٔ «نیم‌فهم» از موتور ۴ساعته این‌جا فقط گمراهی می‌آورد.

**قرارداد این ماژول (تست دارد):**

۱. **هیچ نگاه به آینده‌ای در تشخیص نیست.** هر سه شرط رویداد فقط از کندل‌های
   `[i-lookback, i]` محاسبه می‌شوند. کندل `i+1` فقط برای *سنجش* نتیجه استفاده
   می‌شود، نه برای تصمیم.
۲. **ورود واقع‌گرایانه.** پیش‌فرض `entry="next_open"` است: سیگنال روی بستهٔ کندل
   `i` صادر می‌شود و پر شدن سفارش روی بازِ کندل `i+1` است. ورود با «بستهٔ همان
   کندل پامپ» یک خیال است (باید قبل از بسته‌شدن آن‌جا بوده باشی) و فقط برای
   مقایسه گزارش می‌شود.
۳. **هزینه همیشه کسر می‌شود** (رفت‌وبرگشت) و حساسیتش با ۳ سطح گزارش می‌شود.
۴. **مقایسه با خط پایه.** اگر همهٔ کندل‌های بازار در ۶ کندل آینده به‌طور میانگین
   +۰.۰۵٪ بدهند، رویدادی که +۰.۰۵٪ می‌دهد «لبه» نیست. پس میانهٔ بازده **همهٔ**
   کندل‌ها در همان بازه هم حساب می‌شود و «اختلاف با خط پایه» گزارش می‌شود.
۵. **شمارش رویداد مستقل، نه خام.** پنج رویداد در یک ساعت یک رویداد است. هم
   خوشه‌بندی درون‌نمادی حساب می‌شود، هم خوشه‌بندی زمانی بین نمادها (همه با هم
   پامپ می‌کنند).

اجرا: `python3 -m mtflab pumpdump [--download --days 365 --tf 15m]`
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Candle, tf_to_minutes

VERSION = "1.0"

#: تعریف یخ‌زدهٔ رویداد — از `docs/PUMPDUMP_PLAN_FA.md` کپی شده. تغییرش = آزمون تازه.
DEFAULTS: Dict[str, object] = {
    "lookback": 50,          # کندل مرجع برای میانگین دامنه/حجم
    "range_mult": 2.5,       # دامنه ≥ ۲.۵× میانگین
    "vol_mult": 3.0,         # حجم ≥ ۳× میانگین
    "close_pos": 0.75,       # بسته در ۲۵٪ بالای دامنه (پامپ) / پایین (دامپ)
    "cluster_gap": 4,        # کندل — رویدادهای نزدیک‌تر، یکی شمرده می‌شوند
    "horizons": (1, 3, 6, 12),
    "primary_horizon": 6,    # از پیش تعیین‌شده؛ بقیه فقط زمینه‌اند
    "cost_frac": 0.0015,     # ۰.۱۵٪ رفت‌وبرگشت
    "cost_grid": (0.0005, 0.0015, 0.0030),
    "entry": "next_open",
    "min_events": 100,       # دروازهٔ ۱
    "min_months_pct": 60.0,  # دروازهٔ ۳
    "min_symbols_pct": 60.0,  # دروازهٔ ۵
}


# ══════════════════════════════════════════════════════════════════════════
#  ابزار آماری (بدون numpy)
# ══════════════════════════════════════════════════════════════════════════
def quantile(xs: Sequence[float], q: float) -> Optional[float]:
    """چارک با درون‌یابی خطی — همان تعریف رایج، بدون numpy."""
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * max(0.0, min(1.0, q))
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def median(xs: Sequence[float]) -> Optional[float]:
    return quantile(xs, 0.5)


def _mean(xs: Sequence[float]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def worst_fraction_mean(xs: Sequence[float], frac: float = 0.05) -> Optional[float]:
    """میانگین بدترین `frac` از نمونه — برای کنترل دنبالهٔ چپ."""
    if not xs:
        return None
    s = sorted(xs)
    k = max(1, int(round(len(s) * frac)))
    return sum(s[:k]) / k


# ══════════════════════════════════════════════════════════════════════════
#  تشخیص رویداد (بدون نگاه به آینده)
# ══════════════════════════════════════════════════════════════════════════
def bar_features(candles: Sequence[Candle], i: int, lookback: int = 50) -> Optional[dict]:
    """ویژگی‌های کندل `i` با مرجعِ `lookback` کندل **قبل از آن**.

    اگر تاریخچه کافی نباشد `None` برمی‌گردد (دورهٔ warmup).
    هیچ عنصری از `i+1` به بعد خوانده نمی‌شود.
    """
    if i < lookback or i >= len(candles):
        return None
    cur = candles[i]
    prior = candles[i - lookback:i]
    if not prior:
        return None
    rng = cur.high - cur.low
    avg_rng = sum(c.high - c.low for c in prior) / len(prior)
    avg_vol = sum(c.volume for c in prior) / len(prior)
    if avg_rng <= 0 or avg_vol <= 0 or rng <= 0:
        return None
    close_pos = (cur.close - cur.low) / rng
    return {
        "i": i, "ts": cur.open_time_ms,
        "range_mult": rng / avg_rng,
        "vol_mult": cur.volume / avg_vol,
        "close_pos": close_pos,
        "ret_pct": (cur.close / cur.open - 1.0) * 100.0 if cur.open else 0.0,
        "range_pct": rng / cur.close * 100.0 if cur.close else 0.0,
    }


def detect(candles: Sequence[Candle], side: Optional[str] = None,
           lookback: int = 50, range_mult: float = 2.5, vol_mult: float = 3.0,
           close_pos: float = 0.75) -> List[dict]:
    """رویدادهای پامپ/دامپ.

    `side`: `"pump"`, `"dump"` یا `None` (هر دو).

    پیاده‌سازی با **جمع تجمعی** (prefix sums) است، نه جمع دوبارهٔ پنجره: روی
    ۳۵ هزار کندلِ یک نماد ۱۵ دقیقه‌ای، نسخهٔ سادهٔ O(n·lookback) روی گوشی چند
    دقیقه طول می‌کشید. این نسخه خطی است و همان نتیجه را می‌دهد (تست دارد).
    """
    out: List[dict] = []
    n = len(candles)
    lb = int(lookback)
    if n <= lb or lb <= 0:
        return out
    want_pump = side in (None, "pump", "up")
    want_dump = side in (None, "dump", "down")

    pre_r = [0.0] * (n + 1)
    pre_v = [0.0] * (n + 1)
    for i in range(n):
        c = candles[i]
        pre_r[i + 1] = pre_r[i] + (c.high - c.low)
        pre_v[i + 1] = pre_v[i] + c.volume

    for i in range(lb, n):
        c = candles[i]
        rng = c.high - c.low
        if rng <= 0:
            continue
        avg_rng = (pre_r[i] - pre_r[i - lb]) / lb
        avg_vol = (pre_v[i] - pre_v[i - lb]) / lb
        if avg_rng <= 0 or avg_vol <= 0 or avg_vol < 0:
            continue
        rm = rng / avg_rng
        if rm < range_mult:
            continue
        vm = c.volume / avg_vol
        if vm < vol_mult:
            continue
        cp = (c.close - c.low) / rng
        if want_pump and cp >= close_pos:
            out.append({"i": i, "ts": c.open_time_ms, "range_mult": rm,
                        "vol_mult": vm, "close_pos": cp,
                        "ret_pct": (c.close / c.open - 1.0) * 100.0 if c.open else 0.0,
                        "range_pct": rng / c.close * 100.0 if c.close else 0.0,
                        "side": "pump"})
        elif want_dump and cp <= (1.0 - close_pos):
            out.append({"i": i, "ts": c.open_time_ms, "range_mult": rm,
                        "vol_mult": vm, "close_pos": cp,
                        "ret_pct": (c.close / c.open - 1.0) * 100.0 if c.open else 0.0,
                        "range_pct": rng / c.close * 100.0 if c.close else 0.0,
                        "side": "dump"})
    return out


# ══════════════════════════════════════════════════════════════════════════
#  بازده (فقط برای سنجش — هرگز برای تصمیم)
# ══════════════════════════════════════════════════════════════════════════
def _prices(candles: Sequence[Candle], i: int, k: int,
            entry: str) -> Optional[Tuple[float, float]]:
    """(قیمت ورود، قیمت خروج) برای افق k — یا None اگر داده کافی نیست."""
    if entry == "close":
        if i + k >= len(candles):
            return None
        return candles[i].close, candles[i + k].close
    # next_open: سیگنال روی بستهٔ i، پر شدن روی بازِ i+1
    if i + 1 >= len(candles) or i + k >= len(candles):
        return None
    return candles[i + 1].open, candles[i + k].close


def net_return(candles: Sequence[Candle], i: int, side: str, k: int,
               cost_frac: float = 0.0015, entry: str = "next_open") -> Optional[float]:
    """بازده خالص (کسری) برای یک رویداد. پامپ = لانگ، دامپ = شورت."""
    pr = _prices(candles, i, k, entry)
    if not pr:
        return None
    e, x = pr
    if e <= 0 or x <= 0:
        return None
    r = (x / e - 1.0) if side == "pump" else (e / x - 1.0)
    return r - cost_frac


def baseline_returns(candles: Sequence[Candle], horizons: Sequence[int],
                     cost_frac: float, entry: str, side: str = "pump",
                     step: int = 1, warmup: int = 50) -> Dict[int, dict]:
    """بازده «همهٔ کندل‌ها» — خط پایه‌ای که هر ادعای لبه باید از آن رد شود.

    `step` فقط برای سریع‌کردن است (هر n کندل یک نمونه)؛ میانه با نمونهٔ بزرگ
    تقریباً همان می‌ماند و گزارش می‌گوید نمونه‌گیری شده است.
    """
    out: Dict[int, dict] = {}
    for k in horizons:
        vals = []
        for i in range(warmup, len(candles) - k - 1, max(1, int(step))):
            r = net_return(candles, i, side, k, cost_frac, entry)
            if r is not None:
                vals.append(r)
        out[k] = {"n": len(vals), "median": median(vals),
                  "mean": _mean(vals)}
    return out


# ══════════════════════════════════════════════════════════════════════════
#  خوشه‌بندی: «چند رویداد مستقل داریم؟»
# ══════════════════════════════════════════════════════════════════════════
def cluster_events(events: List[dict], bar_ms: int, gap_bars: int) -> List[dict]:
    """رویدادها را به خوشه‌های زمانی تبدیل می‌کند و خوشه برمی‌گرداند.

    هر خوشه = رویدادها روی **همان نماد** که فاصله‌شان کمتر از `gap_bars` است.
    خروجی: فهرست خوشه‌ها؛ هر خوشه یک `head` (نخستین رویداد) و تعداد اعضا دارد.
    """
    gap_ms = bar_ms * max(1, int(gap_bars))
    by_sym: Dict[str, List[dict]] = {}
    for e in events:
        by_sym.setdefault(e["symbol"], []).append(e)
    clusters: List[dict] = []
    for sym, evs in by_sym.items():
        evs = sorted(evs, key=lambda x: x["ts"])
        cur: List[dict] = []
        for e in evs:
            if cur and (e["ts"] - cur[-1]["ts"]) <= gap_ms and e["side"] == cur[-1]["side"]:
                cur.append(e)
            else:
                if cur:
                    clusters.append({"symbol": sym, "side": cur[0]["side"],
                                     "head": cur[0], "n": len(cur),
                                     "ts": cur[0]["ts"]})
                cur = [e]
        if cur:
            clusters.append({"symbol": sym, "side": cur[0]["side"],
                             "head": cur[0], "n": len(cur), "ts": cur[0]["ts"]})
    clusters.sort(key=lambda c: c["ts"])
    return clusters


def time_clusters(clusters: List[dict], bar_ms: int, gap_bars: int) -> List[List[dict]]:
    """خوشه‌های هم‌زمان **بین نمادها** (همه با هم پامپ می‌کنند).

    اگر ۱۰ سکه در یک ساعت پامپ شوند، این ۱۰ مشاهدهٔ مستقل نیست.
    """
    gap_ms = bar_ms * max(1, int(gap_bars))
    groups: List[List[dict]] = []
    for c in sorted(clusters, key=lambda x: x["ts"]):
        if groups and (c["ts"] - groups[-1][-1]["ts"]) <= gap_ms:
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


# ══════════════════════════════════════════════════════════════════════════
#  ارزیابی کامل
# ══════════════════════════════════════════════════════════════════════════
def evaluate(universe: Dict[str, Sequence[Candle]], tf: str = "15m",
             **params) -> dict:
    """کل آزمون: تشخیص، خوشه‌بندی، بازده‌ها، خط پایه، تفکیک‌ها، دروازه."""
    p = dict(DEFAULTS)
    p.update({k: v for k, v in params.items() if v is not None})
    horizons = tuple(int(h) for h in p["horizons"])
    primary = int(p["primary_horizon"])
    cost = float(p["cost_frac"])
    entry = str(p["entry"])
    bar_ms = tf_to_minutes(tf) * 60_000
    warnings: List[str] = []

    events: List[dict] = []
    n_bars = 0
    for sym, cs in (universe or {}).items():
        n_bars += len(cs)
        ev = detect(cs, None, int(p["lookback"]), float(p["range_mult"]),
                    float(p["vol_mult"]), float(p["close_pos"]))
        for e in ev:
            e["symbol"] = sym
            events.append(e)
    if not universe:
        warnings.append("هیچ داده‌ای نیست — با --download یا کش JSON اجرا کن.")

    # ── خوشه‌بندی: هم درون نماد، هم بین نمادها ──────────────────────────
    cl = cluster_events(events, bar_ms, int(p["cluster_gap"]))
    tcl = time_clusters(cl, bar_ms, int(p["cluster_gap"]))
    independent = len(tcl)

    # ── بازده هر رویداد (فقط سرآمد خوشه‌های زمانی، تا شمارش دوباره نشود) ─
    heads: List[dict] = [g[0]["head"] for g in tcl]
    per_event: List[dict] = []
    for e in heads:
        cs = universe.get(e["symbol"]) or []
        row = {"symbol": e["symbol"], "side": e["side"], "ts": e["ts"],
               "range_mult": round(e["range_mult"], 3),
               "vol_mult": round(e["vol_mult"], 3),
               "close_pos": round(e["close_pos"], 3), "net": {}}
        for k in horizons:
            r = net_return(cs, int(e["i"]), e["side"], k, cost, entry)
            row["net"][k] = r
        per_event.append(row)

    def _vals(pred, k) -> List[float]:
        return [r["net"][k] for r in per_event
                if pred(r) and r["net"].get(k) is not None]

    # ── جدول افق‌ها + حساسیت هزینه ──────────────────────────────────────
    by_horizon: Dict[int, dict] = {}
    for k in horizons:
        vals = _vals(lambda r: True, k)
        by_horizon[k] = {
            "n": len(vals),
            "median": median(vals),
            "mean": _mean(vals),
            "q10": quantile(vals, 0.10), "q25": quantile(vals, 0.25),
            "q75": quantile(vals, 0.75), "q90": quantile(vals, 0.90),
            "win_rate": (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
            "worst_5pct": worst_fraction_mean(vals, 0.05),
        }
        # بازده ناخالص = بازده گزارش‌شده + هزینهٔ پایه؛ هر هزینهٔ دیگری از همان کم می‌شود
        gross = [r["net"][k] + cost for r in per_event if r["net"].get(k) is not None]
        grid = {}
        for c in p["cost_grid"]:
            net = [g - float(c) for g in gross]
            grid[f"{float(c) * 100:.3f}%"] = {"n": len(net), "median": median(net),
                                              "mean": _mean(net)}
        by_horizon[k]["by_cost"] = grid

    # ── خط پایه: همهٔ کندل‌ها، همان افق و همان هزینه ────────────────────
    base: Dict[int, dict] = {}
    for sym, cs in (universe or {}).items():
        if not cs:
            continue
        step = max(1, len(cs) // 4000)      # نمونه‌گیری برای سرعت
        b = baseline_returns(cs, horizons, cost, entry, "pump", step=step,
                             warmup=int(p["lookback"]))
        for k, d in b.items():
            cur = base.setdefault(k, {"vals": [], "sampled": step})
            if d["median"] is not None:
                cur["vals"].append(d["median"])
    for k in horizons:
        b = base.setdefault(k, {"vals": [], "sampled": 1})
        b["median"] = median(b["vals"]) if b["vals"] else None
        b.pop("vals", None)

    # ── تفکیک ماه و نماد (روی افق اصلی) ────────────────────────────────
    months: Dict[str, List[float]] = {}
    symbols: Dict[str, List[float]] = {}
    for r in per_event:
        v = r["net"].get(primary)
        if v is None:
            continue
        m = time.strftime("%Y-%m", time.gmtime(r["ts"] / 1000))
        months.setdefault(m, []).append(v)
        symbols.setdefault(r["symbol"], []).append(v)
    month_stats = {m: {"n": len(v), "median": median(v)}
                   for m, v in sorted(months.items())}
    symbol_stats = {s: {"n": len(v), "median": median(v)}
                    for s, v in sorted(symbols.items())}
    months_pos = [m for m, d in month_stats.items() if (d["median"] or 0) > 0]
    syms_pos = [s for s, d in symbol_stats.items() if (d["median"] or 0) > 0]

    # ── درون‌نمونه / بیرون‌نمونه (تقسیم زمانی) ──────────────────────────
    stamps = [r["ts"] for r in per_event]
    if stamps:
        t0, t1 = min(stamps), max(stamps)
        cut = t0 + (t1 - t0) * 0.5
    else:
        t0 = t1 = cut = 0
    first = [r["net"][primary] for r in per_event
             if r["ts"] < cut and r["net"].get(primary) is not None]
    second = [r["net"][primary] for r in per_event
              if r["ts"] >= cut and r["net"].get(primary) is not None]

    # ── دروازهٔ ازپیش‌نوشته (شش شرط) ────────────────────────────────────
    prim = by_horizon.get(primary) or {}
    prim_med = prim.get("median")
    cost_stress = ((prim.get("by_cost") or {}).get("0.300%") or {}).get("median")
    checks: List[dict] = []

    def _chk(cid, fa, ok, detail, note="", en=""):
        checks.append({"id": cid, "fa": fa, "en": en or cid, "ok": bool(ok),
                       "detail": detail, "note": note})

    _chk("n_independent", f"رویداد مستقل ≥ {p['min_events']}",
         independent >= int(p["min_events"]),
         f"{independent} خوشهٔ زمانی مستقل (از {len(events)} رویداد خام)",
         en=f"independent events >= {p['min_events']}")
    _chk("median_positive", f"میانهٔ خالص (افق {primary}) > ۰ و با هزینهٔ ۰.۳٪ هم مثبت",
         (prim_med is not None and prim_med > 0
          and cost_stress is not None and cost_stress > 0),
         f"میانه {_pct(prim_med)} · با ۰.۳٪ {_pct(cost_stress)}",
         en=f"net median (h={primary}) > 0, still positive at 0.3% cost")
    mpct = (len(months_pos) / len(month_stats) * 100.0) if month_stats else 0.0
    _chk("months_positive", f"در ≥ {p['min_months_pct']:.0f}٪ ماه‌ها مثبت",
         mpct >= float(p["min_months_pct"]),
         f"{len(months_pos)}/{len(month_stats)} ماه ({mpct:.0f}٪)",
         en=f"positive in >= {p['min_months_pct']:.0f}% of months")
    w5 = prim.get("worst_5pct")
    tail_ok = (w5 is not None and prim_med is not None and prim_med > 0
               and abs(w5) <= 2.0 * prim_med)
    _chk("left_tail", "دنبالهٔ چپ کنترل‌شده (بدترین ۵٪ ≤ ۲× میانه)",
         tail_ok, f"بدترین ۵٪ {_pct(w5)} در برابر میانه {_pct(prim_med)}",
         en="left tail controlled (worst 5% <= 2x median)")
    spct = (len(syms_pos) / len(symbol_stats) * 100.0) if symbol_stats else 0.0
    _chk("symbols_positive", f"در ≥ {p['min_symbols_pct']:.0f}٪ نمادها مثبت",
         spct >= float(p["min_symbols_pct"]),
         f"{len(syms_pos)}/{len(symbol_stats)} نماد ({spct:.0f}٪)",
         en=f"positive in >= {p['min_symbols_pct']:.0f}% of symbols")
    m2 = median(second)
    _chk("out_of_sample", "نیمهٔ دوم داده هم مثبت",
         m2 is not None and m2 > 0, f"نیمهٔ دوم {_pct(m2)} · نیمهٔ اول {_pct(median(first))}",
         en="second half of the data is positive too")

    passed = all(c["ok"] for c in checks)

    # ── تشخیص «افزوده» (سخت‌گیرانه‌تر، بعد از نوشتن نقشه) ───────────────
    base_med = (base.get(primary) or {}).get("median")
    lift = (prim_med - base_med) if (prim_med is not None and base_med is not None) else None

    if len(events) and independent < len(events) * 0.5:
        warnings.append(
            f"خوشه‌بندی شدید: {len(events)} رویداد خام فقط {independent} خوشهٔ مستقل — "
            "شمارش خام، آماری را چند برابر بزرگ‌تر نشان می‌دهد.")
    if lift is not None and lift <= 0 and passed:
        warnings.append("شش شرط پاس شد ولی از خط پایه بهتر نیست — این «روند بازار» است، نه لبهٔ پامپ.")
    if (cost_stress is not None and prim_med is not None and prim_med > 0
            and cost_stress < prim_med * 0.5):
        warnings.append("با هزینهٔ ۰.۳٪ بخش زیادی از سود می‌رود — اسپرد واقعی پامپ را جدی بگیر.")

    return {
        "version": VERSION, "tf": tf,
        "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()},
        "symbols": sorted(universe or {}),
        "bars": {s: len(c) for s, c in (universe or {}).items()},
        "n_bars": n_bars,
        "n_events_raw": len(events),
        "n_clusters_symbol": len(cl),
        "n_independent": independent,
        "span": [t0, t1], "cut_ts": int(cut),
        "events_raw": [{"symbol": e["symbol"], "side": e["side"], "ts": e["ts"],
                        "range_mult": round(e["range_mult"], 3),
                        "vol_mult": round(e["vol_mult"], 3),
                        "close_pos": round(e["close_pos"], 3)} for e in events][:5000],
        "by_horizon": by_horizon,
        "baseline": base,
        "lift_primary": lift,
        "by_month": month_stats,
        "by_symbol": symbol_stats,
        "in_sample": {"n": len(first), "median": median(first)},
        "out_of_sample": {"n": len(second), "median": median(second)},
        "checks": checks, "passed": passed,
        "lift_warning": (None if lift is None or lift > 0 else
                         "از خط پایه بهتر نیست"),
        "warnings": warnings,
        "events_evaluated": per_event,
    }


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:+.3f}%"


# ══════════════════════════════════════════════════════════════════════════
#  گزارش فارسی
# ══════════════════════════════════════════════════════════════════════════
def render(rep: dict, lang: str = "fa") -> str:
    fa = lang != "en"
    p = rep["params"]
    L: List[str] = []
    L.append("# پامپ و دامپ — اندازه‌گیری واکنش قیمت\n" if fa else
             "# Pump & dump — price reaction measurement\n")
    L.append(f"*{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}* · "
             + (f"نسخهٔ {rep['version']}" if fa else f"v{rep['version']}") + "\n")
    L.append("> این گزارش **اندازه‌گیری** است، نه توصیه. تعریف رویداد قبل از دیدن "
             "نتیجه یخ زده و در `docs/PUMPDUMP_PLAN_FA.md` ثبت شده.\n" if fa else
             "> This is a measurement, not advice.\n")

    L.append("## تعریف یخ‌زدهٔ رویداد\n" if fa else "## Frozen definition\n")
    if fa:
        L.append(f"- دامنهٔ کندل ≥ **{p['range_mult']}×** میانگین {p['lookback']} کندل قبل")
        L.append(f"- حجم ≥ **{p['vol_mult']}×** میانگین همان بازه")
        L.append(f"- بسته‌شدن در **{p['close_pos'] * 100:.0f}٪** بالای دامنه (پامپ) یا پایین (دامپ)")
        L.append(f"- ورود واقع‌گرایانه: **{p['entry']}** (سیگنال روی بسته، پر شدن روی بازِ کندل بعد)")
        L.append(f"- هزینهٔ پایه: **{p['cost_frac'] * 100:.3f}٪** رفت‌وبرگشت · افق اصلی: **{p['primary_horizon']} کندل**\n")
    else:
        L.append(f"- bar range >= **{p['range_mult']}x** mean of prior {p['lookback']} bars")
        L.append(f"- volume >= **{p['vol_mult']}x** mean of the same window")
        L.append(f"- close in the **{p['close_pos'] * 100:.0f}%** top (pump) or bottom (dump) of the bar")
        L.append(f"- realistic entry: **{p['entry']}** (signal at close, fill at next open)")
        L.append(f"- base cost: **{p['cost_frac'] * 100:.3f}%** round trip · primary horizon: **{p['primary_horizon']} bars**\n")

    L.append("## داده و شمارش\n" if fa else "## Data\n")
    if fa:
        L.append(f"- نماد: **{len(rep['symbols'])}** · کندل: **{rep['n_bars']:,}** · تایم‌فریم: `{rep['tf']}`")
    else:
        L.append(f"- symbols: **{len(rep['symbols'])}** · bars: **{rep['n_bars']:,}** · tf: `{rep['tf']}`")
    L.append((f"- رویداد خام: **{rep['n_events_raw']}** · خوشهٔ درون‌نمادی: **{rep['n_clusters_symbol']}** "
              f"· **رویداد مستقل (خوشهٔ زمانی): {rep['n_independent']}**") if fa else
             (f"- raw events: **{rep['n_events_raw']}** · symbol clusters: **{rep['n_clusters_symbol']}** "
              f"· **independent (time clusters): {rep['n_independent']}**"))
    if rep["n_events_raw"] and rep["n_independent"] < rep["n_events_raw"]:
        L.append(f"  ⚠️ نسبت خام به مستقل: **{rep['n_events_raw'] / max(1, rep['n_independent']):.1f}×** — "
                 "شمارش خام، آمار را چند برابر بزرگ‌تر نشان می‌دهد." if fa else "")
    L.append("")

    L.append("## بازده خالص به تفکیک افق\n" if fa else "## Net returns by horizon\n")
    L.append("| افق (کندل) | n | میانه خالص | میانگین | چارک ۲۵٪ | چارک ۷۵٪ | نرخ برد | بدترین ۵٪ |"
             if fa else
             "| horizon (bars) | n | median net | mean | q25 | q75 | win rate | worst 5% |")
    L.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, d in sorted(rep["by_horizon"].items(), key=lambda x: int(x[0])):
        wr = "—" if d["win_rate"] is None else f"{d['win_rate'] * 100:.1f}%"
        L.append(f"| {k} | {d['n']} | **{_pct(d['median'])}** | {_pct(d['mean'])} | "
                 f"{_pct(d['q25'])} | {_pct(d['q75'])} | {wr} | "
                 f"{_pct(d['worst_5pct'])} |")
    L.append("")

    L.append("## حساسیت به هزینه (افق اصلی)\n" if fa else "## Cost sensitivity\n")
    L.append("| هزینهٔ رفت‌وبرگشت | میانه خالص | میانگین |" if fa else
             "| round-trip cost | median net | mean |")
    L.append("|---|---:|---:|")
    for c, d in (rep["by_horizon"].get(p["primary_horizon"]) or {}).get("by_cost", {}).items():
        L.append(f"| {c} | **{_pct(d['median'])}** | {_pct(d['mean'])} |")
    L.append("")

    L.append("## مقایسه با خط پایه (همهٔ کندل‌ها)\n" if fa else "## vs baseline\n")
    L.append("| افق | میانهٔ رویداد | میانهٔ خط پایه | اختلاف |" if fa else
             "| horizon | event median | baseline median | diff |")
    L.append("|---:|---:|---:|---:|")
    for k in sorted(rep["by_horizon"], key=lambda x: int(x)):
        b = (rep["baseline"].get(k) or {}).get("median")
        h = rep["by_horizon"][k]["median"]
        diff = (h - b) if (h is not None and b is not None) else None
        L.append(f"| {k} | {_pct(h)} | {_pct(b)} | **{_pct(diff)}** |")
    L.append("")

    L.append("## دروازهٔ ازپیش‌نوشته\n" if fa else "## Pre-declared gate\n")
    L.append("| شرط | نتیجه | جزئیات |" if fa else "| check | result | detail |")
    L.append("|---|---|---|")
    for c in rep["checks"]:
        L.append(f"| {c['fa'] if fa else c.get('en', c['fa'])} | "
                 f"{'✅' if c['ok'] else '❌'} | {c['detail']} |")
    L.append("")
    if rep["passed"]:
        L.append("**نتیجه: ✅ همهٔ شش شرط پاس شد**\n" if fa else "**result: ✅ all six checks passed**\n")
    else:
        L.append("**نتیجه: ❌ پاس نشد**\n" if fa else "**result: ❌ gate failed**\n")

    if rep.get("lift_primary") is not None:
        lift = rep["lift_primary"]
        L.append(f"🔎 اختلاف با خط پایه (افق {p['primary_horizon']}): **{_pct(lift)}** "
                 + ("— یعنی بهتر از «همهٔ کندل‌ها» نیست." if lift <= 0 else "— یعنی بهتر از حالت عادی است.") + "\n")

    if rep["warnings"]:
        L.append("## هشدارها\n" if fa else "## Warnings\n")
        for w in rep["warnings"]:
            L.append(f"- ⚠️ {w}")
        L.append("")

    L.append("## تفکیک ماه (افق اصلی)\n" if fa else "## By month\n")
    ms = rep["by_month"]
    if ms:
        row = []
        for m, d in sorted(ms.items()):
            row.append(f"`{m}` {_pct(d['median'])}")
        L.append(" · ".join(row))
    else:
        L.append("—")
    L.append("")

    L.append("## تفکیک نماد\n" if fa else "## By symbol\n")
    L.append("| نماد | n | میانه خالص |")
    L.append("|---|---:|---:|")
    for s, d in sorted(rep["by_symbol"].items(), key=lambda x: -(x[1]["n"])):
        L.append(f"| {s} | {d['n']} | **{_pct(d['median'])}** |")
    L.append("")

    L.append("## محدودیت‌ها (بخوان قبل از هر نتیجه‌گیری)\n" if fa else "## Limits\n")
    L.append("- ما با کندل بستهٔ ۱۵ دقیقه تصمیم می‌گیریم؛ ربات واقعی سریع‌تر است. "
             "نتیجه **کف** است، نه سقف." if fa else "- bar-close decision only.")
    L.append("- اسپرد در پامپ باز می‌شود؛ هزینهٔ ثابت خوش‌بینانه است. "
             "ستون ۰.۳٪ را جدی بگیر." if fa else "- spread widens during pumps.")
    L.append("- «پامپ» برچسبی **پس‌نگر** است؛ تعریفش باید یخ بماند، وگرنه هر بار "
             "داده را دوباره تفسیر می‌کنیم." if fa else "- post-hoc label.")
    L.append("- انتخاب نمادها بعد از دیدن داده = سوگیری بقا. فهرست باید از قبل ثابت باشد.")
    L.append("")
    return "\n".join(x for x in L if x is not None)


# ══════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════
def pumpdump_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab pumpdump",
        description="پامپ و دامپ: تشخیص رویداد + اندازه‌گیری واکنش (بدون تصمیم)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="15m")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--download", action="store_true", help="اگر کش نبود/قدیمی بود دانلود کن")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--entry", choices=["next_open", "close"], default="next_open")
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--cost", type=float, default=0.0015)
    p.add_argument("--range-mult", type=float, default=2.5)
    p.add_argument("--vol-mult", type=float, default=3.0)
    p.add_argument("--close-pos", type=float, default=0.75)
    p.add_argument("--cluster-gap", type=int, default=4)
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    p.add_argument("--json-only", action="store_true")
    a = p.parse_args(argv)

    from .autoscan import fetch_or_load
    from .live import _default_symbols
    from .desk import load_universe

    syms = a.symbols or _default_symbols()
    universe: Dict[str, List[Candle]] = {}
    if a.download:
        from .autoscan import pick_base_url
        base = pick_base_url(progress=not a.json_only)
        for sym in syms:
            try:
                cs, meta = fetch_or_load(sym, a.tf, a.days, a.data_dir,
                                         base_url=base, refresh=a.refresh,
                                         progress=not a.json_only)
                if cs:
                    universe[sym] = cs
            except Exception as e:                                  # noqa: BLE001
                print(f"⚠️ {sym}: {type(e).__name__}: {str(e)[:80]}")
    else:
        universe = load_universe(a.data_dir, a.tf, syms)
        if not universe:
            print(("❌ دادهٔ کش‌شده در "
                   f"{os.path.join(a.data_dir, 'json')} برای {a.tf} نیست.\n"
                   "   این را بزن:  python3 -m mtflab pumpdump --download --days 180\n"
                   "   (برای دیدن سریع‌تر: --symbols BTCUSDT ETHUSDT SOLUSDT --days 90)")
                  if a.lang != "en" else "❌ no cached data; use --download")
            return 2

    rep = evaluate(universe, a.tf, entry=a.entry, primary_horizon=a.horizon,
                   cost_frac=a.cost, range_mult=a.range_mult, vol_mult=a.vol_mult,
                   close_pos=a.close_pos, cluster_gap=a.cluster_gap)
    os.makedirs(a.out_dir, exist_ok=True)
    js = os.path.join(a.out_dir, "pumpdump_report.json")
    md_path = os.path.join(a.out_dir, "pumpdump_report.md")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    md = render(rep, a.lang)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    if not a.json_only:
        print(md)
        # خلاصهٔ یک‌خطی: اگر کاربر فقط ۱۰ ثانیه وقت داشت، همین کافی است
        prim = rep["by_horizon"].get(a.horizon) or {}
        base = (rep["baseline"].get(a.horizon) or {}).get("median")
        lift = rep.get("lift_primary")
        ok = "✅ پاس" if rep["passed"] else "❌ پاس نشد"
        print("─" * 62)
        print(f"خلاصه: {ok} · رویداد مستقل {rep['n_independent']} · "
              f"میانهٔ خالص {_pct(prim.get('median'))} · "
              f"خط پایه {_pct(base)} · اختلاف {_pct(lift)}")
        print(f"        تعریف یخ‌زده: دامنه ≥{a.range_mult}× + حجم ≥{a.vol_mult}× + "
              f"بسته در {a.close_pos:.0%} دامنه")
        print("─" * 62)
    print(f"📄 {os.path.abspath(md_path)}\n🗂 {os.path.abspath(js)}")
    try:
        from .sweep import deliver
        deliver([md_path, js], a.out_dir, lang=a.lang)
    except Exception as e:                                         # noqa: BLE001
        print(f"⚠️ کپی به Download انجام نشد: {type(e).__name__}")
    return 0
