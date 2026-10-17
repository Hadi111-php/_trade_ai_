"""موتور مدیریت ریسک / اجرای سفارش (PAPER در این ماژول).

پیاده‌سازی دقیق شرط‌های کاربر:
- حداکثر N معاملهٔ همزمان (max_concurrent، پیش‌فرض ۴)
- حجم و لوریج قابل تنظیم (trade_size_quote, leverage)
- Circuit breaker: با cb_losses ضرر، همهٔ پوزیشن‌ها بسته و ورود متوقف می‌شود
- سود/ضرر شناور: stop اولیه + trailing stop برای قفل کردن سود

این ماژول فقط منطق خالص + لاگ دارد؛ اتصال واقعی به صرافی در لایهٔ جدا
(live_adapter) و فقط با کلیدهای لوکال کاربر انجام می‌شود — هرگز در git/چت.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Position:
    model_id: str
    direction: int
    entry: float
    qty: float
    size_quote: float
    leverage: float
    stop: float
    high_water: float
    open_ts: int
    confidence: float
    trail_pct: float = 0.003


@dataclass
class RiskConfig:
    trade_size_quote: float = 100.0
    leverage: float = 3.0
    max_concurrent: int = 4
    cb_losses: int = 2
    stop_pct: float = 0.005      # stop اولیه 0.5% (حالت ثابت)
    trail_pct: float = 0.003     # trailing 0.3% (حالت ثابت)
    adaptive: bool = True        # استاپ/trailing بر پایهٔ ATR (سازگار با تایم‌فریم)
    stop_atr_mult: float = 1.5   # stop = ATR% × این
    trail_atr_mult: float = 1.0  # trail = ATR% × این


class RiskEngine:
    def __init__(self, rc: RiskConfig, fee_bps: float, writer=None):
        self.rc = rc
        self.fee_frac = 2 * fee_bps / 10_000
        self.w = writer
        self.positions: List[Position] = []
        self.closed: List[dict] = []
        self.halted = False
        self.halt_until_ts = 0
        self.session_losses = 0
        self.consecutive_losses = 0
        self.events: List[dict] = []

    def _log(self, ev: dict):
        self.events.append(ev)
        if self.w:
            self.w.write(ev)

    @property
    def slots_free(self) -> bool:
        return len(self.positions) < self.rc.max_concurrent

    def on_signal(self, direction: int, price: float, ts: int,
                  model_id: str, confidence: float, atr_pct: float = 0.0):
        # بررسی پایان مهلت خنک‌سازی مدار شکن (Circuit Breaker Cooldown)
        if self.halted:
            if ts >= self.halt_until_ts and self.halt_until_ts > 0:
                self.halted = False
                self.consecutive_losses = 0
                self._log({"type": "resume", "ts": ts, "reason": "cooldown_expired_resuming_trading"})
            else:
                self._log({"type": "reject", "ts": ts, "reason": "halted_circuit_breaker",
                           "model_id": model_id})
                return

        if not self.slots_free:
            self._log({"type": "reject", "ts": ts, "reason": "max_concurrent",
                       "model_id": model_id})
            return

        # جلوگیری از باز کردن پوزیشن متضاد در جهت عکس روی همان نماد
        for p in self.positions:
            if p.direction != direction and p.direction != 0:
                self._log({"type": "reject", "ts": ts, "reason": "opposing_position_exists",
                           "model_id": model_id})
                return

        rc = self.rc
        # استاپ سازگار با نوسان: ATR×ضریب؛ وگرنه درصد ثابت
        if rc.adaptive and atr_pct > 0:
            sp = (atr_pct / 100.0) * rc.stop_atr_mult
            tp = (atr_pct / 100.0) * rc.trail_atr_mult
        else:
            sp, tp = rc.stop_pct, rc.trail_pct
        stop = price * (1 - sp) if direction == 1 else price * (1 + sp)
        qty = rc.trade_size_quote * rc.leverage / price
        pos = Position(model_id, direction, price, qty, rc.trade_size_quote,
                       rc.leverage, stop, price, ts, confidence, tp)
        self.positions.append(pos)
        self._log({"type": "open", "ts": ts, "model_id": model_id,
                   "direction": direction, "entry": price, "qty": round(qty, 6),
                   "size_quote": rc.trade_size_quote, "leverage": rc.leverage,
                   "stop": round(stop, 2), "confidence": confidence,
                   "open_positions": len(self.positions)})

    def tick(self, price: float, ts: int, reversal_detected: bool = False, reversal_reason: str = ""):
        to_close = []
        for p in list(self.positions):
            # به‌روزرسانی high-water و trailing stop
            if p.direction == 1:
                p.high_water = max(p.high_water, price)
                new_stop = p.high_water * (1 - p.trail_pct)
                p.stop = max(p.stop, new_stop)
                if price <= p.stop:
                    to_close.append((p, "stop/trail"))
                elif reversal_detected and price > p.entry * 1.004:
                    to_close.append((p, reversal_reason or "trend_reversal_exit"))
            else:
                p.high_water = min(p.high_water, price)
                new_stop = p.high_water * (1 + p.trail_pct)
                p.stop = min(p.stop, new_stop)
                if price >= p.stop:
                    to_close.append((p, "stop/trail"))
                elif reversal_detected and price < p.entry * 0.996:
                    to_close.append((p, reversal_reason or "trend_reversal_exit"))
        for p, reason in to_close:
            self._close(p, price, ts, reason)

        # مدار شکن هوشمند: اگر ۲ ضرر متوالی رخ دهد، خنک‌سازی ۳۰ دقیقه‌ای اعمال می‌شود (نه قفل ابدی)
        if self.consecutive_losses >= self.rc.cb_losses and not self.halted:
            self.halted = True
            cooldown_ms = 30 * 60 * 1000  # ۳۰ دقیقه خنک‌سازی
            self.halt_until_ts = ts + cooldown_ms
            for p in list(self.positions):
                self._close(p, price, ts, "circuit_breaker_close_all")
            self._log({"type": "halt", "ts": ts,
                       "reason": f"{self.rc.cb_losses} consecutive losses -> cooldown until {ts + cooldown_ms}",
                       "resume_ts": ts + cooldown_ms})

    def _close(self, p: Position, price: float, ts: int, reason: str):
        if p not in self.positions:
            return
        self.positions.remove(p)
        gross = p.direction * (price - p.entry) / p.entry * p.leverage
        net = gross - self.fee_frac
        is_loss = net < 0
        if is_loss:
            self.session_losses += 1
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0  # ریست شدن شمارشگر با معامله سودده

        dollar_pnl = net * p.size_quote
        rec = {"type": "close", "ts": ts, "model_id": p.model_id,
               "direction": p.direction, "entry": p.entry, "exit": price,
               "gross_pct": round(gross * 100, 3), "net_pct": round(net * 100, 3),
               "pnl_usd": round(dollar_pnl, 3),
               "loss": is_loss, "reason": reason,
               "consecutive_losses": self.consecutive_losses,
               "session_losses": self.session_losses,
               "open_positions": len(self.positions)}
        self.closed.append(rec)
        self._log(rec)

    def summary(self) -> dict:
        wins = [c for c in self.closed if not c["loss"]]
        losses = [c for c in self.closed if c["loss"]]
        net_sum = sum(c["net_pct"] for c in self.closed)
        return {"trades": len(self.closed), "wins": len(wins), "losses": len(losses),
                "sum_net_pct": round(net_sum, 3), "halted": self.halted,
                "still_open": len(self.positions)}
