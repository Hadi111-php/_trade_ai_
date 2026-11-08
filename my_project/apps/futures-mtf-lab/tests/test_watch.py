"""تست‌های شکار زنده — وزن آمادگی، شرط‌ها، و اعلان.

مهم‌ترین چیزهایی که باید قفل شود:

۱. **وزن‌ها ۱۰۰ باشند و از شرط‌های واقعی بیایند** (نه یک امتیاز ساختگی).
۲. **هر لایه اندیس خودش را بگیرد** — باگی که واقعاً رخ داد: دادن اندیس تریگر
   (۲۱۹۰ کندل) به لایهٔ روزانه (۳۶۶ کندل) ⇒ همیشه «رژیم unknown» و وزن ۱۸٪.
۳. **حالت‌ها درست تشخیص داده شوند**: سیگنال / نزدیک / دور.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.config import MTFConfig                                    # noqa: E402
from mtflab.data import synthetic_candles                              # noqa: E402
from mtflab.watch import (CHECKS_FA, NEAR_WEIGHT, WEIGHTS, alert,      # noqa: E402
                          evaluate_symbol, render, scan)

CFG = MTFConfig(tf_trigger="4h", tf_filter="1d", tf_bias="1d")


def _uni(n=2200, syms=("A", "B", "C", "D"), seed0=61):
    return {s: synthetic_candles("4h", n, seed=seed0 + i)
            for i, s in enumerate(syms)}


def test_weights_sum_to_100_and_cover_every_check():
    assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9
    assert set(WEIGHTS) == set(CHECKS_FA)


def test_readiness_is_a_fraction_and_checks_carry_value_and_threshold():
    uni = _uni()
    r = evaluate_symbol("A", uni["A"], CFG)
    assert 0.0 <= r["readiness"] <= 1.0
    assert r["state"] in ("سیگنال", "نزدیک", "دور")
    assert len(r["checks"]) == len(WEIGHTS)
    for c in r["checks"]:
        assert c["id"] in CHECKS_FA
        assert c["weight"] > 0
        assert isinstance(c["detail"], str) and c["detail"]
        assert set(c) >= {"ok", "hard", "value", "threshold"}


def test_readiness_matches_weighted_pass_fraction():
    r = evaluate_symbol("A", _uni()["A"], CFG)
    total = sum(c["weight"] for c in r["checks"])
    got = sum(c["weight"] for c in r["checks"] if c["ok"])
    assert abs(r["readiness"] - got / total) < 1e-6


def test_bias_layer_gets_its_own_index_not_the_trigger_index():
    """رگرسیون: با ۲۲۰۰ کندل ۴ ساعته، لایهٔ روزانه ۳۶۶ کندل دارد و باید
    «رژیم» داشته باشد، نه unknown."""
    r = evaluate_symbol("A", _uni()["A"], CFG)
    assert r["bars"]["trigger"] > r["bars"]["bias"]
    assert r["checks"][0]["ok"] is True, r["checks"][0]   # data
    assert "unknown" not in r["checks"][1]["detail"]      # bias regime


def test_cost_check_is_provisional_when_trigger_is_neutral():
    """اگر موتور به مرحلهٔ هزینه نرسیده، ما خودمان از «حرکت مورد انتظار» حساب
    می‌کنیم تا شرط «نامعلوم» نماند."""
    r = evaluate_symbol("A", _uni()["A"], CFG)
    cost = [c for c in r["checks"] if c["id"] == "cost"][0]
    if r["decision"] == "WAIT":
        assert cost["value"] is not None
        assert "÷" in cost["detail"]


def test_near_state_rule_is_respected():
    rep = scan(_uni(), CFG)
    for r in rep["rows"]:
        missing = r["missing"]
        if r["state"] == "سیگنال":
            assert r["decision"] != "WAIT"
        elif r["state"] == "نزدیک":
            assert r["readiness"] >= NEAR_WEIGHT or len(missing) == 1
        else:
            assert r["readiness"] < NEAR_WEIGHT and len(missing) != 1


def test_scan_sorts_signals_first_then_by_readiness():
    rep = scan(_uni(), CFG)
    order = {"سیگنال": 0, "نزدیک": 1, "دور": 2}
    keys = [(order[r["state"]], -r["readiness"]) for r in rep["rows"]]
    assert keys == sorted(keys)
    assert rep["n"] == 4


def test_short_data_is_safe_and_says_so():
    r = evaluate_symbol("X", synthetic_candles("4h", 4, seed=1), CFG)
    assert r["state"] == "دور"
    assert r["blocking"]
    assert len(r["checks"]) == len(WEIGHTS)


def test_intra_candle_flag_is_reported():
    r = evaluate_symbol("A", _uni()["A"], CFG, intra_candle=True)
    assert r["intra_candle"] is True
    assert "داخل کندل" in render(scan(_uni(), CFG, intra_candle=True))


def test_alert_text_names_the_missing_condition():
    r = evaluate_symbol("A", _uni()["A"], CFG)
    r = dict(r, symbol="SOLUSDT", state="نزدیک", readiness=0.75, missing=["trigger"])
    res = alert(r, use_beep=False, use_notify=False)
    assert "SOLUSDT" in res["title"]
    assert "تریگر" in res["body"]
    assert res["beep"] is False and res["notify"] is False


def test_alert_for_signal_has_different_title():
    r = {"symbol": "BTCUSDT", "state": "سیگنال", "readiness": 1.0,
         "missing": [], "mode": "breakout"}
    res = alert(r, use_beep=False, use_notify=False)
    assert "سیگنال" in res["title"] and "breakout" in res["body"]


def test_render_is_markdown_with_a_row_per_symbol():
    md = render(scan(_uni(), CFG))
    assert md.startswith("# شکار زنده")
    for s in ("A", "B", "C", "D"):
        assert f"| {s} |" in md
