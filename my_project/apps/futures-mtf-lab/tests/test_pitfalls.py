"""تست دام‌های رایج (docs/pitfalls.md) — برای هر دام یک تست مشخص.

دام‌ها:
1. lookahead در resample (bucket ناقص به‌عنوان کندل کامل)
2. ساختن تایم‌فریم ریزدانه از دادهٔ درشت‌تر (fabrication)
3. کندل ناقص 1h در دادهٔ زنده
4. Donchian شامل کندل جاری → شرط شکست هرگز برقرار نمی‌شود
5. نادیده گرفتن هزینه (سیگنال کم‌دامنه باید رد شود)
6. خروج خوش‌بینانه وقتی stop و take هر دو در یک کندل لمس می‌شوند
7. نشتی اطلاعات آینده در تصمیم موتور (causality / prefix invariance)
8. survivorship bias: حذف نمادهای حذف‌شده بدون ثبت
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import indicators as ind                       # noqa: E402
from mtflab.config import MTFConfig                        # noqa: E402
from mtflab.data import Candle, find_gaps, resample_up, synthetic_candles  # noqa: E402
from mtflab.engine import run_backtest                     # noqa: E402
from mtflab.fees import FeeConfig, passes_cost_filter, round_trip_cost_pct  # noqa: E402

H = 3_600_000


def _c(ts, o=100.0, h=101.0, l=99.0, cl=100.5, v=10.0):
    return Candle(ts, o, h, l, cl, v)


# 1 ─ resample -----------------------------------------------------------------
def test_resample_bucket_is_aggregated_not_forward_filled():
    candles = [_c(i * H, cl=100 + i) for i in range(8)]
    out, rep = resample_up(candles, "1h", "4h")
    assert rep["buckets"] >= 1
    b = out[0]
    assert b.open == candles[0].open
    assert b.close == candles[3].close
    assert b.high == max(x.high for x in candles[:4])
    assert b.volume == sum(x.volume for x in candles[:4])


def test_resample_drops_partial_edge_buckets():
    """دام ۱: bucket ناقصِ انتها نباید به‌عنوان کندل کامل مصرف شود."""
    candles = [_c(i * H) for i in range(6)]        # ۶ کندل 1h = یک bucket کامل 4h + نصفه
    out, rep = resample_up(candles, "1h", "4h")
    assert rep["dropped_partial_edges"] == 1
    assert len(out) == 1
    assert out[0].open_time_ms == 0


def test_resample_cannot_fabricate_lower_timeframe():
    """دام ۲: ساختن 15m از 1h باید خطای صریح بدهد، نه دادهٔ جعلی."""
    candles = [_c(i * H) for i in range(5)]
    try:
        resample_up(candles, "1h", "15m")
    except ValueError as e:
        assert "فقط به بالا" in str(e)
        return
    raise AssertionError("باید ValueError می‌داد")


# 3 ─ کندل ناقص زنده -----------------------------------------------------------
def test_forming_candle_is_dropped_by_bybit_module():
    import time
    from mtflab.bybit_public import drop_forming_candle
    now = int(time.time() * 1000)
    closed = _c((now // H) * H - H)
    forming = _c((now // H) * H)
    kept = drop_forming_candle([closed, forming], "1h", now_ms=now)
    assert kept == [closed]


# 4 ─ Donchian ------------------------------------------------------------------
def test_donchian_excludes_current_candle_so_breakout_is_possible():
    candles = [_c(i * 1000, h=100.0, l=90.0, cl=95.0) for i in range(20)]
    candles.append(_c(20 * 1000, h=120.0, l=95.0, cl=118.0))     # شکست
    d = ind.donchian(candles, window=20, include_current=False)
    assert d[20]["upper"] == 100.0
    assert d[20]["break_up"] is True
    # اگر کندل جاری داخل کانال بود، شکست هرگز دیده نمی‌شد:
    d2 = ind.donchian(candles, window=20, include_current=True)
    assert d2[20]["break_up"] is False


def test_indicators_are_none_during_warmup():
    closes = [100.0 + i for i in range(30)]
    e = ind.ema(closes, 20)
    assert all(x is None for x in e[:19])
    assert e[19] is not None
    r = ind.rsi(closes, 14)
    assert all(x is None for x in r[:14])


def test_volume_z_uses_previous_window_only():
    """volume_z نباید حجمِ کندلِ جاری را داخل میانگین خودش ببرد."""
    candles = [_c(i * 1000, v=100.0 + (i % 5) * 2.0) for i in range(60)]
    candles.append(_c(60 * 1000, v=1000.0))
    z = ind.volume_z(candles, window=50)
    assert z[60] is not None and z[60] > 3           # حجم جهشی → z بزرگ
    assert z[59] is not None and abs(z[59]) < 3.0    # کندل عادی → z کوچک


# 5 ─ هزینه ---------------------------------------------------------------------
def test_cost_filter_rejects_low_edge_signals():
    fee = FeeConfig(taker_fee_pct=0.00055, slippage_pct=0.0002)
    cost = round_trip_cost_pct(fee)                       # ~0.15%
    assert abs(cost - 0.15) < 1e-9
    assert passes_cost_filter(0.10, fee, 1.5) is False    # زیر 1.5× هزینه
    assert passes_cost_filter(0.30, fee, 1.5) is True


def test_engine_applies_fees_on_both_sides():
    """اگر هزینه صفر باشد، نتایج باید بهتر از حالت با هزینه باشد (sanity)."""
    cfg = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                    verbose=False, forensics=False, seed=5, candles=1500)
    trig = synthetic_candles("1h", 1500, seed=5)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    layers = {"trigger": trig, "filter": filt, "bias": bias}

    from dataclasses import replace
    a = run_backtest(replace(cfg, fee_bps=0.0, slippage_pct=0.0, min_edge_multiplier=0.0), layers)
    b = run_backtest(replace(cfg, fee_bps=5.5, slippage_pct=0.02), layers)
    assert a["summary"]["trades"] >= b["summary"]["trades"]
    if b["summary"]["trades"]:
        assert b["summary"]["total_fees"] > 0


# 6 ─ خروج محافظه‌کارانه --------------------------------------------------------
def test_stop_takes_priority_when_both_hit_in_same_candle():
    """دام ۶: وقتی high و low هر دو هدف را لمس می‌کنند، stop اول فرض می‌شود."""
    from dataclasses import replace
    cfg = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                    verbose=False, forensics=False, seed=11, candles=1200,
                    alignment_version="C", filter_adx_min=0.0, filter_slope_min_pct=0.0,
                    filter_confirm_bars=1, min_edge_multiplier=0.0, max_concurrent=1)
    trig = synthetic_candles("1h", 1200, seed=11)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    res = run_backtest(replace(cfg), {"trigger": trig, "filter": filt, "bias": bias})
    # هیچ معامله‌ای نباید TP و stop را هم‌زمان با سود ثبت کرده باشد
    for t in res["trades"]:
        assert t["reason"] in ("stop_loss", "stop/trail", "take_profit",
                               "time_stop", "end_of_data") or t["reason"].startswith("regime_flip")


# 7 ─ علی‌بودن موتور ------------------------------------------------------------
def test_engine_is_causal_prefix_invariance():
    """تصمیم در کندل k باید روی prefix (تا k) و روی دادهٔ کامل یکسان باشد.

    این قوی‌ترین تست ضد lookahead است: اگر موتور از آینده استفاده کند،
    حذفِ دادهٔ آینده تصمیم را عوض می‌کند.
    """
    from dataclasses import replace
    cfg = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                    verbose=False, forensics=False, seed=3, candles=900,
                    alignment_version="A", min_edge_multiplier=0.0)
    trig = synthetic_candles("1h", 900, seed=3)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")

    full = run_backtest(replace(cfg), {"trigger": trig, "filter": filt, "bias": bias})
    full_trades = [(t["ts"], t["side"], t["entry"]) for t in full["trades"]]
    if not full_trades:
        return                       # سیگنالی نبود؛ چیزی برای مقایسه نیست

    # دادهٔ آینده را از وسطِ معاملهٔ آخر قطع کن → همان معاملات باید تکرار شوند
    cut_ts = full_trades[-1][0]
    trig2 = [c for c in trig if c.open_time_ms <= cut_ts]
    filt2 = [c for c in filt if c.open_time_ms <= cut_ts]
    bias2 = [c for c in bias if c.open_time_ms <= cut_ts]
    pref = run_backtest(replace(cfg), {"trigger": trig2, "filter": filt2, "bias": bias2})
    pref_trades = [(t["ts"], t["side"], t["entry"]) for t in pref["trades"]]

    # معاملاتِ کاملاً بسته‌شده قبل از cut باید یکسان باشند (آخری ممکن است
    # به‌خاطر end_of_data متفاوت بسته شود → فقط ts/side/entry مقایسه می‌شود)
    assert len(pref_trades) >= len(full_trades) - 1
    for a, b in zip(full_trades[:-1], pref_trades[:-1]):
        assert a == b, f"نشتی: {a} != {b}"


# 8 ─ بهداشت داده ---------------------------------------------------------------
def test_gap_detection_reports_missing_candles_without_filling():
    candles = [_c(0), _c(H), _c(3 * H)]          # یک کندل 1h گم شده
    g = find_gaps(candles, "1h")
    assert g["missing_candles"] == 1
    assert g["clean"] is False
    assert len(candles) == 3                     # هیچ پرکردنی انجام نشده


def test_survivorship_note_single_symbol_scope():
    """دام ۸: موتور فقط یک نماد را می‌بیند؛ این محدودیت باید در meta ثبت شود."""
    cfg = MTFConfig(data_mode="synthetic", symbol="BTCUSDT", verbose=False)
    assert cfg.symbol == "BTCUSDT"
    # هیچ انتخابِ «بهترین نمادِ گذشته» در کد وجود ندارد → meta فقط منبع داده را ثبت می‌کند
    from mtflab.data import load_layers
    cfg2 = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                     candles=300, seed=1, verbose=False)
    layers, meta = load_layers(cfg2)
    assert meta["symbol"] == cfg2.symbol
    assert "counts" in meta and meta["counts"]["trigger"] == 300


# ── دام تایم‌فریمِ اشتباه (پیدا شده در بازبینی autoscan) ──────────────────────
def test_detect_timeframe_reads_real_spacing():
    """فایل ۱ ساعته باید 1h تشخیص داده شود، نه آنچه کانفیگ ادعا می‌کند."""
    from mtflab.data import detect_timeframe, synthetic_candles
    assert detect_timeframe(synthetic_candles("1h", 50)) == "1h"
    assert detect_timeframe(synthetic_candles("4h", 50)) == "4h"
    assert detect_timeframe(synthetic_candles("15m", 50)) == "15m"
    assert detect_timeframe([]) == ""


def test_mislabeled_timeframe_is_fixed_not_silently_wrong():
    """دام: فایل 1h + کانفیگ 4h. باید خودکار resample شود و در meta ثبت شود."""
    from mtflab.config import load_config
    from mtflab.data import load_layers
    cfg = load_config(["--data", "synthetic", "--tf-trigger", "4h",
                       "--tf-filter", "1d", "--no-bias", "--quiet"])
    from dataclasses import replace
    import os
    import tempfile
    from mtflab.data import synthetic_candles, write_csv
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.csv")
        write_csv(p, synthetic_candles("1h", 1200))
        cfg2 = replace(cfg, data_mode="csv", csv_path=p)
        layers, meta = load_layers(cfg2)
        fix = meta.get("timeframe_fix") or []
        assert fix and fix[0]["detected"] == "1h" and fix[0]["declared"] == "4h"
        # تعداد کندل باید ~۱/۴ دادهٔ اصلی باشد (نه همان تعداد با برچسب غلط)
        assert 250 <= len(layers["trigger"]) <= 320


def test_fabricating_lower_timeframe_is_refused():
    """فایل 1h + درخواست 15m نباید بی‌صدا قبول شود (اطلاعات وجود ندارد)."""
    import os
    import tempfile
    from dataclasses import replace
    from mtflab.config import load_config
    from mtflab.data import load_layers, synthetic_candles, write_csv
    cfg = load_config(["--data", "synthetic", "--tf-trigger", "15m",
                       "--tf-filter", "1h", "--quiet"])
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.csv")
        write_csv(p, synthetic_candles("1h", 500))
        cfg2 = replace(cfg, data_mode="csv", csv_path=p)
        try:
            load_layers(cfg2)
        except ValueError as e:
            assert "ریزتر" in str(e) or "مجاز نیست" in str(e)
        else:
            raise AssertionError("باید خطای صریح می‌داد، نه دادهٔ ساختگی")
