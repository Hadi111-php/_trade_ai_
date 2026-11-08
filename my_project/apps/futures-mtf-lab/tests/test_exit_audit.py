"""تست‌های حسابرسی خروج — «چقدر سود روی میز ماند؟».

ریاضیاتش ساده است ولی مهم: `mfe_r = mfe_pct ÷ risk_pct`. اگر این نسبت غلط
حساب شود، گزارش یا سودِ خیالی نشان می‌دهد یا ضررِ خیالی.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.exits import analyze, collect, render                    # noqa: E402


def _rec(sid, r, mfe_pct, mae_pct, rule="trail_stop", risk=10.0,
         notional=500.0, bars=10, mode="breakout", risk_control=False):
    """notional=500 و risk=10 ⇒ risk_pct=2٪ ⇒ هر ۲٪ حرکت = ۱R."""
    return [
        {"type": "open", "id": sid, "ts": 1000, "symbol": "X",
         "entry_pattern": {"mode": mode},
         "order": {"notional": notional, "risk_amount": risk,
                   "side": "LONG", "entry": 100.0, "stop": 98.0}},
        {"type": "close", "id": sid + ":c", "open_id": sid, "ts": 2000,
         "symbol": "X",
         "closed_by": {"id": rule, "fa": rule, "is_risk_control": risk_control},
         "result": {"r_multiple": r, "pnl": r * risk, "is_win": r > 0,
                    "mfe_pct": mfe_pct, "mae_pct": mae_pct, "bars_held": bars}},
    ]


def _write(td, recs):
    p = os.path.join(td, "j.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def test_mfe_is_converted_to_r_using_risk_from_the_order():
    with tempfile.TemporaryDirectory() as td:
        # ریسک ۲٪ ⇒ MFE ۶٪ = ۳R
        rows = collect(_write(td, _rec("a", 1.0, mfe_pct=6.0, mae_pct=-2.0)))
        assert len(rows) == 1
        t = rows[0]
        assert abs(t["risk_pct"] - 2.0) < 1e-9
        assert abs(t["mfe_r"] - 3.0) < 1e-9
        assert abs(t["mae_r"] + 1.0) < 1e-9
        assert abs(t["give_back_r"] - 2.0) < 1e-9


def test_categories_cover_the_four_real_cases():
    with tempfile.TemporaryDirectory() as td:
        recs = (_rec("giveback", 0.1, 4.0, -2.0)      # در سود بود، سربه‌سر بست
                + _rec("short", 1.0, 6.0, -2.0)        # ۳R دید، ۱R گرفت (۲R ریخت)
                + _rec("good", 2.5, 5.2, -1.0)         # نزدیک سقف بست
                + _rec("clean", -1.0, 0.2, -2.0, rule="stop_loss",
                       risk_control=True))             # هرگز سود نشد
        rows = {t["symbol"] + str(i): t for i, t in
                enumerate(collect(_write(td, recs)))}
        cats = [t["category"] for t in rows.values()]
        assert cats == ["برندهٔ پس‌داده‌شده", "کوتاه‌شده", "خوب", "حد ضرر سالم"]
        rep = analyze(list(rows.values()))
        assert rep["categories"]["برندهٔ پس‌داده‌شده"] == 1
        assert rep["leak_total_r"] > 0


def test_total_leak_is_sum_of_positive_givebacks():
    with tempfile.TemporaryDirectory() as td:
        recs = _rec("a", 1.0, 6.0, -2.0) + _rec("b", 0.0, 4.0, -2.0)
        rep = analyze(collect(_write(td, recs)))
        # a: mfe 3R - 1R = 2R · b: mfe 2R - 0 = 2R
        assert abs(rep["leak_total_r"] - 4.0) < 1e-6


def test_missing_mfe_is_not_invented():
    with tempfile.TemporaryDirectory() as td:
        recs = _rec("a", 1.0, mfe_pct=None, mae_pct=None)
        rows = collect(_write(td, recs))
        assert rows[0]["mfe_r"] is None
        assert rows[0]["give_back_r"] is None
        assert rows[0]["category"] == "نامعلوم"
        rep = analyze(rows)
        assert any("mfe_pct" in w for w in rep["warnings"])


def test_small_sample_warns_but_still_renders():
    with tempfile.TemporaryDirectory() as td:
        rep = analyze(collect(_write(td, _rec("a", 0.1, 4.0, -2.0))))
        assert any("n=1" in w for w in rep["warnings"])
        md = render(rep)
        assert "حسابرسی خروج" in md and "پارامتری را خودش عوض نمی‌کند" in md


def test_breakdown_by_rule_and_pattern_and_symbol():
    with tempfile.TemporaryDirectory() as td:
        recs = (_rec("a", 1.0, 6.0, -2.0, rule="trail_stop", mode="pullback")
                + _rec("b", -1.0, 1.0, -2.0, rule="stop_loss", mode="breakout",
                       risk_control=True))
        rep = analyze(collect(_write(td, recs)))
        assert set(rep["by_rule"]) == {"trail_stop", "stop_loss"}
        assert set(rep["by_pattern"]) == {"pullback", "breakout"}
        assert set(rep["by_symbol"]) == {"X"}


def test_candidates_are_offered_but_nothing_is_changed():
    with tempfile.TemporaryDirectory() as td:
        rep = analyze(collect(_write(td, _rec("a", 0.1, 4.0, -2.0))))
        knobs = {c["knob"] for c in rep["candidates"]}
        assert "breakeven_at_r" in knobs
        md = render(rep)
        assert "نه تغییر خودکار" in md


def test_empty_journal_is_safe():
    rep = analyze(collect("/nonexistent/none.jsonl"))
    assert rep["n"] == 0 and rep["trades"] == []
    render(rep)                                   # نباید استثنا بدهد


def test_truncated_line_does_not_kill_the_report():
    with tempfile.TemporaryDirectory() as td:
        p = _write(td, _rec("a", 1.0, 6.0, -2.0))
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"type": "close", "open_id": "zz"')
        assert len(collect(p)) == 1
