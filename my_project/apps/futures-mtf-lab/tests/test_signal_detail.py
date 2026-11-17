"""تست‌های «پروندهٔ کامل سیگنال» + کاتالوگ الگوریتم‌ها + سیگنال دستی.

چرا این تست‌ها: کاربر خواست همهٔ اعداد (حد ضرر/سود، کارمزد، کندل بسته و باز شده،
الگو، قاعدهٔ بست) **در لحظهٔ ورود و لحظهٔ خروج** ذخیره و نمایش داده شوند. اگر این
فیلدها بی‌سروصدا خالی شوند، تب داشبورد پر از «—» می‌شود و هیچ‌کس نمی‌فهمد چرا.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                    # noqa: E402

from mtflab.autoscan import candles_to_json                        # noqa: E402
from mtflab.catalog import catalog, catalog_command                # noqa: E402
from mtflab.config import load_config                              # noqa: E402
from mtflab.data import synthetic_candles                          # noqa: E402
from mtflab.desk import Lab                                        # noqa: E402
from mtflab.live import LiveRunner, read_journal                   # noqa: E402


def _cfg():
    cfg = load_config(["--data", "synthetic", "--quiet"])
    return replace(cfg, tf_trigger="4h", tf_filter="1d", tf_bias="1d",
                   verbose=False, forensics=False, run_id="", symbol="")


def _write_cache(d: str, n: int = 1600, seed: int = 303) -> str:
    """کش محلی ۴ساعته/روزانه بساز تا live بدون شبکه اجرا شود."""
    os.makedirs(os.path.join(d, "json"), exist_ok=True)
    for tf, bars in (("4h", n), ("1d", max(120, n // 4))):
        cs = synthetic_candles(tf, bars, seed=seed)
        with open(os.path.join(d, "json", f"btcusdt_{tf}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(candles_to_json(cs, {"symbol": "BTCUSDT", "tf": tf}), f)
    return d


def _run_live(td: str, cs, votes=True):
    journal = os.path.join(td, "j.jsonl")
    r = LiveRunner(_cfg(), "base", "پایه", {}, os.path.join(td, "s.json"),
                   journal, votes=votes)
    out = r.run_symbol("BTCUSDT", cs, backfill=len(cs))
    return out, read_journal(journal)


# ══════════════════════════════════════════════════════════════════════════
#  ۱) کارمزد تفکیک‌شده در موتور
# ══════════════════════════════════════════════════════════════════════════
def test_close_records_split_fees_and_they_add_up():
    """کارمزد ورود + خروج باید با کارمزد کل برابر باشد (هیچ جزء گم نشود)."""
    with tempfile.TemporaryDirectory() as td:
        _out, jr = _run_live(td, synthetic_candles("4h", 1600, seed=303))
        closes = [r for r in jr if r["type"] == "close"]
        assert closes, "معاملهٔ بسته‌شده‌ای نیست"
        c = closes[0]
        fo = c["result"]["fee_open"]
        fc = c["result"]["fee_close"]
        assert fo > 0 and fc > 0
        # هر جزء تا ۴ رقم گرد شده؛ جمعشان با کل حداکثر یک‌صدمِ سنت فرق دارد
        assert abs(fo + fc - c["result"]["fees"]) < 2e-4


# ══════════════════════════════════════════════════════════════════════════
#  ۲) ژورنال: همهٔ اعداد لحظهٔ ورود و خروج
# ══════════════════════════════════════════════════════════════════════════
def test_journal_records_full_open_and_close_snapshots():
    with tempfile.TemporaryDirectory() as td:
        out, jr = _run_live(td, synthetic_candles("4h", 1600, seed=303))
        assert out["opened"] > 0, "هیچ سیگنالی باز نشد؛ تست بی‌معنا می‌شد"
        opens = [r for r in jr if r["type"] == "open"]
        closes = [r for r in jr if r["type"] == "close"]
        o = opens[0]
        assert o["entry_candle"]["open"] and o["entry_candle"]["ts"] == o["ts"]
        assert o["order"]["stop"] and o["order"]["take"]
        assert o["order"]["fee_open"] > 0
        assert o["origin"] == "auto"
        assert "pattern_votes" in o
        c = closes[0]
        assert c["has_snapshot"] is True
        assert c["exit_candle"]["ts"] and c["exit_candle"]["close"] > 0
        assert c["exit_indicators"], "اندیکاتورهای لحظهٔ خروج ثبت نشده"
        assert c["result"]["fee_close"] > 0
        assert c["order"]["take"] and c["order"]["stop_initial"]
        assert c["closed_by"]["rule"]


# ══════════════════════════════════════════════════════════════════════════
#  ۳) داشبورد: کارت سیگنال و بنر اعتبارسنجی
# ══════════════════════════════════════════════════════════════════════════
def test_lab_signals_card_exposes_every_number():
    with tempfile.TemporaryDirectory() as td:
        j = os.path.join(td, "j.jsonl")
        st = Lab(data_dir=td, journal_path=j, state_path=os.path.join(td, "s.json"),
                 report_dir=td)
        _run_live(td, synthetic_candles("4h", 1600, seed=303))
        rows = st.signals(limit=50)
        assert rows
        s = rows[0]
        for k in ("entry", "stop", "take", "fee_open", "fee_close", "fees_total",
                  "open_candle", "exit_candle", "votes", "origin",
                  "open_indicators", "exit_indicators", "has_close_snapshot"):
            assert k in s, k
        assert s["take"] is not None and s["fee_open"] is not None


def test_validation_status_is_honest_about_small_samples():
    with tempfile.TemporaryDirectory() as td:
        j = os.path.join(td, "j.jsonl")
        st = Lab(data_dir=td, journal_path=j, state_path=os.path.join(td, "s.json"),
                 report_dir=td)
        st0 = st.validation_status()
        assert st0["n"] == 0 and st0["complete"] is False
        assert st0["manual_allowed"] is True
        _run_live(td, synthetic_candles("4h", 1600, seed=303))
        st1 = st.validation_status()
        assert st1["n"] > 0
        assert st1["complete"] is (st1["n"] >= st1["min_n"])


# ══════════════════════════════════════════════════════════════════════════
#  ۴) سیگنال دستی
# ══════════════════════════════════════════════════════════════════════════
def test_manual_signal_is_blocked_in_demo_mode():
    with tempfile.TemporaryDirectory() as td:
        lab = Lab(data_dir=td, demo=True, journal_path=os.path.join(td, "j.jsonl"),
                  state_path=os.path.join(td, "s.json"), report_dir=td)
        r = lab.manual_signal(offline=True)
        assert r["ok"] is False and "نمایشی" in r["note"]


def test_manual_signal_runs_a_real_step_offline():
    with tempfile.TemporaryDirectory() as td:
        data = _write_cache(os.path.join(td, "data"))
        lab = Lab(data_dir=data, symbols=["BTCUSDT"],
                  journal_path=os.path.join(td, "j.jsonl"),
                  state_path=os.path.join(td, "s.json"),
                  report_dir=td, lab_dir=os.path.join(td, "lab"))
        r = lab.manual_signal(offline=True)
        assert r["ok"] is True
        assert r["signals"], "روی این داده باید سیگنال دستی ساخته شود"
        s = r["signals"][0]
        for k in ("symbol", "side", "entry", "stop", "take", "mode"):
            assert s[k] is not None, k
        rows = read_journal(os.path.join(td, "j.jsonl"))
        assert any(x.get("origin") == "manual" for x in rows if x["type"] == "open")


# ══════════════════════════════════════════════════════════════════════════
#  ۵) کاتالوگ الگوریتم‌ها
# ══════════════════════════════════════════════════════════════════════════
def test_catalog_covers_all_algorithms_with_live_parameters():
    cat = catalog()
    ids = {s["id"] for s in cat["sections"]}
    assert {"mtf", "v10", "exits", "pump"} <= ids
    mtf = [s for s in cat["sections"] if s["id"] == "mtf"][0]
    assert {i["id"] for i in mtf["items"]} == {"base", "trend", "trend_tp",
                                               "pullback", "climax"}
    for it in mtf["items"]:
        assert it["formulas"] and all(f.get("expr") for f in it["formulas"])
        assert it["params"], it["id"]


def test_catalog_v10_formula_has_real_numbers():
    cat = catalog()
    v10 = [s for s in cat["sections"] if s["id"] == "v10"][0]["items"][0]
    vals = " ".join(f.get("values", "") for f in v10["formulas"])
    assert "20" in vals and "2.5" in vals and "٪" in vals
    assert v10["params"]["rr_ratio"] == 2.5


def test_catalog_excludes_zero_thresholds_from_looking_like_rules():
    """«۰×ATR» نباید به‌صورت یک قاعدهٔ فعال نمایش داده شود."""
    cat = catalog()
    mtf = [s for s in cat["sections"] if s["id"] == "mtf"][0]
    # فقط متنِ فرمول‌ها معیار است؛ خودِ مقدار خام پارامتر (۰) در params مشکلی ندارد.
    import re
    text = json.dumps([f.get("values", "") for it in mtf["items"]
                       for f in it["formulas"]], ensure_ascii=False)
    # «0×ATR» یعنی آستانهٔ صفر که نباید شبیه یک قاعدهٔ فعال دیده شود؛
    # اما «50×ATR» عددی واقعی است و فقط باید برچسب «عملاً بدون TP» بگیرد.
    assert not re.search(r"(?<![\d.,])0×ATR", text), text[:200]
    assert "عملاً بدون TP" in text


def test_catalog_command_writes_json():
    with tempfile.TemporaryDirectory() as td:
        rc = catalog_command(["--out-dir", td, "--json"])
        assert rc == 0
        path = os.path.join(td, "algorithms_catalog.json")
        data = json.load(open(path, encoding="utf-8"))
        assert data["counts"]["items"] >= 15


# ══════════════════════════════════════════════════════════════════════════
#  ۶) داشبورد: تب‌ها و مسیرها
# ══════════════════════════════════════════════════════════════════════════
def test_dashboard_has_new_tabs_and_routes():
    from mtflab import labweb

    page = labweb.PAGE
    for needle in ('data-tab="algos"', 'id="tab-algos"', 'id="manualBtn"',
                   'id="sigValid"', "کندل ورود", "کارمزد"):
        assert needle in page, needle
    src = open(labweb.__file__, encoding="utf-8").read()
    for route in ('"/api/algorithms"', '"/api/validation"', '"/api/manual_signal"'):
        assert route in src, route
