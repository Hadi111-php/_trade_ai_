"""اندیکاتورهای علی (causal) — همه آرایه‌ها هم‌ایندکس با لیست کندل‌ها.

قاعدهٔ سراسری: مقدار خانهٔ `i` فقط از کندل‌های `<= i` محاسبه می‌شود و تا
پایانِ دورهٔ گرم‌شدن (warmup) مقدار `None` است. هیچ خانه‌ای «حدس» نمی‌زند.

نکتهٔ مهم دربارهٔ Donchian: کانال از `window` کندلِ **قبلی** ساخته می‌شود
(بدون کندل جاری)، وگرنه شرط «شکست کانال» هرگز برقرار نمی‌شد (چون high جاری
همیشه بخشی از max است) — این یک دام رایج است که در docs/pitfalls.md آمده.

فقط کتابخانهٔ استاندارد؛ بدون numpy/pandas.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from .data import Candle

Num = Optional[float]


def _sma(values: Sequence[float], i: int, window: int) -> Num:
    if i + 1 < window:
        return None
    return sum(values[i - window + 1:i + 1]) / window


def ema(values: Sequence[float], period: int) -> List[Num]:
    """EMA با ضریب استاندارد 2/(period+1). تا قبل از `period` مقدار None."""
    out: List[Num] = [None] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> List[Num]:
    """RSI وایلدر (Wilder smoothing) — همان تعریف کلاسیک صرافی‌ها."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def true_range(candles: Sequence[Candle]) -> List[Num]:
    out: List[Num] = [None] * len(candles)
    for i, c in enumerate(candles):
        if i == 0:
            out[i] = c.high - c.low
        else:
            p = candles[i - 1].close
            out[i] = max(c.high - c.low, abs(c.high - p), abs(c.low - p))
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> List[Num]:
    """ATR وایلدر (قیمت مطلق، نه درصد)."""
    trs = true_range(candles)
    n = len(trs)
    out: List[Num] = [None] * n
    if n <= period:
        return out
    out[period - 1] = sum(trs[:period]) / period
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def atr_pct(candles: Sequence[Candle], period: int = 14) -> List[Num]:
    """ATR به‌صورت درصدِ قیمتِ بسته‌شدن (برای مقایسهٔ بین کوین‌ها/تایم‌فریم‌ها)."""
    a = atr(candles, period)
    return [None if (a[i] is None or not candles[i].close) else a[i] / candles[i].close * 100.0
            for i in range(len(a))]


def adx(candles: Sequence[Candle], period: int = 14) -> List[Num]:
    """ADX وایلدر به‌همراه +DI/−DI (خروجی فقط ADX؛ نسخهٔ سه‌تایی در `dmi`)."""
    return [d["adx"] for d in dmi(candles, period)]


def dmi(candles: Sequence[Candle], period: int = 14) -> List[dict]:
    """DMI کامل: {adx, plus_di, minus_di, dx}. همه علی (بدون آینده)."""
    n = len(candles)
    out: List[dict] = [{"adx": None, "plus_di": None, "minus_di": None, "dx": None} for _ in range(n)]
    if n <= period + 1:
        return out
    tr, up, dn = [], [], []
    for i in range(1, n):
        h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        u = h - candles[i - 1].high
        d = candles[i - 1].low - l
        up.append(u if (u > d and u > 0) else 0.0)
        dn.append(d if (d > u and d > 0) else 0.0)

    atr_s = sum(tr[:period])
    up_s = sum(up[:period])
    dn_s = sum(dn[:period])
    dxs: List[float] = []
    for i in range(period, len(tr)):
        if i > period:
            atr_s = atr_s - atr_s / period + tr[i]
            up_s = up_s - up_s / period + up[i]
            dn_s = dn_s - dn_s / period + dn[i]
        pdi = 100.0 * up_s / atr_s if atr_s else 0.0
        mdi = 100.0 * dn_s / atr_s if atr_s else 0.0
        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0
        dxs.append(dx)
        k = i + 1                       # ایندکس در آرایهٔ اصلی (چون tr از 1 شروع شد)
        out[k]["plus_di"], out[k]["minus_di"], out[k]["dx"] = pdi, mdi, dx
        if len(dxs) == period:
            out[k]["adx"] = sum(dxs) / period
        elif len(dxs) > period:
            out[k]["adx"] = (out[k - 1]["adx"] * (period - 1) + dx) / period if out[k - 1]["adx"] is not None else None
    return out


def donchian(candles: Sequence[Candle], window: int = 20,
             include_current: bool = False) -> List[dict]:
    """کانال Donchian.

    `include_current=False` (پیش‌فرض و صحیح برای شکست): کران‌ها از `window`
    کندلِ **قبل از** کندل جاری ساخته می‌شوند → `close > upper` معنادار است.
    خروجی هر خانه: {upper, lower, mid, pos, break_up, break_down}.
    `pos` = موقعیت نسبی close درون کانال (0=کف، 1=سقف).
    """
    n = len(candles)
    out: List[dict] = [{"upper": None, "lower": None, "mid": None, "pos": None,
                        "break_up": False, "break_down": False} for _ in range(n)]
    need = window + (0 if include_current else 1)
    for i in range(n):
        if i + 1 < need:
            continue
        end = i + 1 if include_current else i
        start = end - window
        seg = candles[start:end]
        if not seg:
            continue
        up = max(c.high for c in seg)
        lo = min(c.low for c in seg)
        mid = (up + lo) / 2
        c = candles[i].close
        pos = (c - lo) / (up - lo) if up > lo else 0.5
        out[i] = {"upper": up, "lower": lo, "mid": mid, "pos": pos,
                  "break_up": c > up, "break_down": c < lo}
    return out


def _rolling_mean_std(values: Sequence[float], i: int, window: int):
    if i + 1 < window:
        return None, None
    seg = values[i - window + 1:i + 1]
    m = sum(seg) / window
    var = sum((x - m) ** 2 for x in seg) / window
    return m, var ** 0.5


def bollinger(closes: Sequence[float], window: int = 20, k: float = 2.0) -> List[dict]:
    """بولینگر: {mid, upper, lower, pos, width}. width = (upper-lower)/mid."""
    n = len(closes)
    out: List[dict] = [{"mid": None, "upper": None, "lower": None,
                        "pos": None, "width": None} for _ in range(n)]
    for i in range(n):
        m, sd = _rolling_mean_std(closes, i, window)
        if m is None or sd is None:
            continue
        up, lo = m + k * sd, m - k * sd
        c = closes[i]
        pos = (c - lo) / (up - lo) if up > lo else 0.5
        out[i] = {"mid": m, "upper": up, "lower": lo, "pos": pos,
                  "width": (up - lo) / m if m else 0.0}
    return out


def volume_z(candles: Sequence[Candle], window: int = 50) -> List[Num]:
    """z-score حجم نسبت به `window` کندلِ قبلی (بدون کندل جاری → ضد خودشکوفایی)."""
    n = len(candles)
    out: List[Num] = [None] * n
    vols = [c.volume for c in candles]
    for i in range(n):
        if i < window:
            continue
        seg = vols[i - window:i]          # عمداً بدون vols[i]
        m = sum(seg) / window
        var = sum((x - m) ** 2 for x in seg) / window
        sd = var ** 0.5
        out[i] = (vols[i] - m) / sd if sd > 0 else 0.0
    return out


def volume_ratio(candles: Sequence[Candle], window: int = 50) -> List[Num]:
    """نسبت حجم جاری به میانگین `window` کندلِ قبلی."""
    n = len(candles)
    out: List[Num] = [None] * n
    vols = [c.volume for c in candles]
    for i in range(n):
        if i < window:
            continue
        m = sum(vols[i - window:i]) / window
        out[i] = vols[i] / m if m > 0 else 0.0
    return out


def slope_pct(values: Sequence[Num], bars: int = 3) -> List[Num]:
    """شیب درصدی نسبت به `bars` خانهٔ قبل: (v[i]/v[i-bars] - 1) × 100."""
    n = len(values)
    out: List[Num] = [None] * n
    for i in range(n):
        if i < bars:
            continue
        a, b = values[i - bars], values[i]
        if a is None or b is None or a == 0:
            continue
        out[i] = (b / a - 1.0) * 100.0
    return out


def market_structure(candles: Sequence[Candle], window: int = 20) -> List[dict]:
    """ساختار بازار (HH/HL در برابر LH/LL) روی `window` کندلِ قبلی.

    خروجی هر خانه: {direction (+1/-1/0), hh, hl, lh, ll, score}
    `direction` از رویدادِ غالبِ آخرین swing گرفته می‌شود:
      - شکست سقفِ window به بالا (HH) → +1
      - شکست کفِ window به پایین (LL)  → −1
      - در غیر این صورت جهتِ آخرین رویدادِ معتبر (بدون lookahead: فقط رویدادهای
        بسته‌شده تا خانهٔ i).
    """
    n = len(candles)
    out: List[dict] = [{"direction": 0, "hh": False, "hl": False, "lh": False,
                        "ll": False, "score": 0.0} for _ in range(n)]
    last = 0
    for i in range(n):
        if i < window:
            continue
        seg = candles[i - window:i]
        hi_max = max(c.high for c in seg)
        lo_min = min(c.low for c in seg)
        hi_prev = max(c.high for c in seg[-max(1, window // 2):])
        lo_prev = min(c.low for c in seg[-max(1, window // 2):])
        c = candles[i]
        hh = c.high > hi_max
        ll = c.low < lo_min
        hl = (not ll) and c.low > lo_prev
        lh = (not hh) and c.high < hi_prev
        if hh:
            last = 1
        elif ll:
            last = -1
        out[i] = {"direction": last, "hh": hh, "hl": hl, "lh": lh, "ll": ll,
                  "score": (1.0 if hh else 0.0) + (0.5 if hl else 0.0)
                           - (1.0 if ll else 0.0) - (0.5 if lh else 0.0)}
    return out


def rolling_max_drawdown(equity: Sequence[float]) -> float:
    """حداکثر افت (به درصد) روی منحنی موجودی."""
    peak = -1e18
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, (e - peak) / peak * 100.0)
    return round(mdd, 4)
