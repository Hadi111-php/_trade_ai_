"""تست‌های زمان/منطقهٔ زمانی و انبار داده.

چرا این دو با هم؟

- **زمان**: اگر جایی از ساعت محلی استفاده شده باشد، همان کد روی گوشیِ کاربر
  (تهران) و روی CI (UTC) دو نتیجهٔ متفاوت می‌دهد — و هیچ‌وقت نمی‌فهمیم کدام
  درست است. تست `test_engine_results_are_identical_in_any_local_timezone`
  این را قطعی می‌کند: سه منطقهٔ زمانی، خروجی باید بیت‌به‌بیت یکی باشد.
- **انبار**: اگر داده دوباره دانلود شود یا فایلش عوض شود، حکم بی‌اعتبار می‌شود.
  تست‌های `store` قفل می‌کنند که فهرست نوشته شود و دست‌کاری فایل دیده شود.
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.data import (normalize_epoch_ms, resample_up,             # noqa: E402
                         synthetic_candles)
from mtflab.autoscan import (build_layers, candles_to_json,          # noqa: E402
                             fetch_or_load, run_variant, variants_for)
from mtflab.config import load_config                                # noqa: E402

CFG = load_config(["--data", "synthetic", "--quiet"])


def _fresh(cs, tf="15m"):
    """آخرین کندل را روی «الان» می‌گذارد (برای تست کش/سلامت)."""
    from dataclasses import replace
    step = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}[tf] * 60_000
    last = cs[-1].open_time_ms
    shift = ((int(time.time() * 1000) // step) * step) - last
    return [replace(c, open_time_ms=c.open_time_ms + shift) for c in cs]


# ═══════════════════════════════════════════════════════════════════════════
# ۱) منطقهٔ زمانی نباید هیچ اثری روی نتیجه داشته باشد
# ═══════════════════════════════════════════════════════════════════════════
def test_engine_results_are_identical_in_any_local_timezone():
    """UTC / تهران / نیویورک ⇒ همان تعداد معامله، همان PnL، همان سال‌ها.

    این تست کل زنجیره را می‌سنجد: resample، alignment، سال‌بندی، و آمار.
    اگر جایی `datetime.now()` یا `localtime` باقی مانده باشد، همین‌جا می‌شکند.
    """
    cs = synthetic_candles("15m", 4000, seed=21)
    L = build_layers(cs, "15m", "1h", "4h", bias_enabled=True)

    def run_all():
        out = {}
        for vid, _label, over in variants_for("15m", "1h", "4h"):
            r = run_variant(CFG, L, over)
            out[vid] = (r["n"], round(r["pnl"], 6), r["profit_factor"],
                        r["positive_years"], r["years_n"])
        return out

    old = os.environ.get("TZ")
    try:
        results = []
        for tz in ("UTC", "Asia/Tehran", "America/New_York", "Asia/Kolkata"):
            os.environ["TZ"] = tz
            time.tzset()
            results.append(run_all())
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()

    assert results[0] == results[1] == results[2] == results[3], \
        "نتیجه به منطقهٔ زمانی محلی وابسته است — یعنی جایی از ساعت محلی استفاده شده"


def test_daily_buckets_start_at_utc_midnight():
    """کندل روزانه باید از ۰۰:۰۰ UTC شروع شود، نه از نیمه‌شب محلی."""
    cs = synthetic_candles("1h", 24 * 12, seed=2)
    daily, _ = resample_up(cs, "1h", "1d")
    assert daily
    assert all(c.open_time_ms % 86_400_000 == 0 for c in daily)


def test_hourly_buckets_start_on_the_hour():
    """۱۵m → ۱h باید دقیقاً روی مرز ساعت (۰۰ دقیقه) بیفتد."""
    cs = synthetic_candles("15m", 15 * 96, seed=2)
    hourly, _ = resample_up(cs, "15m", "1h")
    assert hourly
    assert all(c.open_time_ms % 3_600_000 == 0 for c in hourly)


def test_epoch_units_are_normalised():
    """ثانیه/میلی‌ثانیه/میکرو/نانو همه باید به میلی‌ثانیه برسند."""
    base = 1_700_000_000_000
    assert normalize_epoch_ms(base // 1000) == base      # ثانیه
    assert normalize_epoch_ms(base) == base             # میلی‌ثانیه
    assert normalize_epoch_ms(base * 1000) == base      # میکرو
    assert normalize_epoch_ms(base * 1_000_000) == base  # نانو


def test_csv_with_seconds_is_read_as_ms():
    """CSV با زمان ثانیه‌ای نباید «۱۹۷۰» خوانده شود."""
    from mtflab.data import csv_candles
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("ts,open,high,low,close,volume\n")
            for i in range(3):
                f.write(f"{1_700_000_000 + i * 3600},{100+i},{101+i},{99+i},"
                        f"{100.5+i},10\n")
        cs = csv_candles(p)
    assert len(cs) == 3
    assert cs[0].open_time_ms == 1_700_000_000_000


def test_csv_with_textual_dates_fails_loudly():
    """تاریخ متنی منطقهٔ زمانی ندارد؛ بهتر است خطا بدهد تا بی‌صدا جابه‌جا کند."""
    from mtflab.data import csv_candles
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("ts,open,high,low,close,volume\n")
            f.write("2024-01-01 00:00:00,100,101,99,100.5,10\n")
        try:
            csv_candles(p)
        except ValueError as e:
            assert "یونیکس" in str(e)
        else:
            raise AssertionError("باید ValueError می‌داد")


# ═══════════════════════════════════════════════════════════════════════════
# ۲) کش: کوتاه‌تر از بازهٔ درخواستی نباید پذیرفته شود
# ═══════════════════════════════════════════════════════════════════════════
def test_cache_is_reused_but_a_longer_window_forces_redownload():
    """۷۳۰ روز کش، برای درخواست ۱۴۶۰ روز کافی نیست — وگرنه گزارش دروغ می‌گوید."""
    import mtflab.bybit_public as BP
    calls = []
    real = BP.fetch_klines_range

    def fake(symbol, tf, days, **kw):
        calls.append(days)
        return _fresh(synthetic_candles(tf, int(days * 96), seed=4))

    BP.fetch_klines_range = fake
    try:
        with tempfile.TemporaryDirectory() as td:
            _c, m1 = fetch_or_load("BTCUSDT", "15m", 60, td, "")
            _c, m2 = fetch_or_load("BTCUSDT", "15m", 60, td, "")   # از کش
            _c, m3 = fetch_or_load("BTCUSDT", "15m", 120, td, "")  # باید دانلود کند
    finally:
        BP.fetch_klines_range = real

    assert calls == [60, 120], calls
    assert m1.get("from_cache") is not True
    assert m2.get("from_cache") is True
    assert m3.get("from_cache") is not True


# ═══════════════════════════════════════════════════════════════════════════
# ۳) انبار داده: یک فایل که همه‌چیز را ثبت می‌کند
# ═══════════════════════════════════════════════════════════════════════════
def _make_dataset(td, symbol="BTCUSDT", tf="15m", n=600):
    cs = _fresh(synthetic_candles(tf, n, seed=8))
    os.makedirs(os.path.join(td, "json"), exist_ok=True)
    path = os.path.join(td, "json", f"{symbol.lower()}_{tf}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(candles_to_json(cs, {"symbol": symbol, "tf": tf, "days": 30}), f)
    return path, cs


def test_reindex_records_existing_files_and_verify_passes():
    from mtflab.store import index_path, read_index, reindex, verify
    with tempfile.TemporaryDirectory() as td:
        _make_dataset(td)
        rep = reindex(td)
        assert rep["added"] == 1
        assert os.path.exists(index_path(td))
        idx = read_index(td)
        assert "BTCUSDT_15m" in idx["datasets"]
        e = idx["datasets"]["BTCUSDT_15m"]
        assert e["n"] == 600 and e["sha256"] and e["content_sha256"]
        assert all(r["status"] == "ok" for r in verify(td, deep=True))


def test_verify_detects_a_tampered_file():
    """اگر یک کندل عوض شود، باید دیده شود — وگرنه حکم روی دادهٔ ناشناس است."""
    from mtflab.store import reindex, verify
    with tempfile.TemporaryDirectory() as td:
        path, cs = _make_dataset(td)
        reindex(td)
        assert verify(td, deep=True)[0]["status"] == "ok"

        payload = json.loads(open(path, encoding="utf-8").read())
        payload["candles"][10][4] = float(payload["candles"][10][4]) + 1.0
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        assert verify(td, deep=True)[0]["status"] == "changed"


def test_verify_reports_a_deleted_file():
    from mtflab.store import reindex, verify
    with tempfile.TemporaryDirectory() as td:
        path, _ = _make_dataset(td)
        reindex(td)
        os.remove(path)
        assert verify(td)[0]["status"] == "missing"


def test_index_report_says_no_download_is_needed():
    from mtflab.store import reindex, render_index
    with tempfile.TemporaryDirectory() as td:
        _make_dataset(td)
        reindex(td)
        fa = render_index(td, lang="fa")
        en = render_index(td, lang="en")
    assert "BTCUSDT_15m" in fa and "BTCUSDT_15m" in en
    assert "دانلود" in fa
    assert "downloads nothing" in en
