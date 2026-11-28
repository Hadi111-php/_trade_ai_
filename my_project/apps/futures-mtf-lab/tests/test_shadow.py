"""تست‌های «دفتر خبر»: سیگنال خبری کاغذی + کارنامهٔ اعتبار منبع.

چرا این تست‌ها: کاربر می‌خواهد در لحظهٔ خبر یک سیگنال بزند و بعد بسنجد «آن منبع
چقدر معتبر بود». دو چیز نباید خراب شود:
  ۱) این دفتر **نباید** روی سیستم اثر بگذارد (سرمایه/اسلات/ژورنال).
  ۲) خروج خودکار باید با همان اعداد تنظیمات باشد، وگرنه R بی‌معنا می‌شود.
"""
import json
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import shadow as sh                                  # noqa: E402
from mtflab.config import load_config                           # noqa: E402
from mtflab.data import Candle, synthetic_candles               # noqa: E402
from mtflab.desk import Lab                                     # noqa: E402


def _cfg(**kw):
    cfg = load_config(["--data", "synthetic", "--quiet"])
    base = dict(verbose=False, forensics=False, run_id="", symbol="",
                tf_trigger="4h", fee_bps=5.5, slippage_pct=0.02,
                stop_atr_mult=1.5, take_profit_atr_mult=3.0,
                trail_enabled=False, breakeven_at_r=0.0, max_holding_bars=0)
    base.update(kw)
    return replace(cfg, **base)


def _rec(side="LONG", entry=100.0, stop=99.0, take=102.0, bar_ts=1000,
         stop_dist=1.0, tid="t1"):
    return {"type": "open", "id": tid, "symbol": "XUSDT", "side": side,
            "entry": entry, "stop": stop, "take": take, "bar_ts": bar_ts,
            "stop_dist": stop_dist,
            "source": {"votes": {"available": True, "ids": [], "n": 0},
                       "bias": None, "agree": None}}


def _c(ts, o, h, l, cl, v=1.0):
    return Candle(open_time_ms=ts, open=o, high=h, low=l, close=cl, volume=v)


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ساخت سیگنال: جهت، حد ضرر، حد سود، قیمت
# ══════════════════════════════════════════════════════════════════════════
def test_open_trade_respects_side_and_uses_live_price():
    cs = synthetic_candles("4h", 300, seed=303)
    cfg = _cfg()
    long_rec = sh.open_trade("BTCUSDT", "BUY", cs, cfg, price=12345.6,
                             price_source="ticker", note="خبر تست")
    short_rec = sh.open_trade("BTCUSDT", "SELL", cs, cfg, price=12345.6)
    assert long_rec["side"] == "LONG" and short_rec["side"] == "SHORT"
    assert long_rec["entry"] == 12345.6 and long_rec["price_source"] == "ticker"
    assert long_rec["stop"] < long_rec["entry"] < long_rec["take"]
    assert short_rec["stop"] > short_rec["entry"] > short_rec["take"]
    assert long_rec["note"] == "خبر تست"


def test_zero_or_huge_take_profit_is_reported_as_none():
    cs = synthetic_candles("4h", 300, seed=303)
    for tp in (0.0, 50.0):
        rec = sh.open_trade("BTCUSDT", "LONG", cs, _cfg(take_profit_atr_mult=tp), price=1000.0)
        assert rec["take"] is None, tp


def test_side_must_be_valid():
    try:
        sh.open_trade("BTCUSDT", "SIDEWAYS", synthetic_candles("4h", 300, seed=303), _cfg())
    except ValueError as e:
        assert "BUY" in str(e)
    else:
        raise AssertionError("جهت نامعتبر باید خطا بدهد")


# ══════════════════════════════════════════════════════════════════════════
#  ۲) خروج خودکار با تنظیمات
# ══════════════════════════════════════════════════════════════════════════
def test_stop_hit_closes_with_minus_one_r():
    cs = [_c(1000, 100, 100, 100, 100), _c(2000, 100, 100.4, 98.5, 99.0)]
    out = sh._walk_exit(_rec(), cs, _cfg())
    assert out and out["reason"] == "stop"
    assert out["exit"] == 99.0
    assert -1.2 < out["r_multiple"] <= -0.9, out["r_multiple"]
    assert out["is_win"] is False


def test_take_hit_closes_with_positive_r():
    cs = [_c(1000, 100, 100, 100, 100), _c(2000, 100, 102.5, 99.8, 102.0)]
    out = sh._walk_exit(_rec(), cs, _cfg())
    assert out["reason"] == "take" and out["exit"] == 102.0
    assert out["r_multiple"] > 1.5 and out["is_win"] is True


def test_same_bar_both_levels_assumes_stop_first():
    """بدبینانه‌ترین فرض: اگر یک کندل هم حد ضرر و هم حد سود را لمس کرد، ضرر."""
    cs = [_c(1000, 100, 100, 100, 100), _c(2000, 100, 103.0, 98.0, 100.5)]
    out = sh._walk_exit(_rec(), cs, _cfg())
    assert out["reason"] == "stop"


def test_time_stop_closes_at_bar_count():
    cs = [_c(1000, 100, 100, 100, 100),
          _c(2000, 100, 100.3, 99.6, 100.1),
          _c(3000, 100, 100.4, 99.7, 100.2)]
    out = sh._walk_exit(_rec(), cs, _cfg(max_holding_bars=2))
    assert out["reason"] == "time_stop" and out["bars_held"] == 2
    assert out["exit"] == 100.2, out["exit"]          # بستهٔ همان کندلِ دوم


def test_no_exit_while_price_inside_range():
    cs = [_c(1000, 100, 100, 100, 100), _c(2000, 100, 100.4, 99.6, 100.1)]
    assert sh._walk_exit(_rec(), cs, _cfg()) is None


def test_fees_and_slippage_reduce_net_pct():
    cs = [_c(1000, 100, 100, 100, 100), _c(2000, 100, 102.5, 99.8, 102.0)]
    out = sh._walk_exit(_rec(), cs, _cfg(fee_bps=10.0, slippage_pct=0.05))
    assert out["fee_pct"] == 0.2 and out["slip_pct"] == 0.1
    assert abs(out["net_pct"] - (out["gross_pct"] - 0.3)) < 1e-3


# ══════════════════════════════════════════════════════════════════════════
#  ۳) دفتر: بی‌اثر روی سیستم، بدون بست تکراری
# ══════════════════════════════════════════════════════════════════════════
def test_book_appends_each_close_only_once():
    with tempfile.TemporaryDirectory() as td:
        book = sh.ShadowBook(os.path.join(td, "shadow.jsonl"))
        book.append(_rec())
        cs = {"XUSDT": [_c(1000, 100, 100, 100, 100), _c(2000, 100, 100.4, 98.5, 99.0)]}
        first = book.book(cs, _cfg())
        assert first["fresh_closes"] == 1
        second = book.book(cs, _cfg())
        assert second["fresh_closes"] == 0
        assert len([e for e in book.events() if e["type"] == "close"]) == 1
        assert second["rows"][0]["status"] == "closed"


def test_lab_shadow_take_does_not_touch_journal_or_state():
    with tempfile.TemporaryDirectory() as td:
        data = os.path.join(td, "data", "json")
        os.makedirs(data, exist_ok=True)
        from mtflab.autoscan import candles_to_json
        for i, tf in enumerate(("4h", "1d")):
            cs = synthetic_candles(tf, 600 if tf == "4h" else 200, seed=303 + i)
            with open(os.path.join(data, f"btcusdt_{tf}.json"), "w", encoding="utf-8") as f:
                json.dump(candles_to_json(cs, {"symbol": "BTCUSDT", "tf": tf}), f)
        j = os.path.join(td, "journal.jsonl")
        st = os.path.join(td, "state.json")
        lab = Lab(data_dir=os.path.join(td, "data"), journal_path=j, state_path=st,
                  report_dir=td, lab_dir=td, symbols=["BTCUSDT"])
        r = lab.shadow_take("BTCUSDT", "LONG", note="خبر", offline=True)
        assert r["ok"] is True, r["note"]
        assert r["trade"]["price_source"] == "last_close"     # شبکه نبود ⇒ صادقانه
        assert not os.path.exists(j), "دفتر خبر نباید ژورنال اصلی را بسازد"
        assert not os.path.exists(st), "دفتر خبر نباید state را بنویسد"
        assert os.path.exists(lab.shadow_path)


def test_demo_mode_refuses_shadow_signal():
    with tempfile.TemporaryDirectory() as td:
        lab = Lab(data_dir=td, demo=True, journal_path=os.path.join(td, "j.jsonl"),
                  state_path=os.path.join(td, "s.json"), report_dir=td, lab_dir=td)
        r = lab.shadow_take("BTCUSDT", "LONG")
        assert r["ok"] is False and "نمایشی" in r["note"]


def test_manual_close_marks_reason_manual():
    with tempfile.TemporaryDirectory() as td:
        book = sh.ShadowBook(os.path.join(td, "shadow.jsonl"))
        book.append(_rec())
        out = book.close_manual("t1", price=101.0, candles=[_c(2000, 100, 101, 99, 100.5)],
                                cfg=_cfg())
        assert out["reason"] == "manual" and out["is_win"] is True
        try:
            book.close_manual("t1", price=101.0, cfg=_cfg())
        except ValueError as e:
            assert "قبلاً" in str(e)
        else:
            raise AssertionError("بستن دوباره باید خطا بدهد")


# ══════════════════════════════════════════════════════════════════════════
#  ۴) کارنامهٔ منبع
# ══════════════════════════════════════════════════════════════════════════
def _row(r, side="LONG", votes=(), agree=True):
    return {"status": "closed", "r_multiple": r, "side": side,
            "source": {"votes": {"ids": list(votes),
                                 "patterns": [{"id": v, "side": side} for v in votes]},
                       "agree": agree}}


def test_scorecard_math_and_verdict_thresholds():
    rows = [_row(2.0, votes=("base",)), _row(-1.0, votes=("base",)),
            _row(1.0, votes=("base",)), _row(-1.0, votes=("base",))]
    sc = sh.scorecard(rows, min_n=4)
    assert sc["overall"]["n"] == 4 and sc["overall"]["win_rate"] == 50.0
    assert sc["overall"]["expectancy_r"] == 0.25
    assert sc["by_source"][0]["id"] == "base"
    assert sc["by_source"][0]["verdict"]["code"] == "keep"
    sc2 = sh.scorecard([_row(-1.0)] * 5, min_n=4)
    assert sc2["overall"]["verdict"]["code"] == "drop"
    sc3 = sh.scorecard([_row(1.0)], min_n=10)
    assert sc3["overall"]["verdict"]["code"] == "need_more"


def test_scorecard_ignores_votes_with_opposite_side():
    row = {"status": "closed", "r_multiple": 1.0, "side": "LONG",
           "source": {"votes": {"ids": ["base", "trend"],
                                "patterns": [{"id": "base", "side": "LONG"},
                                             {"id": "trend", "side": "SHORT"}]},
                      "agree": True}}
    sc = sh.scorecard([row], min_n=1)
    ids = [s["id"] for s in sc["by_source"]]
    assert ids == ["base"], ids


def test_scorecard_groups_by_bias_agreement():
    rows = [_row(1.0, agree=True), _row(-1.0, agree=False), _row(0.5, agree=None)]
    sc = sh.scorecard(rows, min_n=10)
    got = {s["label"]: s["n"] for s in sc["by_agreement"]}
    assert got == {"هم‌جهت با بایاس": 1, "خلاف بایاس": 1, "بایاس نامشخص": 1}


def test_unvoted_news_signal_is_its_own_group():
    """سیگنالی که هیچ الگویی تأییدش نکرد باید جدا شمرده شود، نه نادیده."""
    row = {"status": "closed", "r_multiple": -1.0, "side": "LONG",
           "source": {"votes": {"ids": [], "patterns": []}, "agree": None}}
    sc = sh.scorecard([row], min_n=10)
    assert sc["unvoted"]["n"] == 1 and sc["unvoted"]["win_rate"] == 0.0
    assert any(x["id"] == sh.NONE_VOTE_LABEL for x in sc["by_source"])


# ══════════════════════════════════════════════════════════════════════════
#  ۵) CLI و داشبورد
# ══════════════════════════════════════════════════════════════════════════
def test_cli_opens_and_writes_json():
    with tempfile.TemporaryDirectory() as td:
        data = os.path.join(td, "data", "json")
        os.makedirs(data)
        from mtflab.autoscan import candles_to_json
        for i, tf in enumerate(("4h", "1d")):
            cs = synthetic_candles(tf, 400 if tf == "4h" else 150, seed=305 + i)
            with open(os.path.join(data, f"btcusdt_{tf}.json"), "w", encoding="utf-8") as f:
                json.dump(candles_to_json(cs, {"symbol": "BTCUSDT", "tf": tf}), f)
        book = os.path.join(td, "shadow.jsonl")
        rc = sh.shadow_command(["--book", book, "--data-dir", os.path.join(td, "data"),
                                "--open", "BTCUSDT", "--side", "SHORT",
                                "--note", "خبر", "--offline", "--json",
                                "--out-dir", td])
        assert rc == 0
        assert os.path.exists(book)
        assert os.path.exists(os.path.join(td, "shadow_book.json"))
        rec = json.loads(open(book, encoding="utf-8").readline())
        assert rec["side"] == "SHORT" and rec["shadow"] is True


def test_dashboard_has_shadow_tab_and_routes():
    from mtflab import labweb
    for needle in ('data-tab="shadow"', 'id="tab-shadow"', 'id="shBuy"',
                   'id="shSell"', 'id="shNote"', "دفتر خبر"):
        assert needle in labweb.PAGE, needle
    src = open(labweb.__file__, encoding="utf-8").read()
    for route in ('"/api/shadow"', '"/api/shadow_open"', '"/api/shadow_close"'):
        assert route in src, route


def test_ticker_helper_is_silent_when_offline():
    from mtflab.bybit_public import last_price
    assert last_price("BTCUSDT", base_url="http://127.0.0.1:9", timeout=1, retries=0) is None
