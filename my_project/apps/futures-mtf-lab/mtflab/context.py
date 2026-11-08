"""پروندهٔ زمینه در لحظهٔ سیگنال — «صحنهٔ جرم» که بعداً مقایسه می‌شود.

## چرا این فایل وجود دارد

پرسش کاربر: «سیستم باید چشم شکارچی باشد؛ بگذار ببینیم در چه موقعیت‌هایی بهتر
شکار می‌کند». پاسخ کد این است: **هر سیگنال، همهٔ ویژگی‌های آن لحظه را با خودش
ثبت کند**، تا بعد بتوان برنده‌ها را از بازنده‌ها روی همان ویژگی‌ها مقایسه کرد
(`mtflab/hunter.py`).

## قاعده‌ای که نمی‌شکنیم

`snapshot()` **فقط** از کندل‌های `[0..i]` می‌خواند. هیچ عددی از آینده در آن نیست.
اگر این قاعده بشکند، هر مقایسه‌ای «کشف» می‌کند که مثلاً «قیمت بعداً بالا رفت
یعنی سیگنال خوب بود» — که خودفریبی است. تست
`test_context_never_looks_ahead` همین را قفل می‌کند.

## چرا این ویژگی‌ها

سه دسته‌اند و هر دسته یک فرضیهٔ متفاوت را ممکن می‌کند:

| دسته | نمونه | فرضیه |
|---|---|---|
| **نوسان** | `atr_pct`, `range_pct`, `volatility_regime` | «فقط وقتی نوسان به‌قدر کافی بزرگ است که کارمزد را بپوشاند» |
| **جهت/قدرت** | `adx`, `ema_slope_pct`, `dist_ema_pct`, `donchian_pos` | «روند در برابر رِنج» |
| **هزینه/زمان** | `cost_to_atr`, `hour_utc`, `weekday`, `recent_streak` | «هزینه نسبت به حرکت»، «ساعت روز»، «خستگی بعد از ضرر» |

`cost_to_atr` را عمداً گذاشتم: نسبت هزینهٔ رفت‌وبرگشت به ATR همان چیزی است که
می‌گوید «این حرکت به‌قدری بزرگ هست که ارزش معامله داشته باشد یا نه». به‌نظر من
محتمل‌ترین نامزد برای یافتن تفاوت بین برد و باخت است.
"""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Sequence

from .data import Candle

#: نسخهٔ اسکیمای زمینه. اگر کلیدی اضافه/حذف شد، این را بالا ببر تا گزارش‌های
#: قدیمی با گزارش‌های تازه قاطی نشوند.
SCHEMA = "mtflab.context.v1"

#: (کلید، برچسب فارسی) — ترتیب همین است که در گزارش می‌آید.
FEATURES: List[tuple] = [
    ("atr_pct", "نوسان (ATR٪ قیمت)"),
    ("range_pct", "دامنهٔ کندل (٪)"),
    ("body_ratio", "بدنه به دامنه"),
    ("close_pos", "جای بسته در دامنه"),
    ("adx", "قدرت روند (ADX)"),
    ("rsi", "RSI"),
    ("vol_z", "حجم غیرعادی (z)"),
    ("ema_slope_pct", "شیب EMA (٪ در ۳ کندل)"),
    ("dist_ema_pct", "فاصله از EMA (٪)"),
    ("donchian_pos", "جایگاه در کانال ۲۰"),
    ("gap_pct", "گپ باز شدن (٪)"),
    ("bars_in_range", "عمر رِنج فعلی (کندل)"),
    ("swing_position", "جایگاه میان قله/دره"),
    ("hour_utc", "ساعت (UTC)"),
    ("weekday", "روز هفته"),
    ("recent_r_mean", "میانگین R سه معاملهٔ اخیر"),
    ("recent_streak", "رشتهٔ برد/باخت اخیر"),
    ("cost_to_atr", "هزینهٔ رفت‌وبرگشت ÷ ATR"),
]

FEATURE_FA: Dict[str, str] = {k: fa for k, fa in FEATURES}

#: ویژگی‌هایی که «بزرگ‌تر بهتر» یا «کوچک‌تر بهتر» نیستند و فقط برای تفکیک‌اند.
NEUTRAL = {"hour_utc", "weekday"}


# ══════════════════════════════════════════════════════════════════════════
#  محاسبه‌های کوچک و مستقل (بدون numpy)
# ══════════════════════════════════════════════════════════════════════════
def _safe(x) -> Optional[float]:
    """NaN/None/بی‌نهایت را None می‌کند تا JSON سالم بماند و آمار خراب نشود."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _ema_last(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _atr(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    trs = []
    for j in range(1, len(candles)):
        h, l = candles[j].high, candles[j].low
        pc = candles[j - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if len(trs) >= period else None


def _rsi(closes: Sequence[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for j in range(1, period + 1):
        d = closes[j] - closes[j - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for j in range(period + 1, len(closes)):
        d = closes[j] - closes[j - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def _adx(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    if len(candles) < period * 2 + 1:
        return None
    plus, minus, trs = [], [], []
    for j in range(1, len(candles)):
        h, l = candles[j].high, candles[j].low
        ph, pl = candles[j - 1].high, candles[j - 1].low
        up, dn = h - ph, pl - l
        plus.append(up if (up > dn and up > 0) else 0.0)
        minus.append(dn if (dn > up and dn > 0) else 0.0)
        pc = candles[j - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def _wilder(vals):
        out = [sum(vals[:period])]
        for v in vals[period:]:
            out.append(out[-1] - out[-1] / period + v)
        return out

    ap, am, at = _wilder(plus), _wilder(minus), _wilder(trs)
    dxs = []
    for p, m, t in zip(ap, am, at):
        if t <= 0:
            continue
        dip, dim = 100.0 * p / t, 100.0 * m / t
        s = dip + dim
        dxs.append(100.0 * abs(dip - dim) / s if s > 0 else 0.0)
    if len(dxs) < period:
        return None
    adx = sum(dxs[:period]) / period
    for d in dxs[period:]:
        adx = (adx * (period - 1) + d) / period
    return adx


def _vol_z(candles: Sequence[Candle], window: int = 50) -> Optional[float]:
    if len(candles) < window + 1:
        return None
    prior = [c.volume for c in candles[-window - 1:-1]]
    mean = sum(prior) / len(prior)
    var = sum((v - mean) ** 2 for v in prior) / len(prior)
    sd = math.sqrt(var)
    if sd <= 0:
        return 0.0
    return (candles[-1].volume - mean) / sd


def _bars_in_range(candles: Sequence[Candle], window: int = 20) -> Optional[float]:
    """چند کندل است قیمت داخل همان کانال ۲۰ کندلی مانده (سقفِ window)."""
    if len(candles) < window + 2:
        return None
    seg = candles[-window - 1:]
    hi = max(c.high for c in seg)
    lo = min(c.low for c in seg)
    if hi <= lo:
        return 0.0
    cnt = 0
    for c in reversed(seg[:-1]):
        if c.high > hi * 1.001 or c.low < lo * 0.999:
            break
        cnt += 1
    return float(min(cnt, window))


def volatility_regime(atr_pct_value: Optional[float],
                      history: Sequence[float]) -> str:
    """رژیم نوسان: «کم / عادی / زیاد» بر اساس چارک‌های **تاریخچهٔ گذشته**.

    چارک‌ها از گذشته گرفته می‌شوند، نه از کل نمونه — وگرنه رژیم امروز با دانستن
    آینده تعیین می‌شد.
    """
    if atr_pct_value is None or len(history) < 30:
        return "نامعلوم"
    s = sorted(history)
    q33 = s[int(len(s) * 0.33)]
    q66 = s[int(len(s) * 0.66)]
    if atr_pct_value <= q33:
        return "کم"
    if atr_pct_value >= q66:
        return "زیاد"
    return "عادی"


# ══════════════════════════════════════════════════════════════════════════
#  ضربهٔ اصلی
# ══════════════════════════════════════════════════════════════════════════
def snapshot(candles: Sequence[Candle], i: int, *,
             swing: Optional[float] = None,
             structure: Optional[int] = None,
             recent_r: Optional[Sequence[float]] = None,
             roundtrip_cost_pct: float = 0.15,
             lookback: int = 250) -> dict:
    """ویژگی‌های کندل `i` — **فقط** از دادهٔ `[0..i]`.

    :param swing: جایگاه میان قله/دره (اگر بیرون حساب شده)
    :param structure: ۱ صعودی / −۱ نزولی / ۰ خنثی
    :param recent_r: R معاملات اخیر (تازه‌ترین آخر) — برای «خستگی بعد از ضرر»
    :param roundtrip_cost_pct: هزینهٔ رفت‌وبرگشت ٪، برای نسبت هزینه به ATR
    :param lookback: چند کندل گذشته به‌عنوان تاریخچه کافی است
    """
    out: dict = {"schema": SCHEMA, "i": int(i)}
    if not candles or i < 0 or i >= len(candles):
        return out
    start = max(0, i - int(lookback) + 1)
    seg = list(candles[start:i + 1])              # شامل خودِ کندل i
    c = seg[-1]
    if c.close <= 0:
        return out

    rng = c.high - c.low
    atr = _atr(seg, 14)
    atr_pct = (atr / c.close * 100.0) if atr else None
    out.update({
        "atr_pct": _round(atr_pct),
        "range_pct": _round(rng / c.close * 100.0 if rng > 0 else None),
        "body_ratio": _round((c.close - c.open) / rng if rng > 0 else None),
        "close_pos": _round((c.close - c.low) / rng if rng > 0 else None),
        "adx": _round(_adx(seg, 14)),
        "rsi": _round(_rsi([x.close for x in seg], 14)),
        "vol_z": _round(_vol_z(seg, 50)),
    })

    closes = [x.close for x in seg]
    ema20 = _ema_last(closes, 20)
    if ema20 and len(closes) >= 23:
        prev_ema = _ema_last(closes[:-3], 20)
        out["ema_slope_pct"] = _round(
            ((ema20 - prev_ema) / prev_ema * 100.0) if prev_ema else None)
        out["dist_ema_pct"] = _round((c.close - ema20) / ema20 * 100.0)
    else:
        out["ema_slope_pct"] = None
        out["dist_ema_pct"] = None

    if len(seg) >= 21:
        win = seg[-21:-1]
        hi = max(x.high for x in win)
        lo = min(x.low for x in win)
        out["donchian_pos"] = _round((c.close - lo) / (hi - lo)
                                     if hi > lo else None)
    else:
        out["donchian_pos"] = None

    if len(seg) >= 2:
        prev = seg[-2].close
        out["gap_pct"] = _round((c.open - prev) / prev * 100.0 if prev else None)
    else:
        out["gap_pct"] = None

    out["bars_in_range"] = _round(_bars_in_range(seg, 20))
    out["swing_position"] = _round(swing)
    out["structure"] = int(structure or 0)
    out["hour_utc"] = time.gmtime(c.open_time_ms / 1000).tm_hour
    out["weekday"] = time.gmtime(c.open_time_ms / 1000).tm_wday

    rr = [float(x) for x in (recent_r or [])]
    out["recent_r_mean"] = _round(sum(rr[-3:]) / len(rr[-3:]) if rr else None)
    streak = 0
    for v in reversed(rr):
        if v == 0:
            break
        if streak == 0:
            streak = 1 if v > 0 else -1
        elif (v > 0) == (streak > 0):
            streak += 1 if v > 0 else -1
        else:
            break
    out["recent_streak"] = streak if rr else None

    # هزینه نسبت به نوسان: اگر ATR کوچک باشد، کارمزد همهٔ حرکت را می‌خورد
    if atr_pct and atr_pct > 0:
        out["cost_to_atr"] = _round(float(roundtrip_cost_pct) / atr_pct)
    else:
        out["cost_to_atr"] = None

    hist = []
    if len(seg) > 40:
        for k in range(30, len(seg)):
            a = _atr(seg[max(0, k - 40):k + 1], 14)
            if a and seg[k].close > 0:
                hist.append(a / seg[k].close * 100.0)
    out["volatility_regime"] = volatility_regime(atr_pct, hist)
    return out


def _round(x, nd: int = 4):
    v = _safe(x)
    return None if v is None else round(v, nd)


def feature_vector(snap: dict, keys: Optional[Sequence[str]] = None) -> Dict[str, float]:
    """فقط عددها را برمی‌گرداند (برای آمار). کلیدهای ناموجود حذف می‌شوند."""
    out: Dict[str, float] = {}
    for k in (keys or [k for k, _ in FEATURES]):
        v = _safe((snap or {}).get(k))
        if v is not None:
            out[k] = v
    return out
