"""تست‌های پامپ و دامپ.

چهار چیز باید قفل شود، وگرنه این ماژول می‌تواند هر عددی را «لبه» نشان دهد:

  ۱. **هیچ نگاه به آینده‌ای در تشخیص نیست** — کندل‌های بعدی نباید روی تشخیص
     رویداد در کندل i اثری بگذارند.
  ۲. **ورود واقع‌گرایانه** — پیش‌فرض روی بازِ کندل بعد، نه بستهٔ همان کندل پامپ.
  ۳. **شمارش مستقل** — ۱۰ رویداد در یک ساعت یک رویداد است، نه ده.
  ۴. **بی‌ساختاری لبه نمی‌سازد** — روی دادهٔ تصادفی، دروازه نباید پاس شود.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.data import Candle, synthetic_candles                        # noqa: E402
from mtflab.pumpdump import (bar_features, cluster_events, detect,       # noqa: E402
                             evaluate, median, net_return, quantile, render,
                             time_clusters, worst_fraction_mean)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEP = 15 * 60 * 1000


def _quiet(n=120, price=100.0, vol=100.0):
    """کندل‌های آرام: دامنهٔ کوچک و حجم ثابت (برای کاشتن رویداد در آن)."""
    out = []
    for i in range(n):
        o = price
        c = price * 1.0002
        out.append(Candle(i * STEP, o, o * 1.001, o * 0.999, c, vol))
    return out


def _plant_pump(candles, at, mult=6.0):
    """یک کندل انفجاری می‌کارد: دامنهٔ بزرگ + حجم بزرگ + بسته در سقف."""
    cs = list(candles)
    o = cs[at].open
    cs[at] = Candle(at * STEP, o, o * (1 + mult / 100), o * 0.999,
                    o * (1 + mult / 100 * 0.95), 5000.0)
    return cs


# ═══════════════════════════════════════════════════════════════════════════
# ۱) بدون نگاه به آینده
# ═══════════════════════════════════════════════════════════════════════════
def test_features_ignore_future_candles():
    cs = _plant_pump(_quiet(), at=80)
    f1 = bar_features(cs, 80, 50)
    # کندل‌های بعد از ۸۰ را کاملاً عوض می‌کنیم
    cs2 = cs[:81] + [Candle(81 * STEP + i * STEP, 1, 999, 0.1, 5, 1e9) for i in range(20)]
    f2 = bar_features(cs2, 80, 50)
    assert f1 == f2


def test_detection_at_i_is_stable_when_future_changes():
    cs = _plant_pump(_quiet(), at=80)
    a = [(e["i"], e["side"]) for e in detect(cs)]
    cs2 = cs[:81] + [Candle(81 * STEP + i * STEP, 1, 999, 0.1, 5, 1e9) for i in range(40)]
    b = [(e["i"], e["side"]) for e in detect(cs2) if e["i"] <= 80]
    assert a == b


def test_pumpdump_never_imports_trading_logic():
    """پامپ‌ودامپ نباید به موتور/سیگنال/هم‌راستایی وابسته باشد — مکانیزم جداست."""
    src = open(os.path.join(HERE, "mtflab", "pumpdump.py"), encoding="utf-8").read()
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[-1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[-1])
    forbidden = {"engine", "signals", "alignment", "brain", "brainview", "observer"}
    assert not (mods & forbidden), mods & forbidden


# ═══════════════════════════════════════════════════════════════════════════
# ۲) تشخیص درست
# ═══════════════════════════════════════════════════════════════════════════
def test_planted_pump_is_detected_with_all_three_conditions():
    cs = _plant_pump(_quiet(), at=80)
    ev = detect(cs)
    assert len(ev) == 1
    e = ev[0]
    assert e["i"] == 80 and e["side"] == "pump"
    assert e["range_mult"] >= 2.5 and e["vol_mult"] >= 3.0 and e["close_pos"] >= 0.75


def test_planted_dump_is_detected_as_dump():
    cs = _quiet()
    o = cs[80].open
    cs = list(cs)
    cs[80] = Candle(80 * STEP, o, o * 1.001, o * (1 - 0.06), o * (1 - 0.058), 5000.0)
    ev = detect(cs)
    assert [e["side"] for e in ev] == ["dump"]


def test_quiet_market_produces_no_events():
    assert detect(_quiet(300)) == []


def test_warmup_is_respected():
    cs = _plant_pump(_quiet(60), at=10)          # رویداد قبل از پر شدن warmup
    assert detect(cs, lookback=50) == []


# ═══════════════════════════════════════════════════════════════════════════
# ۳) ورود واقع‌گرایانه و هزینه
# ═══════════════════════════════════════════════════════════════════════════
def test_default_entry_is_next_open_not_the_pump_close():
    cs = _plant_pump(_quiet(), at=80)
    cs = list(cs)
    # بازِ کندل بعد را عمداً از بستهٔ کندل پامپ جدا می‌کنیم
    nxt = cs[81]
    cs[81] = Candle(nxt.open_time_ms, cs[80].close * 1.10, nxt.high, nxt.low,
                    nxt.close, nxt.volume)
    r_next = net_return(cs, 80, "pump", 3, 0.0, entry="next_open")
    r_close = net_return(cs, 80, "pump", 3, 0.0, entry="close")
    assert abs(r_next - (cs[83].close / cs[81].open - 1)) < 1e-12
    assert abs(r_close - (cs[83].close / cs[80].close - 1)) < 1e-12
    assert r_next != r_close


def test_cost_is_subtracted_exactly_once():
    cs = _plant_pump(_quiet(), at=80)
    free = net_return(cs, 80, "pump", 3, 0.0)
    paid = net_return(cs, 80, "pump", 3, 0.0015)
    assert abs((free - paid) - 0.0015) < 1e-12


def test_dump_return_is_short_side():
    cs = _quiet()
    o = cs[80].open
    cs = list(cs)
    cs[80] = Candle(80 * STEP, o, o * 1.001, o * 0.94, o * 0.942, 5000.0)
    r = net_return(cs, 80, "dump", 3, 0.0)
    e, x = cs[81].open, cs[83].close
    assert abs(r - (e / x - 1)) < 1e-12


def test_no_return_when_future_is_missing():
    cs = _plant_pump(_quiet(90), at=85)
    assert net_return(cs, 85, "pump", 12, 0.0) is None      # افق از داده بیرون است


# ═══════════════════════════════════════════════════════════════════════════
# ۴) خوشه‌بندی — «چند رویداد مستقل؟»
# ═══════════════════════════════════════════════════════════════════════════
def test_events_close_in_time_collapse_into_one_cluster():
    cs = _quiet(200)
    for at in (80, 81, 82, 83, 84):                         # ۵ پامپ پشت‌سرهم
        cs = _plant_pump(cs, at)
    ev = detect(cs)
    assert len(ev) >= 4
    ev = [dict(e, symbol="X") for e in ev]
    cl = cluster_events(ev, STEP, gap_bars=4)
    assert len(cl) == 1, [c["n"] for c in cl]
    assert len(time_clusters(cl, STEP, 4)) == 1


def test_far_apart_events_stay_separate():
    cs = _quiet(400)
    for at in (80, 200, 320):
        cs = _plant_pump(cs, at)
    ev = [dict(e, symbol="X") for e in detect(cs)]
    assert len(time_clusters(cluster_events(ev, STEP, 4), STEP, 4)) == 3


def test_cross_symbol_simultaneous_events_are_one_independent_event():
    """همهٔ سکه‌ها با هم پامپ می‌کنند — ۱۰ مشاهدهٔ مستقل نیست."""
    uni = {}
    for i, sym in enumerate(("A", "B", "C", "D", "E")):
        cs = _plant_pump(_quiet(200), at=80)
        uni[sym] = cs
    rep = evaluate(uni, "15m")
    assert rep["n_events_raw"] >= 5
    assert rep["n_independent"] == 1, rep["n_independent"]


# ═══════════════════════════════════════════════════════════════════════════
# ۵) آمار پایه
# ═══════════════════════════════════════════════════════════════════════════
def test_quantile_and_median_are_sane():
    xs = list(range(101))
    assert median(xs) == 50
    assert quantile(xs, 0.0) == 0 and quantile(xs, 1.0) == 100
    assert abs(quantile(xs, 0.25) - 25) < 1e-9
    assert median([]) is None and quantile([], 0.5) is None


def test_worst_five_percent_uses_the_tail():
    xs = [-10, -9, -8] + [1] * 17          # ۲۰ نمونه، ۵٪ = ۱ نمونه
    assert worst_fraction_mean(xs, 0.05) == -10
    assert worst_fraction_mean([], 0.05) is None


# ═══════════════════════════════════════════════════════════════════════════
# ۶) بی‌ساختاری نباید لبه بسازد (مهم‌ترین تست)
# ═══════════════════════════════════════════════════════════════════════════
def test_random_data_does_not_pass_the_gate():
    uni = {f"R{i}": synthetic_candles("15m", 4000, seed=101 + i) for i in range(6)}
    rep = evaluate(uni, "15m")
    assert rep["passed"] is False, [
        (c["id"], c["detail"]) for c in rep["checks"] if c["ok"]]
    # و «اختلاف با خط پایه» نباید ادعای بزرگی بدهد
    if rep["lift_primary"] is not None:
        assert abs(rep["lift_primary"]) < 0.01


def test_report_always_compares_to_baseline_and_shows_gate():
    uni = {"X": synthetic_candles("15m", 2500, seed=7)}
    rep = evaluate(uni, "15m")
    md = render(rep, "fa")
    assert "خط پایه" in md and "دروازهٔ ازپیش‌نوشته" in md
    assert rep["baseline"] and 6 in rep["baseline"]


def test_empty_input_is_safe():
    rep = evaluate({}, "15m")
    assert rep["n_events_raw"] == 0 and rep["passed"] is False
    assert "هیچ داده‌ای نیست" in " ".join(rep["warnings"])
    render(rep, "fa")                                  # نباید استثنا بدهد


def test_cost_grid_is_monotonic():
    uni = {"X": synthetic_candles("15m", 3000, seed=5)}
    rep = evaluate(uni, "15m")
    grid = rep["by_horizon"][6]["by_cost"]
    keys = list(grid)
    meds = [grid[k]["median"] for k in keys]
    assert all(a > b for a, b in zip(meds, meds[1:])), (keys, meds)


def test_gate_reports_six_predeclared_checks():
    rep = evaluate({"X": synthetic_candles("15m", 2000, seed=3)}, "15m")
    ids = [c["id"] for c in rep["checks"]]
    assert ids == ["n_independent", "median_positive", "months_positive",
                   "left_tail", "symbols_positive", "out_of_sample"]
