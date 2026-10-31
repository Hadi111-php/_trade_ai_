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


# ═══════════════════════════════════════════════════════════════════════════
# ۴) بایگانی: شناسنامهٔ کوچک از دادهٔ بزرگ
# ═══════════════════════════════════════════════════════════════════════════
def test_digest_carries_hashes_ranges_and_samples():
    from mtflab.archive import build_digest
    with tempfile.TemporaryDirectory() as td:
        _make_dataset(td, n=900)
        d = build_digest(td, tag="t")
    assert d["n_datasets"] == 1 and d["n_candles"] == 900
    one = d["datasets"]["BTCUSDT_15m"]
    assert one["sha256"] and one["content_sha256"] and one["bytes"] > 0
    assert one["first_ms"] < one["last_ms"]
    assert len(one["samples"]["head"]) == 3 and len(one["samples"]["tail"]) == 3
    assert d["problems"] == []


def test_monthly_bars_use_utc_month_boundaries():
    from mtflab.archive import monthly_bars
    cs = _fresh(synthetic_candles("15m", 15 * 24 * 40, seed=3))   # ~۴۰ روز
    m = monthly_bars(cs)
    assert m
    for row in m:
        assert len(row) == 6
    # open هر ماه باید با open اولین کندل همان ماه یکی باشد
    assert m[0][1] == cs[0].open
    assert m[-1][4] == cs[-1].close


def test_digest_is_small_even_for_a_long_dataset():
    """شناسنامه باید کوچک بماند: هدف چند صد کیلوبایت برای ۲۰ نماد، نه ۹۰ مگابایت."""
    from mtflab.archive import build_digest
    with tempfile.TemporaryDirectory() as td:
        _make_dataset(td, n=9000)
        js = json.dumps(build_digest(td), ensure_ascii=False, separators=(",", ":"))
    assert len(js.encode("utf-8")) < 200_000, len(js)


def test_digest_hash_changes_when_the_file_changes():
    """اگر داده دست‌کاری شود، هش شناسنامه عوض می‌شود — همان چیزی که می‌خواهیم."""
    from mtflab.archive import build_digest
    with tempfile.TemporaryDirectory() as td:
        path, _ = _make_dataset(td, n=600)
        before = build_digest(td)["datasets"]["BTCUSDT_15m"]["content_sha256"]
        payload = json.loads(open(path, encoding="utf-8").read())
        payload["candles"][3][2] = float(payload["candles"][3][2]) + 0.5
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        after = build_digest(td)["datasets"]["BTCUSDT_15m"]["content_sha256"]
    assert before != after


def test_archive_writes_json_and_markdown_manifest():
    from mtflab.archive import write_archive
    with tempfile.TemporaryDirectory() as td:
        _make_dataset(td, n=600)
        out = os.path.join(td, "out")
        rep = write_archive(td, out, tag="x")
        assert os.path.exists(rep["json"]) and os.path.exists(rep["md"])
        assert rep["sha256"]
        md = open(rep["md"], encoding="utf-8").read()
    assert "BTCUSDT_15m" in md and "UTC" in md


# ═══════════════════════════════════════════════════════════════════════════
# ۵) گارد: گزینهٔ ابزار جانبی نباید بی‌صدا به اسکن تبدیل شود
# ═══════════════════════════════════════════════════════════════════════════
def test_tool_flags_are_refused_by_the_scanner():
    """`--archive`/`--data-index` اسکن نیستند؛ باید پیام روشن بدهند نه اجرای ۴ ساعته."""
    from mtflab.autoscan import autoscan_command
    from mtflab import autoscan as A
    A.set_lang("en")
    try:
        for flag in ("--archive", "--data-index"):
            assert autoscan_command([flag, "--tag", "x"]) == 2
    finally:
        A.set_lang("fa")


def test_app_level_script_handles_archive_and_index():
    """اسکریپت خود اپ هم باید این دو را بشناسد (نه فقط لانچر ریشهٔ مخزن)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(here, "run-auto.sh"), encoding="utf-8").read()
    assert "--archive" in text and "mtflab archive" in text
    assert "--data-index" in text and "mtflab data-index" in text


# ═══════════════════════════════════════════════════════════════════════════
# ۶) سقف نرخ Bybit: نماد نباید کامل حذف شود
# ═══════════════════════════════════════════════════════════════════════════
def _fake_http(responses):
    """urllib.request.urlopen جعلی که پاسخ‌های آماده برمی‌گرداند."""
    seq = list(responses)
    calls = {"n": 0}

    class R:
        status = 200

        def __init__(self, data):
            self._d = data

        def read(self):
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _open(req, timeout=0):
        calls["n"] += 1
        return R(json.dumps(seq.pop(0)).encode("utf-8"))

    return _open, calls


def test_rate_limit_is_retried_instead_of_dropping_the_symbol():
    """retCode 10006 (سقف نرخ) نباید نماد را حذف کند — در اجرای واقعی ۴ نماد رفت."""
    import mtflab.bybit_public as bp
    rl = {"retCode": 10006, "retMsg": "Too many visits.", "result": {}}
    good = {"retCode": 0, "result": {"list": [["1700000000000", "1", "2", "0.5", "1.5",
                                               "10", ""]]}}
    open_, calls = _fake_http([rl, rl, good])
    real_open, real_sleep = bp.urllib.request.urlopen, bp.time.sleep
    bp.urllib.request.urlopen = open_
    bp.time.sleep = lambda x: None
    try:
        cs = bp.fetch_klines("BTCUSDT", "15m", limit=1, drop_forming=False)
    finally:
        bp.urllib.request.urlopen = real_open
        bp.time.sleep = real_sleep
    assert len(cs) == 1 and calls["n"] == 3


def test_other_api_errors_still_fail_fast():
    """خطای غیر از سقف نرخ باید صریح بالا بیاید، نه با ۶ بار تلاش پنهان."""
    import mtflab.bybit_public as bp
    bad = {"retCode": 10001, "retMsg": "params error", "result": {}}
    open_, calls = _fake_http([bad] * 10)
    real_open, real_sleep = bp.urllib.request.urlopen, bp.time.sleep
    bp.urllib.request.urlopen = open_
    bp.time.sleep = lambda x: None
    try:
        try:
            bp.fetch_klines("BTCUSDT", "15m", limit=1, drop_forming=False)
        except RuntimeError as e:
            assert "retCode=10001" in str(e)
        else:
            raise AssertionError("باید RuntimeError می‌داد")
    finally:
        bp.urllib.request.urlopen = real_open
        bp.time.sleep = real_sleep
    assert calls["n"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# ۷) فایل بایگانی باید به پوشهٔ Download گوشی هم کپی شود
# ═══════════════════════════════════════════════════════════════════════════
def test_archive_copies_digest_to_the_phone_download_folder():
    """کاربر باید فایل را در Download پیدا کند، نه در عمق مخزن.

    یک‌بار همین اتفاق افتاد: شناسنامه ساخته شد ولی کاربر «فایل را پیدا نمی‌کنم».
    """
    import shutil
    import subprocess
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(here, "run-auto.sh")
    if not shutil.which("bash"):
        return
    with tempfile.TemporaryDirectory() as td:
        home = os.path.join(td, "home")
        dl = os.path.join(home, "storage", "downloads")
        os.makedirs(dl)
        # داده را کنار خود اپ می‌گذاریم، چون اسکریپت از پوشهٔ اپ اجرا می‌شود
        data_dir = os.path.join(here, "data")
        backup = None
        made_json = os.path.join(data_dir, "json")
        created = not os.path.exists(os.path.join(made_json, "btcusdt_15m.json"))
        try:
            _make_dataset(data_dir, n=300)
            env = dict(os.environ, HOME=home)
            r = subprocess.run(["bash", script, "--archive", "--tag", "unittest"],
                               cwd=here, env=env, capture_output=True, text=True,
                               timeout=180)
            assert r.returncode == 0, r.stdout + r.stderr
            files = os.listdir(dl)
            assert any(f.startswith("data_digest_unittest") for f in files), files
        finally:
            for f in os.listdir(dl) if os.path.isdir(dl) else []:
                os.remove(os.path.join(dl, f))
            if created:
                try:
                    os.remove(os.path.join(made_json, "btcusdt_15m.json"))
                    os.remove(os.path.join(made_json, "_index.json"))
                except OSError:
                    pass
            for f in os.listdir(os.path.join(here, "data_archive")):
                if f.startswith("data_digest_unittest"):
                    os.remove(os.path.join(here, "data_archive", f))
