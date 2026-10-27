"""TraderBrain — «نقش معامله‌گر فیوچرز» (rule-based, PAPER only).

این مودول همان «نقش» (role) request‌شده را اجرا می‌کند:
- **فقط با روند торговه**: صعودی → فقط لانگ، نزولی → فقط شورت، رنج → صبر (یا معامله محدۊد).
- **ورود** بر اساس تحریک (pullback به EMA21 یا شکست Donchian با حجم).
- **خروج** با استاپ اولیه، سود (R:R)، تریلینگ استاپ، و *تغییر روند* (exit).
- **مدیریت ریسک**: هر معامله فقط خطر X% از موجودی، حداکثر اهرم، حد ضرر روزانه، مدار شکن.
- **فقط مجازی (PAPER)** — LIVE عمداً پیاده‌سازی نشده؛ بعد از تأیید (validation) متصل می‌شود.

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
    max_leverage: float = 5.0           # حداکثر اهرم
    take_profit_rr: float = 2.0         # نسبت سود:ریسک
    stop_atr_mult: float = 1.5
    trail_atr_mult: float = 1.0
    trail_enabled: bool = True
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
    stop: float
    take: float
    high_water: float
    low_water: float
    open_ts: int
    confidence: float
    regime: str
    reason: str
    open_fee: float = 0.0
    trail_pct: float = 0.0


# ----------------------------------------------------------------------------
# موتور تصمیم‌گیری
# ----------------------------------------------------------------------------
class TraderBrain:
    """نقش معامله‌گر: تصمیم ورود/خروج + مدیریت پوزیشن PAPER."""

    def __init__(self, cfg: TraderConfig, writer=None):
        self.cfg = cfg
        self.fee_frac = 2 * cfg.fee_bps / 10_000
        self.w = writer                       # JsonlWriter برای لاگ معاملات
        self.equity = float(cfg.initial_equity)
        self.positions: List[Position] = []
        self.trades: List[dict] = []
        self.halted = False
        self.halt_until_ts = 0
        self.consecutive_losses = 0
        self.day_start_equity = self.equity
        self.last_regime: Optional[str] = None
        self.cooldown_until: dict = {}

    # -- helpers ------------------------------------------------------------
    def _clamp(self, x: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))

    def has_position(self, symbol: str) -> bool:
        return any(p.symbol == symbol for p in self.positions)

    def _slots_free(self) -> bool:
        return len(self.positions) < self.cfg.max_concurrent

    def _atr_price(self, candles: List[Candle], i: int) -> float:
        """ATR جاری (در واحد قیمت) از indicators.atr (علی)."""
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
        atr_abs = self._atr_price(candles, i)
        if atr_abs <= 0:
            atr_abs = price * 0.004
        bias = regime_bias(regime["regime"])
        rsi = snap.get("rsi", 50.0)
        ema_slow = regime.get("ema_slow", price)
        donch_pos = regime.get("donch_pos", 0.5)
        vol_z = regime.get("vol_z", 0.0)

        side = 0
        trigger = ""
        if bias == 0:
            # رنج: با اشاره range_trade معامله محدۊد، وگرنه صبر
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
            # روند: فقط جهت موافق
            want = 1 if bias == 1 else -1
            entry_mode = self.cfg.entry_mode
            pullback = entry_mode in ("pullback", "both")
            breakout = entry_mode in ("breakout", "both")
            fired = False
            if pullback and abs(price - ema_slow) <= 0.7 * atr_abs:
                # در روند، بازگشت به EMA21
                rsi_ok = (rsi < 60) if want == 1 else (rsi > 40)
                if rsi_ok:
                    fired = True
                    trigger = "روند + بازگشت به EMA21"
            if not fired and breakout:
                # شکست Donchian با حجم
                if (want == 1 and donch_pos > 0.75) or (want == -1 and donch_pos < 0.25):
                    if vol_z > 0.0:
                        fired = True
                        trigger = "روند + شکست Donchian"
            if not fired:
                return {"action": "WAIT", "symbol": sym,
                        "reason": f"روند {regime['regime']}، تحریک ورود هنوز برآورده نشده"}
            side = want

        # سطح‌های ریسک
        stop_dist = atr_abs * self.cfg.stop_atr_mult
        stop_dist = max(stop_dist, price * 0.0012)
        if side == 1:
            entry = price
            stop = entry - stop_dist
            take = entry + stop_dist * self.cfg.take_profit_rr
        else:
            entry = price
            stop = entry + stop_dist
            take = entry - stop_dist * self.cfg.take_profit_rr

        # اندازه‌گیری بر اساس ریسک (1% موجودی) + سقف اهرم
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
            "fee_open": round(fee_open, 4),
            "ts": ts,
        }

    # -- باز/بسته شدن پوزیشن ---------------------------------------------
    def open(self, decision: dict) -> bool:
        if decision["action"] != "ENTER":
            return False
        if self._daily_loss_exceeded():
            return False
        if not self._slots_free():
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
            stop=decision["stop"],
            take=decision["take"],
            high_water=decision["entry"],
            low_water=decision["entry"],
            open_ts=decision["ts"],
            confidence=decision["confidence"],
            regime=decision["regime"],
            reason=decision["reason"],
            open_fee=decision["fee_open"],
            trail_pct=trail_pct,
        )
        self.positions.append(pos)
        self.cooldown_until[decision["symbol"]] = decision["ts"] + \
            self.cfg.cooldown_bars * 60_000
        self._log({"type": "open", **{k: decision[k] for k in
                    ("symbol", "side", "direction", "entry", "qty", "notional",
                     "stop", "take", "confidence", "regime", "reason", "ts")}})
        return True

    def on_candle(self, price: float, ts: int, regime: Optional[dict]) -> List[dict]:
        """مدیریت خروج: استاپ/سود/تریلینگ/تغییر روند + مدار شکن."""
        exits: List[dict] = []
        regime_name = regime["regime"] if regime else None
        if regime_name and regime_name != self.last_regime and self.last_regime is not None:
            # تغییر روند (مثلاً صعودی → نزولی)
            for p in list(self.positions):
                if p.direction == 1 and regime_name == "downtrend":
                    exits.append(self._close(p, price, ts, "regime_change_downtrend"))
                elif p.direction == -1 and regime_name == "uptrend":
                    exits.append(self._close(p, price, ts, "regime_change_uptrend"))
        if regime_name:
            self.last_regime = regime_name

        to_close: List[tuple] = []
        for p in list(self.positions):
            if p.direction == 1:
                p.high_water = max(p.high_water, price)
                if self.cfg.trail_enabled and p.trail_pct > 0:
                    new_stop = p.high_water * (1 - p.trail_pct)
                    p.stop = max(p.stop, new_stop)
                if price <= p.stop:
                    to_close.append((p, "stop_loss"))
                elif price >= p.take:
                    to_close.append((p, "take_profit"))
            else:
                p.low_water = min(p.low_water, price)
                if self.cfg.trail_enabled and p.trail_pct > 0:
                    new_stop = p.low_water * (1 + p.trail_pct)
                    p.stop = min(p.stop, new_stop)
                if price >= p.stop:
                    to_close.append((p, "stop_loss"))
                elif price <= p.take:
                    to_close.append((p, "take_profit"))
        for p, reason in to_close:
            exits.append(self._close(p, price, ts, reason))

        # مدار شکن: ضرر متوالی
        if self.consecutive_losses >= self.cfg.cb_losses and not self.halted:
            self.halted = True
            cooldown_ms = 30 * 60 * 1000
            self.halt_until_ts = ts + cooldown_ms
            for p in list(self.positions):
                self._close(p, price, ts, "circuit_breaker")
            self._log({"type": "halt", "ts": ts,
                       "reason": f"{self.cfg.cb_losses} ضرر متوالی"})
        return exits

    def _close(self, pos: Position, price: float, ts: int, reason: str) -> dict:
        if pos not in self.positions:
            return {}
        self.positions.remove(pos)
        gross = pos.direction * (price - pos.entry) / pos.entry
        net = gross - self.fee_frac
        is_loss = net < 0
        if is_loss:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        pnl = net * pos.notional
        self.equity += pnl
        rec = {"type": "close", "symbol": pos.symbol, "side": pos.direction,
               "entry": pos.entry, "exit": price, "gross_pct": round(gross * 100, 3),
               "net_pct": round(net * 100, 3), "pnl": round(pnl, 3),
               "loss": is_loss, "reason": reason, "regime": pos.regime,
               "confidence": pos.confidence, "ts": ts}
        self.trades.append(rec)
        self._log(rec)
        return rec

    def _log(self, ev: dict):
        if self.w:
            self.w.write(ev)

    def summary(self) -> dict:
        wins = [t for t in self.trades if not t["loss"]]
        losses = [t for t in self.trades if t["loss"]]
        return {
            "trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(self.trades), 3) if self.trades else 0.0,
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
        return "بازپخش دادهٔ CSV واقعی — PAPER؛ هنوز سود واقعی نیست"
    return "دادهٔ مصنوعی — فقط اعتبارسنجی مکانیزم؛ NOT real market"


def run_trader(cfg: TraderConfig) -> int:
    if cfg.data_mode == "synthetic" and not cfg.run_id:
        cfg.run_id = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(cfg.out_dir, exist_ok=True)
    tw = JsonlWriter(os.path.join(cfg.out_dir, f"trader_trades_{cfg.run_id}.jsonl"))
    brain = TraderBrain(cfg, tw)

    params = dict(DEFAULT_PARAMS)
    params["model_version"] = __version__
    regime_params = dict(cfg.regime_params)

    # منبع جریان
    from .auto import SyntheticStream          # إعادة استفاده از شبیه‌ساز
    from .data import csv_candles

    buf: List[Candle] = []
    maxbuf = 300 if cfg.light else 800
    tick = 0
    live_cfg = None
    if cfg.data_mode in ("binance", "bybit"):
        from .config import LabConfig
        live_cfg = LabConfig(symbol=cfg.symbol, timeframe=cfg.timeframe,
                             data_mode=cfg.data_mode)

    print("=" * 68)
    print("  🧠 TraderBrain — نقش معامله‌گر فیوچرز (PAPER)")
    print("=" * 68)
    print(f"📈 {cfg.symbol} • {cfg.timeframe} • {cfg.data_mode} • {_label(cfg)}")
    print(f"💰 موجودی: {cfg.initial_equity} | خطر/معامله: {cfg.risk_per_trade_pct}% "
          f"| اهرم حداکثر: {cfg.max_leverage}x | RR: {cfg.take_profit_rr}")
    print(f"⚙️  ورود trigger: {cfg.entry_mode} | range_trade: {cfg.range_trade} "
          f"| خروج با تغییر روند: {cfg.regime_change_exit}")
    print("-" * 68)

    stream = None
    csv_rows = None
    if cfg.data_mode == "synthetic":
        stream = SyntheticStream(seed=42)
    elif cfg.data_mode == "csv":
        csv_rows = iter(csv_candles(cfg))

    while tick < cfg.max_ticks:
        # دریافت کندل بعدی
        if cfg.data_mode == "synthetic":
            buf.append(stream.next())
        elif cfg.data_mode == "csv":
            try:
                buf.append(next(csv_rows))
            except StopIteration:
                print("پایان فایل CSV.")
                break
        else:  # binance / bybit — فقط کندل بسته
            from .auto import fetch_last_closed as _fetch
            try:
                closed = _fetch(live_cfg)
            except Exception as e:
                print(f"خطای شبکه: {e}")
                closed = None
            if closed is None or (buf and closed.ts == buf[-1].ts):
                import time as _t
                _t.sleep(max(cfg.interval, 1.0))
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

        ts = buf[i].ts
        dec = brain.decide(buf, reg, snap, i, ts)
        if dec["action"] == "ENTER":
            if brain.open(dec):
                print(f"[{tick:4d}] 🟢 {dec['side']} {dec['symbol']} "
                      f"px={dec['entry']:.2f} stop={dec['stop']:.2f} "
                      f"take={dec['take']:.2f} qty={dec['qty']:.6f} "
                      f"({dec['regime']} | {dec['reason']})")
        # مدیریت خروج
        exits = brain.on_candle(buf[i].c, ts, reg)
        for ex in exits:
            tag = "💰" if not ex.get("loss") else "🛡️"
            print(f"[{tick:4d}] {tag} خروج {ex['symbol']} "
                  f"px={ex['exit']:.2f} pnl={ex['pnl']:+.2f} ({ex['reason']})")

    if cfg.data_mode in ("binance", "bybit") and cfg.interval > 0:
        import time as _t
        _t.sleep(0)

    tw.close()
    s = brain.summary()
    print("\n" + "=" * 68)
    print(f"📊 خلاصهٔ TraderBrain: معاملات={s['trades']} سودِ={s['wins']} "
          f"زیان={s['losses']} rate={s['win_rate']:.0%}")
    print(f"💰 موجودی نهایی: {s['equity']} USDT ({s['return_pct']:+.2f}%)")
    print(f"🛑 مدار شکن: {s['halted']} | پوزیشن باز: {s['still_open']}")
    print(f"📄 لاگ: {os.path.join(cfg.out_dir, f'trader_trades_{cfg.run_id}.jsonl')}")
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
    # ریسک / معامله
    p.add_argument("--equity", type=float, default=1000.0)
    p.add_argument("--risk", dest="risk_per_trade_pct", type=float, default=1.0,
                   help="خطر هر معامله، درصد موجودی")
    p.add_argument("--lev", dest="max_leverage", type=float, default=5.0)
    p.add_argument("--rr", dest="take_profit_rr", type=float, default=2.0)
    p.add_argument("--stop-atr", dest="stop_atr_mult", type=float, default=1.5)
    p.add_argument("--trail-atr", dest="trail_atr_mult", type=float, default=1.0)
    p.add_argument("--no-trail", action="store_true")
    p.add_argument("--max-concurrent", type=int, default=3)
    p.add_argument("--daily-loss", dest="daily_loss_limit_pct", type=float, default=3.0)
    p.add_argument("--cb", dest="cb_losses", type=int, default=2)
    p.add_argument("--entry-mode", choices=["pullback", "breakout", "both"], default="pullback")
    p.add_argument("--range-trade", action="store_true", help="در حالت رنج معامله محدود کند")
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
        initial_equity=args.equity,
        risk_per_trade_pct=args.risk_per_trade_pct,
        max_leverage=args.max_leverage,
        take_profit_rr=args.take_profit_rr,
        stop_atr_mult=args.stop_atr_mult,
        trail_atr_mult=args.trail_atr_mult,
        trail_enabled=not args.no_trail,
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
