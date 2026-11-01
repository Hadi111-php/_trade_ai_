"""تست‌های بازبینی سلامت معاملات.

این ابزار باید بتواند «ضررِ طبیعی» را از «خطای مکانیکی» جدا کند:
  • ضرر ≈۱R با قاعدهٔ ضدضرر = طبیعی (هر سیستمی می‌بازد)
  • ضرر ۱.۸R = خطای اجرا/گپ، باید علامت بخورد
  • بسته‌شدن با «سقف زمان» یا «پایان داده» = نیازمند بررسی
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.audit import audit, read_journal, render          # noqa: E402


def _rec(sid, r, pnl=None, rule="stop_loss", bars=20, risk=10.0, symbol="X"):
    return [
        {"type": "open", "id": sid, "symbol": symbol, "ts": 1000,
         "order": {"side": "LONG", "entry": 100.0, "stop": 98.0,
                   "risk_amount": risk},
         "entry_pattern": {"mode": "breakout"},
         "algorithm": {"id": "trend"}},
        {"type": "close", "id": sid + ":c", "open_id": sid, "symbol": symbol,
         "ts": 2000, "closed_by": {"rule": rule},
         "result": {"pnl": pnl if pnl is not None else r * risk,
                    "r_multiple": r, "is_win": r > 0, "exit": 100.0,
                    "bars_held": bars}},
    ]


def _write(td, recs):
    p = os.path.join(td, "j.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def test_three_normal_one_r_losses_are_not_flagged():
    with tempfile.TemporaryDirectory() as td:
        recs = []
        for i, r in enumerate((-1.0, -1.02, -0.98, 3.5)):
            recs += _rec(f"a{i}", r)
        rep = audit(_write(td, recs))
        assert rep["n"] == 4 and rep["losses"] == 3 and rep["wins"] == 1
        assert rep["flags"] == []
        assert all(c["ok"] for c in rep["checks"] if c["id"] != "enough_sample")
        assert rep["risk_per_trade"] == 10.0
        assert abs(rep["expectancy_r"] - (0.5 / 4)) < 1e-6


def test_loss_beyond_one_r_is_flagged():
    with tempfile.TemporaryDirectory() as td:
        rep = audit(_write(td, _rec("big", -1.8)))
        assert [f["id"] for f in rep["flags"]] == ["loss_beyond_risk"]
        check = [c for c in rep["checks"] if c["id"] == "each_loss_is_about_1r"][0]
        assert check["ok"] is False


def test_time_stop_loss_is_flagged():
    with tempfile.TemporaryDirectory() as td:
        rep = audit(_write(td, _rec("t", -0.4, rule="time_stop", bars=50)))
        assert "loss_not_risk_rule" in [f["id"] for f in rep["flags"]]
        check = [c for c in rep["checks"] if c["id"] == "losses_closed_by_risk_rule"][0]
        assert check["ok"] is False


def test_end_of_data_is_flagged_even_when_profitable():
    with tempfile.TemporaryDirectory() as td:
        rep = audit(_write(td, _rec("e", 2.0, rule="end_of_data")))
        assert "end_of_data" in [f["id"] for f in rep["flags"]]


def test_small_sample_check_warns():
    with tempfile.TemporaryDirectory() as td:
        rep = audit(_write(td, _rec("a", -1.0)))
        check = [c for c in rep["checks"] if c["id"] == "enough_sample"][0]
        assert check["ok"] is False and "n=1" in check["detail"]


def test_longest_loss_streak_is_counted():
    with tempfile.TemporaryDirectory() as td:
        recs = []
        for i, r in enumerate((-1, -1, -1, 2, -1, -1)):
            recs += _rec(f"s{i}", r)
        rep = audit(_write(td, recs))
        assert rep["longest_loss_streak"] == 3


def test_truncated_line_does_not_kill_the_audit():
    with tempfile.TemporaryDirectory() as td:
        p = _write(td, _rec("a", -1.0) + _rec("b", 2.0))
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"type": "close", "id": "x", "open_id": "y"')   # نیمه‌کاره
        assert len(read_journal(p)) == 4
        rep = audit(p)
        assert rep["n"] == 2


def test_render_contains_the_honest_sentence_for_small_samples():
    with tempfile.TemporaryDirectory() as td:
        md = render(audit(_write(td, _rec("a", -1.0))))
        assert "بازبینی سلامت معاملات" in md
        assert "تعداد معامله کم است" in md
