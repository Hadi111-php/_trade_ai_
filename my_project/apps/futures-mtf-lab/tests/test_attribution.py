"""تست‌های انتساب سیگنال به الگو — «این سیگنال بابت کدام الگو بود؟»

هدف تست‌ها: مطمئن شویم عددی که به کاربر می‌گوییم («این الگو بی‌فایده است») از
یک منبع واقعی می‌آید و نه از یک حدس. سه چیز قفل می‌شود:

1. الگویی که خودش سیگنال داده، **همیشه** در رأی‌ها هست (وگرنه کارنامه دروغ است).
2. حساب‌وکتاب کارنامه درست است (expectancy، نرخ برد، ضریب سود، حکم).
3. قاعدهٔ حذف با نمونهٔ کم حکم نمی‌دهد.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                   # noqa: E402

from mtflab.attribution import (MIN_N, VERDICT_DROP, VERDICT_KEEP,  # noqa: E402
                                VERDICT_NEED, pattern_votes, patterns_command,
                                prune_plan, render, scorecard)
from mtflab.config import load_config                             # noqa: E402
from mtflab.data import Candle, synthetic_candles                  # noqa: E402


def _cfg():
    cfg = load_config(["--data", "synthetic", "--quiet"])
    return replace(cfg, tf_trigger="4h", tf_filter="1d", tf_bias="1d",
                   verbose=False, forensics=False, run_id="", symbol="")


def _candles(n=1400, seed=301):
    return synthetic_candles("4h", n, seed=seed)


# ══════════════════════════════════════════════════════════════════════════
#  ۱) رأی‌گیری
# ══════════════════════════════════════════════════════════════════════════
def test_votes_are_available_and_deterministic():
    cs = _candles()
    bar_ts = cs[900].open_time_ms
    a = pattern_votes(cs, bar_ts, cfg=_cfg())
    b = pattern_votes(cs, bar_ts, cfg=_cfg())
    assert a["available"] is True
    assert a["ids"] == b["ids"], "رأی‌گیری باید تکرارپذیر باشد"
    assert a["method"] == "gates"


def test_votes_do_not_depend_on_position_slots():
    """رأی = «شرط‌های ورود برقرار بود»، نه «اسلات آزاد بود»."""
    cs = _candles()
    v = pattern_votes(cs, cs[900].open_time_ms, cfg=_cfg())
    assert v["available"] and "method" in v
    assert "checked" in v and v["checked"] >= 1


def test_votes_short_history_is_graceful():
    cs = _candles(n=40)
    v = pattern_votes(cs, cs[-1].open_time_ms, cfg=_cfg())
    assert v["available"] is False and v["ids"] == []
    assert "کندل کافی نیست" in v["note"]


def test_votes_unknown_bar_is_graceful():
    cs = _candles()
    v = pattern_votes(cs, 10_000, cfg=_cfg())        # قبل از شروع داده
    assert v["available"] is False


def test_producing_pattern_is_always_among_votes():
    """مهم‌ترین تست: الگویی که سیگنال داد، باید در رأی‌های همان کندل باشد."""
    from mtflab.live import LiveRunner

    cs = _candles(n=1600, seed=303)
    d = tempfile.mkdtemp()
    cfg = _cfg()
    runner = LiveRunner(cfg, "base", "پایه", {"tf_trigger": "4h"},
                        os.path.join(d, "state.json"),
                        os.path.join(d, "journal.jsonl"), votes=True)
    runner.run_symbol("TESTUSDT", cs, backfill=400)
    path = os.path.join(d, "journal.jsonl")
    assert os.path.exists(path), "هیچ سیگنالی باز نشد؛ تست بی‌معنا می‌شد"
    rows = [json.loads(x) for x in open(path, encoding="utf-8")]
    opens = [r for r in rows if r.get("type") == "open"]
    assert opens, "سیگنالی باز نشد"
    for o in opens:
        votes = o.get("pattern_votes") or {}
        assert votes.get("available") is True
        assert "base" in votes.get("ids", []), (
            f"سیگنال {o['id']} از base آمده ولی در رأی‌ها نیست: {votes.get('ids')}")


# ══════════════════════════════════════════════════════════════════════════
#  ۲) کارنامه
# ══════════════════════════════════════════════════════════════════════════
def _fake_journal(votes_for_first=True):
    out = []
    # ۳۰ سیگنال؛ ۲۰ برد ۲R و ۱۰ باخت −۱R ⇒ expectancy = (20*2 − 10)/30 = 1.0R
    for k in range(30):
        oid = f"X:base:{1000 + k}"
        out.append({"type": "open", "id": oid, "ts": 1000 + k, "symbol": "X",
                    "algorithm": {"id": "base", "label": "پایه"},
                    "entry_pattern": {"mode": "pullback"},
                    "pattern_votes": ({"available": True, "ids": ["base", "trend"]}
                                      if votes_for_first else None)})
        out.append({"type": "close", "open_id": oid, "ts": 2000 + k, "symbol": "X",
                    "algorithm": {"id": "base", "label": "پایه"},
                    "result": {"r_multiple": (2.0 if k < 20 else -1.0),
                               "pnl": (20.0 if k < 20 else -10.0),
                               "is_win": k < 20}})
    return out


def test_scorecard_math_and_verdict():
    card = scorecard(_fake_journal())
    base = card["by_algorithm"]["base"]
    assert base["n"] == 30 and base["wins"] == 20
    assert abs(base["win_rate"] - 66.7) < 0.1
    assert abs(base["expectancy_r"] - 1.0) < 1e-9
    assert abs(base["profit_factor"] - 4.0) < 1e-9
    assert base["verdict"] == VERDICT_KEEP


def test_scorecard_marks_loser_as_drop_candidate():
    j = _fake_journal()
    for c in j:
        if c.get("type") == "close":
            c["result"]["r_multiple"] = -1.0
            c["result"]["is_win"] = False
    card = scorecard(j)
    assert card["by_algorithm"]["base"]["verdict"] == VERDICT_DROP


def test_scorecard_refuses_to_judge_small_samples():
    j = _fake_journal()[:20]                      # ۱۰ سیگنال
    card = scorecard(j)
    assert card["by_algorithm"]["base"]["n"] == 10
    assert card["by_algorithm"]["base"]["verdict"] == VERDICT_NEED
    plan = prune_plan(card)
    assert plan["drop"] == []


def test_scorecard_counts_unvoted_old_journal_separately():
    card = scorecard(_fake_journal(votes_for_first=False))
    assert card["unvoted_signals"] == 30
    assert card["voted_signals"] == 0
    # سیگنال بدون رأی باید به حساب سازنده‌اش برود، نه اینکه حذف شود
    assert card["by_pattern_vote"]["base"]["signals"] == 30


def test_confluence_split_is_computed():
    card = scorecard(_fake_journal())
    assert card["confluence"]["multi"]["n"] == 30
    assert card["confluence"]["solo"]["n"] == 0


def test_prune_plan_separates_keep_and_need_more():
    card = scorecard(_fake_journal())
    plan = prune_plan(card)
    ids = [x["id"] for x in plan["keep"]]
    assert "base" in ids and "trend" in ids
    assert plan["drop"] == []
    assert "n ≥ 30" in plan["rule"]


# ══════════════════════════════════════════════════════════════════════════
#  ۳) گزارش و CLI
# ══════════════════════════════════════════════════════════════════════════
def test_render_has_the_three_sections():
    txt = render(scorecard(_fake_journal()))
    for needle in ("الگویی که سیگنال را ساخت", "رأی الگوها", "پیشنهاد حذف"):
        assert needle in txt


def test_patterns_command_writes_files():
    d = tempfile.mkdtemp()
    jp = os.path.join(d, "journal.jsonl")
    with open(jp, "w", encoding="utf-8") as f:
        for rec in _fake_journal():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rc = patterns_command(["--journal", jp, "--out-dir", d, "--json"])
    assert rc == 0
    assert os.path.exists(os.path.join(d, "pattern_scorecard.md"))
    with open(os.path.join(d, "pattern_scorecard.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert data["card"]["signals_total"] == 30
    assert "keep" in data["plan"]


def test_patterns_command_missing_journal_is_clear():
    assert patterns_command(["--journal", "/tmp/definitely-not-here.jsonl"]) == 2


# ══════════════════════════════════════════════════════════════════════════
#  ۴) اتصال به اتوترید و بایگانی V10
# ══════════════════════════════════════════════════════════════════════════
def test_autotrade_api_exposes_v10_and_votes():
    from mtflab import autotrade_api as api

    ds = {"BTCUSDT": synthetic_candles("15m", 900, seed=7)}
    rep = api.v10_run(ds)
    assert rep["strategy"] == "v10pro" and "metrics" in rep
    prox = api.v10_proximity(ds)
    assert prox and "long_score" in prox[0]

    ds4 = {"BTCUSDT": _candles(n=700)}
    rows = api.votes_now(ds4, "4h", "1d", "1d")
    assert rows and "firing" in rows[0]


def test_v10_archive_is_forensic():
    from mtflab.v10pro import archive_signals

    cs = synthetic_candles("15m", 2000, seed=9)
    d = tempfile.mkdtemp()
    res = archive_signals(cs, "TESTUSDT", d)
    assert res["written"] > 0
    files = sorted(os.listdir(os.path.join(d, "signal_archives")))
    assert files
    payload = json.load(open(os.path.join(d, "signal_archives", files[0]),
                             encoding="utf-8"))
    assert payload["algorithm"]["id"] == "v10pro"
    assert set(payload["components"]) == {"باند بولینگر", "RSI", "حجم", "کندل بازگشتی"}
    assert payload["last_5_candles"] and len(payload["last_5_candles"]) <= 5


# ══════════════════════════════════════════════════════════════════════════
#  ۵) تنظیمات پروپوزال (settings.json) روی V10
# ══════════════════════════════════════════════════════════════════════════
def test_proposal_settings_are_mapped_not_renamed():
    """فایل تنظیمات کاربر با همان کلیدهای خودش خوانده می‌شود."""
    from mtflab.v10pro import PARAMS, load_settings

    d = tempfile.mkdtemp()
    p = os.path.join(d, "v10_settings.json")
    json.dump({"fee_rate": 0.00055, "slippage": 0.0002,
               "round_trip_cost_pct": 0.0015,
               "v9_parameters": {"rr_ratio": 3.0, "rsi_period": 10,
                                 "min_reward_filter_pct": 0.005,
                                 "volume_multiplier": 1.5,
                                 "unknown_thing": 1}},
              open(p, "w", encoding="utf-8"))
    r = load_settings(p)
    assert r["found"] is True
    assert r["params"]["rr_ratio"] == 3.0
    assert r["params"]["rsi_period"] == 10
    assert abs(r["params"]["min_reward_pct"] - 0.5) < 1e-9   # کسری → درصد
    assert r["params"]["volume_multiplier"] == 1.5
    assert "unknown_thing" in r["ignored"]
    assert PARAMS["rr_ratio"] == 2.5, "پیش‌فرض ما نباید با خواندن فایل عوض شود"


def test_missing_settings_keeps_defaults():
    from mtflab.v10pro import PARAMS, apply_settings

    got = apply_settings("/tmp/definitely-no-such-file.json")
    assert got["rr_ratio"] == PARAMS["rr_ratio"]
    assert got["fee_rate"] == PARAMS["fee_rate"]


def test_repo_settings_file_is_consistent():
    """فایل تنظیمات داخل مخزن با پیش‌فرض‌ها هم‌خوان باشد (تا کسی سردرگم نشود)."""
    from mtflab.v10pro import PARAMS, load_settings

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "v10_settings.json")
    r = load_settings(path)
    assert r["found"] is True and r["ignored"] == []
    for k in ("rr_ratio", "bb_period", "bb_std", "time_stop_bars",
              "volume_multiplier", "atr_buffer"):
        assert abs(float(r["params"][k]) - float(PARAMS[k])) < 1e-9, k
