"""تشخیص «۳ حالت بازار» (Market Regime) — قواعدی، بدون ML و بدون lookahead.

سه روند request‌شده توسط کاربر:
- ``uptrend``   → روند صعودی (بالا می‌رود)
- ``downtrend`` → روند نزولی (پایین می‌رود)
- ``sideways``  → رنج / خنثی (भिdırجان، حرکت عمودی ندارد)

الگوریتم ترکیبی (همه علی — فقط از دادهٔ <= t استفاده می‌کنند):
- ADX (Wilder)          → قدرت روند (ADX>25 روند قوی، <20 رنج)
- شیب EMA21            → جهت روند
- قیمت vs EMA21         → جهت
- ساختار HH/HL از Donchian → تایید شکست روند
- موقعیت Bollinger (bb_pos) → سیگنال خروج/فشرده‌شدن
- حجم (volume_z)        → تایید ورود

خروجی هر t: regime + confidence + adx + slope + donch_pos + bb_pos + vol_z + reasons.
"""
from __future__ import annotations

from math import sqrt
from typing import List, Optional

from .data import Candle


DEFAULT_REGIME_PARAMS = {
    "adx_period": 14,
    "adx_trend_strong": 25.0,   # ADX بالاتر از این → روند قوی
    "adx_trend_weak": 20.0,     # ADX بین این دو → روند ضعیف
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_trend": 55,
    "slope_lookback": 5,        # شیب EMA21 روی N کندلِ آخر
    "slope_trend_pct": 0.08,    # حداقل شیب (درصد) برای توانถือว่า روند
    "donchian_window": 20,
    "bb_window": 20,
    "vol_window": 50,
    "vol_spike": 1.3,
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ema(values: List[float], period: int) -> List[Optional[float]]:
    """EMA ساده با warmup (None قبل از قدری که عدد فعلی قابل محاسبه نباشد)."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def adx(candles: List[Candle], period: int = 14) -> List[Optional[float]]:
    """ADX با هموارسازی Wilder (علمی، استاندارد). None در warmup."""
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n <= 2 * period:
        return out

    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up_move = candles[i].h - candles[i - 1].h
        down_move = candles[i - 1].l - candles[i].l
        plus_dm[i] = max(up_move, 0.0) if up_move > down_move else 0.0
        minus_dm[i] = max(down_move, 0.0) if down_move > up_move else 0.0
        tr[i] = max(
            candles[i].h - candles[i].l,
            abs(candles[i].h - candles[i - 1].c),
            abs(candles[i].l - candles[i - 1].c),
        )

    # کاشت اولیه (Wilder): مجموع `period` تای اول
    plus_s = sum(plus_dm[1:period + 1])
    minus_s = sum(minus_dm[1:period + 1])
    atr_s = sum(tr[1:period + 1])
    plus_di = 100.0 * plus_s / atr_s if atr_s else 0.0
    minus_di = 100.0 * minus_s / atr_s if atr_s else 0.0
    dx = 100.0 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) else 0.0

    adx_val = dx
    out[period] = adx_val
    for i in range(period + 1, n):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        plus_s = (plus_s * (period - 1) + plus_dm[i]) / period
        minus_s = (minus_s * (period - 1) + minus_dm[i]) / period
        plus_di = 100.0 * plus_s / atr_s if atr_s else 0.0
        minus_di = 100.0 * minus_s / atr_s if atr_s else 0.0
        dx = 100.0 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) else 0.0
        adx_val = (adx_val * (period - 1) + dx) / period
        out[i] = adx_val
    return out


def donchian(candles: List[Candle], window: int = 20):
    """کران بالا/پایین پنجرهٔ قبلی (بدون کندل جاری — شکست واقعی)."""
    n = len(candles)
    up: List[Optional[float]] = [None] * n
    lo: List[Optional[float]] = [None] * n
    for i in range(window, n):
        seg = candles[i - window:i]
        up[i] = max(x.h for x in seg)
        lo[i] = min(x.l for x in seg)
    return up, lo


def _rolling_mean_std(values: List[float], window: int):
    n = len(values)
    means: List[Optional[float]] = [None] * n
    stds: List[Optional[float]] = [None] * n
    buf: List[float] = []
    s = s2 = 0.0
    for i, v in enumerate(values):
        buf.append(v)
        s += v
        s2 += v * v
        if len(buf) > window:
            old = buf.pop(0)
            s -= old
            s2 -= old * old
        if i >= window - 1:
            m = s / window
            var = max(s2 / window - m * m, 0.0)
            means[i] = m
            stds[i] = sqrt(var)
    return means, stds


def bollinger(closes: List[float], window: int = 20):
    means, stds = _rolling_mean_std(closes, window)
    pos: List[Optional[float]] = [None] * len(closes)
    width: List[Optional[float]] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        m, sd = means[i], stds[i]
        if sd is None or m is None:
            continue
        up, lo = m + 2 * sd, m - 2 * sd
        pos[i] = 0.5 if up == lo else (closes[i] - lo) / (up - lo)
        width[i] = (up - lo) / m if m else 0.0
    return pos, width


def volume_z(candles: List[Candle], window: int = 50) -> List[Optional[float]]:
    vols = [c.v for c in candles]
    means, stds = _rolling_mean_std(vols, window)
    out: List[Optional[float]] = [None] * len(candles)
    for i in range(window - 1, len(candles)):
        sd = stds[i]
        if sd:
            out[i] = (vols[i] - means[i]) / sd
    return out


def compute_regimes(candles: List[Candle], params: dict) -> List[Optional[dict]]:
    """برای هر کندل، جایگاه بازار (regime) + اطمینان (confidence) + دلیل.

    خروجی لیست هم‌طول `candles`؛ Garant warmup = None.
    """
    n = len(candles)
    p = dict(DEFAULT_REGIME_PARAMS)
    p.update(params or {})
    if n < p["ema_trend"] + p["slope_lookback"] + 2:
        return [None] * n

    closes = [c.c for c in candles]
    ef = ema(closes, p["ema_fast"])
    es = ema(closes, p["ema_slow"])
    et = ema(closes, p["ema_trend"])
    ad = adx(candles, p["adx_period"])
    du, dl = donchian(candles, p["donchian_window"])
    bp, bw = bollinger(closes, p["bb_window"])
    vz = volume_z(candles, p["vol_window"])

    out: List[Optional[dict]] = [None] * n
    for i in range(n):
        if None in (ef[i], es[i], et[i], ad[i], du[i], dl[i], bp[i], bw[i], vz[i]):
            continue
        price = closes[i]
        # شیب EMA21 روی N کندلِ آخر (درصد)
        lb = p["slope_lookback"]
        if i - lb < 0:
            continue
        base = es[i - lb]
        if not base:
            continue
        slope_pct = (es[i] - base) / base * 100.0

        rng = (du[i] - dl[i])
        donch_pos = (price - dl[i]) / rng if rng > 0 else 0.5

        # ۱. قدرت روند از ADX
        a = ad[i]
        if a >= p["adx_trend_strong"]:
            strength = 2
        elif a >= p["adx_trend_weak"]:
            strength = 1
        else:
            strength = 0

        # ۲. جهت روند از شیب EMA21 + قیمت vs EMA21
        trend_up = slope_pct > p["slope_trend_pct"] and price > es[i]
        trend_dn = slope_pct < -p["slope_trend_pct"] and price < es[i]

        # ۳. تصمیم نهایی
        if strength >= 1 and trend_up:
            regime = "uptrend"
        elif strength >= 1 and trend_dn:
            regime = "downtrend"
        else:
            regime = "sideways"

        # ۴. اطمینان
        conf = 0.45 + (a / 50.0) * 0.25
        conf += _clamp(abs(slope_pct) / (p["slope_trend_pct"] * 2.0)) * 0.15
        if regime != "sideways":
            if (regime == "uptrend" and donch_pos > 0.6) or \
               (regime == "downtrend" and donch_pos < 0.4):
                conf += 0.10
        if vz[i] > 0:
            conf += _clamp(vz[i] / 3.0) * 0.10
        conf = _clamp(conf)

        # ۵. دلیل (فارسی، برای لاگ و داشبورد)
        reasons = [
            f"ADX={a:.0f} ({'روند' if strength >= 1 else 'رنج'})",
            f"شیب EMA21={slope_pct:+.2f}%",
            f"قیمت vs EMA21: {'بالا' if price > es[i] else 'پایین'}",
            f"Donchian: {donch_pos:.2f}",
            f"BB pos: {bp[i]:.2f}",
        ]

        out[i] = {
            "regime": regime,
            "confidence": round(conf, 3),
            "adx": round(a, 2),
            "slope_pct": round(slope_pct, 3),
            "donch_pos": round(donch_pos, 3),
            "bb_pos": round(bp[i], 3),
            "bb_width": round(bw[i], 5),
            "vol_z": round(vz[i], 2),
            "ema_fast": round(ef[i], 4),
            "ema_slow": round(es[i], 4),
            "ema_trend": round(et[i], 4),
            "reasons": reasons,
        }
    return out


def regime_bias(regime: str) -> int:
    """جهت ترجیحی هر حالت: +1 صعودی، -1 نزولی، 0 رنج."""
    if regime == "uptrend":
        return 1
    if regime == "downtrend":
        return -1
    return 0
