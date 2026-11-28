"""تست‌های بستهٔ مستقل (`exports/autotrade_core`) و API عمومی.

سه چیز باید قفل شود:

  ۱. بسته **واقعاً** مستقل است: بدون این مخزن هم import و اجرا می‌شود.
  ۲. بسته با کد فعلی یکی است؛ اگر موتور عوض شود و بسته بازسازی نشود، تست
     می‌شکند (نه این‌که ماه‌ها نسخهٔ کهنه دست کاربر بماند).
  ۳. آمارِ API با آمارِ داشبورد **یکی** است — نه دو پیاده‌سازی با اختلاف کوچک.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import autotrade_api as api                                 # noqa: E402
from mtflab.bundle import CORE_FILES, build, check                     # noqa: E402
from mtflab.data import synthetic_candles                              # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMITTED = os.path.join(HERE, "exports", "autotrade_core")


def _dataset(n=2, bars=900):
    return {f"X{i}": synthetic_candles("4h", bars, seed=11 + i) for i in range(n)}


# ═══════════════════════════════════════════════════════════════════════════
# ۱) بسته مستقل است
# ═══════════════════════════════════════════════════════════════════════════
def test_bundle_builds_and_runs_without_the_repo():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "autotrade_core")
        man = build(out, clean=True)
        assert set(man["files"]) == set(CORE_FILES)
        for name in CORE_FILES:
            assert os.path.exists(os.path.join(out, name))
        assert os.path.exists(os.path.join(out, "README_FA.md"))
        assert os.path.exists(os.path.join(out, "demo.py"))
        # اجرا در یک فرایند تازه، با PYTHONPATH فقط به والدِ بسته
        env = dict(os.environ, PYTHONPATH=os.path.dirname(td))
        code = (
            "import autotrade_core.autotrade_api as a\n"
            "from autotrade_core.data import synthetic_candles\n"
            "d = {'A': synthetic_candles('4h', 700, seed=3)}\n"
            "r = a.run(d, variant='trend')\n"
            "print(r['variant'], r['metrics']['n'], len(r['by_rule']))\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=td, env=env,
                           capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, r.stderr[-1500:]
        assert r.stdout.split()[0] == "trend"


def test_bundle_demo_runs_standalone():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "autotrade_core")
        build(out, clean=True)
        r = subprocess.run([sys.executable, os.path.join(out, "demo.py")],
                           cwd=td, capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, r.stderr[-1500:]
        assert "variants:" in r.stdout and "by_rule:" in r.stdout


# ═══════════════════════════════════════════════════════════════════════════
# ۲) بستهٔ کامیت‌شده نباید از موتور عقب بماند
# ═══════════════════════════════════════════════════════════════════════════
def test_check_detects_stale_and_tampered_files():
    with tempfile.TemporaryDirectory() as td:
        build(td, clean=True)
        assert check(td)["ok"] is True
        # (الف) فایل داخل بسته دست‌کاری شود
        p = os.path.join(td, "engine.py")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n# تغییر نمایشی\n")
        rep = check(td)
        assert rep["ok"] is False and "engine.py" in rep["stale"]
        # (ب) بسته کهنه شود: manifest مثل یک ساخت قدیمی دست‌کاری می‌شود
        build(td, clean=True)
        mp = os.path.join(td, "manifest.json")
        man = json.load(open(mp, encoding="utf-8"))
        man["files"]["signals.py"] = "0" * 64
        json.dump(man, open(mp, "w", encoding="utf-8"))
        rep = check(td)
        assert rep["ok"] is False and "signals.py" in rep["tampered"]


def test_committed_bundle_is_in_sync_with_engine():
    """اگر این شکست، یعنی `python3 -m mtflab bundle` را بعد از تغییر موتور نزدی."""
    assert os.path.isdir(COMMITTED), "بستهٔ exports/autotrade_core کامیت نشده است"
    rep = check(COMMITTED)
    assert rep["ok"], (f"بسته کهنه است — بزن: python3 -m mtflab bundle · "
                       f"stale={rep.get('stale')} missing={rep.get('missing')}")


def test_manifest_records_every_file_and_version():
    man = json.load(open(os.path.join(COMMITTED, "manifest.json"), encoding="utf-8"))
    assert set(man["files"]) == set(CORE_FILES)
    assert man["version"] and man["built_utc"]


# ═══════════════════════════════════════════════════════════════════════════
# ۳) API و داشبورد باید همان عدد را بدهند
# ═══════════════════════════════════════════════════════════════════════════
def test_api_matches_desk_metrics():
    from mtflab.desk import Lab
    data = _dataset(n=2, bars=900)
    r = api.run(data, variant="trend", overrides={"trail_atr_mult": 4.0})
    with tempfile.TemporaryDirectory() as td:
        lab = Lab(data_dir=os.path.join(td, "data"), tf="4h", tf_filter="1d",
                  tf_bias="1d", variant="trend",
                  state_path=os.path.join(td, "s.json"),
                  journal_path=os.path.join(td, "j.jsonl"),
                  lab_dir=os.path.join(td, "lab"), demo=False,
                  report_dir=os.path.join(td, "rep"))
        lab._universe = data
        ev = lab.evaluate({"trail_atr_mult": 4.0}, symbols=sorted(data), variant="trend")
    assert r["metrics"]["n"] == ev["metrics"]["n"]
    assert abs((r["metrics"]["expectancy_r"] or 0) - (ev["metrics"]["expectancy_r"] or 0)) < 1e-6
    assert abs((r["metrics"]["pnl"] or 0) - (ev["metrics"]["pnl"] or 0)) < 1e-6
    assert set(r["by_rule"]) == set(ev["by_rule"])


def test_api_accepts_plain_rows_and_dict_rows():
    rows = [[1700000000000 + i * 14_400_000, 100 + i, 101 + i, 99 + i, 100.5 + i, 10]
            for i in range(80)]
    cs = api.to_candles(rows)
    assert len(cs) == 80 and cs[1].open_time_ms - cs[0].open_time_ms == 14_400_000
    dd = [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in rows]
    assert len(api.to_candles(dd)) == 80


def test_unknown_overrides_are_reported_not_applied():
    r = api.run(_dataset(n=1, bars=600), variant="trend",
                overrides={"stop_atr_mult": 2.0, "nonsense": 5})
    assert r["overrides"] == {"stop_atr_mult": 2.0}
    assert r["ignored_keys"] == ["nonsense"]


def test_signals_now_returns_a_decision_or_none():
    out = api.signals_now(_dataset(n=2, bars=700), variant="trend")
    assert {x["symbol"] for x in out} == {"X0", "X1"}
    for x in out:
        assert x["available"] is True
        assert x["signal"] is None or x["signal"]["rule"]


def test_open_positions_are_excluded_from_metrics():
    """پوزیشن بازِ آخر داده نباید در سنجه‌ها بیاید (وگرنه آخرِ روند پاداش می‌گیرد)."""
    r = api.run(_dataset(n=1, bars=700))
    assert r["metrics"]["open_at_end"] >= 0
    assert len(r["trades"]) == r["metrics"]["n"]
