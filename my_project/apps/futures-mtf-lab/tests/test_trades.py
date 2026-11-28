"""تست‌های ابزار آزمون معاملات: قله/دره و «استراحت بعد از سود».

چرا مهم است؟ این ابزار دو ادعا را می‌سنجد که هر دو وسوسه‌کننده‌اند و هر دو
می‌توانند به overfit تبدیل شوند. پس سه چیز باید قفل شود:

۱. **قله/دره بدون نگاه به آینده** — قله فقط k کندل بعد تأیید می‌شود.
۲. **آزمون روی دادهٔ بدون اثر، اثر پیدا نکند** — و روی دادهٔ با اثر، پیدا کند.
۳. **باند نویز درست باشد** — اگر اثر صفر باشد، «بهبود» هم باید صفر بماند.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.data import Candle, synthetic_candles                     # noqa: E402
from mtflab.trades import (GATE, _structure_at, analysis_cluster,     # noqa: E402
                           analysis_peakvalley, cluster_sim,
                           flatten_symbols, swing_ratio_from, swings)


# ═══════════════════════════════════════════════════════════════════════════
# ۱) قله/درهٔ تأییدشده — بدون نگاه به آینده
# ═══════════════════════════════════════════════════════════════════════════
def _zigzag():
    """قیمت مصنوعی با قله و درهٔ روشن: ۱۰۰ → ۱۱۰ → ۹۰ → ۱۲۰ …"""
    ohlc = [(100, 101, 99), (105, 106, 104), (110, 111, 109), (105, 106, 104),
            (100, 101, 99), (95, 96, 94), (90, 91, 89), (95, 96, 94),
            (100, 101, 99), (110, 111, 109), (120, 121, 119), (115, 116, 114)]
    return [Candle(i * 3600_000, o, h, l, c, 1.0) for i, (o, h, l) in enumerate(ohlc)] \
        if False else [Candle(i * 3600_000, float(h), float(h), float(l), float(l), 1.0)
                       for i, (o, h, l) in enumerate(ohlc)]


def test_peak_is_never_known_before_it_is_confirmed():
    """قلهٔ کندل ۲ فقط در کندل ۲+k معلوم می‌شود، نه زودتر."""
    cs = _zigzag()
    sw = swings(cs, k=2)
    # قله در ایندکس ۲ (high=111). تا i=4 نباید دیده شود (2+2=4 ⇒ در ۴ دیده می‌شود)
    assert sw[3]["peak"] is None or sw[3]["peak_i"] != 2
    assert sw[4]["peak_i"] == 2


def test_trough_is_confirmed_the_same_way():
    cs = _zigzag()
    sw = swings(cs, k=2)
    # درهٔ ۸۹ در ایندکس ۶ رخ داده و در ۶+۲=۸ تأیید می‌شود — نه زودتر
    assert sw[7]["trough"] is None
    assert sw[8]["trough_i"] == 6


def test_swing_ratio_is_zero_at_the_trough_and_one_at_the_peak():
    cs = _zigzag()
    sw = swings(cs, k=2)
    s = sw[-1]        # آخرین قلهٔ تأییدشده ۱۱۱ و دره ۸۹ است (۱۲۱ هنوز تأیید نشده)
    assert s["peak"] == 111 and s["trough"] == 89
    assert swing_ratio_from(s, 89) == 0.0
    assert swing_ratio_from(s, 111) == 1.0
    assert 0.0 < swing_ratio_from(s, 105) < 1.0
    # شکست سقف ⇒ نسبت بالای ۱، و این خودش خبر است نه خطا
    assert swing_ratio_from(s, 121) > 1.0


def test_swing_ratio_is_none_when_nothing_confirmed_yet():
    cs = synthetic_candles("4h", 10, seed=1)
    sw = swings(cs, k=3)
    assert sw[0]["peak"] is None and sw[0]["trough"] is None
    assert swing_ratio_from(sw[0], cs[0].close) is None


# ═══════════════════════════════════════════════════════════════════════════
# ۲) آزمون پنجکی — روی دادهٔ با اثر و بدون اثر
# ═══════════════════════════════════════════════════════════════════════════
def _rows(n=600, slope=0.0, noise=1.2, seed=3):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        x = i / n
        out.append({"swing": x, "don_pos": x, "r": -0.5 + slope * x + rng.gauss(0, noise),
                    "mode": "breakout" if i % 2 else "pullback"})
    return out


def test_quintiles_detect_a_real_effect():
    a = analysis_peakvalley(_rows(slope=2.0), "real")
    assert a["swing"]["monotone"] is True
    assert a["swing"]["passes"] is True
    assert a["swing"]["spread_r"] > GATE["quintile_spread_min_r"]


def test_quintiles_find_nothing_in_pure_noise():
    """اگر ویژگی بی‌اثر باشد، ابزار **نباید** لبه بسازد."""
    a = analysis_peakvalley(_rows(slope=0.0), "null")
    assert a["swing"]["passes"] is False


def test_quintiles_refuse_to_run_on_too_few_trades():
    a = analysis_peakvalley(_rows(n=100, slope=2.0), "small")
    assert a["swing"]["quintiles"] == []


# ═══════════════════════════════════════════════════════════════════════════
# ۳) قاعدهٔ «استراحت بعد از سود»
# ═══════════════════════════════════════════════════════════════════════════
def _box(seq, bar_ms=4 * 3600_000, struct=None, bars=1000):
    """seq: [(ts, win, r), ...]"""
    return {"trades": [{"ts": t, "win": w, "r": r, "bars": 2} for t, w, r in seq],
            "structure": struct or [], "bars": bars, "bar_ms": bar_ms}


def test_rule_is_inert_when_trades_are_far_apart():
    """با N=4 روی ۴ ساعته (۱۶ ساعت)، معاملات هفته‌به‌هفته هرگز بلاک نمی‌شوند."""
    bar = 4 * 3600_000
    seq = [(i * 30 * bar, True, 1.0) for i in range(10)]
    r = cluster_sim({"X": _box(seq)}, N=4, need_structure=False)
    assert r["dropped"] == []


def test_skip_next_removes_exactly_the_trade_after_a_win():
    bar = 4 * 3600_000
    seq = [(0, True, 1.0), (bar, False, -1.0), (2 * bar, True, 1.0), (3 * bar, False, -1.0)]
    r = cluster_sim({"X": _box(seq)}, N=1, need_structure=False, mode="next")
    assert len(r["dropped"]) == 2
    assert all(not t["win"] for t in r["dropped"])


def test_skip_next_is_cancelled_when_structure_flips():
    """شرط دوم (خواستهٔ کاربر): اگر ساختار بازار عوض شد، بلاک برداشته می‌شود."""
    bar = 4 * 3600_000
    seq = [(0, True, 1.0), (bar, False, -1.0)]
    # ساختار در ts=0 مثبت بود و در ts=bar عوض شده (منفی)
    struct = [[0, 1], [bar, -1]]
    blocked = cluster_sim({"X": _box(seq, struct=struct)}, N=1,
                          need_structure=False, mode="next")
    freed = cluster_sim({"X": _box(seq, struct=struct)}, N=1,
                        need_structure=True, mode="next")
    assert len(blocked["dropped"]) == 1
    assert len(freed["dropped"]) == 0


def test_structure_lookup_returns_the_latest_value_before_the_time():
    series = [[0, 1], [100, -1], [200, 1]]
    assert _structure_at(series, 50) == 1
    assert _structure_at(series, 150) == -1
    assert _structure_at(series, 500) == 1
    assert _structure_at([], 500) == 0


def test_cluster_test_reports_noise_when_there_is_nothing_to_find():
    """اگر بردها تصادفی باشند، بهبود باید داخل باند نویز بماند."""
    rng = random.Random(9)
    bar = 4 * 3600_000
    symbols = {}
    for s in range(4):
        seq = []
        for i in range(60):
            win = rng.random() < 0.3
            seq.append((i * bar, win, (2.5 if win else -1.0) + rng.gauss(0, 0.3)))
        symbols[f"S{s}"] = _box(seq)
    out = analysis_cluster(symbols, settings=((1, False, "next"),))
    v = out["variants"][0]
    assert v["observed_gain_r"] is not None
    assert v["passes"] is False


def test_cluster_test_detects_a_planted_alternation():
    """اگر واقعاً بعد از هر برد یک باخت بیاید، ابزار باید پیدایش کند."""
    bar = 4 * 3600_000
    symbols = {}
    for s in range(4):
        seq = []
        for i in range(60):
            win = (i % 2 == 0)
            seq.append((i * bar, win, 2.5 if win else -1.0))
        symbols[f"S{s}"] = _box(seq)
    out = analysis_cluster(symbols, settings=((1, False, "next"),))
    v = out["variants"][0]
    # حذف معاملهٔ بعد از برد، همهٔ باخت‌ها را حذف می‌کند ⇒ بهبود بزرگ
    assert v["observed_gain_r"] > GATE["cluster_gain_min_r"]
    assert v["passes"] is True


# ═══════════════════════════════════════════════════════════════════════════
# ۴) ورودی/خروجی
# ═══════════════════════════════════════════════════════════════════════════
def test_flatten_symbols_picks_one_variant_or_all():
    symbols = {"X": {"trades": {"trend": [{"r": 1.0}], "base": [{"r": 2.0}]},
                     "structure": [], "bars": 10, "bar_ms": 100}}
    one = flatten_symbols(symbols, "trend")
    both = flatten_symbols(symbols, None)
    assert len(one["X"]["trades"]) == 1
    assert len(both["X"]["trades"]) == 2


def test_lab_command_fails_cleanly_without_data():
    from mtflab.trades import export
    r = export("/tmp/definitely-not-a-data-dir", "4h", "1d", "1d", ["trend"],
               progress=False)
    assert "error" in r


# ═══════════════════════════════════════════════════════════════════════════
# ۵) ساختار پاداش — مهم‌ترین یافتهٔ ساختاری
# ═══════════════════════════════════════════════════════════════════════════
def test_payoff_detects_a_lottery_profile():
    """اگر ۵ معامله کل سود را بسازند، ابزار باید «قرعه‌کشی» را علامت بزند."""
    from mtflab.trades import analysis_payoff
    rows = [{"r": -1.0, "mfe": 0.5, "ts": i * 86_400_000} for i in range(100)]
    rows += [{"r": 40.0, "mfe": 60.0, "ts": i * 86_400_000} for i in range(5)]
    po = analysis_payoff(rows)
    assert po["lottery"] is True
    assert po["top_share"]["5"] > 0.6


def test_payoff_does_not_cry_lottery_for_a_steady_edge():
    """سود یکنواخت (۶۰٪ برد ۱R) نباید «قرعه‌کشی» علامت بخورد."""
    from mtflab.trades import analysis_payoff
    rows = [{"r": (1.0 if i % 5 < 3 else -1.0), "mfe": 3.0,
             "ts": i * 3_600_000} for i in range(200)]
    po = analysis_payoff(rows)
    assert po["lottery"] is False
    assert po["top_share"]["5"] < 0.6


def test_payoff_refuses_to_report_shares_when_total_is_negative():
    """با مجموع منفی، «۱۲۰٪ از سود» بی‌معنی است — نباید چاپ شود."""
    from mtflab.trades import analysis_payoff
    rows = [{"r": -1.0, "mfe": 0.5, "ts": i * 3_600_000} for i in range(50)]
    rows += [{"r": 2.0, "mfe": 5.0, "ts": i * 3_600_000} for i in range(3)]
    po = analysis_payoff(rows)
    assert po["top_share"]["5"] is None      # سهم بی‌معنی است، نه صفر
    assert po["lottery"] is False


def test_independent_events_groups_trades_on_the_same_wave():
    """۴ معامله در یک هفته = یک رویداد، نه چهار."""
    from mtflab.trades import analysis_payoff
    day = 86_400_000
    rows = [{"r": 10.0, "mfe": 30.0, "ts": i * day} for i in range(4)]        # یک هفته
    rows += [{"r": 10.0, "mfe": 30.0, "ts": (100 + i) * day} for i in range(4)]  # جدا
    rows += [{"r": -1.0, "mfe": 1.0, "ts": (200 + i) * day} for i in range(50)]
    po = analysis_payoff(rows)
    assert po["independent_events_45d"] == 2, po["independent_events_45d"]
