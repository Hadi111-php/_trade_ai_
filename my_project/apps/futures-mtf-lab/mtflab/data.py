"""منابع داده + هم‌ترازی ساختاری کندل‌ها (Candle) + resample فقط به بالا.

قواعد سخت این ماژول:
1. `resample_up` فقط تایم‌فریم پایین‌تر را به بالاتر تبدیل می‌کند. ساختن 15m از
   1h **غیرممکن** است و این ماژول به‌جای حدس زدن، خطای صریح می‌دهد
   (دام «دادهٔ جعلی ریزدانه» در docs/pitfalls.md).
2. bucket‌های ناقصِ ابتدا/انتها حذف می‌شوند تا OHLC جزئی به‌عنوان کندل کامل
   به موتور نرسد (دام «کندل ناقص»).
3. هیچ forward-fill کورکورانه‌ای انجام نمی‌شود؛ گپ‌ها گزارش می‌شوند.
"""
from __future__ import annotations

import csv as _csv
import math
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------------------
# تایم‌فریم‌ها
# ----------------------------------------------------------------------------
TF_MINUTES: Dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440, "1D": 1440,
}

# کد interval مورد انتظار Bybit v5 (بر حسب دقیقه یا "D"/"W"/"M")
BYBIT_INTERVAL: Dict[int, str] = {
    1: "1", 3: "3", 5: "5", 15: "15", 30: "30", 60: "60",
    120: "120", 240: "240", 360: "360", 720: "720", 1440: "D",
}


def tf_to_minutes(tf: str) -> int:
    """تبدیل نام تایم‌فریم به دقیقه. اعداد خالی هم پذیرفته می‌شوند (مثل "60")."""
    if tf in TF_MINUTES:
        return TF_MINUTES[tf]
    s = str(tf).strip().lower()
    if s.isdigit():
        return int(s)          # قرارداد قدیم: عدد = دقیقه
    if s.endswith("m") and s[:-1].isdigit():
        return int(s[:-1])
    if s.endswith("h") and s[:-1].isdigit():
        return int(s[:-1]) * 60
    if s.endswith("d") and s[:-1].isdigit():
        return int(s[:-1]) * 1440
    raise ValueError(f"تایم‌فریم پشتیبانی‌نشده: {tf!r}")


def tf_to_ms(tf: str) -> int:
    return tf_to_minutes(tf) * 60 * 1000


# ----------------------------------------------------------------------------
# کندل
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Candle:
    """یک کندل OHLCV.

    نام فیلدها همان قرارداد اسکلت اصلی سناریو است (`open_time_ms`, `open`, …)
    تا با `alignment.py` و `bybit_public.py` هم‌راستا بماند؛ میان‌برهای
    `ts/o/h/l/c/v` فقط برای سازگاری با بقیهٔ مخزن اضافه شده‌اند.
    """
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    # -- میان‌برهای سازگاری -------------------------------------------------
    @property
    def ts(self) -> int:
        return self.open_time_ms

    @property
    def o(self) -> float:
        return self.open

    @property
    def h(self) -> float:
        return self.high

    @property
    def l(self) -> float:
        return self.low

    @property
    def c(self) -> float:
        return self.close

    @property
    def v(self) -> float:
        return self.volume

    def close_time_ms(self, timeframe_ms: int) -> int:
        """زمان بسته‌شدن کندل = زمان شروع + طول تایم‌فریم."""
        return self.open_time_ms + timeframe_ms

    def to_dict(self) -> dict:
        return {"ts": self.open_time_ms, "o": self.open, "h": self.high,
                "l": self.low, "c": self.close, "v": self.volume}


def candle_from_row(ts, o, h, l, c, v=0.0) -> Candle:
    return Candle(int(float(ts)), float(o), float(h), float(l), float(c), float(v or 0.0))


# ----------------------------------------------------------------------------
# خواندن CSV
# ----------------------------------------------------------------------------
_TS_KEYS = ("ts", "timestamp", "time", "open_time", "open_time_ms", "date")
_VOL_KEYS = ("volume", "vol", "v", "base_volume")


def csv_candles(path: str) -> List[Candle]:
    """CSV با ستون‌های ts,open,high,low,close,volume (هدر اختیاری/انعطافی)."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"فایل CSV پیدا نشد: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in _csv.reader(f) if r and any(x.strip() for x in r)]
    if not rows:
        return []

    first = [c.strip().lower() for c in rows[0]]
    idx: Dict[str, int] = {}
    start = 0
    if any(h in ("ts", "timestamp", "time", "open", "open_time") for h in first):
        start = 1
        for i, h in enumerate(first):
            if h in _TS_KEYS and "ts" not in idx:
                idx["ts"] = i
            elif h == "open" and "open" not in idx:
                idx["open"] = i
            elif h == "high" and "high" not in idx:
                idx["high"] = i
            elif h == "low" and "low" not in idx:
                idx["low"] = i
            elif h == "close" and "close" not in idx:
                idx["close"] = i
            elif h in _VOL_KEYS and "volume" not in idx:
                idx["volume"] = i
    if "ts" not in idx:
        idx = {"ts": 0, "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}

    out: List[Candle] = []
    for r in rows[start:]:
        if len(r) < 5:
            continue
        try:
            vol = float(r[idx["volume"]]) if "volume" in idx and len(r) > idx["volume"] else 0.0
            out.append(candle_from_row(r[idx["ts"]], r[idx["open"]], r[idx["high"]],
                                       r[idx["low"]], r[idx["close"]], vol))
        except (ValueError, KeyError, IndexError):
            continue          # ردیف خراب → رد، بدون حدس زدن
    out.sort(key=lambda c: c.open_time_ms)
    return _dedupe(out)


def write_csv(path: str, candles: Sequence[Candle]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.open_time_ms, c.open, c.high, c.low, c.close, round(c.volume, 6)])


def _dedupe(candles: Sequence[Candle]) -> List[Candle]:
    seen, out = set(), []
    for c in candles:
        if c.open_time_ms in seen:
            continue
        seen.add(c.open_time_ms)
        out.append(c)
    return out


# ----------------------------------------------------------------------------
# بهداشت داده: گپ / ناهمسانی
# ----------------------------------------------------------------------------
def find_gaps(candles: Sequence[Candle], tf: str, max_report: int = 20) -> dict:
    """گپ‌های زمانی را پیدا می‌کند (بدون پرکردن!). برای گزارش سلامت داده."""
    step = tf_to_ms(tf)
    missing: List[int] = []
    for a, b in zip(candles, candles[1:]):
        delta = b.open_time_ms - a.open_time_ms
        if delta > step:
            k = delta // step - 1
            missing.extend([a.open_time_ms + step * (j + 1) for j in range(min(k, 5000))])
    return {
        "tf": tf,
        "expected_step_ms": step,
        "candles": len(candles),
        "missing_candles": len(missing),
        "missing_pct": round(100.0 * len(missing) / max(len(candles) + len(missing), 1), 4),
        "first_missing": missing[:max_report],
        "clean": len(missing) == 0,
    }


# ----------------------------------------------------------------------------
# resample — فقط به بالا (پایین‌تر هرگز)
# ----------------------------------------------------------------------------
def resample_up(candles: Sequence[Candle], src_tf: str, dst_tf: str,
                drop_partial_edges: bool = True) -> Tuple[List[Candle], dict]:
    """تبدیل کندل‌های تایم‌فریم پایین‌تر به بالاتر (مثلاً 1h → 4h).

    چرا این تابع امن است؟
    - bucket‌ها با `floor(ts / dst_ms)` ساخته می‌شوند (مرز زمانی صریح، بدون drift).
    - لایهٔ `alignment` فقط bucket‌ای را به سیگنال می‌دهد که `close_time` آن
      کوچک‌تر/مساوی زمانِ شروع کندل تریگر باشد → هیچ اطلاعات آینده‌ای وارد
      تصمیم نمی‌شود، حتی اگر bucket هنوز کامل باشد.
    - bucket‌های ناقصِ ابتدا/انتها (که OHLC جزئی دارند) به‌صورت پیش‌فرض حذف
      می‌شوند تا «کندل نصفه» به‌عنوان کندل کامل مصرف نشود.

    خروجی: (کندل‌های dst، گزارش بهداشت)
    """
    src_ms, dst_ms = tf_to_ms(src_tf), tf_to_ms(dst_tf)
    if dst_ms <= src_ms:
        raise ValueError(
            f"resample فقط به بالا مجاز است: {src_tf} → {dst_tf} یعنی ساختن دادهٔ "
            f"ریزدانه‌تر از دادهٔ درشت‌تر که اطلاعاتش وجود ندارد (دام lookahead/fabrication).")
    if dst_ms % src_ms != 0:
        raise ValueError(f"dst ({dst_tf}) باید مضرب صحیح src ({src_tf}) باشد.")
    if not candles:
        return [], {"src_tf": src_tf, "dst_tf": dst_tf, "buckets": 0, "dropped_partial": 0}

    per_bucket = dst_ms // src_ms
    buckets: Dict[int, List[Candle]] = {}
    for c in candles:
        key = (c.open_time_ms // dst_ms) * dst_ms
        buckets.setdefault(key, []).append(c)

    out: List[Candle] = []
    dropped_partial = 0
    partial_middle = 0
    keys = sorted(buckets)
    for bi, k in enumerate(keys):
        grp = sorted(buckets[k], key=lambda c: c.open_time_ms)
        is_edge = (bi == 0 or bi == len(keys) - 1)
        if len(grp) < per_bucket:
            if is_edge and drop_partial_edges:
                dropped_partial += 1
                continue
            partial_middle += 1        # گپ واقعی در دادهٔ منبع → نگه می‌داریم ولی گزارش می‌شود
        out.append(Candle(
            open_time_ms=k,
            open=grp[0].open,
            high=max(g.high for g in grp),
            low=min(g.low for g in grp),
            close=grp[-1].close,
            volume=sum(g.volume for g in grp),
        ))

    report = {
        "src_tf": src_tf, "dst_tf": dst_tf,
        "src_candles": len(candles), "buckets": len(out),
        "expected_per_bucket": per_bucket,
        "dropped_partial_edges": dropped_partial,
        "partial_middle_buckets": partial_middle,
    }
    return out, report


# ----------------------------------------------------------------------------
# دادهٔ مصنوعی (فقط اعتبارسنجی مکانیزم — NOT real market)
# ----------------------------------------------------------------------------
def synthetic_candles(tf: str, n: int, seed: int = 42, start_price: float = 30000.0,
                      start_ts: int = 1_700_000_000_000) -> List[Candle]:
    """جریان کندل مصنوعی با رژیم‌های متغیر (روند / بازگشت به میانگین / رنج) + جهش.

    فقط برای تست مکانیزم و تست‌های علی‌بودن استفاده می‌شود و در گزارش‌ها
    صریحاً برچسب «مصنوعی» می‌خورد.
    """
    rng = random.Random(seed)
    step = tf_to_ms(tf)
    price = start_price
    ts = (start_ts // step) * step
    regime, remain, drift, mr, anchor = "chop", 0, 0.0, 0.0, price
    base_vol = 0.0009 if step <= 900_000 else 0.0022
    out: List[Candle] = []
    for _ in range(n):
        if remain <= 0:
            regime = rng.choice(["trend", "trend", "meanrev", "chop", "chop"])
            remain = rng.randint(60, 240)
            anchor = price
            if regime == "trend":
                drift = rng.choice([-1, 1]) * rng.uniform(0.00006, 0.00035)
                mr = 0.0
            elif regime == "meanrev":
                drift, mr = 0.0, rng.uniform(0.05, 0.15)
            else:
                drift, mr = 0.0, 0.0
        remain -= 1
        vol = base_vol * rng.uniform(0.6, 1.8)
        shock = rng.gauss(0, 8 * vol) if rng.random() < 0.01 else 0.0
        ret = drift + rng.gauss(0, vol) + shock
        if regime == "meanrev":
            ret -= mr * (price - anchor) / price
        o = price
        c = price * math.exp(ret)
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol)) * 0.5)
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol)) * 0.5)
        v = rng.uniform(50, 200) * (1 + 8 * abs(ret) / vol if vol else 1)
        out.append(Candle(ts, round(o, 2), round(hi, 2), round(lo, 2), round(c, 2), round(v, 2)))
        price, ts = c, ts + step
    return out


# ----------------------------------------------------------------------------
# بارگذاری سه‌لایه (تریگر / فیلتر / بایاس)
# ----------------------------------------------------------------------------
def load_layers(cfg) -> Tuple[Dict[str, List[Candle]], dict]:
    """بر اساس `data_mode` سه لایهٔ زمانی را آماده می‌کند.

    - csv: تریگر از فایل؛ فیلتر/بایاس از فایل جدا (در صورت وجود) وگرنه
      resample به بالا از همان تریگر (حالت «دادهٔ یکسان» برای مقایسه).
    - bybit: هر سه تایم‌فریم مستقیم از API عمومی (بدون کلید) با صفحه‌بندی + کش.
    - synthetic: تریگر مصنوعی + resample به بالا.
    """
    meta: dict = {"data_mode": cfg.data_mode, "symbol": cfg.symbol,
                  "tf_trigger": cfg.tf_trigger, "tf_filter": cfg.tf_filter,
                  "tf_bias": cfg.tf_bias, "resample": [], "sources": {}}

    if cfg.data_mode == "csv":
        trig = csv_candles(cfg.csv_path)
        meta["sources"]["trigger"] = cfg.csv_path
        filt = _load_or_resample(cfg.csv_filter_path, trig, cfg.tf_trigger, cfg.tf_filter, meta)
        bias = _load_or_resample(cfg.csv_bias_path, trig, cfg.tf_trigger, cfg.tf_bias, meta)
    elif cfg.data_mode == "bybit":
        from .bybit_public import fetch_klines_range
        trig = fetch_klines_range(cfg.symbol, cfg.tf_trigger, cfg.days,
                                  base_url=cfg.bybit_base_url, category=cfg.bybit_category,
                                  cache_dir=cfg.data_dir, use_cache=not cfg.refresh_cache)
        filt = fetch_klines_range(cfg.symbol, cfg.tf_filter, cfg.days,
                                  base_url=cfg.bybit_base_url, category=cfg.bybit_category,
                                  cache_dir=cfg.data_dir, use_cache=not cfg.refresh_cache)
        bias = fetch_klines_range(cfg.symbol, cfg.tf_bias, cfg.days,
                                  base_url=cfg.bybit_base_url, category=cfg.bybit_category,
                                  cache_dir=cfg.data_dir, use_cache=not cfg.refresh_cache)
        meta["sources"] = {"trigger": f"bybit:{cfg.tf_trigger}", "filter": f"bybit:{cfg.tf_filter}",
                           "bias": f"bybit:{cfg.tf_bias}"}
    elif cfg.data_mode == "synthetic":
        trig = synthetic_candles(cfg.tf_trigger, cfg.candles or 4000, seed=cfg.seed)
        meta["sources"]["trigger"] = "synthetic"
        filt = _load_or_resample("", trig, cfg.tf_trigger, cfg.tf_filter, meta)
        bias = _load_or_resample("", trig, cfg.tf_trigger, cfg.tf_bias, meta)
    else:
        raise ValueError(f"data_mode پشتیبانی‌نشده: {cfg.data_mode}")

    if cfg.candles and cfg.data_mode != "synthetic":
        trig = trig[-cfg.candles:]
        # فیلتر/بایاس هم باید هم‌پوشان باشند: فقط کندل‌هایی که قبل از انتهای تریگرند
        end = trig[-1].open_time_ms if trig else 0
        filt = [c for c in filt if c.open_time_ms <= end]
        bias = [c for c in bias if c.open_time_ms <= end]
    if not trig:
        raise RuntimeError("هیچ کندلی برای تریگر بارگذاری نشد.")

    meta["counts"] = {"trigger": len(trig), "filter": len(filt), "bias": len(bias)}
    meta["gaps"] = {
        "trigger": find_gaps(trig, cfg.tf_trigger),
        "filter": find_gaps(filt, cfg.tf_filter),
        "bias": find_gaps(bias, cfg.tf_bias),
    }
    return {"trigger": trig, "filter": filt, "bias": bias}, meta


def _load_or_resample(path: str, trig: Sequence[Candle], src_tf: str, dst_tf: str,
                      meta: dict) -> List[Candle]:
    if path:
        cs = csv_candles(path)
        meta["sources"][dst_tf] = path
        return cs
    cs, rep = resample_up(trig, src_tf, dst_tf)
    meta["resample"].append(rep)
    meta["sources"][dst_tf] = f"resample({src_tf}→{dst_tf})"
    return cs
