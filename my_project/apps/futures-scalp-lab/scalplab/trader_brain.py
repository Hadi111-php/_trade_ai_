"""TraderBrain — «نقش معامله‌گر فیوچرز» (rule-based, PAPER only).

این مودول همان «نقش» (role) request‌شده را اجرا می‌کند:
- **فقط با روند market تجارت می‌کند**: صعودی → فقط لانگ، نزولی → فقط شورت، رنج → صبر.
- **ورود** بر اساس تحریک (pullback به EMA21 یا شکست Donchian با حجم).
- **خروج با صبر**: استاپ اولیه، سود (R:R)، تریلینگ استاپ که فقط بعد از سود
  قابل‌توجه فعال می‌شود، و تغییرِ روند **تأییدشده** (تأیید چندین بار).
- **مدیریت ریسک**: هر معامله فقط خطر X% موجودی، حداکثر اهرم، حد ضرر روزانه، مدار شکن.
- **FULL FORENSICS**: هر سیگنال و هر بستن با تمام اسنپ‌شات، مسیر قیمت، MFE/MAE
  و توضیحِ دلیلِ سود/ضرر در JSON ثبت می‌شود (برای بررسی دقیق هر نتیجه).
- **فقط مجازی (PAPER)** — LIVE عمداً پیاده‌سازی نشده؛ بعد از تأیید متصل می‌شود.

کد علی است: خروجی لحظه t فقط از دادهٔ <= t محاسبه می‌شود (بدون lookahead).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import __version__
from .data import Candle
from .indicators import build_snapshot
from .logger import JsonlWriter
from .regimes import compute_regimes, regime_bias
from .runner import DEFAULT_PARAMS


# ----------------------------------------------------------------------------
# پیکربندی
# ----------------------------------------------------------------------------
@dataclass
class TraderConfig:
    # داده
    symbol: str = "BTCUSDT"
    data_mode: str = "synthetic"        # synthetic | csv | binance | bybit
    timeframe: str = "1m"
    candles: int = 2000
    csv_path: str = ""
    out_dir: str = "results"
    run_id: str = ""

    # پارامترهای تشخیص روند (regime)
    regime_params: dict = field(default_factory=dict)

    # حساب / ریسک (paper)
    initial_equity: float = 1000.0
    risk_per_trade_pct: float = 1.0     # خطر هر معامله، درصد موجودی
    fixed_risk: float = 0.0             # اگر >۰: خطر ثابتِ USDT (بدون compounding)
    slippage_pct: float = 0.05          # slippage هر طرف (درصد)
    # حالت legacy (قبل از fix) — برای مقایسه قبل/بعد
    legacy_exit_close: bool = False     # قبل: خروج در قیمتِ close (نه stop/take)
    legacy_regime_any: bool = False     # قبل: تغییر روند هر کسی (نه فقط ضرر)
    legacy_short_trail_bug: bool = False # قبل: bug تسلِ short (low_water − trail)
    # فیلتر حجم بازار (برای پیمانه‌بندیِ خروج)
    vol_avg: float = 0.0                # میانگین حجم (برای ratio)
    vol_entry_filter: bool = False      # ورود فقط وقتی حجم خارج از محدودهِ وسط است
    vol_entry_lo: float = 0.7           # زیرِ این: ورود مجاز
    vol_entry_hi: float = 1.3           # بالایِ این: ورود مجاز
    vol_exit_filter: bool = False       # خروج فقط وقتی حجم کافی است
    vol_exit_min: float = 1.0           # حداقل ratioِ حجم برای خروج
    max_leverage: float = 5.0           # حداکثر اهرم
    take_profit_rr: float = 2.0         # نسبت سود:ریسک
    stop_atr_mult: float = 1.5          # استاپ اولیه = ATR × این
    trail_atr_mult: float = 2.0         # فاصله تریلینگ = ATR × این (با صبر)
    trail_enabled: bool = True
    trail_start_profit_pct: float = 0.008   # تریلینگ فقط بعد از +0.8% سود فعال می‌شود
    regime_confirm_bars: int = 2          # تغییر روند باید N بار تأیید شود
    max_concurrent: int = 3
    daily_loss_limit_pct: float = 3.0
    cb_losses: int = 2                  # ضرر متوالی → مدار شکن
    cooldown_bars: int = 5
    regime_change_exit: bool = True
    range_trade: bool = False           # رنج: معامله محدۊد یا صبر
    min_confidence: float = 0.5
    entry_mode: str = "pullback"        # pullback | breakout | both

    # جریان (حالت auto-like)
    max_ticks: int = 300
    interval: float = 0.0
    forever: bool = False
    light: bool = False

    # کارمزد هر طرف (bps)
    fee_bps: float = 4.0

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class Position:
    symbol: str
    direction: int          # +1 long, -1 short
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
    regime: str
    reason: str
    open_fee: float = 0.0
    trail_pct: float = 0.0
    trail_active: bool = False
    # --- full forensics ---
    entry_snap: dict = field(default_factory=dict)
    entry_regime: dict = field(default_factory=dict)
    entry_candle: dict = field(default_factory=dict)
    risk_amount: float = 0.0
    equity_before: float = 0.0
    path: list = field(default_factory=list)      # candle dicts
    path_ind: list = field(default_factory=list)   # lightweight indicator per bar


# ----------------------------------------------------------------------------
# موتور تصمیم‌گیری
# ----------------------------------------------------------------------------
class TraderBrain:
    """نقش معامله‌گر: تصمیم ورود/خروج + مدیریت پوزیشن PAPER + full journal."""

    def __init__(self, cfg: TraderConfig, signals_w=None, trades_w=None):
        self.cfg = cfg
        self.fee_frac = 2 * cfg.fee_bps / 10_000
        self.sw = signals_w          # JsonlWriter برای سیگنال‌های کامل
        self.tw = trades_w           # JsonlWriter برای بستن‌های کامل
        self.equity = float(cfg.initial_equity)
        self.positions: List[Position] = []
        self.trades: List[dict] = []
        self.halted = False
        self.halt_until_ts = 0
        self.consecutive_losses = 0
        self.day_start_equity = self.equity
        self.last_regimes: list = []     # آخرین N رژیم برای تأیید تغییر

    # -- helpers ------------------------------------------------------------
    def _clamp(self, x: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))

    def has_position(self, symbol: str) -> bool:
        return any(p.symbol == symbol for p in self.positions)

    def _slots_free(self) -> bool:
        return len(self.positions) < self.cfg.max_concurrent

    def _atr_price(self, candles: List[Candle], i: int) -> float:
        from .indicators import atr
        a = atr(candles, 14)
        return a[i] if i < len(a) and a[i] is not None else 0.0

    def _daily_loss_exceeded(self) -> bool:
        start = self.day_start_equity
        if not (start > 0):
            return True
        return ((start - self.equity) / start * 100.0) >= self.cfg.daily_loss_limit_pct

    # -- تصمیم ورود --------------------------------------------------------
    def decide(self, candles: List[Candle], regime: Optional[dict], snap: Optional[dict],
               i: int, ts: int) -> dict:
        """تصمیم ورود بر اساس روند + تحریک + ریسک."""
        sym = self.cfg.symbol
        if self.has_position(sym):
            return {"action": "HOLD", "symbol": sym, "reason": "پوزیشن باز است"}
        if self.halted:
            if ts >= self.halt_until_ts and self.halt_until_ts > 0:
                self.halted = False
                self.consecutive_losses = 0
            else:
                return {"action": "WAIT", "symbol": sym, "reason": "مدار شکن (cooldown)"}
        if regime is None or snap is None:
            return {"action": "WAIT", "symbol": sym, "reason": "warmup / داده کافی نیست"}

        price = candles[i].c
        # ATR از اسنپ‌شات (پیش‌محاسبه‌شده — نه recomputing روی تمام کندل)
        atr_pct = snap.get("atr_pct", 0.0) if snap else 0.0
        atr_abs = (atr_pct / 100.0) * price if atr_pct else price * 0.004
        bias = regime_bias(regime["regime"])
        rsi = snap.get("rsi", 50.0)
        ema_slow = regime.get("ema_slow", price)
        donch_pos = regime.get("donch_pos", 0.5)
        vol_z = regime.get("vol_z", 0.0)

        side = 0
        trigger = ""
        if bias == 0:
            if self.cfg.range_trade:
                if rsi <= 35:
                    side, trigger = 1, "رنج: کف RSI"
                elif rsi >= 65:
                    side, trigger = -1, "رنج: سقف RSI"
                else:
                    return {"action": "WAIT", "symbol": sym, "reason": "رنج و RSI خنثی"}
            else:
                return {"action": "WAIT", "symbol": sym,
                        "reason": "رنج: با روند موافق نیست — صبر"}
        else:
            want = 1 if bias == 1 else -1
            entry_mode = self.cfg.entry_mode
            pullback = entry_mode in ("pullback", "both")
            breakout = entry_mode in ("breakout", "both")
            fired = False
            if pullback and abs(price - ema_slow) <= 0.7 * atr_abs:
                rsi_ok = (rsi < 60) if want == 1 else (rsi > 40)
                if rsi_ok:
                    fired = True
                    trigger = "روند + بازگشت به EMA21"
            if not fired and breakout:
                if (want == 1 and donch_pos > 0.75) or (want == -1 and donch_pos < 0.25):
                    if vol_z > 0.0:
                        fired = True
                        trigger = "روند + شکست Donchian"
            if not fired:
                return {"action": "WAIT", "symbol": sym,
                        "reason": f"روند {regime['regime']}، تحریک ورود برآورده نشده"}
            side = want

        # فیلتر حجم بازار — ورود فقط وقتی حجم خارج از محدودهِ وسطِ ambiguous است
        if self.cfg.vol_entry_filter and self.cfg.vol_avg > 0:
            vol_ratio = candles[i].v / self.cfg.vol_avg
            if self.cfg.vol_entry_lo <= vol_ratio <= self.cfg.vol_entry_hi:
                return {"action": "WAIT", "symbol": sym,
                        "reason": f"فیلتر حجم: ratio={vol_ratio:.2f} در محدودهِ وسط (ambiguous)"}

        # سطح‌های ریسک (ورود با slippage: فیل شده قیمت واقعی)
        stop_dist = max(atr_abs * self.cfg.stop_atr_mult, price * 0.0012)
        slip = self.cfg.slippage_pct / 100.0
        if side == 1:
            entry = price * (1 + slip)          # خرید: پرکردن بدترِ قیمت
            stop = entry - stop_dist
            take = entry + stop_dist * self.cfg.take_profit_rr
        else:
            entry = price * (1 - slip)          # فروش: پرکردن بدترِ قیمت
            stop = entry + stop_dist
            take = entry - stop_dist * self.cfg.take_profit_rr

        # اندازه‌ی پوزیشن بر اساس ریسک (1% موجودی) + سقف اهرم
        if self.cfg.fixed_risk > 0:
            risk_amount = self.cfg.fixed_risk
        else:
            risk_amount = self.equity * (self.cfg.risk_per_trade_pct / 100.0)
        stop_dist_price = abs(entry - stop)
        qty = risk_amount / stop_dist_price if stop_dist_price > 0 else 0.0
        notional = qty * entry
        lev = notional / self.equity if self.equity > 0 else 0.0
        if lev > self.cfg.max_leverage:
            qty = self.equity * self.cfg.max_leverage / entry
            notional = qty * entry

        conf = regime["confidence"]
        if conf < self.cfg.min_confidence:
            return {"action": "WAIT", "symbol": sym,
                    "reason": f"اعتماد {conf:.2f} از حد پایین‌تر است"}

        fee_open = notional * (self.cfg.fee_bps / 10_000)
        return {
            "action": "ENTER",
            "symbol": sym,
            "side": "LONG" if side == 1 else "SHORT",
            "direction": side,
            "entry": entry,
            "stop": stop,
            "take": take,
            "qty": round(qty, 8),
            "notional": round(notional, 2),
            "confidence": round(conf, 3),
            "regime": regime["regime"],
            "reason": trigger,
            "adx": regime.get("adx"),
            "atr": round(atr_abs, 4),
            "slope_pct": regime.get("slope_pct"),
            "donch_pos": donch_pos,
            "bb_pos": regime.get("bb_pos"),
            "vol_z": vol_z,
            "rsi": rsi,
            "ema_fast": regime.get("ema_fast"),
            "ema_slow": ema_slow,
            "ema_trend": regime.get("ema_trend"),
            "fee_open": round(fee_open, 4),
            "ts": ts,
        }

    # -- باز/بسته شدن پوزیشن ---------------------------------------------
    def open(self, decision: dict, snap: dict, regime: dict, candle: Candle,
             bar_index: int) -> bool:
        if decision["action"] != "ENTER":
            return False
        if self._daily_loss_exceeded() or not self._slots_free():
            return False
        self.equity -= decision["fee_open"]
        trail_pct = (self.cfg.trail_atr_mult / max(self.cfg.stop_atr_mult, 1e-9)) \
            if self.cfg.trail_enabled else 0.0
        pos = Position(
            symbol=decision["symbol"],
            direction=decision["direction"],
            entry=decision["entry"],
            qty=decision["qty"],
            notional=decision["notional"],
            stop_initial=decision["stop"],
            take=decision["take"],
            stop_current=decision["stop"],
            high_water=decision["entry"],
            low_water=decision["entry"],
            open_ts=decision["ts"],
            open_bar=bar_index,
            confidence=decision["confidence"],
            regime=decision["regime"],
            reason=decision["reason"],
            open_fee=decision["fee_open"],
            trail_pct=trail_pct,
            trail_active=False,
            entry_snap=dict(snap or {}),
            entry_regime=dict(regime or {}),
            entry_candle=candle.to_dict(),
            equity_before=self.equity + decision["fee_open"],
        )
        # risk_amount: مقادیر risk-based (یا ثابت)
        pos.risk_amount = (self.cfg.fixed_risk if self.cfg.fixed_risk > 0
                           else self.equity * self.cfg.risk_per_trade_pct / 100.0)
        pos.path.append(candle.to_dict())
        pos.path_ind.append({
            "bar": bar_index, "regime": decision["regime"],
            "rsi": snap.get("rsi"), "adx": regime.get("adx"),
            "donch_pos": regime.get("donch_pos"),
        })
        self.positions.append(pos)
        self._log_signal(decision, pos)
        return True

    def on_candle(self, price: float, ts: int, regime: Optional[dict], snap: Optional[dict],
                  candle: Candle, bar_index: int) -> List[dict]:
        """مدیریت خروج با صبر + ثبت کامل مسیر."""
        exits: List[dict] = []
        regime_name = regime["regime"] if regime else None
        if regime_name:
            self.last_regimes.append(regime_name)
            if len(self.last_regimes) > self.cfg.regime_confirm_bars:
                self.last_regimes.pop(0)

        confirm_bars = self.cfg.regime_confirm_bars
        regime_flipped_confirmed = (
            self.cfg.regime_change_exit
            and regime_name
            and len(self.last_regimes) >= confirm_bars
            and all(r == regime_name for r in self.last_regimes)
        )

        to_close: List[tuple] = []
        for p in list(self.positions):
            # ثبت مسیر
            p.path.append(candle.to_dict())
            p.path_ind.append({
                "bar": bar_index, "regime": regime_name,
                "rsi": (snap or {}).get("rsi"), "adx": (regime or {}).get("adx"),
                "donch_pos": (regime or {}).get("donch_pos"),
            })
            # بالا/پایین watermark
            if p.direction == 1:
                p.high_water = max(p.high_water, price)
            else:
                p.low_water = min(p.low_water, price)

            in_profit = (price - p.entry) * p.direction > 0

            # فیلتر حجم برای خروجِ discretionary (take_profit) — stopِ مکمل است (exitأ ممكن نیست)
            vol_ok = True
            if self.cfg.vol_exit_filter and self.cfg.vol_avg > 0:
                vol_ratio = candle.v / self.cfg.vol_avg
                vol_ok = vol_ratio >= self.cfg.vol_exit_min

            # ۱. استاپ اولیه/تریلینگ (صبر: تریلینگ فقط بعد از سود)
            # legacy: خروج در قیمتِ close (نه stop/take)
            exit_px = price if self.cfg.legacy_exit_close else None
            if p.direction == 1:
                if self.cfg.trail_enabled and p.trail_pct > 0:
                    profit_pct = (price - p.entry) / p.entry
                    if profit_pct >= self.cfg.trail_start_profit_pct:
                        p.trail_active = True
                    if p.trail_active:
                        # فاصله تریلینگ: high_water − (stop_dist × trail_pct) — زیرِ high_water
                        trail_target = p.high_water + (p.stop_initial - p.entry) * p.trail_pct
                        if trail_target > p.stop_current:
                            p.stop_current = trail_target
                if price <= p.stop_current:
                    to_close.append((p, "stop_loss" if not p.trail_active else "trailing_stop",
                                     exit_px if exit_px is not None else p.stop_current))
                elif price >= p.take and vol_ok:
                    to_close.append((p, "take_profit", exit_px if exit_px is not None else p.take))
            else:
                if self.cfg.trail_enabled and p.trail_pct > 0:
                    profit_pct = (p.entry - price) / p.entry
                    if profit_pct >= self.cfg.trail_start_profit_pct:
                        p.trail_active = True
                    if p.trail_active:
                        if self.cfg.legacy_short_trail_bug:
                            # bug: low_water − trail (زیرِ low_water) — fillِ غیرواقعی
                            trail_target = p.low_water + (p.entry - p.stop_initial) * p.trail_pct
                        else:
                            # fix: low_water + trail (بالاى low_water) — fillِ realistik
                            trail_target = p.low_water + (p.stop_initial - p.entry) * p.trail_pct
                        if trail_target < p.stop_current:
                            p.stop_current = trail_target
                if price >= p.stop_current:
                    to_close.append((p, "stop_loss" if not p.trail_active else "trailing_stop",
                                     exit_px if exit_px is not None else p.stop_current))
                elif price <= p.take and vol_ok:
                    to_close.append((p, "take_profit", exit_px if exit_px is not None else p.take))

            # ۲. تغییر روند تأییدشده — فقط زمانی که در ضرر است (سودده‌ها رو trailing بلیت)
            # legacy: هر کسی تغییر روند (نه فقط ضرر)
            if regime_flipped_confirmed and not to_close:
                if not self.cfg.legacy_regime_any and in_profit:
                    pass  # سودده — بگذار رو trailing بلیت
                elif p.direction == 1 and regime_name == "downtrend":
                    to_close.append((p, "regime_change_downtrend", price))
                elif p.direction == -1 and regime_name == "uptrend":
                    to_close.append((p, "regime_change_uptrend", price))

        for p, reason, exit_price in to_close:
            exits.append(self._close(p, exit_price, ts, reason, snap, regime, bar_index))

        # مدار شکن
        if self.consecutive_losses >= self.cfg.cb_losses and not self.halted:
            self.halted = True
            cooldown_ms = 30 * 60 * 1000
            self.halt_until_ts = ts + cooldown_ms
            for p in list(self.positions):
                self._close(p, price, ts, "circuit_breaker", snap, regime, bar_index)
            self._log_event({"type": "halt", "ts": ts,
                              "reason": f"{self.cfg.cb_losses} ضرر متوالی"})
        return exits

    def _close(self, pos: Position, price: float, ts: int, reason: str,
               snap: Optional[dict], regime: Optional[dict], bar_index: int) -> dict:
        if pos not in self.positions:
            return {}
        self.positions.remove(pos)
        # slippage خروج: long فروش (بدتر)، short خرید‌کردند (بدتر)
        slip = self.cfg.slippage_pct / 100.0
        fill = price * (1 - slip) if pos.direction == 1 else price * (1 + slip)
        gross = pos.direction * (fill - pos.entry) / pos.entry
        fee_close = pos.notional * (self.cfg.fee_bps / 10_000)
        gross_pnl = gross * pos.notional
        net_pnl = gross_pnl - pos.open_fee - fee_close   # تمام کارمزد (ورود+خروج)
        # fee_open قبلاً از موجودی کسر شده؛ فقط gross − fee_close اضافه می‌کنیم
        self.equity += gross_pnl - fee_close
        is_loss = net_pnl < 0
        if is_loss:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        pnl = net_pnl

        # MFE / MAE از مسیر
        excursions = []
        for c in pos.path[1:]:
            exc = pos.direction * (c["c"] - pos.entry) / pos.entry
            excursions.append(exc)
        mfe = max(excursions) if excursions else 0.0
        mae = min(excursions) if excursions else 0.0
        bars_held = len(pos.path) - 1

        # volume (برای تحلیلِ حجم بازار vs سوددهی)
        vols = [c["v"] for c in pos.path if "v" in c]
        vol_entry = pos.path[0]["v"] if pos.path and "v" in pos.path[0] else 0.0
        vol_exit = pos.path[-1]["v"] if pos.path and "v" in pos.path[-1] else 0.0
        vol_avg = (sum(vols) / len(vols)) if vols else 0.0

        rec = {
            "type": "close",
            "run_id": getattr(self.cfg, "run_id", ""),
            "ts": ts,
            "symbol": pos.symbol,
            "side": pos.direction,
            "entry": pos.entry,
            "exit": price,
            "stop_initial": pos.stop_initial,
            "stop_final": pos.stop_current,
            "take": pos.take,
            "qty": pos.qty,
            "notional": pos.notional,
            "risk_amount": pos.risk_amount,
            "equity_before": pos.equity_before,
            "bars_held": bars_held,
            "reason": reason,
            "volume_entry": round(vol_entry, 4),
            "volume_exit": round(vol_exit, 4),
            "volume_avg": round(vol_avg, 4),
            "gross_pct": round(gross * 100, 3),
            "fee_pct": round(self.fee_frac * 100, 3),
            "net_pct": round((gross - self.fee_frac) * 100, 3),
            "pnl": round(pnl, 3),
            "is_win": not is_loss,
            "high_water": pos.high_water,
            "low_water": pos.low_water,
            "mfe_pct": round(mfe * 100, 3),
            "mae_pct": round(mae * 100, 3),
            "trail_active": pos.trail_active,
            "regime_entry": pos.regime,
            "reason_entry": pos.reason,
            "confidence_entry": pos.confidence,
            "indicators_entry": pos.entry_snap,
            "indicators_regime_entry": pos.entry_regime,
            "indicators_exit": snap or {},
            "regime_exit": regime or {},
            "path_candles": pos.path,
            "path_indicators": pos.path_ind,
            "diagnosis": self._diagnose(pos, reason, price, ts,
                                        (gross - self.fee_frac), mfe, mae, bars_held),
        }
        self.trades.append(rec)
        self._log_trade(rec)
        return rec

    # -- diagnosis (دلیل سود/ضرر) -----------------------------------------
    def _diagnose(self, pos, reason, price, ts, net, mfe, mae, bars_held) -> str:
        """توضیح انسان‌خوانِ دلیل هر سود/ضررِ معامله."""
        sign = "✅" if net >= 0 else "❌"
        win = "سود" if net >= 0 else "ضرر"
        head = f"{sign} {win} ({net*100:+.2f}%) در {bars_held} بار"
        detail = []
        if reason == "take_profit":
            detail.append("TP را لمس کرد؛")
            if mfe > (net - 0.0001):
                detail.append(f"MFE +{mfe*100:.2f}% بهتر از سودِ realisiert بود")
        elif reason in ("stop_loss", "trailing_stop"):
            detail.append("استاپ بست؛")
            if reason == "trailing_stop":
                detail.append("تریلینگ استاپ پس از سودِ شناور فعال شد")
            detail.append(f"MAE -{mae*100:.2f}%")
        elif reason.startswith("regime_change"):
            detail.append("روند تغییر کرد و خروج شد")
        else:
            detail.append(reason)
        # وضعیت روند
        entry_reg = pos.entry_regime.get("regime", "?")
        detail.append(f"ورود در {entry_reg}")
        # ضعیف بودن تحریک
        conf = pos.confidence
        if conf < 0.55:
            detail.append("اعتماد ورود پایین بود (احتمال false signal)")
        # روند برگشته؟
        return head + ": " + "، ".join(detail)

    # -- logging -----------------------------------------------------------
    def _log_signal(self, decision: dict, pos: Position):
        rec = {
            "type": "signal",
            "run_id": getattr(self.cfg, "run_id", ""),
            "ts": decision["ts"],
            "bar_index": pos.open_bar,
            "symbol": decision["symbol"],
            "side": decision["side"],
            "direction": decision["direction"],
            "entry": decision["entry"],
            "stop": decision["stop"],
            "take": decision["take"],
            "qty": decision["qty"],
            "notional": decision["notional"],
            "confidence": decision["confidence"],
            "regime": decision["regime"],
            "reason": decision["reason"],
            "adx": decision.get("adx"),
            "atr": decision.get("atr"),
            "slope_pct": decision.get("slope_pct"),
            "donch_pos": decision.get("donch_pos"),
            "bb_pos": decision.get("bb_pos"),
            "vol_z": decision.get("vol_z"),
            "rsi": decision.get("rsi"),
            "ema_fast": decision.get("ema_fast"),
            "ema_slow": decision.get("ema_slow"),
            "ema_trend": decision.get("ema_trend"),
            "fee_open": decision.get("fee_open"),
            "equity_before": pos.equity_before,
            "risk_amount": pos.risk_amount,
            "candle": pos.entry_candle,
            "settings": {
                "risk_per_trade_pct": self.cfg.risk_per_trade_pct,
                "max_leverage": self.cfg.max_leverage,
                "take_profit_rr": self.cfg.take_profit_rr,
                "stop_atr_mult": self.cfg.stop_atr_mult,
                "trail_atr_mult": self.cfg.trail_atr_mult,
                "trail_start_profit_pct": self.cfg.trail_start_profit_pct,
                "regime_confirm_bars": self.cfg.regime_confirm_bars,
                "entry_mode": self.cfg.entry_mode,
                "fee_bps": self.cfg.fee_bps,
            },
        }
        if self.sw:
            self.sw.write(rec)

    def _log_trade(self, rec: dict):
        if self.tw:
            self.tw.write(rec)

    def _log_event(self, ev: dict):
        if self.tw:
            self.tw.write(ev)

    def summary(self) -> dict:
        wins = [t for t in self.trades if t["is_win"]]
        losses = [t for t in self.trades if not t["is_win"]]
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else 0.0
        avg_win = round(sum(t["pnl"] for t in wins) / len(wins), 3) if wins else 0.0
        avg_loss = round(sum(t["pnl"] for t in losses) / len(losses), 3) if losses else 0.0
        return {
            "trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(self.trades), 3) if self.trades else 0.0,
            "profit_factor": pf,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "expectancy": round(sum(t["pnl"] for t in self.trades) / len(self.trades), 3) if self.trades else 0.0,
            "total_pnl": round(sum(t["pnl"] for t in self.trades), 2),
            "equity": round(self.equity, 2),
            "return_pct": round((self.equity - self.cfg.initial_equity)
                                / self.cfg.initial_equity * 100, 2),
            "halted": self.halted,
            "still_open": len(self.positions),
        }


# ----------------------------------------------------------------------------
# جریان زنده / بازپخش (PAPER)
# ----------------------------------------------------------------------------
def _label(cfg: TraderConfig) -> str:
    if cfg.data_mode == "binance":
        return "دادهٔ واقعی Binance (فقط خواندنی) — PAPER؛ هنوز سود واقعی نیست"
    if cfg.data_mode == "bybit":
        return "دادهٔ واقعی Bybit (فقط خواندنی) — PAPER؛ هنوز سود واقعی نیست"
    if cfg.data_mode == "csv":
        return "بازپخش دادهٔ CSV واقعی (Bybit فیوچرز) — PAPER؛ هنوز سود واقعی نیست"
    return "دادهٔ مصنوعی — فقط اعتبارسنجی مکانیزم؛ NOT real market"


def run_trader(cfg: TraderConfig) -> int:
    if not cfg.run_id:
        cfg.run_id = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(cfg.out_dir, exist_ok=True)
    sw = JsonlWriter(os.path.join(cfg.out_dir, f"trader_signals_{cfg.run_id}.jsonl"))
    tw = JsonlWriter(os.path.join(cfg.out_dir, f"trader_trades_{cfg.run_id}.jsonl"))
    brain = TraderBrain(cfg, sw, tw)

    params = dict(DEFAULT_PARAMS)
    params["model_version"] = __version__
    regime_params = dict(cfg.regime_params)

    print("=" * 68)
    print("  🧠 TraderBrain — نقش معامله‌گر فیوچرز (PAPER)")
    print("=" * 68)
    print(f"📈 {cfg.symbol} • {cfg.timeframe} • {cfg.data_mode} • {_label(cfg)}")
    print(f"💰 موجودی: {cfg.initial_equity} | خطر/معامله: {cfg.risk_per_trade_pct}% "
          f"| اهرم حداکثر: {cfg.max_leverage}x | RR: {cfg.take_profit_rr}")
    print(f"⚙️  ورود trigger: {cfg.entry_mode} | range_trade: {cfg.range_trade} "
          f"| خروج با تغییر روند (تأیید {cfg.regime_confirm_bars} بار): {cfg.regime_change_exit}")
    print(f"🐢 صبر در خروج: تریلینگ بعد از +{cfg.trail_start_profit_pct*100:.1f}% سود | "
          f"فاصله تریلینگ: {cfg.trail_atr_mult}×ATR")
    print("-" * 68)

    if cfg.data_mode == "csv":
        return _run_backtest_csv(cfg, brain, params, regime_params, sw, tw)
    return _run_streaming(cfg, brain, params, regime_params, sw, tw)


def _run_backtest_csv(cfg, brain, params, regime_params, sw, tw) -> int:
    """بازپخش CSV: اسنپ‌شات و رژیم یک‌بارِ پیش‌محاسبه می‌شود (سریع)."""
    from .data import csv_candles
    candles = csv_candles(cfg)
    if not candles:
        print("❌ CSV فاقد داده است.")
        return 1
    n = len(candles)
    # میانگین حجم برای فیلتر ratio
    brain.cfg.vol_avg = (sum(c.v for c in candles) / len(candles)) if candles else 0.0
    print(f"📦 بارگذاری {n} کندلِ {cfg.symbol} {cfg.timeframe} از {candles[0].ts} تا {candles[-1].ts}"
          + (f" | avg vol={brain.cfg.vol_avg:.1f}" if brain.cfg.vol_avg else ""))
    snaps = build_snapshot(candles, params)
    regs = compute_regimes(candles, regime_params)

    tick = 0
    for i in range(n):
        snap = snaps[i]
        reg = regs[i]
        if snap is None or reg is None:
            continue
        candle = candles[i]
        dec = brain.decide(candles, reg, snap, i, candle.ts)
        if dec["action"] == "ENTER":
            if brain.open(dec, snap, reg, candle, i):
                print(f"[{i:6d}] 🟢 {dec['side']} {dec['symbol']} "
                      f"px={dec['entry']:.2f} stop={dec['stop']:.2f} "
                      f"take={dec['take']:.2f} ({dec['regime']} | {dec['reason']})")
        exits = brain.on_candle(candle.c, candle.ts, reg, snap, candle, i)
        for ex in exits:
            tag = "💰" if ex["is_win"] else "🛡️"
            print(f"[{i:6d}] {tag} خروج {ex['symbol']} px={ex['exit']:.2f} "
                  f"pnl={ex['pnl']:+.2f} ({ex['reason']} | {ex['diagnosis'][:40]})")
        tick += 1

    sw.close(); tw.close()
    return _finalize(cfg, brain, tw)


def _run_streaming(cfg, brain, params, regime_params, sw, tw) -> int:
    """جریان زنده/مصنوعی: بافر متحرک (فقط کندل بسته برای live)."""
    from .auto import SyntheticStream, fetch_last_closed
    from .data import csv_candles
    from .config import LabConfig

    buf: List[Candle] = []
    maxbuf = 300 if cfg.light else 800
    tick = 0
    live_cfg = LabConfig(symbol=cfg.symbol, timeframe=cfg.timeframe,
                         data_mode=cfg.data_mode) if cfg.data_mode in ("binance", "bybit") else None

    stream = None
    csv_rows = None
    if cfg.data_mode == "synthetic":
        stream = SyntheticStream(seed=42)
    elif cfg.data_mode == "csv":
        csv_rows = iter(csv_candles(cfg))

    while tick < cfg.max_ticks:
        if cfg.data_mode == "synthetic":
            buf.append(stream.next())
        elif cfg.data_mode == "csv":
            try:
                buf.append(next(csv_rows))
            except StopIteration:
                print("پایان فایل CSV.")
                break
        else:
            try:
                closed = fetch_last_closed(live_cfg)
            except Exception as e:
                print(f"خطای شبکه: {e}")
                closed = None
            if closed is None or (buf and closed.ts == buf[-1].ts):
                time.sleep(max(cfg.interval, 1.0))
                continue
            buf.append(closed)

        if len(buf) > maxbuf:
            buf.pop(0)
        tick += 1

        snaps = build_snapshot(buf, params)
        regs = compute_regimes(buf, regime_params)
        i = len(buf) - 1
        snap = snaps[i]
        reg = regs[i]
        if snap is None or reg is None:
            continue
        candle = buf[i]
        dec = brain.decide(buf, reg, snap, i, candle.ts)
        if dec["action"] == "ENTER":
            if brain.open(dec, snap, reg, candle, i):
                print(f"[{tick:4d}] 🟢 {dec['side']} {dec['symbol']} "
                      f"px={dec['entry']:.2f} stop={dec['stop']:.2f} "
                      f"take={dec['take']:.2f} ({dec['regime']} | {dec['reason']})")
        exits = brain.on_candle(candle.c, candle.ts, reg, snap, candle, i)
        for ex in exits:
            tag = "💰" if ex["is_win"] else "🛡️"
            print(f"[{tick:4d}] {tag} خروج {ex['symbol']} px={ex['exit']:.2f} "
                  f"pnl={ex['pnl']:+.2f} ({ex['reason']} | {ex['diagnosis'][:40]})")

    sw.close(); tw.close()
    return _finalize(cfg, brain, tw)


def _finalize(cfg, brain, tw) -> int:
    s = brain.summary()
    print("\n" + "=" * 68)
    print(f"📊 خلاصهٔ TraderBrain: معاملات={s['trades']} سودِ={s['wins']} "
          f"زیان={s['losses']} rate={s['win_rate']:.0%}")
    print(f"📈 Profit Factor={s['profit_factor']} | Expectancy={s['expectancy']:+.3f} USDT/trade")
    print(f"💰 موجودی نهایی: {s['equity']} USDT ({s['return_pct']:+.2f}%) | کل PnL={s['total_pnl']:+.2f}")
    print(f"🛑 مدار شکن: {s['halted']} | پوزیشن باز: {s['still_open']}")
    print("📄 لاگ‌های کامل (برای بررسیِ دقیقِ سود/ضرر):")
    print(f"   - سیگنال‌ها: trader_signals_{cfg.run_id}.jsonl")
    print(f"   - معاملات: trader_trades_{cfg.run_id}.jsonl")
    print("=" * 68)

    with open(os.path.join(cfg.out_dir, f"trader_report_{cfg.run_id}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"run_id": cfg.run_id, "lab_version": __version__,
                   "config": cfg.to_dict(), "label": _label(cfg), "summary": s},
                  f, ensure_ascii=False, indent=2)
    return 0


# ----------------------------------------------------------------------------
# parser CLI (python -m scalplab trader …)
# ----------------------------------------------------------------------------
def build_trader_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scalplab trader",
                                description="TraderBrain — نقش معامله‌گر فیوچرز (فقط PAPER)")
    # داده
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--data", dest="data_mode", choices=["synthetic", "csv", "binance", "bybit"],
                   default="synthetic")
    p.add_argument("--tf", dest="timeframe", default="1m")
    p.add_argument("--candles", type=int, default=2000)
    p.add_argument("--csv", dest="csv_path", default="")
    p.add_argument("--run-id", dest="run_id", default="")
    p.add_argument("--out", dest="out_dir", default="results")
    p.add_argument("--max-ticks", dest="max_ticks", type=int, default=300)
    p.add_argument("--interval", type=float, default=0.0)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--light", action="store_true")
    p.add_argument("--fee-bps", dest="fee_bps", type=float, default=4.0)
    p.add_argument("--slippage", dest="slippage_pct", type=float, default=0.05,
                   help="slippage هر طرف (درصد)")
    # حالت legacy (قبل از fix) — برای مقایسه
    p.add_argument("--legacy-exit-close", action="store_true",
                   help="قبل: خروج در قیمتِ close (نه stop/take)")
    p.add_argument("--legacy-regime-any", action="store_true",
                   help="قبل: تغییر روند هر کسی (نه فقط ضرر)")
    p.add_argument("--legacy-short-trail-bug", action="store_true",
                   help="قبل: bug تسلِ short (fillِ غیرواقعی)")
    # فیلتر حجم بازار
    p.add_argument("--vol-entry-filter", action="store_true",
                   help="ورود فقط وقتی حجم خارج از محدودهِ وسط است")
    p.add_argument("--vol-entry-lo", dest="vol_entry_lo", type=float, default=0.7)
    p.add_argument("--vol-entry-hi", dest="vol_entry_hi", type=float, default=1.3)
    p.add_argument("--vol-exit-filter", action="store_true",
                   help="take_profit فقط وقتی حجم کافی است")
    p.add_argument("--vol-exit-min", dest="vol_exit_min", type=float, default=1.0)
    # ریسک / معامله
    p.add_argument("--equity", type=float, default=1000.0)
    p.add_argument("--risk", dest="risk_per_trade_pct", type=float, default=1.0)
    p.add_argument("--fixed-risk", dest="fixed_risk", type=float, default=0.0,
                   help="اگر >۰: خطر ثابتِ USDT (بدون compounding)")
    p.add_argument("--lev", dest="max_leverage", type=float, default=5.0)
    p.add_argument("--rr", dest="take_profit_rr", type=float, default=2.0)
    p.add_argument("--stop-atr", dest="stop_atr_mult", type=float, default=1.5)
    p.add_argument("--trail-atr", dest="trail_atr_mult", type=float, default=2.0)
    p.add_argument("--no-trail", action="store_true")
    p.add_argument("--trail-start", dest="trail_start_profit_pct", type=float, default=0.008,
                   help="حداقل سود برای فعال‌سازی تریلینگ (درصد)")
    p.add_argument("--regime-confirm", dest="regime_confirm_bars", type=int, default=2,
                   help="تعداد بار تأیید برای تغییر روند")
    p.add_argument("--no-regime-exit", action="store_true")
    p.add_argument("--max-concurrent", type=int, default=3)
    p.add_argument("--daily-loss", dest="daily_loss_limit_pct", type=float, default=3.0)
    p.add_argument("--cb", dest="cb_losses", type=int, default=2)
    p.add_argument("--entry-mode", choices=["pullback", "breakout", "both"], default="pullback")
    p.add_argument("--range-trade", action="store_true")
    p.add_argument("--min-conf", dest="min_confidence", type=float, default=0.5)
    p.add_argument("--live", action="store_true", help="عمداً غیرفعال؛ LIVE پیاده‌سازی نشده")
    return p


def load_trader_config(argv=None) -> TraderConfig:
    args, _ = build_trader_parser().parse_known_args(argv)
    cfg = TraderConfig(
        symbol=args.symbol,
        data_mode=args.data_mode,
        timeframe=args.timeframe,
        candles=args.candles,
        csv_path=args.csv_path,
        run_id=args.run_id,
        out_dir=args.out_dir,
        max_ticks=args.max_ticks,
        interval=args.interval,
        light=args.light,
        fee_bps=args.fee_bps,
        slippage_pct=args.slippage_pct,
        legacy_exit_close=args.legacy_exit_close,
        legacy_regime_any=args.legacy_regime_any,
        legacy_short_trail_bug=args.legacy_short_trail_bug,
        vol_entry_filter=args.vol_entry_filter,
        vol_entry_lo=args.vol_entry_lo,
        vol_entry_hi=args.vol_entry_hi,
        vol_exit_filter=args.vol_exit_filter,
        vol_exit_min=args.vol_exit_min,
        initial_equity=args.equity,
        risk_per_trade_pct=args.risk_per_trade_pct,
        fixed_risk=args.fixed_risk,
        max_leverage=args.max_leverage,
        take_profit_rr=args.take_profit_rr,
        stop_atr_mult=args.stop_atr_mult,
        trail_atr_mult=args.trail_atr_mult,
        trail_enabled=not args.no_trail,
        trail_start_profit_pct=args.trail_start_profit_pct,
        regime_confirm_bars=args.regime_confirm_bars,
        regime_change_exit=not args.no_regime_exit,
        max_concurrent=args.max_concurrent,
        daily_loss_limit_pct=args.daily_loss_limit_pct,
        cb_losses=args.cb_losses,
        entry_mode=args.entry_mode,
        range_trade=args.range_trade,
        min_confidence=args.min_confidence,
    )
    if args.forever:
        cfg.max_ticks = 10 ** 9
    if not cfg.run_id:
        cfg.run_id = time.strftime("%Y%m%d-%H%M%S")
    return cfg
