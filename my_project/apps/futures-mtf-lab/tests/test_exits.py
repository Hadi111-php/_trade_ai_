"""تست‌های سیاست خروج: خروج جزئی، بریک‌ایون، تریلینگ.

این تست‌ها تضمین می‌کنند افزودن «سود شناور» منطق ریسک را نشکند:
- استاپ هرگز عقب‌تر نمی‌رود (فقط سفت‌تر می‌شود)
- خروج جزئی، حجم و ریسک باقی‌مانده را متناسب کم می‌کند
- مجموع PnL لگ‌های یک پوزیشن = PnL واقعی آن پوزیشن
"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.config import MTFConfig                                   # noqa: E402
from mtflab.data import resample_up, synthetic_candles               # noqa: E402
from mtflab.engine import MTFEngine, Position, run_backtest          # noqa: E402


def _layers(n=1800, seed=31):
    trig = synthetic_candles("1h", n, seed=seed)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    return {"trigger": trig, "filter": filt, "bias": bias}


def _cfg(**over):
    base = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                     candles=1800, seed=31, verbose=False, forensics=False,
                     min_edge_multiplier=0.0, filter_confirm_bars=1,
                     bias_ema_period=20, bias_slope_min_pct=0.0,
                     filter_slope_min_pct=0.0)
    return replace(base, **over) if over else base


def _pos(direction=1, entry=100.0, stop=98.5, take=104.5, qty=1.0, **kw):
    p = Position(symbol="X", direction=direction, entry=entry, qty=qty, notional=qty * entry,
                 stop_initial=stop, take=take, stop_current=stop, high_water=entry,
                 low_water=entry, open_ts=0, open_bar=0, confidence=1.0, score=1.0,
                 risk_amount=abs(entry - stop) * qty, equity_before=1000.0,
                 atr_at_entry=1.0, initial_qty=qty,
                 path=[{"ts": 0, "o": entry, "h": entry, "l": entry, "c": entry, "v": 1.0}])
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_stop_never_loosens_with_breakeven_and_trailing():
    """استاپ فقط می‌تواند سفت‌تر شود؛ هیچ‌وقت عقب‌تر نمی‌رود."""
    cfg = _cfg(trail_enabled=True, trail_start_r=0.5, trail_atr_mult=2.0, breakeven_at_r=1.0)
    eng = MTFEngine(cfg)
    pos = _pos()
    from mtflab.data import Candle
    from mtflab.signals import TFContext
    lay = _layers()
    ctxs = {"trigger": TFContext(lay["trigger"], cfg, "trigger")}
    prev = pos.stop_current
    # کندل‌هایی که قیمت بالا می‌رود (بدون برخورد به stop/TP)
    for k, (hi, lo, cl) in enumerate([(101.0, 99.9, 100.9), (102.0, 100.8, 101.9),
                                      (103.0, 101.7, 102.8), (103.5, 102.4, 103.0)]):
        c = Candle(1000 * k, 100.5, hi, lo, cl, 1.0)
        eng.manage_position(pos, c, 5 + k, ctxs, 0)
        assert pos.stop_current >= prev - 1e-12, "استاپ عقب رفت!"
        prev = pos.stop_current


def test_breakeven_moves_stop_to_entry_after_target_r():
    cfg = _cfg(trail_enabled=False, breakeven_at_r=1.0)
    eng = MTFEngine(cfg)
    pos = _pos()                       # entry=100, stop=98.5 → 1R = 101.5
    from mtflab.data import Candle
    from mtflab.signals import TFContext
    lay = _layers()
    ctxs = {"trigger": TFContext(lay["trigger"], cfg, "trigger")}
    assert pos.breakeven_done is False
    eng.manage_position(pos, Candle(0, 100.2, 101.9, 100.0, 101.6, 1.0), 5, ctxs, 0)
    assert pos.breakeven_done is True
    assert abs(pos.stop_current - pos.entry) < 1e-9


def test_partial_take_reduces_size_and_books_profit():
    cfg = _cfg(partial_take_r=1.0, partial_take_frac=0.5, trail_enabled=False)
    eng = MTFEngine(cfg)
    pos = _pos(qty=2.0)
    pos.notional = 200.0
    pos.open_fee = 0.0
    from mtflab.data import Candle
    from mtflab.signals import TFContext
    lay = _layers()
    ctxs = {"trigger": TFContext(lay["trigger"], cfg, "trigger")}
    eng.manage_position(pos, Candle(0, 100.2, 101.9, 100.0, 101.6, 1.0), 5, ctxs, 0)
    assert pos.partial_taken is True
    assert pos.qty < 2.0            # نصف بسته شد
    assert pos.realized_partial_pnl > 0
    assert eng.trades and eng.trades[-1]["partial"] is True
    assert eng.trades[-1]["reason"].startswith("partial_take")


def test_sum_of_legs_equals_position_pnl():
    """PnL کل یک پوزیشن = جمع PnL لگ‌های آن (هیچ پولی گم/دوباره‌شمرده نشود)."""
    cfg = _cfg(partial_take_r=0.8, partial_take_frac=0.5, trail_enabled=False,
               filter_adx_min=0.0, filter_slope_min_pct=0.0, alignment_version="C",
               bias_enabled=False)
    res = run_backtest(cfg, _layers(2400, seed=77))
    trades = res["trades"]
    by_pos = {}
    for t in trades:
        by_pos.setdefault((t["open_bar"], t["entry"]), []).append(t)
    for key, legs in by_pos.items():
        total = round(sum(l["pnl"] for l in legs), 4)
        # تلورانس ۱e-3: هر لگ تا ۴ رقم اعشار گِرد شده، پس جمعشان هم تا همین حد خطا دارد
        assert abs(total - legs[-1]["position_pnl"]) <= 2e-3, \
            (key, total, legs[-1]["position_pnl"])
    if any(t.get("partial") for t in trades):
        assert res["summary"]["partial_legs"] > 0


def test_partial_exits_count_as_one_position():
    cfg = _cfg(partial_take_r=0.8, partial_take_frac=0.5, trail_enabled=False,
               filter_adx_min=0.0, filter_slope_min_pct=0.0, alignment_version="C",
               bias_enabled=False)
    s = run_backtest(cfg, _layers(2400, seed=77))["summary"]
    assert s["positions_opened"] <= s["trades"]
    assert s["avg_legs_per_position"] >= 1.0
