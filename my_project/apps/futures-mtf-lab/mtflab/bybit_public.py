"""دریافت دادهٔ عمومی کندل (Kline/OHLCV) از Bybit — بدون نیاز به API key.

مستندات رسمی: GET /v5/market/kline (category=linear برای USDT Perpetual)

تفاوت‌های مهم با اسکلت اولیهٔ سناریو (docs/ORIGINAL_SCAFFOLD_NOTES_FA.md):
1. `requests` → `urllib.request` (فقط کتابخانهٔ استاندارد؛ روی Termux/VPS بدون pip).
2. property مردهٔ `Candle.is_closed_relative_to` (که فقط NotImplementedError
   می‌داد) حذف شد؛ منطق «بسته بودن» صریح در `_drop_forming_candle` است.
3. حلقهٔ صفحه‌بندی (pagination) اضافه شد: یک درخواست فقط ۱۰۰۰ کندل می‌دهد،
   ولی یک سال 15m یعنی ~۳۵٬۰۰۰ کندل.
4. کش CSV محلی + retry با backoff تا اجراهای تکراری به شبکه نیاز نداشته باشند.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Sequence

from .data import BYBIT_INTERVAL, Candle, tf_to_minutes, tf_to_ms, write_csv, csv_candles

DEFAULT_BASE_URL = "https://api.bybit.com"
KLINE_ENDPOINT = "/v5/market/kline"
MAX_LIMIT = 1000
#: تعداد تلاش اضافی مخصوص «سقف نرخ» (به‌جز retries شبکهٔ معمولی)
RATE_LIMIT_RETRIES = 6


def _interval_code(tf: str) -> str:
    m = tf_to_minutes(tf)
    if m not in BYBIT_INTERVAL:
        raise ValueError(f"تایم‌فریم پشتیبانی‌نشده برای Bybit: {tf} (دقیقه={m})")
    return BYBIT_INTERVAL[m]


def _timeframe_to_ms(tf: str) -> int:
    return tf_to_ms(tf)


def drop_forming_candle(candles: Sequence[Candle], tf: str,
                        now_ms: Optional[int] = None) -> List[Candle]:
    """حذف صریح آخرین کندلِ در حال شکل‌گیری (محافظت اولیه در برابر lookahead).

    یک کندل فقط وقتی «بسته» است که `open_time + interval <= now`.
    تصمیم نهایی دربارهٔ قابل‌استفاده بودن، در لایهٔ `alignment.py` دوباره
    با شرط `close_time <= trigger_open_time` چک می‌شود (دو لایه محافظت).
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    step = _timeframe_to_ms(tf)
    return [c for c in candles if (c.open_time_ms + step) <= now]


def fetch_klines(symbol: str, timeframe: str,
                 start_time_ms: Optional[int] = None,
                 end_time_ms: Optional[int] = None,
                 limit: int = MAX_LIMIT,
                 base_url: str = DEFAULT_BASE_URL,
                 category: str = "linear",
                 timeout: int = 15,
                 retries: int = 3,
                 drop_forming: bool = True) -> List[Candle]:
    """یک درخواست کندل عمومی از Bybit (صعودی، بدون کندل در حال شکل‌گیری).

    :param symbol: مثل "BTCUSDT"
    :param timeframe: یکی از کلیدهای پشتیبانی‌شده ("15m", "1h", "4h", …)
    :param start_time_ms / end_time_ms: بازهٔ میلی‌ثانیه‌ای (اختیاری)
    :param limit: حداکثر کندل در هر درخواست (سقف مستندات: 1000)
    """
    params = {
        "category": category,
        "symbol": symbol,
        "interval": _interval_code(timeframe),
        "limit": min(int(limit), MAX_LIMIT),
    }
    if start_time_ms is not None:
        params["start"] = int(start_time_ms)
    if end_time_ms is not None:
        params["end"] = int(end_time_ms)

    url = f"{base_url}{KLINE_ENDPOINT}?{urllib.parse.urlencode(params)}"
    last_err: Optional[Exception] = None
    payload = None
    # ۱۰۰۰۶ = سقف نرخ درخواست. روی ۱۵ دقیقه هر نماد ~۷۰ درخواست دارد و این
    # سقف واقعاً می‌خورد؛ قبلاً نماد کامل حذف می‌شد (۴ نماد از ۲۰ در یک اجرا).
    # حالا با عقب‌نشینی نمایی دوباره تلاش می‌شود.
    for attempt in range(retries + RATE_LIMIT_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mtf-lab/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue

        code = payload.get("retCode")
        if code == 0:
            break
        if code == 10006 or "rate limit" in str(payload.get("retMsg", "")).lower():
            wait = min(2.0 * (2 ** min(attempt, 5)), 60.0)
            time.sleep(wait)
            last_err = RuntimeError(f"rate limit (waited {wait:.0f}s)")
            continue
        raise RuntimeError(f"خطای Bybit API: retCode={code} "
                           f"msg={payload.get('retMsg')}")
    else:
        raise RuntimeError(f"خطای شبکه/سقف نرخ در دریافت {url}: {last_err}")

    raw_list = (payload.get("result") or {}).get("list") or []
    candles: List[Candle] = []
    for row in raw_list:
        # [start, open, high, low, close, volume, turnover]
        candles.append(Candle(open_time_ms=int(row[0]), open=float(row[1]),
                              high=float(row[2]), low=float(row[3]),
                              close=float(row[4]),
                              volume=float(row[5]) if len(row) > 5 else 0.0))
    candles.sort(key=lambda c: c.open_time_ms)          # Bybit نزولی می‌دهد
    if drop_forming:
        candles = drop_forming_candle(candles, timeframe)
    return candles


def fetch_klines_range(symbol: str, timeframe: str, days: int = 365,
                       base_url: str = DEFAULT_BASE_URL, category: str = "linear",
                       cache_dir: str = "data", use_cache: bool = True,
                       end_time_ms: Optional[int] = None,
                       rate_sleep: float = 0.25,
                       progress: bool = True,
                       save_csv: bool = True) -> List[Candle]:
    """دریافت `days` روز گذشته با صفحه‌بندی (۱۰۰۰ کندل در هر درخواست) + کش CSV.

    الگوریتم صفحه‌بندی: از انتها به ابتدا (`end` را عقب می‌بریم) چون پارامتر
    `end` در Bybit قابل اتکاتر از ترکیب start/limit برای پوشش کامل است.

    :param save_csv: اگر False، نسخهٔ CSV نوشته نمی‌شود. autoscan این را False
        می‌دهد چون خودش JSON را ذخیره می‌کند؛ نسخهٔ دوم فقط دو برابر فضا می‌برد
        (روی ۲۰ نماد ۱۵ دقیقه‌ای یعنی ~۱۰۰ مگابایت اضافه روی گوشی).
    """
    step = _timeframe_to_ms(timeframe)
    end = int(end_time_ms if end_time_ms is not None else time.time() * 1000)
    end = (end // step) * step                      # مرز دقیق تایم‌فریم
    start = end - days * 86_400_000

    cache_path = (os.path.join(cache_dir or ".",
                               f"{symbol.lower()}_{timeframe}_{days}d_bybit.csv")
                  if save_csv or (use_cache and cache_dir) else "")
    if save_csv:
        os.makedirs(cache_dir or ".", exist_ok=True)
    if use_cache and cache_path and os.path.exists(cache_path):
        cs = csv_candles(cache_path)
        if cs and cs[-1].open_time_ms + step >= end - step:
            if progress:
                print(f"  ↺ کش: {cache_path} ({len(cs)} کندل {timeframe})")
            return cs

    if progress:
        print(f"  ⬇ Bybit {symbol} {timeframe} — {days} روز (~{(end-start)//step} کندل)")
    all_rows: List[Candle] = []
    cursor = end
    guard = 0
    while cursor > start:
        guard += 1
        if guard > 400:                              # محافظت علیه حلقهٔ بی‌پایان
            break
        batch = fetch_klines(symbol, timeframe, start_time_ms=max(start, cursor - MAX_LIMIT * step),
                             end_time_ms=cursor, limit=MAX_LIMIT,
                             base_url=base_url, category=category, drop_forming=True)
        if not batch:
            break
        all_rows = batch + all_rows
        new_cursor = batch[0].open_time_ms - step
        if new_cursor >= cursor:                     # جلوگیری از گیرکردن
            break
        cursor = new_cursor
        if progress and guard % 10 == 0:
            print(f"    … {len(all_rows)} کندل تا {time.strftime('%Y-%m-%d', time.gmtime(cursor/1000))}")
        time.sleep(rate_sleep)

    # حذف تکراری + مرتب‌سازی + برش به بازه
    seen, out = set(), []
    for c in sorted(all_rows, key=lambda x: x.open_time_ms):
        if c.open_time_ms in seen or c.open_time_ms < start:
            continue
        seen.add(c.open_time_ms)
        out.append(c)
    if out and save_csv and cache_path:
        write_csv(cache_path, out)
        if progress:
            print(f"  ✅ {len(out)} کندل {timeframe} ذخیره شد: {cache_path}")
    return out
