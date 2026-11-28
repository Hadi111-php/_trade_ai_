"""هم‌ترازسازی چند‌تایم‌فریمی (Multi-Timeframe Alignment) — ماژول حیاتی ضد lookahead.

قانون طلایی:
برای هر کندل تایم‌فریم پایین (تریگر، مثلاً 15m) که در زمان `t_open` شروع می‌شود،
فقط مجاز به استفاده از آخرین کندل تایم‌فریم بالاتر (مثلاً 1h) هستیم که زمان
بسته‌شدنش کوچک‌تر یا مساوی `t_open` باشد:

    اجازهٔ استفاده از کندل 1h با close_time C  <=>  C <= t_open کندل 15m

یعنی حتی کندل 1h‌ای که دقیقاً هم‌زمان با *پایان* کندل تریگر بسته می‌شود هم
در آن کندل تریگر دیده نمی‌شود (محافظه‌کارانه‌ترین حالت ممکن).

این ماژول عمداً **هیچ forward-fill کورکورانه‌ای** انجام نمی‌دهد: اگر هنوز هیچ
کندل تایم‌فریم بالاتری بسته نشده باشد، مقدار `None` برمی‌گردد و لایهٔ سیگنال
باید آن را «بدون معامله» تفسیر کند.

تفاوت با اسکلت اولیهٔ سناریو: دو فیلد `higher_idx` / `bias_idx` (با مقدار
پیش‌فرض `-1`) اضافه شد تا موتور بتواند بدون جست‌وجوی مجدد، آرایه‌های
اندیکاتور تایم‌فریم بالاتر را ایندکس بزند. امضای توابع عمومی تغییر نکرده و
تست‌های اصلی اسکلت بدون تغییر پاس می‌شوند.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .data import Candle


@dataclass(frozen=True)
class AlignedBar:
    """یک ردیف نهایی برای بک‌تست: کندل تریگر + آخرین کندل(های) بسته‌شدهٔ
    تایم‌فریم(های) بالاتر که مجاز به دیدنشان هستیم."""
    low_tf_candle: Candle
    higher_tf_candle: Optional[Candle]        # None اگر داده کافی نباشد
    bias_tf_candle: Optional[Candle] = None   # لایهٔ اختیاری بایاس (مثلاً 4h)
    higher_idx: int = -1                      # ایندکس در لیست تایم‌فریم بالاتر
    bias_idx: int = -1                        # ایندکس در لیست لایهٔ بایاس
    low_idx: int = -1                         # ایندکس در لیست تریگر


def _close_time_ms(candle: Candle, timeframe_ms: int) -> int:
    """زمان بسته‌شدن یک کندل = زمان شروع + طول تایم‌فریم."""
    return candle.open_time_ms + timeframe_ms


def get_last_closed_index(higher_tf_close_times_ms: Sequence[int],
                          reference_open_time_ms: int) -> int:
    """ایندکس آخرین کندلِ بسته‌شده یا `-1`.

    پیاده‌سازی با `bisect_right` برای کارایی O(log n) به‌جای حلقهٔ خطی.
    """
    if not higher_tf_close_times_ms:
        return -1
    idx = bisect_right(higher_tf_close_times_ms, reference_open_time_ms)
    return idx - 1          # اگر idx == 0 → هیچ کندلی هنوز بسته نشده → -1


def get_last_closed_candle(higher_tf_candles: Sequence[Candle],
                           higher_tf_close_times_ms: Sequence[int],
                           reference_open_time_ms: int) -> Optional[Candle]:
    """آخرین کندل تایم‌فریم بالاتر که قطعاً قبل از شروع کندل تریگر بسته شده."""
    i = get_last_closed_index(higher_tf_close_times_ms, reference_open_time_ms)
    return None if i < 0 else higher_tf_candles[i]


def align_multi_timeframe(low_tf_candles: Sequence[Candle],
                          low_tf_minutes: int,
                          higher_tf_candles: Sequence[Candle],
                          higher_tf_minutes: int,
                          bias_tf_candles: Optional[Sequence[Candle]] = None,
                          bias_tf_minutes: Optional[int] = None) -> List[AlignedBar]:
    """خروجی نهایی: برای هر کندل تریگر، آخرین کندل بسته‌شدهٔ فیلتر و بایاس.

    هشدار: این تابع هیچ forward-fill کورکورانه‌ای انجام نمی‌دهد. اگر هیچ کندل
    بالاتری هنوز بسته نشده باشد (مثلاً ابتدای داده)، `higher_tf_candle` برابر
    `None` است و لایهٔ سیگنال باید این حالت را «بدون معامله» مدیریت کند.

    :param low_tf_minutes / higher_tf_minutes / bias_tf_minutes: طول تایم‌فریم‌ها
        به دقیقه. این مقادیر **فقط** برای محاسبهٔ close_time استفاده می‌شوند.
    """
    _ = low_tf_minutes          # طول تایم‌فریم تریگر برای هم‌ترازی لازم نیست (مرز = open time)
    higher_tf_ms = higher_tf_minutes * 60 * 1000
    higher_close_times = [_close_time_ms(c, higher_tf_ms) for c in higher_tf_candles]

    bias_close_times: Optional[List[int]] = None
    if bias_tf_candles is not None and bias_tf_minutes is not None:
        bias_tf_ms = bias_tf_minutes * 60 * 1000
        bias_close_times = [_close_time_ms(c, bias_tf_ms) for c in bias_tf_candles]

    result: List[AlignedBar] = []
    for i, low_candle in enumerate(low_tf_candles):
        ref_time = low_candle.open_time_ms
        h_i = get_last_closed_index(higher_close_times, ref_time)
        b_i = -1
        if bias_close_times is not None:
            b_i = get_last_closed_index(bias_close_times, ref_time)
        result.append(AlignedBar(
            low_tf_candle=low_candle,
            higher_tf_candle=None if h_i < 0 else higher_tf_candles[h_i],
            bias_tf_candle=None if b_i < 0 else (bias_tf_candles[b_i] if bias_tf_candles else None),
            higher_idx=h_i,
            bias_idx=b_i,
            low_idx=i,
        ))
    return result


def alignment_coverage(bars: Sequence[AlignedBar]) -> dict:
    """چند درصد کندل‌های تریگر اصلاً لایهٔ فیلتر/بایاسِ معتبر دارند؟

    اگر پوشش پایین باشد، بخش بزرگی از داده «بدون معامله» است و مقایسهٔ آماری
    با سناریوی دیگر بی‌معنا می‌شود → این عدد در گزارش سلامت می‌آید.
    """
    n = len(bars)
    if n == 0:
        return {"bars": 0, "filter_coverage": 0.0, "bias_coverage": 0.0, "both": 0.0}
    hf = sum(1 for b in bars if b.higher_tf_candle is not None)
    bs = sum(1 for b in bars if b.bias_tf_candle is not None)
    both = sum(1 for b in bars if b.higher_tf_candle is not None and b.bias_tf_candle is not None)
    return {
        "bars": n,
        "filter_coverage": round(hf / n, 4),
        "bias_coverage": round(bs / n, 4),
        "both": round(both / n, 4),
        "first_usable_bar": next((i for i, b in enumerate(bars) if b.higher_tf_candle is not None), -1),
    }


def leakage_audit(bars: Sequence[AlignedBar], higher_tf_minutes: int,
                  bias_tf_minutes: Optional[int] = None,
                  bias_tf_candles: Optional[Sequence[Candle]] = None) -> dict:
    """خودآزمایی نشتی: هیچ کندل بالاتری با close_time > trigger_open استفاده نشده.

    این تابع در selftest و در تست‌ها اجرا می‌شود و اگر حتی یک مورد نقض باشد،
    `clean=False` برمی‌گرداند. این قوی‌ترین تضمین عملی ضد lookahead است
    (چون روی خروجی واقعیِ هم‌ترازی بررسی می‌کند، نه فقط روی منطق).
    """
    h_ms = higher_tf_minutes * 60 * 1000
    b_ms = (bias_tf_minutes or 0) * 60 * 1000
    violations = []
    for b in bars:
        t = b.low_tf_candle.open_time_ms
        if b.higher_tf_candle is not None and _close_time_ms(b.higher_tf_candle, h_ms) > t:
            violations.append({"layer": "filter", "trigger_ts": t,
                               "higher_close": _close_time_ms(b.higher_tf_candle, h_ms)})
        if b.bias_tf_candle is not None and b_ms and _close_time_ms(b.bias_tf_candle, b_ms) > t:
            violations.append({"layer": "bias", "trigger_ts": t,
                               "higher_close": _close_time_ms(b.bias_tf_candle, b_ms)})
    return {"clean": not violations, "violations": len(violations),
            "sample": violations[:5], "bars_checked": len(bars)}
