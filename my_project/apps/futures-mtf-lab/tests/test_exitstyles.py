"""تست‌های مقایسهٔ «حد ضرر/سود ثابت» با «شناور (ATR+تریل)».

چرا این تست‌ها: اگر شبیه‌ساز خروج اشتباه حساب کند، جواب سؤال کاربر («کدام بهتر
است؟») بی‌معنا می‌شود. سه چیز حیاتی است:
  ۱) ورودی‌ها برای همهٔ سیاست‌ها یکی باشد.
  ۲) ریاضی R با کارمزد درست باشد (حد ضرر ⇒ حدود −۱R).
  ۳) تریل واقعاً قفلِ سود کند، و «هم‌عرض ATR» عرض یکسانی بسازد.
"""
import json
import os
import sys
import tempfile
from dataclasses import dataclass, replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import exitstyles as ex                              # noqa: E402
from mtflab.config import load_config                           # noqa: E402
from mtflab.data import Candle, synthetic_candles               # noqa: E402


def _cfg(**kw):
    c = load_config(["--data", "synthetic", "--quiet"])
    base = dict(verbose=False, forensics=False, run_id="", symbol="",
                tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                fee_bps=0.0, slippage_pct=0.0, max_holding_bars=0)
    base.update(kw)
    return replace(c, **base)


@dataclass
class _Bar:
    low_tf_candle: Candle


def _bars(rows, ts0=1_000_000, step=3_600_000):
    """rows: [(open, high, low, close), ...] → لیست bars شبیه AlignedBar"""
    out = []
    for k, (o, h, l, c) in enumerate(rows):
        out.append(_Bar(Candle(open_time_ms=ts0 + k * step, open=o, high=h,
                               low=l, close=c, volume=1.0)))
    return out


def _entry(i, price, side=1, atr=1.0):
    return {"i": i, "ts": 1_000_000 + i * 3_600_000, "side": side,
            "entry": price, "atr": atr, "symbol": "XUSDT"}


# ══════════════════════════════════════════════════════════════════════════
#  ۱) فاصله‌ها: ثابت درصدی در برابر ATR
# ══════════════════════════════════════════════════════════════════════════
def test_levels_fixed_is_percent_and_atr_is_volatility_scaled():
    sd, td, tr = ex._levels(ex.policy_by_id("fixed_2_4"), 100.0, atr=1.0)
    assert abs(sd - 2.0) < 1e-9 and abs(td - 4.0) < 1e-9
    assert tr["trail_dist"] == 0.0
    sd2, td2, tr2 = ex._levels(ex.policy_by_id("atr_1.5_3_trail"), 100.0, atr=2.0)
    assert abs(sd2 - 3.0) < 1e-9 and abs(td2 - 6.0) < 1e-9
    assert tr2["trail_dist"] == 4.0


def test_matched_policy_same_width_as_atr_stop():
    pol = ex.matched_policy(1.0)                  # میانگین ATR = ۱٪
    assert pol["sl_pct"] == 1.5 and pol["tp_pct"] == 3.0
    sd, td, _ = ex._levels(pol, 100.0, atr=0.0)
    sd_atr, td_atr, _ = ex._levels(ex.policy_by_id("atr_1.5_3_trail"), 100.0, atr=1.0)
    assert (sd, td) == (sd_atr, td_atr)


# ══════════════════════════════════════════════════════════════════════════
#  ۲) خروج: حد ضرر / حد سود / گپ / تریل
# ══════════════════════════════════════════════════════════════════════════
def test_stop_gives_minus_one_r():
    bars = _bars([(100, 100, 100, 100), (100, 100.2, 97.5, 98.0)])
    tr = ex.simulate(bars, [_entry(0, 100.0)], ex.policy_by_id("fixed_2_4"), _cfg())
    assert tr[0]["reason"] == "stop" and abs(tr[0]["r_multiple"] + 1.0) < 0.02


def test_take_gives_plus_two_r():
    bars = _bars([(100, 100, 100, 100), (100, 104.5, 99.5, 104.0)])
    tr = ex.simulate(bars, [_entry(0, 100.0)], ex.policy_by_id("fixed_2_4"), _cfg())
    assert tr[0]["reason"] == "take" and abs(tr[0]["r_multiple"] - 2.0) < 0.02


def test_gap_open_through_stop_fills_at_open():
    """اگر کندل زیر حد ضرر باز شود، پر شدن همان‌جا است (بدتر از حد ضرر)."""
    bars = _bars([(100, 100, 100, 100), (96.0, 96.5, 95.0, 96.0)])
    tr = ex.simulate(bars, [_entry(0, 100.0)], ex.policy_by_id("fixed_2_4"), _cfg())
    assert tr[0]["reason"] == "stop_gap" and tr[0]["exit"] == 96.0
    assert tr[0]["r_multiple"] < -1.9


def test_trailing_locks_profit_above_entry():
    # ورود ۱۰۰، ATR=۱ ⇒ حد ضرر ۹۸.۵، تریل ۲×ATR از ۱R به بالا
    # حد ضرر ۹۸.۵ · حد سود ۱۰۳ (۳×ATR) · تریل ۲×ATR از ۱R
    bars = _bars([(100, 100, 100, 100),
                  (100, 101.0, 99.9, 100.9),      # هنوز زیر ۱R ⇒ تریل خاموش
                  (100.9, 102.0, 100.5, 101.9),   # >۱R ⇒ استاپ به ۱۰۲−۲=۱۰۰
                  (101.9, 102.6, 101.5, 102.2),   # سقف ۱۰۲.۶ ⇒ استاپ ۱۰۰.۶
                  (102.0, 102.1, 100.2, 100.6)])  # زیر ۱۰۰.۶ ⇒ خروج تریل
    tr = ex.simulate(bars, [_entry(0, 100.0)], ex.policy_by_id("atr_1.5_3_trail"), _cfg())
    assert tr[0]["reason"] == "stop"
    assert tr[0]["exit"] > 100.0, tr[0]
    assert tr[0]["r_multiple"] > 0, tr[0]


def test_time_stop_when_configured():
    bars = _bars([(100, 100, 100, 100)] + [(100, 100.2, 99.9, 100.1)] * 5)
    tr = ex.simulate(bars, [_entry(0, 100.0)], ex.policy_by_id("fixed_2_4"),
                     _cfg(max_holding_bars=3))
    assert tr[0]["reason"] == "time_stop" and tr[0]["bars_held"] == 3


# ══════════════════════════════════════════════════════════════════════════
#  ۳) انصاف مقایسه: همان ورودی‌ها
# ══════════════════════════════════════════════════════════════════════════
def test_independent_mode_uses_every_entry_identically():
    rows = [(100, 100, 100, 100)]
    for k in range(10):
        rows.append((100, 101.0, 99.0, 100.0))
    bars = _bars(rows)
    ents = [_entry(i, 100.0) for i in (0, 1, 3, 5, 7)]
    a = ex.simulate(bars, ents, ex.policy_by_id("fixed_1_2"), _cfg(), one_at_a_time=False)
    b = ex.simulate(bars, ents, ex.policy_by_id("fixed_3_6"), _cfg(), one_at_a_time=False)
    assert len(a) == len(b) == len(ents)
    real = ex.simulate(bars, ents, ex.policy_by_id("fixed_3_6"), _cfg(), one_at_a_time=True)
    assert len(real) <= len(ents)


def test_open_at_end_is_flagged_not_counted_as_trade():
    bars = _bars([(100, 100, 100, 100), (100, 100.1, 99.9, 100.0)])
    tr = ex.simulate(bars, [_entry(0, 100.0)], ex.policy_by_id("fixed_2_4"), _cfg())
    assert tr[0]["status"] == "open_at_end"
    m = ex.metrics(tr)
    assert m["n"] == 0 and m["open_at_end"] == 1 and m["expectancy_r"] is None


# ══════════════════════════════════════════════════════════════════════════
#  ۴) سنجه‌ها
# ══════════════════════════════════════════════════════════════════════════
def _t(r, bars=10, status="closed"):
    return {"status": status, "r_multiple": r, "bars_held": bars,
            "net_pct": r * 0.7, "stop_dist_pct": 0.7, "entry_ts": 1}


def test_metrics_math_and_equity():
    m = ex.metrics([_t(2.0), _t(-1.0), _t(-1.0), _t(3.0)], risk_pct=1.0)
    assert m["n"] == 4 and m["wins"] == 2 and m["win_rate"] == 50.0
    assert m["expectancy_r"] == 0.75
    assert m["profit_factor"] == 2.5
    eq = 1.02 * 0.99 * 0.99 * 1.03
    assert abs(m["equity_multiple"] - round(eq, 3)) < 1e-3
    assert m["max_dd_pct"] > 0


def test_metrics_without_compounding_has_no_equity():
    m = ex.metrics([_t(1.0), _t(-1.0)], compound=False)
    assert m["equity_multiple"] is None and m["expectancy_r"] == 0.0


# ══════════════════════════════════════════════════════════════════════════
#  ۵) اجرای کامل روی دادهٔ ساختگی + CLI
# ══════════════════════════════════════════════════════════════════════════
def _write_cache(td, bars=6000, tf="1h"):
    from mtflab.autoscan import candles_to_json
    d = os.path.join(td, "data", "json")
    os.makedirs(d, exist_ok=True)
    for i, sym in enumerate(("BTCUSDT", "ETHUSDT")):
        cs = synthetic_candles(tf, bars, seed=303 + i)
        with open(os.path.join(d, f"{sym.lower()}_{tf}.json"), "w", encoding="utf-8") as f:
            json.dump(candles_to_json(cs, {"symbol": sym, "tf": tf}), f)
    return os.path.join(td, "data")


def test_compare_runs_and_marks_a_base_policy():
    with tempfile.TemporaryDirectory() as td:
        uni = ex._load_cache(_write_cache(td), "1h")
        cfg = _cfg(tf_filter="4h", tf_bias="4h")   # ۲۰۰ کندل ۴ساعته از ۶۰۰۰ کندل ۱ساعته
        res = ex.compare(uni, cfg)
        assert res["entries"] > 0, "روی این داده باید ورودی پیدا شود"
        assert len(res["rows"]) == len(ex.POLICIES) + 1     # + سیاست هم‌عرض
        codes = {r["policy"]["id"]: (r.get("verdict") or {}).get("code") for r in res["rows"]}
        assert codes["atr_1.5_3_trail"] == "base"
        assert all(c in ("base", "better", "worse", "mixed", "need_more")
                   for c in codes.values()), codes
        # در حالت مستقل، **همهٔ** ورودی‌ها شبیه‌سازی می‌شوند؛ آن‌که آخر داده باز
        # مانده «open_at_end» شمرده می‌شود و در n نمی‌آید، پس جمعشان باید یکی باشد.
        totals = {r["ind_all"]["n"] + r["ind_all"]["open_at_end"] for r in res["rows"]}
        assert totals == {res["entries"]}, totals


def test_cli_writes_report_and_refuses_empty_dir():
    with tempfile.TemporaryDirectory() as td:
        assert ex.exitstyles_command(["--data-dir", td, "--tf", "1h"]) == 2
        data = _write_cache(td)
        rc = ex.exitstyles_command(["--data-dir", data, "--tf", "1h",
                                    "--out-dir", os.path.join(td, "out")])
        assert rc == 0
        files = os.listdir(os.path.join(td, "out"))
        assert any(f.endswith(".md") for f in files)
        assert any(f.endswith(".json") for f in files)


def test_cli_is_wired_in_main_and_run_auto():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_src = open(os.path.join(root, "mtflab", "__main__.py"), encoding="utf-8").read()
    assert "exitstyles" in main_src and "exitstyles_command" in main_src
    sh_src = open(os.path.join(root, "run-auto.sh"), encoding="utf-8").read()
    assert "--exit-styles" in sh_src
