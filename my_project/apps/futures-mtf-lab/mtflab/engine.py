"""موتور بک‌تست چندتایم‌فریمی (PAPER فقط — هیچ سفارش واقعی ارسال نمی‌شود).

این موتور از `alignment.py` و `fees.py` موجود استفاده می‌کند و آن‌ها را دور
نمی‌زند (شرط ۱ و ۳ در docs/AGENT_TASK.md).

ترتیب هر کندل تریگر (علی، بدون lookahead):
  1. مدیریت خروجِ پوزیشن باز با high/low همان کندل
     (اگر stop و take هر دو در یک کندل لمس شوند → **stop اول** فرض می‌شود:
     محافظه‌کارانه‌ترین حالت؛ دام رایج «take خوش‌بینانه» در pitfalls آمده)
  2. تصمیم ورود با آخرین کندل‌های بستهٔ فیلتر/بایاس (از AlignedBar)
  3. به‌روزرسانی trailing/کول‌داون در پایان کندل (نه داخل آن)

LIVE عمداً پیاده‌سازی نشده است؛ فقط PAPER.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import __version__
from .alignment import AlignedBar, align_multi_timeframe, alignment_coverage, leakage_audit
from .config import MTFConfig
from .data import Candle, load_layers, tf_to_minutes
from .fees import FeeConfig, fee_on_notional, slip_price
from .logger import JsonlWriter
from .signals import TFContext, bias_state, decide, filter_state, trigger_state


# ----------------------------------------------------------------------------
# پوزیشن
# ----------------------------------------------------------------------------
@dataclass
class Position:
    symbol: str
    direction: int
    entry: float
    qty: float
    notional: float
    stop_initial: float
    take: float
    stop_current: float
    high_water: float
    low_water: float
    open_ts: int
    open_bar: int
    confidence: float
    score: float
    risk_amount: float
    equity_before: float
    regime_bias: str = ""
    regime_filter: str = ""
    trigger_mode: str = ""
    reason: str = ""
    atr_at_entry: float = 0.0
    open_fee: float = 0.0
    trail_active: bool = False
    partial_taken: bool = False
    breakeven_done: bool = False
    initial_qty: float = 0.0
    realized_partial_pnl: float = 0.0
    legs: int = 0
    layers: dict = field(default_factory=dict)
    snap_trigger: dict = field(default_factory=dict)
    snap_filter: dict = field(default_factory=dict)
    snap_bias: dict = field(default_factory=dict)
    path: list = field(default_factory=list)

    @property
    def stop_distance(self) -> float:
        return abs(self.entry - self.stop_initial)


# ----------------------------------------------------------------------------
# موتور
# ----------------------------------------------------------------------------
class MTFEngine:
    def __init__(self, cfg: MTFConfig, signals_w: Optional[JsonlWriter] = None,
                 trades_w: Optional[JsonlWriter] = None):
        self.cfg = cfg
        self.fee = FeeConfig.from_bps(cfg.fee_bps, cfg.slippage_pct)
        self.sw = signals_w
        self.tw = trades_w
        self.equity = float(cfg.initial_equity)
        self.peak_equity = float(cfg.initial_equity)
        self.max_drawdown_pct = 0.0
        self.positions: List[Position] = []
        self.trades: List[dict] = []
        self.positions_opened: int = 0
        self.equity_curve: List[dict] = []
        self.consecutive_losses = 0
        self.cooldown_until_bar = -1
        self.cb_until_bar = -1
        self.day_key: Optional[int] = None
        self.day_start_equity = float(cfg.initial_equity)
        self.daily_limit_hit = False
        self.filter_flip_streak = 0
        self.last_filter_dir = 0
        # آمار لایه‌ها (چند سیگنال توسط کدام لایه وتو شد)
        self.veto_stats: Dict[str, int] = {
            "bias": 0, "filter": 0, "trigger": 0, "cost": 0, "confidence": 0,
            "cooldown": 0, "circuit_breaker": 0, "daily_loss": 0, "slots": 0,
            "hour_filter": 0, "climax": 0,
        }
        self.trigger_stats: Dict[str, int] = {"pullback": 0, "breakout": 0, "none": 0}
        self.decision_log: List[dict] = []

    # -- helpers -------------------------------------------------------------
    def _open_slots_free(self) -> bool:
        return len(self.positions) < self.cfg.max_concurrent

    def _daily_key(self, ts: int) -> int:
        return ts // 86_400_000

    def _check_daily_limit(self, ts: int) -> None:
        k = self._daily_key(ts)
        if self.day_key != k:
            self.day_key = k
            self.day_start_equity = self.equity
            self.daily_limit_hit = False
        elif not self.daily_limit_hit and self.day_start_equity > 0:
            loss_pct = (self.day_start_equity - self.equity) / self.day_start_equity * 100.0
            if loss_pct >= self.cfg.daily_loss_limit_pct:
                self.daily_limit_hit = True

    def _bump_dd(self) -> None:
        self.peak_equity = max(self.peak_equity, self.equity)
        if self.peak_equity > 0:
            dd = (self.equity - self.peak_equity) / self.peak_equity * 100.0
            self.max_drawdown_pct = min(self.max_drawdown_pct, dd)

    # -- تصمیم ورود ----------------------------------------------------------
    def build_decision(self, bar: AlignedBar, ctxs: Dict[str, TFContext]) -> dict:
        trig_i = bar.low_idx
        ctx_t = ctxs["trigger"]
        trig = trigger_state(ctx_t, trig_i, self.cfg)
        self.trigger_stats[trig.mode] = self.trigger_stats.get(trig.mode, 0) + 1

        filt = filter_state(ctxs["filter"], bar.higher_idx, self.cfg)
        bia = bias_state(ctxs["bias"], bar.bias_idx, self.cfg) if self.cfg.bias_enabled else \
            type(filt)(0, 0.0, "disabled", "لایهٔ بایاس غیرفعال (نسخه C)")
        d = decide(bia, filt, trig, self.cfg, self.fee)
        return {
            "decision": d, "trig": trig, "filt": filt, "bias": bia, "bar": bar,
            "snap_trigger": ctx_t.snapshot(trig_i),
            "snap_filter": ctxs["filter"].snapshot(bar.higher_idx),
            "snap_bias": ctxs["bias"].snapshot(bar.bias_idx) if self.cfg.bias_enabled else {},
        }

    def _veto_reason(self, info: dict) -> Optional[str]:
        """چرا سیگنال رد شد؟ (برای آمار وتو و ستون «چرا معامله نکرد» داشبورد)"""
        d = info["decision"]
        if d.action == "ENTER":
            return None
        if info.get("trig") is not None and "کندلِ اوج" in str(info["trig"].reason):
            self.veto_stats["climax"] += 1
            return d.reason
        layer = getattr(d, "veto_layer", "") or "trigger"
        if layer in self.veto_stats:
            self.veto_stats[layer] += 1
        else:
            self.veto_stats["trigger"] += 1
        return d.reason

    # -- بازکردن پوزیشن ------------------------------------------------------
    def open_position(self, info: dict, ctxs: Dict[str, TFContext], i: int,
                      entry_price: float, ts: int) -> Optional[Position]:
        d = info["decision"]
        cfg = self.cfg
        atr_v = ctxs["trigger"].atr[i] or 0.0
        price = info["bar"].low_tf_candle.close
        if atr_v <= 0:
            atr_v = price * 0.004                      # fallback محافظه‌کارانه

        stop_dist = max(atr_v * cfg.stop_atr_mult, price * 0.0008)
        entry = slip_price(entry_price, cfg.slippage_pct, d.direction)
        if d.direction == 1:
            stop = entry - stop_dist
            take = entry + stop_dist * cfg.rr
        else:
            stop = entry + stop_dist
            take = entry - stop_dist * cfg.rr

        risk_amount = cfg.fixed_risk if cfg.fixed_risk > 0 else \
            self.equity * (cfg.risk_per_trade_pct / 100.0)
        qty = risk_amount / stop_dist if stop_dist > 0 else 0.0
        notional = qty * entry
        lev = notional / self.equity if self.equity > 0 else 0.0
        if lev > cfg.max_leverage:                     # سقف اهرم
            qty = self.equity * cfg.max_leverage / entry
            notional = qty * entry
            lev = cfg.max_leverage
        if qty <= 0:
            return None

        open_fee = fee_on_notional(notional, cfg.fee_bps)
        self.equity -= open_fee
        pos = Position(
            symbol=cfg.symbol, direction=d.direction, entry=entry, qty=qty,
            notional=notional, stop_initial=stop, take=take, stop_current=stop,
            high_water=entry, low_water=entry, open_ts=ts, open_bar=i,
            confidence=d.confidence, score=d.score, risk_amount=risk_amount,
            equity_before=self.equity + open_fee,
            regime_bias=info["bias"].regime, regime_filter=info["filt"].regime,
            trigger_mode=info["trig"].mode, reason=d.reason, atr_at_entry=atr_v,
            open_fee=open_fee, layers=d.layers,
            snap_trigger=info["snap_trigger"], snap_filter=info["snap_filter"],
            snap_bias=info["snap_bias"], initial_qty=qty,
            path=[{"ts": ts, "o": info["bar"].low_tf_candle.open,
                   "h": info["bar"].low_tf_candle.high,
                   "l": info["bar"].low_tf_candle.low,
                   "c": info["bar"].low_tf_candle.close,
                   "v": info["bar"].low_tf_candle.volume}],
        )
        self.positions.append(pos)
        self.positions_opened += 1
        self._log_signal(info, pos, i, ts, lev)
        return pos

    # -- مدیریت خروج ---------------------------------------------------------
    def _append_path(self, pos: Position, candle: Candle) -> None:
        pos.path.append({"ts": candle.open_time_ms, "o": candle.open, "h": candle.high,
                         "l": candle.low, "c": candle.close, "v": candle.volume})
        pos.high_water = max(pos.high_water, candle.close)
        pos.low_water = min(pos.low_water, candle.close)

    def _move_to_breakeven(self, pos: Position) -> None:
        """استاپ را به نقطهٔ ورود منتقل کن (هرگز عقب‌تر نبر)."""
        if pos.direction == 1:
            pos.stop_current = max(pos.stop_current, pos.entry)
        else:
            pos.stop_current = min(pos.stop_current, pos.entry)
        pos.breakeven_done = True

    def manage_position(self, pos: Position, candle: Candle, i: int,
                        ctxs: Dict[str, TFContext], filt_dir_now: int) -> Optional[dict]:
        """مدیریت یک پوزیشن در یک کندل — ترتیب بررسی عمداً محافظه‌کارانه است.

        ۱) stop (اول از همه؛ اگر با TP هم‌زمان لمس شود، ضرر فرض می‌شود)
        ۲) خروج جزئی در سطح partial_take_r
        ۳) TP برای باقی‌ماندهٔ پوزیشن
        ۴) انتقال استاپ به نقطهٔ ورود در breakeven_at_r
        ۵) خروج رژیمی / time-stop در close
        ۶) به‌روزرسانی تریلینگ در **پایان** کندل (علی)
        """
        cfg = self.cfg
        sd = pos.stop_distance
        stop_at_open = pos.stop_current        # فقط از کندل‌های قبل معلوم است

        # ۱) stop
        hit_stop = (candle.low <= stop_at_open) if pos.direction == 1 \
            else (candle.high >= stop_at_open)
        if hit_stop:
            px = min(candle.open, stop_at_open) if pos.direction == 1 \
                else max(candle.open, stop_at_open)
            if abs(stop_at_open - pos.entry) < 1e-9:
                reason = "breakeven"
            elif abs(stop_at_open - pos.stop_initial) < 1e-9:
                reason = "stop_loss"
            else:
                reason = "stop/trail"
            self._append_path(pos, candle)
            return self._close(pos, px, candle.open_time_ms, reason, i)

        # ۲) خروج جزئی
        if cfg.partial_take_r > 0 and not pos.partial_taken and pos.qty > 0:
            lvl = pos.entry + pos.direction * sd * cfg.partial_take_r
            hit = (candle.high >= lvl) if pos.direction == 1 else (candle.low <= lvl)
            if hit:
                self._take_partial(pos, lvl, candle.open_time_ms, i, cfg.partial_take_frac)
                if cfg.breakeven_at_r <= 0 or cfg.breakeven_at_r <= cfg.partial_take_r:
                    self._move_to_breakeven(pos)

        # ۳) TP برای باقی‌مانده
        if pos.qty > 1e-12:
            hit_tp = (candle.high >= pos.take) if pos.direction == 1 \
                else (candle.low <= pos.take)
            if hit_tp:
                px = max(candle.open, pos.take) if pos.direction == 1 \
                    else min(candle.open, pos.take)
                self._append_path(pos, candle)
                return self._close(pos, px, candle.open_time_ms, "take_profit", i)

        # ۴) بریک‌ایون
        if cfg.breakeven_at_r > 0 and not pos.breakeven_done:
            lvl = pos.entry + pos.direction * sd * cfg.breakeven_at_r
            hit = (candle.high >= lvl) if pos.direction == 1 else (candle.low <= lvl)
            if hit:
                self._move_to_breakeven(pos)

        # ۵) خروج رژیمی / time-stop
        exit_price: Optional[float] = None
        reason = ""
        if cfg.regime_change_exit and filt_dir_now != 0 \
                and filt_dir_now == -pos.direction \
                and self.filter_flip_streak >= cfg.filter_confirm_bars:
            exit_price = candle.close
            reason = f"regime_flip_confirmed_{self.filter_flip_streak}"
        elif cfg.max_holding_bars > 0 and (i - pos.open_bar) >= cfg.max_holding_bars:
            exit_price = candle.close
            reason = "time_stop"

        self._append_path(pos, candle)

        if exit_price is not None:
            return self._close(pos, exit_price, candle.open_time_ms, reason, i)

        # ۶) تریلینگ در پایان کندل (علی)
        if cfg.trail_enabled and sd > 0:
            r_now = pos.direction * (candle.close - pos.entry) / sd
            if r_now >= cfg.trail_start_r:
                pos.trail_active = True
            if pos.trail_active:
                atr_now = ctxs["trigger"].atr[i] or pos.atr_at_entry
                trail_dist = atr_now * cfg.trail_atr_mult
                if pos.direction == 1:
                    pos.stop_current = max(pos.stop_current, pos.high_water - trail_dist)
                else:
                    pos.stop_current = min(pos.stop_current, pos.low_water + trail_dist)
        return None

    def _take_partial(self, pos: Position, price: float, ts: int, i: int, frac: float) -> None:
        """بستن بخشی از پوزیشن (سود شناور مرحله‌ای)."""
        frac = max(0.0, min(1.0, float(frac)))
        if frac <= 0 or frac >= 1 or pos.qty <= 0:
            return
        qty = pos.qty * frac
        self._close(pos, price, ts, "partial_take_%gR" % self.cfg.partial_take_r, i,
                    qty=qty, partial=True)
        pos.qty -= qty
        pos.notional = pos.qty * pos.entry
        pos.risk_amount *= (1.0 - frac)
        pos.partial_taken = True

    def _close(self, pos: Position, price: float, ts: int, reason: str, i: int,
               qty: Optional[float] = None, partial: bool = False) -> dict:
        """بستن کل یا بخشی از پوزیشن + ثبت فورنزیک."""
        cfg = self.cfg
        full = qty is None
        q = pos.qty if full else min(float(qty), pos.qty)
        if q <= 0:
            return {}
        if full:
            self.positions.remove(pos)

        share = (q / pos.initial_qty) if pos.initial_qty else 1.0
        fill = slip_price(price, cfg.slippage_pct, -pos.direction)   # خروج: پرشدنِ بدتر
        gross_pnl = pos.direction * (fill - pos.entry) * q
        close_fee = fee_on_notional(q * pos.entry, cfg.fee_bps)
        open_fee_leg = pos.open_fee * share
        net_pnl = gross_pnl - open_fee_leg - close_fee
        self.equity += gross_pnl - close_fee
        self._bump_dd()

        pos.realized_partial_pnl += net_pnl
        pos.legs += 1
        is_loss = net_pnl < 0

        if full:
            # شمارنده‌های ریسک فقط روی سود/زیانِ کلِ پوزیشن (شامل لگ‌های جزئی)
            if pos.realized_partial_pnl < 0:
                self.consecutive_losses += 1
                self.cooldown_until_bar = i + cfg.cooldown_bars_after_loss
            else:
                self.consecutive_losses = 0
            if self.consecutive_losses >= cfg.cb_losses:
                self.cb_until_bar = i + cfg.cb_cooldown_bars
                self.consecutive_losses = 0

        exc = [pos.direction * (c["c"] - pos.entry) / pos.entry for c in pos.path[1:]]
        mfe = max(exc) if exc else 0.0
        mae = min(exc) if exc else 0.0
        bars_held = len(pos.path) - 1
        r_multiple = (net_pnl / pos.risk_amount) if pos.risk_amount else 0.0

        rec = {
            "type": "close", "run_id": cfg.run_id, "ts": ts, "symbol": pos.symbol,
            "side": pos.direction, "entry": round(pos.entry, 4), "exit": round(fill, 4),
            "stop_initial": round(pos.stop_initial, 4), "stop_final": round(pos.stop_current, 4),
            "take": round(pos.take, 4), "qty": round(q, 8),
            "notional": round(q * pos.entry, 4),
            "risk_amount": round(pos.risk_amount, 4),
            "equity_before": round(pos.equity_before, 4),
            "equity_after": round(self.equity, 4),
            "bars_held": bars_held, "reason": reason,
            "gross_pnl": round(gross_pnl, 4), "fees": round(open_fee_leg + close_fee, 4),
            "pnl": round(net_pnl, 4),
            "net_pct": round(net_pnl / max(q * pos.entry, 1e-9) * 100, 4),
            "r_multiple": round(r_multiple, 4),
            "r_gross": round(gross_pnl / pos.risk_amount, 4) if pos.risk_amount else 0.0,
            "position_pnl": round(pos.realized_partial_pnl, 4),
            "partial": bool(partial), "leg": pos.legs,
            "mfe_pct": round(mfe * 100, 4), "mae_pct": round(mae * 100, 4),
            "is_win": not is_loss, "trail_active": pos.trail_active,
            "confidence_entry": pos.confidence, "score_entry": pos.score,
            "alignment_version": cfg.alignment_version,
            "regime_bias_entry": pos.regime_bias, "regime_entry": pos.regime_filter,
            "regime_filter_entry": pos.regime_filter,
            "trigger_mode": pos.trigger_mode, "reason_entry": pos.reason,
            "volume_entry": pos.path[0].get("v", 0.0) if pos.path else 0.0,
            "volume_exit": pos.path[-1].get("v", 0.0) if pos.path else 0.0,
            "layers_entry": pos.layers,
            "indicators_entry": pos.snap_trigger, "indicators_filter_entry": pos.snap_filter,
            "indicators_bias_entry": pos.snap_bias,
            "open_bar": pos.open_bar, "exit_bar": i,
            "path_candles": pos.path if cfg.forensics else [],
            "diagnosis": _diagnose(pos, reason, net_pnl, mfe, mae, bars_held, r_multiple),
        }
        self.trades.append(rec)
        if self.tw:
            self.tw.write(rec)
        return rec

    # -- لاگ سیگنال ----------------------------------------------------------
    def _log_signal(self, info: dict, pos: Position, i: int, ts: int, leverage: float) -> None:
        d = info["decision"]
        rec = {
            "type": "open", "run_id": self.cfg.run_id, "i": i, "ts": ts,
            "symbol": self.cfg.symbol, "direction": d.direction,
            "confidence": d.confidence, "score": d.score,
            "alignment_version": d.version, "reason": d.reason,
            "trigger_mode": info["trig"].mode,
            "entry": round(pos.entry, 4), "stop": round(pos.stop_initial, 4),
            "take": round(pos.take, 4), "qty": round(pos.qty, 8),
            "notional": round(pos.notional, 4), "leverage": round(leverage, 4),
            "fee_open": round(pos.open_fee, 4), "risk_amount": round(pos.risk_amount, 4),
            "regime_bias": info["bias"].regime, "regime_filter": info["filt"].regime,
            "layers": d.layers, "cost_check": d.cost_check,
            "snap_trigger": pos.snap_trigger, "snap_filter": pos.snap_filter,
            "snap_bias": pos.snap_bias,
        }
        if self.sw:
            self.sw.write(rec)

    def _log_wait(self, info: dict, i: int, ts: int, reason: str, kind: str = "wait") -> None:
        if not self.cfg.forensics or not self.sw:
            return
        d = info["decision"]
        self.sw.write({
            "type": kind, "run_id": self.cfg.run_id, "i": i, "ts": ts,
            "symbol": self.cfg.symbol, "reason": reason,
            "trigger_mode": info["trig"].mode,
            "regime_bias": info["bias"].regime, "regime_filter": info["filt"].regime,
            "score": d.score, "cost_check": d.cost_check,
        })

    # -- خلاصه ---------------------------------------------------------------
    def summary(self) -> dict:
        t = self.trades
        wins = [x for x in t if x["is_win"]]
        losses = [x for x in t if not x["is_win"]]
        gw = sum(x["pnl"] for x in wins)
        gl = abs(sum(x["pnl"] for x in losses))
        pf = round(gw / gl, 3) if gl > 0 else (float("inf") if gw > 0 else 0.0)
        total = sum(x["pnl"] for x in t)
        rs = [x["r_multiple"] for x in t]
        return {
            "trades": len(t), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(t), 4) if t else 0.0,
            "profit_factor": pf,
            "avg_win": round(gw / len(wins), 4) if wins else 0.0,
            "avg_loss": round(-gl / len(losses), 4) if losses else 0.0,
            "expectancy": round(total / len(t), 4) if t else 0.0,
            "expectancy_r": round(sum(rs) / len(rs), 4) if rs else 0.0,
            "total_pnl": round(total, 4),
            "total_fees": round(sum(x["fees"] for x in t), 4),
            "partial_legs": sum(1 for x in t if x.get("partial")),
            "equity": round(self.equity, 4),
            "return_pct": round((self.equity - self.cfg.initial_equity)
                                / self.cfg.initial_equity * 100, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "avg_bars_held": round(sum(x["bars_held"] for x in t) / len(t), 2) if t else 0.0,
            "avg_mfe_pct": round(sum(x["mfe_pct"] for x in t) / len(t), 4) if t else 0.0,
            "avg_mae_pct": round(sum(x["mae_pct"] for x in t) / len(t), 4) if t else 0.0,
            "positions_opened": self.positions_opened,
            "avg_legs_per_position": round(len(t) / self.positions_opened, 3)
            if self.positions_opened else 0.0,
            "circuit_breaker_hits": self.veto_stats["circuit_breaker"],
            "still_open": len(self.positions),
            "veto_stats": dict(self.veto_stats),
            "trigger_stats": dict(self.trigger_stats),
        }


def _diagnose(pos: Position, reason: str, net: float, mfe: float, mae: float,
              bars_held: int, r_mult: float) -> str:
    sign = "✅" if net >= 0 else "❌"
    kind = "سود" if net >= 0 else "ضرر"
    notes = []
    if net < 0 and mfe > 0.004:
        notes.append(f"⚠️ در مسیر {mfe*100:.2f}% سودِ باز بود ولی نگه داشته نشد (تریلینگ/TP)")
    if net < 0 and abs(mae) > 0.01:
        notes.append(f"MAE بزرگ {mae*100:.2f}% — استاپ نسبت به نوسان تنگ یا ورود دیرهنگام")
    if net >= 0 and r_mult >= 1.8:
        notes.append("TP کامل خورد — R:R طبق طراحی")
    if bars_held <= 1:
        notes.append("خروج فوری (همان کندل ورود) — احتمالاً نویز")
    return (f"{sign} {kind} {net:+.2f} USDT ({r_mult:+.2f}R) در {bars_held} کندل | "
            f"خروج: {reason}" + (" | " + "؛ ".join(notes) if notes else ""))


# ----------------------------------------------------------------------------
# اجرای کامل بک‌تست
# ----------------------------------------------------------------------------
def run_backtest(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                 signals_w: Optional[JsonlWriter] = None,
                 trades_w: Optional[JsonlWriter] = None,
                 collect_waits: bool = False) -> dict:
    """اجرای بک‌تست روی سه لایهٔ زمانی. خروجی: dict شامل summary/trades/health."""
    t_min = tf_to_minutes(cfg.tf_trigger)
    f_min = tf_to_minutes(cfg.tf_filter)
    b_min = tf_to_minutes(cfg.tf_bias) if cfg.bias_enabled else f_min

    bars = align_multi_timeframe(layers["trigger"], t_min, layers["filter"], f_min,
                                 layers["bias"] if cfg.bias_enabled else None,
                                 b_min if cfg.bias_enabled else None)
    ctxs = {
        "trigger": TFContext(layers["trigger"], cfg, "trigger"),
        "filter": TFContext(layers["filter"], cfg, "filter"),
        "bias": TFContext(layers["bias"], cfg, "bias") if cfg.bias_enabled else
                TFContext(layers["filter"], cfg, "filter"),
    }

    engine = MTFEngine(cfg, signals_w, trades_w)
    coverage = alignment_coverage(bars)
    audit = leakage_audit(bars, f_min, b_min if cfg.bias_enabled else None)

    for i, bar in enumerate(bars):
        candle = bar.low_tf_candle
        engine._check_daily_limit(candle.open_time_ms)

        info = engine.build_decision(bar, ctxs)
        filt_dir_now = info["filt"].direction

        # شمارش streakِ تغییر رژیم (برای خروج تأییدشده)
        if filt_dir_now != 0 and filt_dir_now != engine.last_filter_dir:
            engine.filter_flip_streak = 1
        elif filt_dir_now != 0:
            engine.filter_flip_streak += 1
        else:
            engine.filter_flip_streak = 0
        engine.last_filter_dir = filt_dir_now if filt_dir_now != 0 else engine.last_filter_dir

        # 1) مدیریت پوزیشن‌های باز
        for pos in list(engine.positions):
            rec = engine.manage_position(pos, candle, i, ctxs, filt_dir_now)
            if rec and cfg.verbose:
                tag = "💰" if rec["is_win"] else "🛡️"
                print(f"[{i:6d}] {tag} خروج {'LONG' if rec['side']>0 else 'SHORT'} "
                      f"px={rec['exit']:.2f} pnl={rec['pnl']:+.2f} ({rec['reason']})")

        # 2) ورود جدید
        d = info["decision"]
        if d.action == "ENTER":
            blocked = None  # noqa: F841
            if engine.cb_until_bar > i:
                blocked = "circuit_breaker"
            elif i <= engine.cooldown_until_bar:
                blocked = "cooldown"
            elif engine.daily_limit_hit:
                blocked = "daily_loss"
            elif not engine._open_slots_free():
                blocked = "slots"
            hour_utc = (candle.open_time_ms // 3_600_000) % 24
            if cfg.skip_hours_utc and hour_utc in set(cfg.skip_hours_utc):
                blocked = blocked or "hour_filter"
            if blocked:
                engine.veto_stats[blocked] += 1
                if collect_waits:
                    engine._log_wait(info, i, candle.open_time_ms, blocked, kind="blocked")
            else:
                entry_price = layers["trigger"][i + 1].open if (cfg.entry_on_next_open
                                                                 and i + 1 < len(bars)) else candle.close
                pos = engine.open_position(info, ctxs, i, entry_price, candle.open_time_ms)
                if pos and cfg.verbose:
                    print(f"[{i:6d}] 🟢 {'LONG' if pos.direction>0 else 'SHORT'} {cfg.symbol} "
                          f"px={pos.entry:.2f} stop={pos.stop_initial:.2f} take={pos.take:.2f} "
                          f"({info['filt'].regime}/{info['trig'].mode} | v{d.version})")
        else:
            reason = engine._veto_reason(info)
            if collect_waits and reason:
                engine._log_wait(info, i, candle.open_time_ms, reason)

        engine.equity_curve.append({"ts": candle.open_time_ms, "equity": round(engine.equity, 4),
                                    "close": candle.close, "positions": len(engine.positions)})

    # بستن پوزیشن‌های باز در انتهای داده (با برچسب صریح)
    if engine.positions:
        last = layers["trigger"][-1]
        for pos in list(engine.positions):
            engine._close(pos, last.close, last.open_time_ms, "end_of_data", len(bars) - 1)

    health = {
        "alignment_coverage": coverage,
        "leakage_audit": audit,
        "bars": len(bars),
        "trigger_candles": len(layers["trigger"]),
        "filter_candles": len(layers["filter"]),
        "bias_candles": len(layers["bias"]),
        "round_trip_cost_pct": round((cfg.fee_bps / 10_000 + cfg.slippage_pct / 100) * 2 * 100, 5),
        "warmup_warnings": _warmup_warnings(cfg, coverage, layers),
    }
    return {"summary": engine.summary(), "trades": engine.trades,
            "equity_curve": engine.equity_curve, "health": health,
            "engine": engine, "bars": bars, "ctxs": ctxs}


def _warmup_warnings(cfg, coverage: dict, layers: Dict[str, List[Candle]]) -> List[str]:
    """هشدار صریح وقتی دورهٔ warmup نسبت به طول داده بی‌تناسب است."""
    out = []
    if coverage.get("bias_coverage", 1.0) < 0.6 and cfg.bias_enabled:
        out.append(
            f"پوشش لایهٔ بایاس فقط {coverage['bias_coverage']*100:.1f}% است: دورهٔ "
            f"EMA{cfg.bias_ema_period} روی {cfg.tf_bias} برای {len(layers['bias'])} کندلِ موجود "
            f"بلند است. یا دادهٔ بیشتری بیاورید یا --bias-ema را کم کنید.")
    if coverage.get("filter_coverage", 1.0) < 0.5:
        out.append(
            f"پوشش لایهٔ فیلتر فقط {coverage['filter_coverage']*100:.1f}% است "
            f"(warmup EMA{cfg.filter_ema_period}/ADX روی {cfg.tf_filter}).")
    return out


def run_from_config(cfg: MTFConfig) -> dict:
    """بارگذاری داده + اجرای بک‌تست + نوشتن گزارش‌ها."""
    from .report import write_reports
    if not cfg.run_id:
        cfg.run_id = f"mtf-{cfg.alignment_version}-{time.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(cfg.out_dir, exist_ok=True)

    layers, meta = load_layers(cfg)
    sw = JsonlWriter(os.path.join(cfg.out_dir, f"mtf_signals_{cfg.run_id}.jsonl")) \
        if cfg.forensics else None
    tw = JsonlWriter(os.path.join(cfg.out_dir, f"mtf_trades_{cfg.run_id}.jsonl")) \
        if cfg.forensics else None

    if cfg.verbose:
        print("=" * 70)
        print("  🧩 Futures MTF Lab — سناریوی چندتایم‌فریمی (PAPER)")
        print("=" * 70)
        print(f"📈 {cfg.symbol} | تریگر={cfg.tf_trigger} فیلتر={cfg.tf_filter} "
              f"بایاس={cfg.tf_bias if cfg.bias_enabled else '—'} | نسخهٔ هم‌راستایی: {cfg.alignment_version}")
        print(f"💰 موجودی {cfg.initial_equity} | ریسک "
              f"{'ثابت ' + str(cfg.fixed_risk) + ' USDT' if cfg.fixed_risk > 0 else str(cfg.risk_per_trade_pct) + '%'} "
              f"| SL {cfg.stop_atr_mult}×ATR | TP {cfg.take_profit_atr_mult}×ATR (RR={cfg.rr})")
        print(f"💵 هزینهٔ هر طرف: {cfg.fee_bps}bps + {cfg.slippage_pct}% slippage "
              f"| حداقل edge: {cfg.min_edge_multiplier}×")
        print(f"📦 کندل‌ها: trigger={len(layers['trigger'])} filter={len(layers['filter'])} "
              f"bias={len(layers['bias'])} | {cfg.label()}")
        print("-" * 70)

    res = run_backtest(cfg, layers, sw, tw)
    if sw:
        sw.close()
    if tw:
        tw.close()
    res["meta"] = meta
    res["config"] = cfg.to_dict()
    res["run_id"] = cfg.run_id

    if cfg.validate:
        from .validation import full_validation
        res["validation"] = full_validation(cfg, layers, progress=cfg.verbose)

    write_reports(cfg, res)
    if cfg.verbose:
        s = res["summary"]
        print("\n" + "=" * 70)
        print(f"📊 خلاصه: معاملات={s['trades']} (سود {s['wins']} / ضرر {s['losses']}) "
              f"win_rate={s['win_rate']:.1%}")
        print(f"📈 PF={s['profit_factor']} | Expectancy={s['expectancy']:+.3f} USDT "
              f"({s['expectancy_r']:+.3f}R) | کارمزد کل={s['total_fees']:.2f}")
        print(f"💰 موجودی نهایی={s['equity']} ({s['return_pct']:+.2f}%) | MaxDD={s['max_drawdown_pct']:.2f}%")
        print(f"🚦 وتوها: {s['veto_stats']}")
        print(f"🛡️ حسابرسی نشتی: {'✅ پاک' if res['health']['leakage_audit']['clean'] else '❌ نقض'} "
              f"| پوشش فیلتر/بایاس: "
              f"{res['health']['alignment_coverage']['filter_coverage']:.1%}/"
              f"{res['health']['alignment_coverage']['bias_coverage']:.1%}")
        print("=" * 70)
    return res
