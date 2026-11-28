"""تست‌های اجرا در تایم‌فریم ریزتر (ایدهٔ کاربر) + قاعدهٔ «افت سود».

ایده: کندل ۴ساعته باز شود، ولی پوزیشن هر ۱۵ دقیقه بررسی شود (۱۶ بار در هر
کندل) و اگر سود از اوجش افت کرد، بسته شود.

چرا تست لازم است؟ این تغییر قلبِ موتور است. سه چیز باید قفل شود:

۱. **پیش‌فرض خاموش** — بدون `exec_tf`، نتیجه باید بیت‌به‌بیت همان قبلی باشد.
۲. **ترتیب واقعی داخل کندل** — بزرگ‌ترین ارزش این ایده: اگر داخل یک کندل ۴ساعته
   اول TP و بعد استاپ لمس شده باشد، مدل ۴ساعته **استاپ** را ثبت می‌کند
   (محافظه‌کارانه) ولی مدل ۱۵دقیقه‌ای می‌داند اول TP بوده.
۳. **قاعدهٔ افت سود** — بی‌آستانه شلیک نکند، و با آستانه درست شلیک کند.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                     # noqa: E402

from mtflab.config import MTFConfig                                 # noqa: E402
from mtflab.data import Candle, resample_up, synthetic_candles      # noqa: E402
from mtflab.engine import MTFEngine, Position, run_backtest         # noqa: E402
from mtflab.signals import TFContext                                # noqa: E402


def _cfg(**over):
    base = MTFConfig(data_mode="synthetic", tf_trigger="4h", tf_filter="1d",
                     tf_bias="1d", candles=1200, seed=11, verbose=False,
                     forensics=False, min_edge_multiplier=0.0)
    return replace(base, **over) if over else base


def _pos(direction=1, entry=100.0, stop=95.0, take=115.0, qty=1.0, **kw):
    p = Position(symbol="X", direction=direction, entry=entry, qty=qty,
                 notional=qty * entry, stop_initial=stop, take=take,
                 stop_current=stop, high_water=entry, low_water=entry,
                 open_ts=0, open_bar=0, confidence=1.0, score=1.0,
                 risk_amount=abs(entry - stop) * qty, equity_before=1000.0,
                 atr_at_entry=1.0, initial_qty=qty,
                 path=[{"ts": 0, "o": entry, "h": entry, "l": entry,
                        "c": entry, "v": 1.0}])
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _ctxs(n=400):
    trig = synthetic_candles("4h", n, seed=5)
    return {"trigger": TFContext(trig, _cfg(), "trigger"),
            "filter": TFContext(trig, _cfg(), "filter"),
            "bias": TFContext(trig, _cfg(), "bias")}


# ═══════════════════════════════════════════════════════════════════════════
# ۱) پیش‌فرض: خاموش و بی‌اثر
# ═══════════════════════════════════════════════════════════════════════════
def test_exec_tf_and_giveback_are_off_by_default():
    c = MTFConfig(data_mode="synthetic")
    assert c.exec_tf == ""
    assert c.giveback_arm_r == 0.0
    assert c.giveback_frac == 0.0


def test_existing_results_are_bit_identical_without_exec_tf():
    c15 = synthetic_candles("15m", 8000, seed=21)
    t4, _ = resample_up(c15, "15m", "4h")
    filt, _ = resample_up(t4, "4h", "1d")
    layers = {"trigger": t4, "filter": filt, "bias": filt}
    a = run_backtest(_cfg(), layers)
    b = run_backtest(_cfg(exec_tf=""), dict(layers, exec=c15))
    assert len(a["trades"]) == len(b["trades"])
    assert round(a["summary"]["total_pnl"], 6) == round(b["summary"]["total_pnl"], 6)


def test_missing_exec_layer_falls_back_instead_of_crashing():
    t4 = synthetic_candles("4h", 1200, seed=3)
    filt, _ = resample_up(t4, "4h", "1d")
    layers = {"trigger": t4, "filter": filt, "bias": filt}
    r = run_backtest(_cfg(exec_tf="15m"), layers)      # بدون کلید exec
    assert "summary" in r


# ═══════════════════════════════════════════════════════════════════════════
# ۲) ارزش اصلی: ترتیب واقعی داخل کندل ۴ساعته
# ═══════════════════════════════════════════════════════════════════════════
def _bar_that_hits_take_then_stop():
    """یک کندل ۴ساعته که داخلش **اول** سقف خورده و **بعد** کف.

    جمع ۴ساعته: high=116 (بالای TP=115) و low=94 (زیر استاپ=95).
    مدل ۴ساعته نمی‌تواند بداند کدام اول بود ⇒ محافظه‌کارانه استاپ.
    """
    return [Candle(0, 100.0, 116.0, 99.0, 101.0, 1.0),      # 00:00–04:00
            Candle(0, 101.0, 102.0, 94.0, 96.0, 1.0)]       # 04:00–08:00


def test_four_hour_model_is_forced_to_assume_the_stop():
    eng = MTFEngine(_cfg(), None, None)
    pos = _pos()
    eng.positions.append(pos)
    agg = Candle(0, 100.0, 116.0, 94.0, 96.0, 1.0)
    rec = eng.manage_position(pos, agg, 5, _ctxs(), 0)
    assert rec["reason"] == "stop_loss"
    assert rec["is_win"] is False


def test_fifteen_minute_detail_knows_the_take_came_first():
    eng = MTFEngine(_cfg(), None, None)
    pos = _pos()
    eng.positions.append(pos)
    c1, c2 = _bar_that_hits_take_then_stop()
    ctx = _ctxs()
    rec = eng.manage_position(pos, c1, 5, ctx, 0, final_in_bar=False)
    assert rec is not None and rec["reason"] == "take_profit"
    assert rec["is_win"] is True


def test_regime_and_time_stop_only_fire_at_the_end_of_the_trigger_bar():
    """خروج رژیمی و time-stop تصمیم کندل ۴ساعته‌اند، نه ۱۵دقیقه."""
    eng = MTFEngine(_cfg(regime_change_exit=True, max_holding_bars=1), None, None)
    pos = _pos(open_bar=0)
    eng.positions.append(pos)
    c = Candle(0, 100.0, 100.5, 99.5, 100.2, 1.0)
    mid = eng.manage_position(pos, c, 5, _ctxs(), -1, final_in_bar=False)
    assert mid is None, "time-stop نباید وسط کندلِ تریگر شلیک کند"
    end = eng.manage_position(pos, c, 5, _ctxs(), -1, final_in_bar=True)
    assert end is not None and end["reason"] in ("time_stop", "regime_flip_confirmed_1")


# ═══════════════════════════════════════════════════════════════════════════
# ۳) قاعدهٔ «افت سود»
# ═══════════════════════════════════════════════════════════════════════════
def test_giveback_is_silent_when_disabled():
    eng = MTFEngine(_cfg(), None, None)
    pos = _pos()
    eng.positions.append(pos)
    eng.manage_position(pos, Candle(0, 100.0, 112.0, 111.0, 111.5, 1.0), 5, _ctxs(), 0)
    rec = eng.manage_position(pos, Candle(0, 111.0, 111.0, 101.0, 101.0, 1.0), 6, _ctxs(), 0)
    assert rec is None or rec["reason"] != "giveback"


def test_giveback_needs_the_arm_threshold():
    """بدون رسیدن به +۱R، قاعده نباید فعال شود."""
    eng = MTFEngine(_cfg(giveback_arm_r=1.0, giveback_frac=0.5, trail_enabled=False,
                         breakeven_at_r=0.0), None, None)
    pos = _pos()                                   # استاپ ۵ دلار ⇒ ۱R
    eng.positions.append(pos)
    eng.manage_position(pos, Candle(0, 100.0, 103.0, 100.0, 102.0, 1.0), 5, _ctxs(), 0)
    assert pos.mfe_r < 1.0 and pos.giveback_armed is False
    rec = eng.manage_position(pos, Candle(0, 102.0, 102.0, 100.5, 100.6, 1.0), 6, _ctxs(), 0)
    assert rec is None, "قاعده نباید قبل از مسلح‌شدن شلیک کند"


def test_giveback_closes_when_profit_falls_to_half_of_its_peak():
    eng = MTFEngine(_cfg(giveback_arm_r=1.0, giveback_frac=0.5, trail_enabled=False,
                         breakeven_at_r=0.0), None, None)
    pos = _pos()
    eng.positions.append(pos)
    # اوج +۲R (قیمت ۱۱۰) ⇒ آستانهٔ نگه‌داشتن = ۱R ⇒ قیمت ۱۰۵
    eng.manage_position(pos, Candle(0, 100.0, 110.0, 100.0, 109.0, 1.0), 5, _ctxs(), 0)
    assert pos.mfe_r >= 1.9 and pos.giveback_armed is True
    rec = eng.manage_position(pos, Candle(0, 109.0, 109.0, 104.0, 104.5, 1.0), 6, _ctxs(), 0)
    assert rec is not None and rec["reason"] == "giveback"
    assert rec["is_win"] is True                          # بالای نقطهٔ ورود بسته شد
    assert abs(rec["exit"] - 105.0) < 0.2                 # نزدیک سطح ۱R


def test_giveback_never_sells_below_the_kept_profit_level():
    """با کسر کوچک، سطحِ نگه‌داشتن همان نزدیکی نقطهٔ ورود است و زیرش نمی‌فروشد."""
    eng = MTFEngine(_cfg(giveback_arm_r=1.0, giveback_frac=0.05, trail_enabled=False,
                         breakeven_at_r=0.0), None, None)
    pos = _pos()
    eng.positions.append(pos)
    eng.manage_position(pos, Candle(0, 100.0, 110.0, 100.0, 109.0, 1.0), 5, _ctxs(), 0)
    rec = eng.manage_position(pos, Candle(0, 109.0, 109.0, 96.0, 96.0, 1.0), 6, _ctxs(), 0)
    assert rec is not None and rec["reason"] == "giveback"
    # اوج ۲R ⇒ نگه‌داشتن ۰.۱R ⇒ سطح ۱۰۰.۵ ⇒ نباید زیر ورود بفروشد
    assert rec["exit"] >= pos.entry - 0.01


# ═══════════════════════════════════════════════════════════════════════════
# ۴) شمارش درست کندل‌ها
# ═══════════════════════════════════════════════════════════════════════════
def test_bars_held_is_counted_in_trigger_bars_not_sub_candles():
    c15 = synthetic_candles("15m", 24000, seed=7)
    t4, _ = resample_up(c15, "15m", "4h")
    filt, _ = resample_up(t4, "4h", "1d")
    layers = {"trigger": t4, "filter": filt, "bias": filt, "exec": c15}
    r = run_backtest(_cfg(exec_tf="15m"), layers)
    held = [t["bars_held"] for t in r["trades"]]
    assert held, "هیچ معامله‌ای در تست انجام نشد"
    # اگر کندل‌های ریز شمرده می‌شدند، اعداد ۱۶ برابر می‌شدند
    assert max(held) < 400, held


# ═══════════════════════════════════════════════════════════════════════════
# ۵) اجراکنندهٔ آزمون (exec-scan) و گزارش آن
# ═══════════════════════════════════════════════════════════════════════════
def _dataset(tmpdir, symbols=("AAAUSDT", "BBBUSDT"), n15=6000):
    import json as _json
    from mtflab.autoscan import candles_to_json
    json_dir = os.path.join(tmpdir, "json")
    os.makedirs(json_dir, exist_ok=True)
    for i, sym in enumerate(symbols):
        c15 = synthetic_candles("15m", n15, seed=90 + i)
        t4, _ = resample_up(c15, "15m", "4h")
        for tf, cs in (("15m", c15), ("4h", t4)):
            with open(os.path.join(json_dir, f"{sym.lower()}_{tf}.json"),
                      "w", encoding="utf-8") as f:
                _json.dump(candles_to_json(cs, {"symbol": sym, "tf": tf,
                                                "days": 200}), f)
    return tmpdir


def test_exec_scan_runs_the_three_arms():
    import tempfile
    from mtflab.execscan import ARMS, run
    with tempfile.TemporaryDirectory() as td:
        _dataset(td)
        res = run(td, "4h", "15m", "1d", "1d", "base", progress=False)
    assert not res.get("error"), res
    assert [a["key"] for a in res["settings"]["arms"]] == [a[0] for a in ARMS]
    for key in ("A_base", "B_fine", "C_fine_gb"):
        assert res["summary"][key]["ok"], (key, res["summary"][key])
        assert "median_pf" in res["summary"][key]


def test_exec_scan_reports_symbols_that_lack_the_finer_timeframe():
    import tempfile
    from mtflab.execscan import run
    with tempfile.TemporaryDirectory() as td:
        _dataset(td, symbols=("AAAUSDT",))
        # یک نماد فقط ۴ ساعته اضافه می‌کنیم
        import json as _json
        from mtflab.autoscan import candles_to_json
        t4 = synthetic_candles("4h", 800, seed=5)
        with open(os.path.join(td, "json", "cccusdt_4h.json"), "w",
                  encoding="utf-8") as f:
            _json.dump(candles_to_json(t4, {"symbol": "CCCUSDT", "tf": "4h",
                                            "days": 200}), f)
        res = run(td, "4h", "15m", "1d", "1d", "base", progress=False)
    assert res["settings"]["only_one_tf"] == ["CCCUSDT"], res["settings"]
    assert res["settings"]["symbols"] == ["AAAUSDT"]


def test_exec_scan_render_is_bilingual_and_shows_the_gate():
    import tempfile
    from mtflab.execscan import render, run
    with tempfile.TemporaryDirectory() as td:
        _dataset(td)
        res = run(td, "4h", "15m", "1d", "1d", "base", progress=False)
    fa, en = render(res, "fa"), render(res, "en")
    for txt in (fa, en):
        assert "A_base" in txt and "C_fine_gb" in txt
    assert "معیار قبولی" in fa
    assert "Pre-registered gate" in en


def test_exec_scan_fails_cleanly_without_data():
    from mtflab.execscan import run
    res = run("/tmp/definitely-not-a-data-dir", "4h", "15m", "1d", "1d", "base",
              progress=False)
    assert res.get("error") == "no common symbols"
