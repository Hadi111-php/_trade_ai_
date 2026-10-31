"""تست‌های واحد برای اطمینان از عدم lookahead در alignment.py.

این تست‌ها همان تست‌های اسکلت اصلی سناریو هستند (بدون تغییر در منطق) و
علاوه بر آن‌ها چند تست جدید برای `higher_idx`/`bias_idx` و حسابرسی نشتی.
هم با `python3 tests/run_tests.py` و هم با `pytest` قابل اجرا هستند.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.alignment import (align_multi_timeframe, alignment_coverage,  # noqa: E402
                              get_last_closed_candle, get_last_closed_index,
                              leakage_audit)
from mtflab.data import Candle  # noqa: E402

H = 3_600_000        # 1h
Q = 900_000          # 15m


def make_candle(open_time_ms: int, close: float = 100.0) -> Candle:
    return Candle(open_time_ms=open_time_ms, open=close, high=close, low=close,
                  close=close, volume=1.0)


def test_get_last_closed_candle_basic():
    higher = [make_candle(0), make_candle(H), make_candle(2 * H)]
    close_times = [H, 2 * H, 3 * H]
    # کندل 15m که در 5_000_000 شروع می‌شود:
    # کندل 1h اول close=3_600_000 <= 5_000_000 → مجاز
    # کندل 1h دوم close=7_200_000 > 5_000_000 → غیرمجاز
    result = get_last_closed_candle(higher, close_times, reference_open_time_ms=5_000_000)
    assert result is not None
    assert result.open_time_ms == 0


def test_no_lookahead_when_nothing_closed_yet():
    higher = [make_candle(10_000_000)]
    close_times = [13_600_000]
    result = get_last_closed_candle(higher, close_times, reference_open_time_ms=1_000_000)
    assert result is None
    assert get_last_closed_index(close_times, 1_000_000) == -1


def test_align_multi_timeframe_no_forward_fill_blind():
    low_tf = [make_candle(0), make_candle(Q)]
    aligned = align_multi_timeframe(low_tf_candles=low_tf, low_tf_minutes=15,
                                    higher_tf_candles=[], higher_tf_minutes=60)
    for bar in aligned:
        assert bar.higher_tf_candle is None
        assert bar.higher_idx == -1


def test_boundary_candle_that_closes_exactly_at_trigger_open_is_allowed():
    """کندل 1h با close=H و کندل 15m با open=H → مجاز (اطلاعات در H موجود است)."""
    higher = [make_candle(0), make_candle(H)]
    aligned = align_multi_timeframe([make_candle(H)], 15, higher, 60)
    assert aligned[0].higher_tf_candle is not None
    assert aligned[0].higher_tf_candle.open_time_ms == 0      # نه کندل جاریِ 1h
    assert aligned[0].higher_idx == 0


def test_candle_closing_after_trigger_open_is_forbidden():
    higher = [make_candle(0), make_candle(H)]
    aligned = align_multi_timeframe([make_candle(Q)], 15, higher, 60)   # t=15m < 1h
    assert aligned[0].higher_tf_candle is None


def test_bias_layer_aligned_independently():
    bias = [make_candle(0), make_candle(4 * H)]
    higher = [make_candle(0), make_candle(H), make_candle(2 * H)]
    # ۲۰ کندل 15m → تا t=18_000_000 که بعد از close اولین کندل 4h (14_400_000) است
    lows = [make_candle(Q * k) for k in range(1, 21)]
    aligned = align_multi_timeframe(lows, 15, higher, 60, bias, 240)
    assert aligned[0].bias_tf_candle is None                 # هنوز 4h بسته نشده
    assert aligned[7].bias_tf_candle is None                 # t=7.2M < 14.4M
    assert aligned[-1].bias_tf_candle is not None            # t=18.0M > 14.4M
    assert aligned[-1].bias_tf_candle.open_time_ms == 0      # کندل 4h دوم در آینده است
    assert leakage_audit(aligned, 60, 240)["clean"] is True


def test_leakage_audit_detects_violation():
    """اگر کسی عمداً کندلِ بسته‌نشده را بدهد، حسابرسی باید لو بدهد."""
    higher = [make_candle(0), make_candle(H)]
    # ساخت دستی AlignedBar با کندل 1h جاری برای تریگرِ داخل همان ساعت
    from mtflab.alignment import AlignedBar
    bad = [AlignedBar(low_tf_candle=make_candle(Q), higher_tf_candle=higher[1],
                      higher_idx=1, low_idx=0)]
    audit = leakage_audit(bad, 60)
    assert audit["clean"] is False
    assert audit["violations"] == 1


def test_alignment_coverage_counts_none():
    higher = [make_candle(0)]
    lows = [make_candle(0), make_candle(Q), make_candle(H), make_candle(H + Q)]
    cov = alignment_coverage(align_multi_timeframe(lows, 15, higher, 60))
    assert cov["bars"] == 4
    assert cov["filter_coverage"] == 0.5       # فقط دو کندلِ بعد از H پوشش دارند
    assert cov["bias_coverage"] == 0.0
