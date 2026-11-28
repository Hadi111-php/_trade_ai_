"""تست‌های چشم شکارچی.

سه چیز باید قفل شود:

۱. **ریاضیات AUC و آزمون جایگشتی درست است** (وگرنه هر «کشف» بی‌معناست).
۲. **ویژگی کاشته‌شده را پیدا می‌کند** — اگر روی داده‌ای که خودمان ساختیم تفاوت
   را نبیند، ابزار خراب است.
۳. **روی نویز چیزی «کشف» نمی‌کند** — مهم‌ترین تست این فایل: با ۱۸ ویژگی و
   n کوچک، هر ابزاری می‌تواند چند «یافته» جعل کند؛ این یکی نباید.
"""
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.hunter import (_longest_loss_streak, _max_drawdown,    # noqa: E402
                           analyze, auc, permutation_p, read_journal, render)


def _trade(i, r, ctx, ts=None):
    return {"id": f"T{i}", "symbol": "X", "ts": ts if ts is not None else 1000 + i,
            "r": r, "is_win": r > 0, "pnl": r * 10, "bars": 10,
            "rule": "stop_loss", "is_risk_control": r <= 0, "context": dict(ctx)}


def _journal(td, trades):
    p = os.path.join(td, "j.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for i, t in enumerate(trades):
            f.write(json.dumps({
                "type": "open", "id": t["id"], "ts": t["ts"], "symbol": t["symbol"],
                "entry_pattern": {"mode": "breakout"},
                "algorithm": {"id": "trend"},
                "context": t["context"]}, ensure_ascii=False) + "\n")
            f.write(json.dumps({
                "type": "close", "id": t["id"] + ":c", "open_id": t["id"],
                "ts": t["ts"] + 100, "symbol": t["symbol"],
                "algorithm": {"id": "trend"},
                "closed_by": {"id": "stop_loss", "fa": "حد ضرر",
                              "is_risk_control": True},
                "result": {"pnl": t["pnl"], "r_multiple": t["r"],
                           "is_win": t["r"] > 0}}, ensure_ascii=False) + "\n")
    return p


# ═══════════════════════════════════════════════════════════════════════════
# ۱) ریاضیات
# ═══════════════════════════════════════════════════════════════════════════
def test_auc_extremes_and_middle():
    assert auc([5, 6, 7], [1, 2, 3]) == 1.0
    assert auc([1, 2, 3], [5, 6, 7]) == 0.0
    assert abs(auc([1, 2, 3], [1, 2, 3]) - 0.5) < 1e-12     # تساوی کامل
    assert auc([], [1]) is None and auc([1], []) is None


def test_auc_counts_ties_as_half():
    # یک برنده وسط و یک بازنده وسط: نیمی از جفت‌ها مساوی‌اند
    assert abs(auc([2], [2]) - 0.5) < 1e-12


def test_permutation_p_is_small_for_clean_separation_and_large_for_noise():
    pos = [10, 11, 12, 13, 14, 15]
    neg = [1, 2, 3, 4, 5, 6]
    a = auc(pos, neg)
    assert a == 1.0
    p_clean = permutation_p(pos, neg, a, n_perm=200)
    assert p_clean is not None and p_clean < 0.02

    rnd = random.Random(3)
    same = [rnd.gauss(0, 1) for _ in range(30)]
    other = [rnd.gauss(0, 1) for _ in range(30)]
    a_noise = auc(same, other)
    p_noise = permutation_p(same, other, a_noise, n_perm=200)
    assert p_noise > 0.05


def test_permutation_is_deterministic_for_a_fixed_seed():
    pos, neg = [1, 2, 3, 4], [2, 3, 4, 5]
    a = auc(pos, neg)
    assert permutation_p(pos, neg, a, 100, 7) == permutation_p(pos, neg, a, 100, 7)


def test_loss_streak_and_drawdown():
    assert _longest_loss_streak([-1, -1, -1, 2, -1]) == 3
    assert _longest_loss_streak([1, 2]) == 0
    assert _max_drawdown([1, -1, -1, 3]) == -2.0


# ═══════════════════════════════════════════════════════════════════════════
# ۲) ویژگی کاشته‌شده پیدا می‌شود
# ═══════════════════════════════════════════════════════════════════════════
def test_planted_feature_is_flagged_as_candidate():
    rnd = random.Random(11)
    trades = []
    for i in range(60):
        win = i % 2 == 0
        noise = random.Random(500 + i)                     # جریان تصادفی جدا
        ctx = {"adx": (40.0 + rnd.uniform(-2, 2)) if win else (12.0 + rnd.uniform(-2, 2)),
               "rsi": noise.uniform(30, 70)}               # rsi = نویز خالص
        trades.append(_trade(i, 2.0 if win else -1.0, ctx))
    rep = analyze(trades, min_n=40, n_perm=200)
    assert "adx" in rep["candidates"], rep["features"]
    verdicts = {r["key"]: r["verdict"] for r in rep["features"]}
    assert verdicts["adx"] == "قابل بررسی"
    assert verdicts["rsi"] != "قابل بررسی"


def test_feature_that_fails_out_of_sample_is_not_a_candidate():
    """کشف خوب، تأیید برعکس → باید «نویز» شود، نه نامزد."""
    rnd = random.Random(12)
    trades = []
    for i in range(80):
        first_half = i < 48
        win = i % 2 == 0
        base = 30.0 if (win == first_half) else 10.0     # در نیمهٔ دوم برعکس
        trades.append(_trade(i, 2.0 if win else -1.0,
                             {"adx": base + rnd.uniform(-1, 1)}))
    rep = analyze(trades, min_n=40, n_perm=200)
    v = {r["key"]: r["verdict"] for r in rep["features"]}
    assert v["adx"] != "قابل بررسی"


# ═══════════════════════════════════════════════════════════════════════════
# ۳) روی نویز چیزی جعل نمی‌کند
# ═══════════════════════════════════════════════════════════════════════════
def test_pure_noise_produces_no_candidates():
    rnd = random.Random(99)
    keys = ["adx", "rsi", "atr_pct", "vol_z", "ema_slope_pct"]
    trades = []
    for i in range(70):
        ctx = {k: rnd.gauss(0, 1) for k in keys}
        trades.append(_trade(i, rnd.choice([2.0, -1.0, -1.0]), ctx))
    rep = analyze(trades, min_n=40, n_perm=300)
    assert rep["candidates"] == [], [(r["key"], r["auc"], r["p"]) for r in rep["features"]]


def test_small_sample_says_so_and_still_renders():
    trades = [_trade(i, 1.0 if i % 2 else -1.0, {"adx": 20.0 + i}) for i in range(8)]
    rep = analyze(trades, min_n=40, n_perm=100)
    assert any("n=8" in w for w in rep["warnings"])
    md = render(rep)
    assert "چشم شکارچی" in md and "هیچ پارامتری را عوض نمی‌کند" in md


# ═══════════════════════════════════════════════════════════════════════════
# ۴) خواندن ژورنال
# ═══════════════════════════════════════════════════════════════════════════
def test_read_journal_pairs_and_ignores_broken_lines():
    with tempfile.TemporaryDirectory() as td:
        p = _journal(td, [_trade(0, -1.0, {"adx": 10}), _trade(1, 2.0, {"adx": 30})])
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"type": "close", "broken"')
        tr = read_journal(p)
        assert len(tr) == 2
        assert {t["r"] for t in tr} == {-1.0, 2.0}
        assert all(t["context"].get("adx") for t in tr)


def test_missing_journal_is_empty_not_error():
    assert read_journal("/nonexistent/x.jsonl") == []
    rep = analyze([])
    assert rep["dist"]["n"] == 0
    assert rep["candidates"] == []
    render(rep)


def test_trades_without_context_still_count_in_distribution():
    with tempfile.TemporaryDirectory() as td:
        p = _journal(td, [_trade(0, -1.0, {}), _trade(1, 2.0, {})])
        rep = analyze(read_journal(p))
        assert rep["dist"]["n"] == 2
        assert any("هیچ ویژگی زمینه" in w for w in rep["warnings"])


def test_report_counts_wins_and_losses_together():
    trades = [_trade(i, 2.0 if i % 4 == 0 else -1.0, {"adx": 20 + i})
              for i in range(20)]
    rep = analyze(trades, min_n=10, n_perm=50)
    d = rep["dist"]
    assert d["wins"] + d["losses"] == d["n"] == 20
    assert d["expectancy_r"] is not None
    assert d["risk_control_share"] == 1.0
