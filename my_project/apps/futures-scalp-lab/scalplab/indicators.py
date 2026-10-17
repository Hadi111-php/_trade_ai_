"""اندیکاتورهای غلتِ علی (causal): مقدار t فقط از دادهٔ <= t ساخته می‌شود.

خروجی هر تابع لیستی هم‌طول ورودی است؛ جاهای warmup برابر None.
"""
from __future__ import annotations

import math
from typing import List, Optional

from .data import Candle

Num = Optional[float]


def ema(values: List[float], period: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
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


def rsi(closes: List[float], period: int = 14) -> List[Num]:
    """RSI با هموارسازی Wilder."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n <= period:
        return out
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gain += max(d, 0.0)
        loss += max(-d, 0.0)
    avg_g, avg_l = gain / period, loss / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def atr(candles: List[Candle], period: int = 14) -> List[Num]:
    n = len(candles)
    out: List[Num] = [None] * n
    if n <= period:
        return out
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(candles[i].h - candles[i].l,
                     abs(candles[i].h - candles[i - 1].c),
                     abs(candles[i].l - candles[i - 1].c))
    a = sum(trs[1:period + 1]) / period
    out[period] = a
    for i in range(period + 1, n):
        a = (a * (period - 1) + trs[i]) / period
        out[i] = a
    return out


def _rolling_mean_std(values: List[float], window: int):
    n = len(values)
    means: List[Num] = [None] * n
    stds: List[Num] = [None] * n
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
            stds[i] = math.sqrt(var)
    return means, stds


def bollinger(closes: List[float], window: int = 20):
    """brute-safe: میانگین/انحراف غلت؛ bb_pos = جای قیمت نسبت به باند (0..1)."""
    means, stds = _rolling_mean_std(closes, window)
    pos: List[Num] = [None] * len(closes)
    width: List[Num] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        m, sd = means[i], stds[i]
        if sd is None or m is None:
            continue
        up, lo = m + 2 * sd, m - 2 * sd
        pos[i] = 0.5 if up == lo else (closes[i] - lo) / (up - lo)
        width[i] = (up - lo) / m if m else 0.0
    return pos, width


def donchian(candles: List[Candle], window: int = 20):
    """کران‌های پنجرهٔ «قبلی» (بدون کندل جاری) برای تشخیص شکست بدون lookahead."""
    n = len(candles)
    up: List[Num] = [None] * n
    lo: List[Num] = [None] * n
    for i in range(window, n):
        hs = candles[i - window:i]
        up[i] = max(x.h for x in hs)
        lo[i] = min(x.l for x in hs)
    return up, lo


def macd(closes: List[float], fast=12, slow=26, signal=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line: List[Num] = [None] * len(closes)
    for i in range(len(closes)):
        if ef[i] is not None and es[i] is not None:
            line[i] = ef[i] - es[i]
    valid = [(i, v) for i, v in enumerate(line) if v is not None]
    sig: List[Num] = [None] * len(closes)
    hist: List[Num] = [None] * len(closes)
    if len(valid) >= signal:
        vals = [v for _, v in valid]
        k = 2.0 / (signal + 1)
        prev = sum(vals[:signal]) / signal
        start_idx = valid[signal - 1][0]
        sig[start_idx] = prev
        hist[start_idx] = vals[signal - 1] - prev
        j = signal
        for i in range(start_idx + 1, len(closes)):
            if line[i] is None:
                continue
            prev = line[i] * k + prev * (1 - k)
            sig[i] = prev
            hist[i] = line[i] - prev
            j += 1
    return line, sig, hist


def volume_z(candles: List[Candle], window: int = 50) -> List[Num]:
    vols = [c.v for c in candles]
    means, stds = _rolling_mean_std(vols, window)
    out: List[Num] = [None] * len(candles)
    for i in range(window - 1, len(candles)):
        sd = stds[i]
        if sd:
            out[i] = (vols[i] - means[i]) / sd
    return out


def build_snapshot(candles: List[Candle], params: dict) -> List[Optional[dict]]:
    """اسنپ‌شات کامل اندیکاتورها در هر کندل (علی) برای ثبت همراه سیگنال."""
    closes = [c.c for c in candles]
    p = params
    ef = ema(closes, p["ema_fast"])
    es = ema(closes, p["ema_slow"])
    r = rsi(closes, p["rsi_period"])
    a = atr(candles, p["atr_period"])
    bp, bw = bollinger(closes, p["bb_window"])
    du, dl = donchian(candles, p["donchian_window"])
    _, _, mh = macd(closes)
    vz = volume_z(candles, p["vol_window"])

    snaps = []
    for i in range(len(candles)):
        if None in (ef[i], es[i], r[i], a[i], bp[i], bw[i], du[i], dl[i], vz[i]):
            snaps.append(None)
            continue
        snaps.append({
            "ema_fast": round(ef[i], 4), "ema_slow": round(es[i], 4),
            "rsi": round(r[i], 2),
            "atr_pct": round(a[i] / closes[i] * 100, 4) if closes[i] else 0.0,
            "bb_pos": round(bp[i], 3), "bb_width": round(bw[i], 5),
            "donch_up": round(du[i], 2), "donch_dn": round(dl[i], 2),
            "macd_hist": round(mh[i], 4) if mh[i] is not None else None,
            "vol_z": round(vz[i], 2),
        })
    return snaps
