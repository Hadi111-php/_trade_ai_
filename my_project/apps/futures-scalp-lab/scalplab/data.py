"""منابع داده: synthetic (برای اعتبارسنجی در هر محیطی)، csv (بازپخش واقعی)، binance (زنده روی PC)."""
from __future__ import annotations

import csv as _csv
import json
import math
import random
import urllib.request
from dataclasses import dataclass
from typing import List

from .config import LabConfig


@dataclass
class Candle:
    ts: int
    o: float
    h: float
    l: float
    c: float
    v: float

    def to_dict(self):
        return {"ts": self.ts, "o": self.o, "h": self.h, "l": self.l,
                "c": self.c, "v": self.v}


def synthetic_candles(cfg: LabConfig, seed: int) -> List[Candle]:
    """دادهٔ مصنوعی با رژیم‌های متغیر (روند / بازگشت به میانگین / رنج) + جهش.

    فقط برای اعتبارسنجی مکانیزم؛ به‌هیچ‌وجه نمایندهٔ بازار واقعی نیست.
    """
    rng = random.Random(seed)
    n = cfg.candles
    price = 30000.0 + rng.uniform(-2000, 2000)
    ts0 = 1_700_000_000_000
    step_ms = 60_000
    candles: List[Candle] = []

    regime = "chop"
    drift = 0.0
    mr = 0.0
    anchor = price
    remain = 0
    base_vol = 0.0006

    for i in range(n):
        if remain <= 0:
            regime = rng.choice(["trend", "trend", "meanrev", "chop", "chop"])
            remain = rng.randint(80, 300)
            anchor = price
            if regime == "trend":
                drift = rng.choice([-1, 1]) * rng.uniform(0.00004, 0.0002)
                mr = 0.0
            elif regime == "meanrev":
                drift = 0.0
                mr = rng.uniform(0.05, 0.15)
            else:
                drift = 0.0
                mr = 0.0
        remain -= 1

        vol = base_vol * rng.uniform(0.6, 1.8)
        shock = 0.0
        if rng.random() < 0.01:                      # جهش خبری
            shock = rng.gauss(0, 8 * vol)
        ret = drift + rng.gauss(0, vol) + shock
        if regime == "meanrev":                      # کشش به سمت لنگر
            ret -= mr * (price - anchor) / price

        o = price
        c = price * math.exp(ret)
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol)) * 0.5)
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol)) * 0.5)
        v = rng.uniform(50, 200) * (1 + 10 * abs(ret) / vol if vol else 1)
        candles.append(Candle(ts0 + i * step_ms, round(o, 2), round(hi, 2),
                              round(lo, 2), round(c, 2), round(v, 2)))
        price = c
    return candles


def csv_candles(cfg: LabConfig) -> List[Candle]:
    """فایل CSV با ستون‌های ts,open,high,low,close,volume (هدر اختیاری)."""
    candles: List[Candle] = []
    with open(cfg.csv_path, newline="", encoding="utf-8") as f:
        rows = list(_csv.reader(f))
    if not rows:
        return candles
    start = 0
    first = [c.strip().lower() for c in rows[0]]
    if any(h in ("ts", "timestamp", "open", "time") for h in first):
        idx = {h: i for i, h in enumerate(first)}
        start = 1
    else:
        idx = {"ts": 0, "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}
    for r in rows[start:]:
        if not r or len(r) < 5:
            continue
        candles.append(Candle(
            int(float(r[idx["ts"]])), float(r[idx["open"]]), float(r[idx["high"]]),
            float(r[idx["low"]]), float(r[idx["close"]]),
            float(r[idx.get("volume", 5)] if len(r) > 5 else 0.0)))
    return candles


def binance_candles(cfg: LabConfig) -> List[Candle]:
    """کندل‌های زندهٔ Binance (فقط روی PC با اینترنت). خطا شفاف گزارش می‌شود."""
    url = f"{cfg.binance_url}?symbol={cfg.symbol}&interval={cfg.timeframe}&limit={cfg.candles}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = json.load(resp)
    except Exception as e:  # pragma: no cover - وابسته به شبکه
        raise RuntimeError(
            f"دسترسی به Binance ممکن نشد ({e}). "
            f"این حالت فقط روی PC با اینترنت کار می‌کند؛ برای آزمایش بدون شبکه از "
            f"--data synthetic یا --data csv استفاده کن.") from e
    return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                   float(r[4]), float(r[5])) for r in raw]


def _bybit_interval(cfg: LabConfig) -> str:
    return cfg.timeframe.replace("m", "") or "1"


def bybit_candles(cfg: LabConfig) -> List[Candle]:
    """کندل‌های زندهٔ Bybit (v5, عمومی، بدون کلید). جدیدترین اول → برعکس می‌کنیم."""
    url = (f"{cfg.bybit_url}?category={cfg.bybit_category}&symbol={cfg.symbol}"
           f"&interval={_bybit_interval(cfg)}&limit={cfg.candles}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = json.load(resp)
        rows = raw["result"]["list"]
    except Exception as e:  # pragma: no cover - وابسته به شبکه
        raise RuntimeError(
            f"دسترسی به Bybit ممکن نشد ({e}). فقط روی PC با اینترنت؛ "
            f"برای بدون شبکه از --data synthetic/csv استفاده کن.") from e
    out = [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                  float(r[4]), float(r[5])) for r in rows]
    out.reverse()
    return out


def bybit_last_closed(cfg: LabConfig):
    """آخر کندلِ بستهٔ Bybit (برای حالت auto)."""
    url = (f"{cfg.bybit_url}?category={cfg.bybit_category}&symbol={cfg.symbol}"
           f"&interval={_bybit_interval(cfg)}&limit=3")
    with urllib.request.urlopen(url, timeout=15) as resp:
        raw = json.load(resp)
    rows = raw["result"]["list"]
    if len(rows) < 2:
        return None
    r = rows[-2]   # جدیدترین اول → اندیس -2 کندل بسته است
    return Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                  float(r[4]), float(r[5]))


def load_candles(cfg: LabConfig, seed: int) -> List[Candle]:
    if cfg.data_mode == "csv":
        return csv_candles(cfg)
    if cfg.data_mode == "binance":
        return binance_candles(cfg)
    if cfg.data_mode == "bybit":
        return bybit_candles(cfg)
    return synthetic_candles(cfg, seed)
