"""تست‌های پروندهٔ زمینه — «صحنهٔ جرم».

مهم‌ترین قفل این فایل: **هیچ عددی از آینده**. اگر این بشکند، هر مقایسهٔ
برد/باخت تبدیل می‌شود به خودفریبی (ویژگی‌ای که فقط بعد از نتیجه معلوم می‌شود).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.context import (FEATURES, SCHEMA, feature_vector,      # noqa: E402
                            snapshot, volatility_regime)
from mtflab.data import Candle, synthetic_candles                  # noqa: E402

STEP = 4 * 3600 * 1000


def test_context_never_looks_ahead():
    cs = synthetic_candles("4h", 400, seed=11)
    i = 350
    kw = dict(swing=0.4, structure=1, recent_r=[-1, 2, 0.5],
              roundtrip_cost_pct=0.15)
    a = snapshot(cs, i, **kw)
    # آینده را کاملاً دگرگون می‌کنیم
    cs2 = list(cs[:i + 1]) + [
        Candle(cs[i].open_time_ms + STEP * (k + 1), 1.0, 1e9, 0.001, 1e8, 1e12)
        for k in range(30)]
    b = snapshot(cs2, i, **kw)
    assert a == b


def test_all_features_are_computed_on_a_long_series():
    cs = synthetic_candles("4h", 500, seed=12)
    s = snapshot(cs, len(cs) - 1, swing=0.3, structure=1,
                 recent_r=[-1, 1, -1], roundtrip_cost_pct=0.15)
    assert s["schema"] == SCHEMA
    for key, _ in FEATURES:
        assert key in s, key
        if key in ("recent_r_mean", "recent_streak", "swing_position"):
            continue
        assert s[key] is not None, key
        assert isinstance(s[key], (int, float))
    assert 0 <= s["rsi"] <= 100
    assert s["adx"] >= 0
    assert s["volatility_regime"] in ("کم", "عادی", "زیاد", "نامعلوم")


def test_cost_to_atr_is_the_ratio_it_claims():
    cs = synthetic_candles("4h", 300, seed=13)
    s = snapshot(cs, len(cs) - 1, roundtrip_cost_pct=0.15)
    assert abs(s["cost_to_atr"] - 0.15 / s["atr_pct"]) < 1e-3


def test_short_series_is_safe():
    cs = synthetic_candles("4h", 5, seed=14)
    s = snapshot(cs, 4)
    assert s["schema"] == SCHEMA
    assert s["adx"] is None            # داده کافی نیست ≠ خطا
    assert s["atr_pct"] is None or s["atr_pct"] >= 0


def test_out_of_range_index_returns_partial_not_crash():
    cs = synthetic_candles("4h", 50, seed=15)
    assert snapshot(cs, 999)["schema"] == SCHEMA
    assert snapshot([], 0)["schema"] == SCHEMA


def test_recent_streak_counts_consecutive_same_sign():
    cs = synthetic_candles("4h", 300, seed=16)
    i = len(cs) - 1
    assert snapshot(cs, i, recent_r=[2, -1, -1, -1])["recent_streak"] == -3
    assert snapshot(cs, i, recent_r=[-1, 2, 3])["recent_streak"] == 2
    assert snapshot(cs, i, recent_r=[])["recent_streak"] is None


def test_volatility_regime_uses_only_past_values():
    hist = [0.2] * 50 + [1.0] * 50
    assert volatility_regime(0.1, [0.1] * 60) == "کم"
    assert volatility_regime(5.0, hist) == "زیاد"
    assert volatility_regime(0.5, hist) == "عادی"
    assert volatility_regime(0.5, []) == "نامعلوم"
    assert volatility_regime(None, hist) == "نامعلوم"


def test_feature_vector_drops_missing_and_nan():
    snap = {"adx": 20.0, "rsi": None, "atr_pct": float("nan"), "hour_utc": 7}
    v = feature_vector(snap)
    assert v == {"adx": 20.0, "hour_utc": 7}


def test_gap_feature_is_measurable_on_real_like_data():
    cs = synthetic_candles("4h", 300, seed=17)
    o = cs[100].open
    cs = list(cs)
    cs[100] = Candle(cs[100].open_time_ms, o * 1.01, cs[100].high,
                     cs[100].low, cs[100].close, cs[100].volume)
    s = snapshot(cs, 100)
    assert s["gap_pct"] is not None and s["gap_pct"] > 0
