"""تست‌های ابزار اسکن خودکار (autoscan) — آنچه روی گوشی کاربر اجرا می‌شود.

چرا این تست‌ها مهم‌اند: این ابزار بدون نظارت اجرا می‌شود و خروجی‌اش مبنای
قضاوت بعدی است. پس سه چیز باید قفل شود:

1. **دادهٔ ذخیره‌شده همان دادهٔ اصلی است** (رفت‌وبرگشت JSON بدون تغییر)
2. **دروازهٔ پذیرش واقعاً می‌تواند شکست بخورد** (تست منفی؛ وگرنه تزئینی است)
3. **همهٔ نسخه‌ها روی یک تایم‌فریم اجرا می‌شوند** (مقایسهٔ منصفانه)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.autoscan import (GATE, aggregate, build_layers,          # noqa: E402
                             candles_from_json, candles_to_json,
                             discover_cached_symbols, _json_path,
                             variants_for, VERSION)
from mtflab.config import load_config, PRESETS                      # noqa: E402
from mtflab.data import synthetic_candles                            # noqa: E402


# ── ۱) ذخیره/بازخوانی JSON ───────────────────────────────────────────────────
def test_json_roundtrip_is_lossless():
    """دادهٔ ذخیره‌شده باید بیت‌به‌بیت همان کندل اصلی باشد."""
    cs = synthetic_candles("4h", 300, seed=11)
    payload = candles_to_json(cs, {"symbol": "TESTUSDT", "tf": "4h"})
    back = candles_from_json(json.loads(json.dumps(payload)))
    assert len(back) == len(cs)
    for a, b in zip(cs, back):
        assert (a.open_time_ms, a.open, a.high, a.low, a.close) == \
               (b.open_time_ms, b.open, b.high, b.low, b.close)


def test_json_payload_has_meta_and_schema_version():
    """بستهٔ JSON باید خودتوصیف باشد: نسخه، نماد، تایم‌فریم، تعداد."""
    cs = synthetic_candles("1d", 60)
    p = candles_to_json(cs, {"symbol": "btcusdt", "tf": "1d"})
    assert p["meta"]["symbol"] == "btcusdt"
    assert p["meta"]["tf"] == "1d"
    assert p["meta"]["n"] == 60
    assert "schema" in p["meta"] or "version" in p["meta"]
    assert len(p["candles"]) == 60


def test_json_path_is_stable_and_lowercase():
    """نام فایل کش باید قابل پیش‌بینی باشد (وگرنه ادامهٔ کار بعد از قطعی می‌شکند)."""
    a = _json_path("/x/data", "BTCUSDT", "4h")
    b = _json_path("/x/data", "btcusdt", "4h")
    assert a == b
    assert a.endswith(os.path.join("json", "btcusdt_4h.json"))


def test_discover_cached_symbols_only_returns_matching_tf():
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "json")
        os.makedirs(d)
        for name in ("btcusdt_4h.json", "ethusdt_4h.json", "solusdt_1h.json"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("{}")
        got = discover_cached_symbols(td, "4h")
        assert got == ["BTCUSDT", "ETHUSDT"]


# ── ۲) لایه‌ها و نسخه‌ها ─────────────────────────────────────────────────────
def test_build_layers_with_bias_disabled_returns_empty_bias():
    """در پریست trend بایاس خاموش است؛ لایهٔ بایاس نباید ساخته شود."""
    trig = synthetic_candles("4h", 500)
    layers = build_layers(trig, "4h", "1d", "1d", bias_enabled=False)
    assert layers["bias"] == []
    assert len(layers["filter"]) > 0 and len(layers["filter"]) < len(trig)


def test_variants_all_use_the_scan_timeframe():
    """مقایسهٔ منصفانه: هیچ نسخه‌ای نباید تایم‌فریم خودش را تحمیل کند."""
    vs = variants_for("4h", "1d", "1d")
    assert [v[0] for v in vs][0] == "base"
    for vid, _label, over in vs:
        assert over["tf_trigger"] == "4h", vid
        assert over["tf_filter"] == "1d", vid
        assert over["tf_bias"] == "1d", vid


def test_trend_variant_matches_the_documented_preset():
    """نسخهٔ trend باید دقیقاً همان پریست مستند trend_4h باشد (نه کپی دستی)."""
    trend = dict(PRESETS["trend_4h"])
    for k in ("tf_trigger", "tf_filter", "tf_bias"):
        trend.pop(k, None)
    got = dict([v for v in variants_for("4h", "1d", "1d") if v[0] == "trend"][0][2])
    for k in ("tf_trigger", "tf_filter", "tf_bias"):
        got.pop(k, None)
    assert got == trend


def test_gate_thresholds_are_fixed_values():
    """دروازه از پیش ثبت شده؛ تغییرش باید آگاهانه باشد، نه تصادفی."""
    assert GATE["min_symbols"] == 8
    assert GATE["min_profitable_symbols_pct"] == 60.0
    assert GATE["min_positive_years_pct"] == 60.0
    assert GATE["min_sign_test_p"] == 0.10
    assert VERSION


# ── ۳) ریاضیات دروازه (شامل تست منفی) ───────────────────────────────────────
def _row(n, pf, exp, pnl, years_n=3, pos=3):
    return {"n": n, "profit_factor": pf, "expectancy": exp, "pnl": pnl,
            "years_n": years_n, "positive_years": pos}


def test_aggregate_rejects_a_small_sample_even_if_perfect():
    """۲ نمادِ عالی نباید قبول شود — کم بودن نمونه خودش دلیل رد است."""
    per = {"A": {"base": _row(50, 1.0, 0.0, 0.0), "v": _row(120, 3.0, 9.0, 500.0)},
           "B": {"base": _row(50, 1.0, 0.0, 0.0), "v": _row(120, 2.5, 8.0, 400.0)}}
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["checks"]["symbols"] is False
    assert agg["v"]["survived"] is False


def test_aggregate_rejects_when_sign_test_is_not_significant():
    """حتی با ۸ نمادِ سودده، اگر برتری بر پایه در ۵ از ۸ باشد، p زیاد است → رد."""
    per = {}
    for i in range(8):
        better = i < 5
        per[f"S{i}"] = {"base": _row(100, 1.0, 0.0, 0.0),
                        "v": _row(200, 1.5, 2.0, 100.0,
                                  pos=3 if better else 2)}
        if not better:
            # expectancy پایین‌تر از پایه → بازندهٔ آزمون علامت
            per[f"S{i}"]["v"] = _row(200, 1.2, -0.5, -20.0, pos=2)
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["sign_vs_base"]["wins"] == 5
    assert agg["v"]["checks"]["significance"] is False
    assert agg["v"]["survived"] is False


def test_aggregate_accepts_only_when_every_check_passes():
    """تست مثبت: با نمونهٔ بزرگ، همهٔ نمادها بهتر، سال‌های مثبت کافی → قبول."""
    per = {f"S{i}": {"base": _row(100, 1.0, 0.0, 0.0),
                     "v": _row(250, 1.6, 3.0, 200.0)}
           for i in range(10)}
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["checks"] == {"symbols": True, "trades": True,
                                  "profitable_symbols": True,
                                  "positive_years": True, "median_pf": True,
                                  "significance": True}
    assert agg["v"]["survived"] is True


def test_aggregate_can_fail_on_median_pf_only():
    """یک شرط شکست بخورد کافی است — دروازه «همه یا هیچ» است."""
    per = {f"S{i}": {"base": _row(100, 1.0, 0.0, 0.0),
                     "v": _row(250, 1.02, 3.0, 50.0)}     # PF < 1.05
           for i in range(10)}
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["checks"]["median_pf"] is False
    assert agg["v"]["survived"] is False


def test_aggregate_never_lets_base_win_by_significance_default():
    """پایه با خودش مقایسه نمی‌شود؛ ولی شرط معناداری‌اش نباید خودکار «قبول» شود."""
    per = {f"S{i}": {"base": _row(100, 0.9, -1.0, -50.0, pos=1)} for i in range(10)}
    agg = aggregate(per, ["base"])
    assert agg["base"]["sign_vs_base"] is None
    assert agg["base"]["survived"] is False       # PF<1 و سال منفی → رد


# ── ۴) کانفیگ با دادهٔ ساختگی (بدون شبکه) ───────────────────────────────────
def test_autoscan_config_does_not_require_network():
    """کانفیگ باید آفلاین ساخته شود؛ فقط دانلود به شبکه نیاز دارد."""
    cfg = load_config(["--data", "synthetic", "--quiet"])
    assert cfg.data_mode in ("synthetic", "csv")
    assert cfg.fee_bps > 0


# ── ۵) اثر انگشت داده ───────────────────────────────────────────────────────
def test_fingerprint_is_stable_and_detects_any_change():
    """اگر یک کندل عوض شود، اثر انگشت باید عوض شود (تشخیص دستکاری/دادهٔ دیگر)."""
    from mtflab.autoscan import data_fingerprint
    cs = synthetic_candles("4h", 100, seed=3)
    f1 = data_fingerprint(cs)
    assert f1 == data_fingerprint(synthetic_candles("4h", 100, seed=3))
    assert len(f1) == 16
    cs2 = list(cs)
    from mtflab.data import Candle
    cs2[-1] = Candle(cs[-1].open_time_ms, cs[-1].open, cs[-1].high, cs[-1].low,
                     cs[-1].close * 1.001, cs[-1].volume)
    assert data_fingerprint(cs2) != f1
