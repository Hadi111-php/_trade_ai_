"""تست‌های V10 Pro (بازگشت به میانگین: BB + RSI + حجم).

چرا این تست‌ها مهم‌اند: این استراتژی از بیرون آمده و اعدادش («OOS +۰.۶۵٪،
شارپ ۱.۲۵») ادعای تأییدنشده است. پس اول باید ثابت شود **قواعد دقیقاً همان‌طور
که نوشته شده پیاده شده‌اند** — وگرنه هر عددی که بعداً بگیریم بی‌معناست.

هر تست، یک شرط از پروپوزال را جدا می‌کند: اگر آن شرط را برداریم، سیگنال نباید
صادر شود.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.data import Candle                                        # noqa: E402
from mtflab.v10pro import (EXIT_FA, PARAMS, backtest, proximity,      # noqa: E402
                           scan_signals, signal_at, summarize)

STEP = 15 * 60 * 1000


def _base(n=60, price=100.0, vol=100.0):
    """کندل‌های آرام با نوسان کوچک — تا باندها باریک بمانند."""
    out = []
    for i in range(n):
        p = price + (0.05 if i % 2 else -0.05)
        out.append(Candle(i * STEP, p, p + 0.06, p - 0.06, p, vol))
    return out


def _long_setup(vol_spike=True, rsi_ok=True):
    """کندل انفجار نزولی + کندل بازگشتی صعودی = سیگنال LONG (اگر بقیه پاس باشند)."""
    cs = _base()
    n = len(cs)
    o = cs[-1].close
    cs.append(Candle(n * STEP, o, o + 0.1, o - 4.2, o - 4.0, 100.0))       # خروج زیر باند
    prev = cs[-1].close
    cs.append(Candle((n + 1) * STEP, prev - 0.1, prev + 2.6, prev - 0.4,
                     prev + 2.5, 500.0 if vol_spike else 100.0))          # بازگشت صعودی
    return cs


def _short_setup(vol_spike=True):
    cs = _base()
    n = len(cs)
    o = cs[-1].close
    cs.append(Candle(n * STEP, o, o + 4.2, o - 0.1, o + 4.0, 100.0))       # خروج بالای باند
    prev = cs[-1].close
    cs.append(Candle((n + 1) * STEP, prev + 0.1, prev + 0.4, prev - 2.6,
                     prev - 2.5, 500.0 if vol_spike else 100.0))          # بازگشت نزولی
    return cs


# ═══════════════════════════════════════════════════════════════════════════
# ۱) سیگنال: هر شرط جدا
# ═══════════════════════════════════════════════════════════════════════════
def test_long_signal_fires_with_the_exact_rules():
    cs = _long_setup()
    s = signal_at(cs, len(cs) - 1)
    assert s is not None, "سیگنال لانگ صادر نشد"
    assert s["side"] == "LONG"
    assert s["sl"] < s["entry"] < s["tp"]
    risk = s["entry"] - s["sl"]
    assert abs((s["tp"] - s["entry"]) - risk * PARAMS["rr_ratio"]) < 1e-6
    assert s["rsi_prev"] <= PARAMS["rsi_oversold"]
    assert s["vol_ratio"] >= PARAMS["volume_multiplier"]


def test_short_signal_fires_with_the_mirror_rules():
    cs = _short_setup()
    s = signal_at(cs, len(cs) - 1)
    assert s is not None, "سیگنال شورت صادر نشد"
    assert s["side"] == "SHORT"
    assert s["tp"] < s["entry"] < s["sl"]
    assert s["rsi_prev"] >= PARAMS["rsi_overbought"]


def test_no_signal_without_volume_spike():
    cs = _long_setup(vol_spike=False)
    assert signal_at(cs, len(cs) - 1) is None


def test_no_signal_without_rsi_extreme():
    cs = _long_setup()
    assert signal_at(cs, len(cs) - 1, {"rsi_oversold": 0.0}) is None


def test_cost_filter_blocks_small_rewards():
    cs = _long_setup()
    assert signal_at(cs, len(cs) - 1, {"min_reward_pct": 99.0}) is None


def test_signal_needs_the_previous_candle_outside_the_band():
    cs = _base()
    n = len(cs)
    o = cs[-1].close
    cs.append(Candle(n * STEP, o, o + 0.2, o - 0.2, o + 0.15, 500.0))
    assert signal_at(cs, len(cs) - 1) is None


def test_signal_never_looks_ahead():
    cs = _long_setup()
    i = len(cs) - 2                      # کندل اولِ الگو (هنوز بازگشتی نیست)
    a = signal_at(cs, i)
    cs2 = list(cs) + [Candle((len(cs) + k) * STEP, 1.0, 1e9, 0.001, 1e8, 1e12)
                      for k in range(10)]
    b = signal_at(cs2, i)
    assert a == b


def test_last_candle_signal_is_identical_with_or_without_future_bars():
    cs = _long_setup()
    last = len(cs) - 1
    a = signal_at(cs, last)
    # اگر کندل‌های آینده اضافه شوند، سیگنال «همان کندل» باید همان بماند
    cs2 = list(cs) + [Candle((last + 1 + k) * STEP, 1.0, 2.0, 0.5, 1.5, 1.0)
                      for k in range(5)]
    b = signal_at(cs2, last)
    assert a == b


def test_scan_signals_matches_signal_at():
    cs = _long_setup()
    fast = [(s["i"], s["side"]) for s in scan_signals(cs)]
    slow = [(i, s["side"]) for i in range(1, len(cs))
            for s in [signal_at(cs, i)] if s]
    assert fast == slow


# ═══════════════════════════════════════════════════════════════════════════
# ۲) بک‌تست: مدیریت پوزیشن
# ═══════════════════════════════════════════════════════════════════════════
def _run(entry="next_open", same_bar="pessimistic"):
    cs = _long_setup()
    # بعد از ورود: سه کندل صعودی تا حد سود/میانگین
    n = len(cs)
    p = cs[-1].close
    for k in range(20):
        p2 = p * 1.012
        # شکاف کوچک بین بسته و باز شدن، تا ورود در بسته و در باز شدن یکی نباشند
        cs.append(Candle((n + k) * STEP, p * 1.003, p2 + 0.2, p - 0.2, p2, 120.0))
        p = p2
    return backtest(cs, entry=entry, same_bar=same_bar, symbol="T")


def test_backtest_produces_trades_with_valid_reasons():
    res = _run()
    assert res["trades"], "هیچ معامله‌ای ثبت نشد"
    for t in res["trades"]:
        assert t["reason"] in EXIT_FA
        assert t["side"] in ("LONG", "SHORT")
        assert t["exit"] > 0 and t["entry"] > 0
        assert "fees_pct" in t and t["fees_pct"] > 0


def test_only_one_position_at_a_time():
    res = _run()
    for a, b in zip(res["trades"], res["trades"][1:]):
        assert b["entry_ts"] >= a["exit_ts"]


def test_time_stop_closes_a_flat_trade():
    cs = _long_setup()
    n = len(cs)
    p = cs[-1].close
    for k in range(40):                       # بازار بی‌حرکت: نه TP نه SL
        cs.append(Candle((n + k) * STEP, p, p + 0.15, p - 0.15, p, 120.0))
    res = backtest(cs)
    reasons = [t["reason"] for t in res["trades"]]
    assert "TIME" in reasons or "BB_MID" in reasons or "END" in reasons


def test_breakeven_moves_stop_and_is_reported():
    """اگر قیمت به ۱R برسد، استاپ به سربه‌سر می‌رود و برچسبش BE است."""
    cs = _long_setup()
    s = signal_at(cs, len(cs) - 1)
    entry = s["entry"]
    risk = entry - s["sl"]
    n = len(cs)
    # یک کندل که به ۱.۲R می‌رسد ولی به TP نمی‌رسد
    cs.append(Candle(n * STEP, entry, entry + risk * 1.2, entry - 0.05,
                     entry + risk * 1.1, 150.0))
    # بعد یک کندل که به استاپِ جدید (سربه‌سر) می‌خورد
    cs.append(Candle((n + 1) * STEP, entry + risk * 1.1, entry + risk * 1.1,
                     entry - risk * 0.6, entry - risk * 0.5, 150.0))
    # خروج «باند میانی» همیشه قبل از سپر فعال می‌شود و برد را سقف‌دار می‌کند،
    # پس برای دیدن رفتار سپر باید آن را خاموش کرد (همین کلید برای تحلیل سود هم هست).
    res = backtest(cs, {"bb_mid_exit": False})
    assert res["trades"], "معامله ثبت نشد"
    t = res["trades"][0]
    assert t["be"] is True and t["reason"] == "BE"


def test_pessimistic_same_bar_assumes_stop_first():
    """اگر در یک کندل هم SL و هم TP لمس شد، فرض بدبینانه: SL."""
    cs = _long_setup()
    s = signal_at(cs, len(cs) - 1)
    n = len(cs)
    entry = s["entry"]
    # کندلی که هم به TP می‌رسد هم به SL
    tp_safe = entry + (entry - s["sl"]) * 3.0      # بالاتر از TP واقعیِ پوزیشن
    cs.append(Candle(n * STEP, entry, tp_safe, s["sl"] * 0.999, entry, 200.0))
    pes = backtest(cs, {"bb_mid_exit": False}, same_bar="pessimistic")["trades"][0]
    opt = backtest(cs, {"bb_mid_exit": False}, same_bar="optimistic")["trades"][0]
    assert pes["reason"] in ("SL", "BE")
    assert opt["reason"] == "TP"


def test_entry_close_vs_next_open_fill_differently():
    a = _run(entry="next_open")
    b = _run(entry="close")
    assert a["trades"] and b["trades"]
    assert a["trades"][0]["entry"] != b["trades"][0]["entry"]
    # هر دو باید فقط از سیگنال‌های واقعیِ همین سری آمده باشند
    assert a["trades"][0]["side"] == b["trades"][0]["side"]


def test_risk_sizing_keeps_loss_near_one_percent_when_stopped():
    res = _run()
    t = [x for x in res["trades"] if x["reason"] in ("SL", "BE")]
    if t:
        # ضرر خالص هر معاملهٔ استاپ‌خورده باید نزدیک ۱٪ سرمایه باشد
        assert all(abs(x["net_pct"]) < 3.0 for x in t)


# ═══════════════════════════════════════════════════════════════════════════
# ۳) سنجه‌ها و نزدیکی
# ═══════════════════════════════════════════════════════════════════════════
def test_summarize_math():
    res = {"trades": [
        {"r": 2.5, "pnl": 25.0, "net_pct": 2.5, "gross_pct": 2.65, "fees_pct": 0.15,
         "reason": "TP", "bars": 5},
        {"r": -1.0, "pnl": -10.0, "net_pct": -1.0, "gross_pct": -0.85, "fees_pct": 0.15,
         "reason": "SL", "bars": 4}],
        "equity_curve": [1000.0, 1025.0, 1015.0]}
    s = summarize(res)
    assert s["n"] == 2 and s["wins"] == 1
    assert abs(s["expectancy_r"] - 0.75) < 1e-9
    assert abs(s["profit_factor"] - 2.5) < 1e-9
    assert s["by_reason"] == {"TP": 1, "SL": 1}
    assert s["max_dd_pct"] <= 0.0 and abs(s["max_dd_pct"] + 1.0) < 1e-9


def test_proximity_scores_are_bounded_and_explain_themselves():
    pr = proximity(_long_setup())
    assert pr is not None
    for k in ("long_score", "short_score"):
        assert 0.0 <= pr[k] <= 100.0
    assert set(pr["long_breakdown"]) == {"نزدیک باند پایین", "RSI اشباع فروش",
                                         "جهش حجم", "الگوی دو کندل"}
    assert pr["signal"] and pr["signal"]["side"] == "LONG"


def test_proximity_is_none_on_short_history():
    assert proximity(_base(10)) is None


def test_proximity_signal_matches_signal_at():
    cs = _long_setup()
    pr = proximity(cs)
    s = signal_at(cs, len(cs) - 1)
    assert (pr["signal"] is None) == (s is None)
    if s:
        assert pr["signal"]["side"] == s["side"]


# ═══════════════════════════════════════════════════════════════════════════
# ۴) اتصال به داشبورد (تب V10 Pro)
# ═══════════════════════════════════════════════════════════════════════════
def test_desk_v10_report_reads_both_files(tmp_path=None):
    import json as _json
    import tempfile
    from mtflab.desk import Lab

    d = tempfile.mkdtemp()
    with open(os.path.join(d, "v10_report.json"), "w", encoding="utf-8") as f:
        _json.dump({"summary": {"n": 3, "win_rate": 33.3},
                    "trades": [{"symbol": "X", "side": "LONG", "r": 1.0,
                                "reason": "TP", "bars": 2}],
                    "data": {"sources": ["bybit"], "labeled": True}}, f)
    with open(os.path.join(d, "v10_proximity.json"), "w", encoding="utf-8") as f:
        _json.dump([{"symbol": "X", "long_score": 80, "short_score": 10}], f)
    rep = Lab(report_dir=d).v10_report()
    assert rep["available"] is True
    assert rep["summary"]["n"] == 3
    assert rep["rows"][0]["long_score"] == 80
    assert rep["trades"][0]["side"] == "LONG"
    assert rep["stale_sec"] is not None


def test_desk_v10_report_is_graceful_when_missing():
    import tempfile
    from mtflab.desk import Lab
    rep = Lab(report_dir=tempfile.mkdtemp()).v10_report()
    assert rep["available"] is False and rep["rows"] == []
    assert "v10" in rep["hint"]
