"""تست‌های «مدیریت کلان»: کارهای پس‌زمینه، دادهٔ واقعی/آفلاین، گزارش‌های مستقل.

سه چیزی که نباید خراب شود:
  ۱) کار سنگین صفحه را قفل نکند (پس‌زمینه) و وضعیتش درست گزارش شود.
  ۲) وقتی شبکه نبود، کش قبلی **دست‌نخورده** بماند و پیام صریح باشد.
  ۳) گزارش‌ها مستقل باشند: بیرون از ژورنال/سرمایه/آمار سیستم.
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import ops                                           # noqa: E402
from mtflab.autoscan import candles_to_json                      # noqa: E402
from mtflab.data import Candle, synthetic_candles                # noqa: E402


def _ops_dir(td):
    """گزارش‌ها را به پوشهٔ موقت ببر (تست نباید results/ops واقعی را شلوغ کند)."""
    ops.OPS_DIR = os.path.join(td, "ops")
    return ops.OPS_DIR


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ادغام داده: تاریخ قدیم نباید پاک شود
# ══════════════════════════════════════════════════════════════════════════
def test_merge_keeps_history_and_dedupes():
    old = [Candle(i * 1000, 1, 1, 1, 1) for i in range(5)]
    new = [Candle(i * 1000, 2, 2, 2, 2) for i in range(3, 8)]
    merged = ops.merge_candles(old, new)
    assert len(merged) == 8
    assert [c.open_time_ms for c in merged] == sorted(c.open_time_ms for c in merged)
    # رکورد تازه جای قدیمی را می‌گیرد (قیمت ۲)
    assert next(c for c in merged if c.open_time_ms == 3000).close == 2


def test_cache_roundtrip_and_status():
    with tempfile.TemporaryDirectory() as td:
        cs = synthetic_candles("1h", 300, seed=7)
        p = ops._write_cache(td, "BTCUSDT", "1h", cs, {"source": "test"})
        back, meta = ops._read_cache(p)
        assert len(back) == len(cs) and meta["source"] == "test"
        st = ops.data_status(td)
        assert st["files"] == 1 and st["symbols"] == ["BTCUSDT"] and st["by_tf"] == {"1h": 1}
        assert st["oldest"] and st["newest"]


# ══════════════════════════════════════════════════════════════════════════
#  ۲) اجراکنندهٔ کارها
# ══════════════════════════════════════════════════════════════════════════
def test_background_job_runs_and_reports():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        job = ops.start("test_ok", "کار آزمایشی", lambda log: (log("سلام"), {"n": 3})[1])
        done = ops._wait(job["id"], timeout=10, echo=False)
        assert done["status"] == "done" and done["summary"] == {"n": 3}
        assert done["duration_s"] is not None
        assert os.path.exists(os.path.join(td, "ops", f"{job['id']}.json"))


def test_background_job_captures_error():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)

        def boom(log):
            log("قبل از خطا")
            raise RuntimeError("شبکه قطع است")

        job = ops.start("test_err", "کار خطادار", boom)
        done = ops._wait(job["id"], timeout=10, echo=False)
        assert done["status"] == "error" and "شبکه قطع است" in done["error"]
        assert any("قبل از خطا" in x for x in done["log"])


def test_same_kind_cannot_run_twice():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        gate = threading.Event()
        job = ops.start("test_lock", "کار کند", lambda log: (gate.wait(5), {})[1])
        try:
            try:
                ops.start("test_lock", "تکراری", lambda log: {})
            except RuntimeError as e:
                assert "در حال اجراست" in str(e)
            else:
                raise AssertionError("اجرای هم‌زمان دو کار هم‌نوع باید رد شود")
        finally:
            gate.set()
            ops._wait(job["id"], timeout=10, echo=False)


# ══════════════════════════════════════════════════════════════════════════
#  ۳) شبکه: آفلاین نباید کش را خراب کند
# ══════════════════════════════════════════════════════════════════════════
def test_sync_offline_fails_loudly_and_keeps_cache(monkeypatch=None):
    from mtflab import autoscan, bybit_public

    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        cs = synthetic_candles("1h", 400, seed=9)
        path = ops._write_cache(td, "BTCUSDT", "1h", cs, {"source": "seed"})
        before = _sha(path)

        real_pick, real_fetch = autoscan.pick_base_url, bybit_public.fetch_klines_range

        def fake_pick(*a, **k):
            return "http://fake"

        def fake_fetch(*a, **k):
            raise RuntimeError("شبکه در دسترس نیست")

        autoscan.pick_base_url, bybit_public.fetch_klines_range = fake_pick, fake_fetch
        try:
            job = ops.start("sync", "به‌روزرسانی", ops.job_sync(["BTCUSDT"], ["1h"], 30, td))
            done = ops._wait(job["id"], timeout=15, echo=False)
        finally:
            autoscan.pick_base_url, bybit_public.fetch_klines_range = real_pick, real_fetch

        assert done["status"] == "error" and "شبکه" in done["error"]
        assert _sha(path) == before, "با خطای شبکه نباید فایل کش تغییر کند"


def test_sync_online_appends_without_losing_history():
    from mtflab import autoscan, bybit_public

    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        cs = synthetic_candles("1h", 400, seed=9)
        ops._write_cache(td, "BTCUSDT", "1h", cs, {"source": "seed"})
        fresh = [Candle(cs[-1].open_time_ms + 3_600_000 * (k + 1), 10, 11, 9, 10.5)
                 for k in range(3)]

        real_pick, real_fetch = autoscan.pick_base_url, bybit_public.fetch_klines_range
        autoscan.pick_base_url = lambda *a, **k: "http://fake"
        bybit_public.fetch_klines_range = lambda *a, **k: fresh
        try:
            job = ops.start("sync", "به‌روزرسانی", ops.job_sync(["BTCUSDT"], ["1h"], 30, td))
            done = ops._wait(job["id"], timeout=15, echo=False)
        finally:
            autoscan.pick_base_url, bybit_public.fetch_klines_range = real_pick, real_fetch

        assert done["status"] == "done", done.get("error")
        assert done["summary"]["updated"][0]["added"] == 3
        back, meta = ops._read_cache(ops._cache_path(td, "BTCUSDT", "1h"))
        assert len(back) == 403 and meta["source"] == "sync"


def test_download_without_network_is_an_honest_error():
    from mtflab import autoscan
    real = autoscan.pick_base_url
    autoscan.pick_base_url = lambda *a, **k: ""
    try:
        with tempfile.TemporaryDirectory() as td:
            _ops_dir(td)
            job = ops.start("download", "دانلود", ops.job_download(["BTCUSDT"], ["1h"], 10, td))
            done = ops._wait(job["id"], timeout=10, echo=False)
    finally:
        autoscan.pick_base_url = real
    assert done["status"] == "error" and "Bybit" in done["error"]


# ══════════════════════════════════════════════════════════════════════════
#  ۴) آزمون‌های مستقل: گزارش جدا، بدون لمس ژورنال
# ══════════════════════════════════════════════════════════════════════════
def test_exitstyles_job_writes_independent_report():
    with tempfile.TemporaryDirectory() as td:
        od = _ops_dir(td)
        data = os.path.join(td, "data")
        for i, sym in enumerate(("BTCUSDT", "ETHUSDT")):
            cs = synthetic_candles("1h", 2600, seed=303 + i)
            ops._write_cache(data, sym, "1h", cs, {"source": "test"})
        journal = os.path.join(td, "journal.jsonl")
        job = ops.start("exitstyles", "آزمایش خروج",
                        ops.job_exitstyles("1h", "base", data))
        done = ops._wait(job["id"], timeout=90, echo=False)
        assert done["status"] == "done", done.get("error")
        md = done["summary"]["report_md"]
        assert md.startswith(od) and os.path.exists(md)
        text = open(md, encoding="utf-8").read()
        assert "expectancy" in text and "بیرون‌نمونه" in text
        assert not os.path.exists(journal), "این آزمون نباید ژورنال بسازد"


def test_exitstyles_job_without_data_is_a_clear_error():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        job = ops.start("exitstyles", "آزمایش خروج",
                        ops.job_exitstyles("1h", "base", os.path.join(td, "empty")))
        done = ops._wait(job["id"], timeout=20, echo=False)
        assert done["status"] == "error" and "داده" in done["error"]


def test_doctor_job_writes_report():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        job = ops.start("doctor", "معاینه", ops.job_doctor())
        done = ops._wait(job["id"], timeout=30, echo=False)
        assert done["status"] == "done"
        assert os.path.exists(done["summary"]["report_md"])


# ══════════════════════════════════════════════════════════════════════════
#  ۵) وضعیت، خواندن گزارش، امنیت مسیر
# ══════════════════════════════════════════════════════════════════════════
def test_status_and_read_report():
    with tempfile.TemporaryDirectory() as td:
        od = _ops_dir(td)
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, "sample.md"), "w", encoding="utf-8") as f:
            f.write("# سلام\n")
        st = ops.status(td)
        assert any(r["id"] == "sample" for r in st["reports"])
        got = ops.read_report("sample")
        assert "سلام" in got["text"]


def test_read_report_blocks_path_traversal():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        try:
            ops.read_report("../../etc/passwd")
        except KeyError as e:
            assert "پیدا نشد" in str(e)
        else:
            raise AssertionError("مسیر بیرونی نباید خوانده شود")


def test_cli_status_runs():
    with tempfile.TemporaryDirectory() as td:
        _ops_dir(td)
        assert ops.ops_command(["--status", "--data-dir", td]) == 0


def test_dashboard_has_ops_tab_and_routes():
    from mtflab import labweb
    for needle in ('data-tab="ops"', 'id="tab-ops"', 'id="opsSync"',
                   'id="opsDownload"', 'id="opsExitStyles"', "مدیریت کلان"):
        assert needle in labweb.PAGE, needle
    src = open(labweb.__file__, encoding="utf-8").read()
    for route in ('"/api/ops"', '"/api/ops/start"', '"/api/ops/report"'):
        assert route in src, route
