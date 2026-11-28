"""تست‌های تب «پامپ و دامپ»: خواندن گزارش، نه محاسبهٔ دوباره.

قاعدهٔ این پروژه: داشبورد نباید عدد بسازد. تب فقط `pumpdump_report.json` را
می‌خواند؛ اگر فایل نبود، راه ساختش را می‌گوید.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import pumpdump                                     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(td, payload, with_md=True):
    with open(os.path.join(td, "pumpdump_report.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    if with_md:
        with open(os.path.join(td, "pumpdump_report.md"), "w", encoding="utf-8") as f:
            f.write("# report\n")
    with open(os.path.join(td, "pumpdump_scenarios.md"), "w", encoding="utf-8") as f:
        f.write("# scenarios\n")


def test_missing_report_says_how_to_build_it():
    with tempfile.TemporaryDirectory() as td:
        r = pumpdump.latest(td)
        assert r["available"] is False
        assert "--pump" in r["hint"]


def test_reads_report_and_exposes_primary_horizon():
    with tempfile.TemporaryDirectory() as td:
        _write(td, {"version": "1", "scenario": "follow", "n_independent": 70,
                    "params": {"primary_horizon": 6},
                    "by_horizon": {"6": {"n": 70, "median": -0.0019}},
                    "by_symbol": {"BTCUSDT": {"n": 34, "median": -0.0009}},
                    "lift_primary": -0.0003, "passed": False, "symbols": ["BTCUSDT"]})
        r = pumpdump.latest(td)
        assert r["available"] is True
        assert r["primary_horizon"] == 6
        assert r["n_independent"] == 70
        assert r["paths"]["md"].endswith("pumpdump_report.md")
        assert r["paths"]["scenarios"].endswith("pumpdump_scenarios.md")
        assert r["generated_utc"]                     # مهر زمانی از mtime


def test_broken_json_is_reported_not_raised():
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "pumpdump_report.json"), "w").write("{not json")
        r = pumpdump.latest(td)
        assert r["available"] is False
        assert r["hint"]


def test_dashboard_tab_and_route_exist():
    src = open(os.path.join(ROOT, "mtflab", "labweb.py"), encoding="utf-8").read()
    assert 'data-tab="pump"' in src
    assert 'id="tab-pump"' in src
    assert '"/api/pump"' in src
    assert "loadPump" in src and "renderPump" in src
    # جدول نمادها از گزارش خوانده می‌شود
    assert "by_symbol" in src


def test_desk_exposes_pump_report():
    src = open(os.path.join(ROOT, "mtflab", "desk.py"), encoding="utf-8").read()
    assert "def pump_report" in src
    assert "from .pumpdump import latest" in src
