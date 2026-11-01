"""اتوترید مجازی (PAPER) با انتساب کامل — «این سیگنال از کدام الگو آمد و کدام الگو بستش؟»

**چرا این ماژول:** تا امروز موتور بک‌تست می‌کرد و نتیجه را جمع می‌زد. ولی برای
رصد اعتبار سیگنال‌ها روی بازار واقعی، هر سیگنال باید یک **سند** داشته باشد:

  • از کدام الگوریتم آمد؟ (`trend` + هش دقیقِ پیکربندی)
  • با کدام الگو وارد شد؟ (`breakout` / `pullback` + رژیم + دلیل لایه‌ها)
  • در لحظهٔ ورود چه دید؟ (همهٔ اندیکاتورها، جایگاه قیمت میان قله/دره، ساختار)
  • با کدام قاعده بسته شد؟ (و آیا آن قاعده برای **کم‌کردن ضرر** بوده؟)

بدون این انتساب، سه ماه بعد نمی‌شود فهمید کدام بخش سود داد و کدام ضرر.

**قاعدهٔ طلایی:** این ماژول هیچ منطق معاملهٔ جدیدی ندارد. همان `MTFEngine`
بک‌تست را گام‌به‌گام صدا می‌زند، برای همین یک تست تضمین می‌کند خروجی
«پخش زنده» با «بک‌تست» بیت‌به‌بیت یکی است. هر اختلاف، باگ است.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, fields, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .alignment import align_multi_timeframe
from .autoscan import build_layers
from .config import PRESETS, MTFConfig, load_config
from .data import Candle, tf_to_minutes
from .engine import MTFEngine, Position
from .signals import TFContext

STATE_VERSION = 1

#: انتساب هر قاعدهٔ خروج: (نوع، توضیح فارسی، توضیح انگلیسی، آیا برای کم‌کردن ضرر است؟)
RULE_META: Dict[str, Tuple[str, str, str, bool]] = {
    "stop_loss": ("risk", "حد ضرر اولیه (ATR×ضریب)", "initial stop loss", True),
    "stop_trail": ("risk", "تریلینگ استاپ (ATR×ضریب)", "trailing stop", True),
    "breakeven": ("risk", "انتقال استاپ به نقطهٔ ورود", "stop moved to breakeven", True),
    "giveback": ("risk", "قاعدهٔ افت سود (سود برگشتی)", "profit-giveback rule", True),
    "regime_flip": ("risk", "چرخش تأییدشدهٔ رژیم فیلتر", "confirmed regime flip", True),
    "time_stop": ("time", "سقف زمان نگه‌داری", "max holding bars", False),
    "take_profit": ("profit", "حد سود", "take profit", False),
    "partial_take": ("profit", "برداشت جزئی", "partial take", False),
    "manual": ("manual", "بسته‌شده به‌دست کاربر", "closed manually", False),
    "end_of_data": ("data", "پایان داده", "end of data", False),
}


#: نام فارسی «چرا وارد نشد» — همان شمارنده‌های موتور
VETO_FA = {
    "circuit_breaker": "فیوز ضررهای پیاپی",
    "cooldown": "استراحت بعد از ضرر",
    "daily_loss": "سقف ضرر روزانه",
    "slots": "همهٔ جایگاه‌ها پر بود",
    "hour_filter": "ساعت ممنوع",
    "climax": "شرط climax",
}


def normalize_reason(reason: str) -> str:
    """دلیل خروج موتور → کلید استاندارد. (`stop/trail` و `regime_flip_confirmed_3`)"""
    r = str(reason or "").strip()
    if r in ("stop/trail", "stop_trail"):
        return "stop_trail"
    if r.startswith("regime_flip"):
        return "regime_flip"
    if r.startswith("partial_take"):
        return "partial_take"
    return r or "unknown"


def rule_meta(reason: str) -> dict:
    key = normalize_reason(reason)
    kind, fa, en, risk = RULE_META.get(key, ("other", key, key, False))
    return {"rule": key, "kind": kind, "fa": fa, "en": en, "is_risk_control": risk}


def cfg_digest(overrides: dict) -> str:
    """اثر انگشت پیکربندی — تا سیگنال‌های دو نسخهٔ متفاوت قاطی نشوند."""
    blob = json.dumps(overrides, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------
# سریال‌کردن پوزیشن (تا بین اجراها زنده بماند)
# ---------------------------------------------------------------------------
_SKIP = {"layers", "snap_trigger", "snap_filter", "snap_bias"}


def pos_to_state(pos: Position, keep_path: int = 40) -> dict:
    d = {}
    for f in fields(Position):
        if f.name in _SKIP:
            continue
        d[f.name] = getattr(pos, f.name)
    d["path"] = (pos.path or [])[-keep_path:]
    return d


def pos_from_state(d: dict) -> Position:
    known = {f.name for f in fields(Position)}
    kw = {k: v for k, v in d.items() if k in known}
    kw["path"] = kw.get("path") or []
    return Position(**kw)


# ---------------------------------------------------------------------------
# وضعیت و ژورنال
# ---------------------------------------------------------------------------
def _empty_state() -> dict:
    return {"version": STATE_VERSION, "updated_at": None, "symbols": {},
            "open": [], "equity": None, "peak_equity": None,
            "counters": {"signals": 0, "closed": 0}}

def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    base = _empty_state()
    base.update(st or {})
    return base


def save_state(path: str, state: dict) -> None:
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)          # نوشتن اتمی: قطعی برق، ژورنال را خراب نمی‌کند


def append_jsonl(path: str, rec: dict) -> None:
    """افزودن یک رکورد به ژورنال (JSONL).

    اگر نوشتن قبلی وسط کار قطع شده باشد، فایل با یک خطِ **ناتمام و بدون `\\n`**
    تمام می‌شود؛ در آن حالت رکورد تازه به انتهای همان خطِ خراب می‌چسبد و *هر دو*
    رکورد از دست می‌روند. پس اول مطمئن می‌شویم فایل با `\\n` تمام شده است.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    needs_nl = False
    if os.path.exists(path):
        try:
            with open(path, "rb") as rf:
                rf.seek(0, os.SEEK_END)
                if rf.tell() > 0:
                    rf.seek(-1, os.SEEK_END)
                    needs_nl = rf.read(1) != b"\n"
        except OSError:
            needs_nl = False
    with open(path, "a", encoding="utf-8") as f:
        if needs_nl:
            f.write("\n")
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def read_journal(path: str) -> List[dict]:
    out: List[dict] = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # خط نیمه‌نوشته (قطعی وسط نوشتن) نادیده
    return out


# ---------------------------------------------------------------------------
# وضعیت موتور بین دو اجرا
# ---------------------------------------------------------------------------
#: چرا با «زمان» ذخیره می‌شود و نه شمارهٔ کندل؟ چون در اجرای زنده پنجرهٔ داده
#: می‌لغزد (مثلاً ۲۴۰ روز) و شمارهٔ کندل بین دو اجرا جابه‌جا می‌شود؛ زمانِ کندل
#: تنها شناسهٔ پایدار است.
_ENGINE_KEYS = ("last_filter_dir", "filter_flip_streak", "consecutive_losses",
                "day_key", "day_start_equity", "daily_limit_hit",
                "max_drawdown_pct")


def engine_state(engine: MTFEngine, bars: Sequence) -> dict:
    """وضعیت قاعده‌های سراسری موتور را برای اجرای بعدی ذخیره می‌کند."""
    def bar_ts(idx: int) -> Optional[int]:
        return (bars[idx].low_tf_candle.open_time_ms
                if 0 <= idx < len(bars) else None)

    out = {k: getattr(engine, k) for k in _ENGINE_KEYS}
    out["cooldown_until_ts"] = bar_ts(engine.cooldown_until_bar)
    out["cb_until_ts"] = bar_ts(engine.cb_until_bar)
    # شمارندهٔ «چرا وارد نشد» — لازم برای این‌که سکوتِ الگوریتم هم توضیح داشته باشد
    out["veto_stats"] = dict(engine.veto_stats)
    return out


def _restore_engine(engine: MTFEngine, saved: Optional[dict], bars: Sequence) -> None:
    """بازگرداندن وضعیت موتور؛ هر چیزی که نبود، پیش‌فرضِ سالم می‌گیرد."""
    saved = saved or {}

    def bar_idx(ts) -> int:
        if not ts:
            return -1
        idx = -1
        for k, b in enumerate(bars):
            if b.low_tf_candle.open_time_ms <= int(ts):
                idx = k
            else:
                break
        return idx

    for k in _ENGINE_KEYS:
        if k not in saved or saved[k] is None:
            continue
        cur = getattr(engine, k)
        if isinstance(cur, bool):
            setattr(engine, k, bool(saved[k]))
        elif isinstance(cur, float):
            setattr(engine, k, float(saved[k]))
        else:
            setattr(engine, k, int(saved[k]))
    engine.cooldown_until_bar = bar_idx(saved.get("cooldown_until_ts"))
    engine.cb_until_bar = bar_idx(saved.get("cb_until_ts"))
    if isinstance(saved.get("veto_stats"), dict):
        for k, v in saved["veto_stats"].items():
            try:
                engine.veto_stats[k] = engine.veto_stats.get(k, 0) + int(v)
            except (TypeError, ValueError):
                continue


# ---------------------------------------------------------------------------
# یک گام = دقیقاً همان گام بک‌تست
# ---------------------------------------------------------------------------
def process_bar(engine: MTFEngine, bar, ctxs: Dict[str, TFContext], cfg, i: int,
                on_open: Optional[Callable] = None,
                on_close: Optional[Callable] = None) -> None:
    """بدنهٔ حلقهٔ `run_backtest` برای **یک** کندل.

    چرا کپی شده و از `run_backtest` صدا زده نمی‌شود؟ چون بک‌تست یک حلقهٔ
    یک‌جا است و پخش زنده باید بتواند از وسط شروع کند و بین اجراها متوقف شود.
    وفاداری با تست `live == backtest` تضمین می‌شود، نه با تکرار کد.
    """
    candle = bar.low_tf_candle
    engine._check_daily_limit(candle.open_time_ms)

    info = engine.build_decision(bar, ctxs)
    filt_dir_now = info["filt"].direction

    if filt_dir_now != 0 and filt_dir_now != engine.last_filter_dir:
        engine.filter_flip_streak = 1
    elif filt_dir_now != 0:
        engine.filter_flip_streak += 1
    else:
        engine.filter_flip_streak = 0
    engine.last_filter_dir = (filt_dir_now if filt_dir_now != 0
                              else engine.last_filter_dir)

    # ۱) مدیریت پوزیشن‌های باز
    for pos in list(engine.positions):
        rec = engine.manage_position(pos, candle, i, ctxs, filt_dir_now)
        if rec and on_close:
            on_close(rec, info, pos)

    # ۲) ورود جدید
    d = info["decision"]
    if d.action == "ENTER":
        blocked = None
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
            engine.veto_stats[blocked] = engine.veto_stats.get(blocked, 0) + 1
        else:
            entry_price = candle.close
            pos = engine.open_position(info, ctxs, i, entry_price, candle.open_time_ms)
            if pos and on_open:
                on_open(pos, info)

    engine.equity_curve.append({"ts": candle.open_time_ms, "equity": round(engine.equity, 4)})

    # ۳) آخر دوره: به‌روزرسانی اوج سرمایه
    engine.peak_equity = max(engine.peak_equity, engine.equity)


# ---------------------------------------------------------------------------
# اجراکننده
# ---------------------------------------------------------------------------
class LiveRunner:
    """اجرای گام‌به‌گام روی دادهٔ تازه، با حالت ماندگار و ژورنال انتسابی."""

    def __init__(self, cfg, variant_id: str, variant_label: str, overrides: dict,
                 state_path: str, journal_path: str, lang: str = "fa"):
        self.cfg = cfg
        self.variant_id = variant_id
        self.variant_label = variant_label
        self.overrides = overrides
        self.digest = cfg_digest(overrides)
        self.state_path = state_path
        self.journal_path = journal_path
        self.lang = lang
        self.state = load_state(state_path)
        if self.state.get("equity") is None:
            self.state["equity"] = float(cfg.initial_equity)
            self.state["peak_equity"] = float(cfg.initial_equity)

    # -- انتساب ----------------------------------------------------------
    def _algorithm(self) -> dict:
        return {"id": self.variant_id, "label": self.variant_label,
                "cfg_digest": self.digest,
                "tf": f"{self.cfg.tf_trigger}/{self.cfg.tf_filter}/{self.cfg.tf_bias}",
                "alignment": self.cfg.alignment_version}

    def _open_record(self, pos: Position, info: dict, symbol: str,
                     swing: Optional[float], structure: int, backfilled: bool) -> dict:
        trig = info["trig"]
        return {
            "type": "open",
            "id": f"{symbol}:{self.variant_id}:{pos.open_ts}",
            "ts": pos.open_ts,
            "symbol": symbol,
            "backfilled": backfilled,
            "algorithm": self._algorithm(),
            "entry_pattern": {
                "mode": trig.mode,
                "regime_filter": info["filt"].regime,
                "regime_bias": info["bias"].regime,
                "trigger_reason": trig.reason,
                "decision_reason": info["decision"].reason,
                "confidence": round(float(info["decision"].confidence), 4),
                "score": round(float(info["decision"].score), 4),
            },
            "layers": info["decision"].layers,
            "indicators": info.get("snap_trigger") or {},
            "filter_indicators": info.get("snap_filter") or {},
            "context": {"swing_position": swing, "structure": structure},
            "cost_check": getattr(info["decision"], "cost_check", None),
            "order": {
                "side": "LONG" if pos.direction > 0 else "SHORT",
                "entry": round(pos.entry, 6),
                "stop": round(pos.stop_initial, 6),
                "take": round(pos.take, 6),
                "qty": round(pos.qty, 8),
                "notional": round(pos.notional, 2),
                "risk_amount": round(pos.risk_amount, 2),
                "fee_open": round(pos.open_fee, 4),
            },
        }

    def _close_record(self, rec: dict, symbol: str, open_ts: int) -> dict:
        meta = rule_meta(rec.get("reason"))
        return {
            "type": "close",
            "id": f"{symbol}:{self.variant_id}:{open_ts}:closed",
            "open_id": f"{symbol}:{self.variant_id}:{open_ts}",   # ← پیوند به سیگنال
            "ts": rec.get("ts"),
            "symbol": symbol,
            "algorithm": self._algorithm(),
            "closed_by": meta,
            "result": {
                "exit": rec.get("exit"),
                "pnl": rec.get("pnl"),
                "gross_pnl": rec.get("gross_pnl"),
                "fees": rec.get("fees"),
                "r_multiple": rec.get("r_multiple"),
                "mfe_pct": rec.get("mfe_pct"),
                "mae_pct": rec.get("mae_pct"),
                "bars_held": rec.get("bars_held"),
                "is_win": rec.get("is_win"),
            },
        }

    # -- اجرا ------------------------------------------------------------
    def run_symbol(self, symbol: str, candles: Sequence[Candle],
                   backfill: int = 0, progress: bool = False) -> dict:
        """یک نماد را تا آخرین کندل بسته‌شده جلو می‌برد."""
        cfg = self.cfg
        t_min = tf_to_minutes(cfg.tf_trigger)
        f_min = tf_to_minutes(cfg.tf_filter)
        b_min = tf_to_minutes(cfg.tf_bias) if cfg.bias_enabled else f_min

        layers = build_layers(candles, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                              bias_enabled=cfg.bias_enabled)
        bars = align_multi_timeframe(layers["trigger"], t_min, layers["filter"], f_min,
                                     layers["bias"] if cfg.bias_enabled else None,
                                     b_min if cfg.bias_enabled else None)
        ctxs = {
            "trigger": TFContext(layers["trigger"], cfg, "trigger"),
            "filter": TFContext(layers["filter"], cfg, "filter"),
            "bias": (TFContext(layers["bias"], cfg, "bias") if cfg.bias_enabled
                     else TFContext(layers["filter"], cfg, "filter")),
        }

        engine = MTFEngine(cfg, None, None)
        engine.equity = float(self.state.get("equity") or cfg.initial_equity)
        engine.peak_equity = float(self.state.get("peak_equity") or engine.equity)
        engine.day_start_equity = float(self.state.get("equity") or cfg.initial_equity)
        _restore_engine(engine, self.state.get("engine"), bars)

        # بازگرداندن پوزیشن‌های بازِ همین نماد (شمارهٔ کندل از روی زمانِ ورود)
        keep_open = [p for p in self.state["open"] if p.get("symbol") != symbol]
        mine = [p for p in self.state["open"] if p.get("symbol") == symbol]
        restore_gap = 0
        for d in mine:
            pos = pos_from_state(d)
            pos.symbol = symbol                 # نماد از خودِ ران، نه مقدار پیش‌فرض موتور
            idx = next((k for k, b in enumerate(bars)
                        if b.low_tf_candle.open_time_ms == pos.open_ts), None)
            if idx is None:
                # کندلِ ورود از پنجرهٔ داده بیرون افتاده: پوزیشن را دور نمی‌ریزیم
                # (وگرنه بی‌سروصدا از حسابِ مجازی غیب می‌شود) و از آخرین کندل
                # مدیریتش می‌کنیم؛ وضعیتش با `restore_gap` علامت می‌خورد.
                idx = len(bars) - 1
                restore_gap += 1
            pos.open_bar = max(0, idx)
            engine.positions.append(pos)

        last_ms = int(self.state["symbols"].get(symbol, {}).get("last_bar_ms") or 0)
        fresh = [i for i, b in enumerate(bars) if b.low_tf_candle.open_time_ms > last_ms]
        if not fresh:
            self.state["symbols"].setdefault(symbol, {})["last_bar_ms"] = \
                bars[-1].low_tf_candle.open_time_ms if bars else last_ms
            self.state["open"] = keep_open + [pos_to_state(p) for p in engine.positions]
            self.state["equity"] = engine.equity
            self.state["peak_equity"] = engine.peak_equity
            self.state["engine"] = engine_state(engine, bars)
            return {"symbol": symbol, "new_bars": 0, "opened": 0, "closed": 0,
                    "restore_gap": restore_gap}

        # اولین اجرا: اگر backfill خواسته شده، از انتها به عقب شروع کن
        if last_ms == 0 and backfill > 0:
            start = max(0, len(bars) - backfill)
            fresh = [i for i in fresh if i >= start]
        elif last_ms == 0 and backfill == 0:
            fresh = fresh[-1:]            # فقط آخرین کندل (بدون بازسازی تاریخ)

        opened = closed = 0
        pending_closes: List[dict] = []

        def on_open(pos: Position, info: dict) -> None:
            nonlocal opened
            pos.symbol = symbol        # موتور نماد پیش‌فرض می‌گذارد؛ اینجا اصلاح می‌شود
            idx = pos.open_bar
            sw = _swing_at(layers["trigger"], idx) if idx < len(bars) else None
            rec = self._open_record(pos, info, symbol, sw,
                                    int(info["filt"].direction),
                                    backfilled=(idx < len(bars) - 1))
            append_jsonl(self.journal_path, rec)
            opened += 1

        def on_close(rec: dict, info: dict, pos: Position) -> None:
            nonlocal closed
            pending_closes.append((rec, pos.open_ts))
            closed += 1

        for i in fresh:
            process_bar(engine, bars[i], ctxs, cfg, i, on_open, on_close)

        for rec, open_ts in pending_closes:
            append_jsonl(self.journal_path,
                         self._close_record(rec, symbol, open_ts))

        self.state["symbols"].setdefault(symbol, {})["last_bar_ms"] = \
            bars[fresh[-1]].low_tf_candle.open_time_ms
        self.state["open"] = keep_open + [pos_to_state(p) for p in engine.positions]
        self.state["equity"] = engine.equity
        self.state["peak_equity"] = engine.peak_equity
        self.state["engine"] = engine_state(engine, bars)
        self.state["counters"]["signals"] += opened
        self.state["counters"]["closed"] += closed
        return {"symbol": symbol, "new_bars": len(fresh), "opened": opened,
                "closed": closed, "restore_gap": restore_gap}

    def save(self) -> None:
        save_state(self.state_path, self.state)


def _swing_at(candles: Sequence[Candle], i: int) -> Optional[float]:
    """جایگاه قیمت میان قله/درهٔ تأییدشده — **بدون** نگاه به آینده."""
    from .indicators import swing_ratio
    try:
        return swing_ratio(candles, i)
    except Exception:                                            # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# گزارش رصد اعتبار سیگنال‌ها
# ---------------------------------------------------------------------------
def summarize(journal: Sequence[dict]) -> dict:
    """آمار انتسابی: هر الگوریتم چند سیگنال داد، هر قاعده چند تا را بست."""
    opens = {r["id"]: r for r in journal if r.get("type") == "open"}
    closes = [r for r in journal if r.get("type") == "close"]

    by_algo: Dict[str, dict] = {}
    for o in opens.values():
        a = (o.get("algorithm") or {}).get("id", "?")
        d = by_algo.setdefault(a, {"signals": 0, "closed": 0, "wins": 0,
                                   "pnl": 0.0, "r_sum": 0.0,
                                   "patterns": {}, "label": (o.get("algorithm") or {}).get("label", "")})
        d["signals"] += 1
        m = (o.get("entry_pattern") or {}).get("mode")
        if m:
            d["patterns"][m] = d["patterns"].get(m, 0) + 1

    by_rule: Dict[str, dict] = {}
    per_pattern: Dict[str, dict] = {}
    for c in closes:
        a = (c.get("algorithm") or {}).get("id", "?")
        d = by_algo.setdefault(a, {"signals": 0, "closed": 0, "wins": 0, "pnl": 0.0,
                                   "r_sum": 0.0, "patterns": {}, "label": ""})
        res = c.get("result") or {}
        d["closed"] += 1
        d["wins"] += 1 if res.get("is_win") else 0
        d["pnl"] += float(res.get("pnl") or 0.0)
        d["r_sum"] += float(res.get("r_multiple") or 0.0)

        cb = c.get("closed_by") or {}
        key = cb.get("rule", "?")
        e = by_rule.setdefault(key, {"count": 0, "is_risk_control": cb.get("is_risk_control", False),
                                     "fa": cb.get("fa", ""), "en": cb.get("en", ""),
                                     "pnl": 0.0, "wins": 0})
        e["count"] += 1
        e["pnl"] += float(res.get("pnl") or 0.0)
        e["wins"] += 1 if res.get("is_win") else 0

        # الگوی ورود در برابر الگوی خروج
        o = opens.get(c.get("open_id") or "")
        mode = ((o or {}).get("entry_pattern") or {}).get("mode", "?")
        p = per_pattern.setdefault(mode, {"closed": 0, "pnl": 0.0, "wins": 0,
                                          "risk_closed": 0})
        p["closed"] += 1
        p["pnl"] += float(res.get("pnl") or 0.0)
        p["wins"] += 1 if res.get("is_win") else 0
        if cb.get("is_risk_control"):
            p["risk_closed"] += 1

    for d in by_algo.values():
        n = d["closed"]
        d["win_rate"] = round(d["wins"] / n, 4) if n else None
        d["expectancy_r"] = round(d["r_sum"] / n, 4) if n else None
    for e in by_rule.values():
        e["share"] = round(e["count"] / len(closes), 4) if closes else None

    # آخرین سیگنال‌های بسته‌شده: برای «کدام سیگنال با کدام قاعده بسته شد»
    recent = []
    for c in sorted(closes, key=lambda r: r.get("ts") or 0, reverse=True):
        o = opens.get(c.get("open_id") or "") or {}
        res = c.get("result") or {}
        cb = c.get("closed_by") or {}
        oid = c.get("open_id") or ""
        recent.append({
            "signal_id": oid,
            "symbol": c.get("symbol") or (o.get("symbol")),
            "mode": ((o.get("entry_pattern") or {}).get("mode")),
            "algorithm": (c.get("algorithm") or {}).get("id"),
            "ts": c.get("ts"),
            "entry": (o.get("order") or {}).get("entry"),
            "exit": res.get("exit"),
            "r_multiple": res.get("r_multiple"),
            "pnl": res.get("pnl"),
            "rule": cb.get("rule"),
            "is_risk_control": cb.get("is_risk_control"),
        })

    return {"opens": len(opens), "closes": len(closes),
            "open_now": len(opens) - len(closes),
            "by_algorithm": by_algo, "by_rule": by_rule,
            "by_entry_pattern": per_pattern, "recent": recent}


def render(report: dict, state: dict, lang: str = "fa") -> str:
    fa = lang != "en"
    L: List[str] = []
    w = L.append
    if fa:
        w("# رصد اعتبار سیگنال‌ها — اتوترید مجازی\n")
        w(f"*{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}*\n")
    else:
        w("# Signal credit monitor — paper trading\n")

    eq = float(state.get("equity") or 0.0)
    peak = float(state.get("peak_equity") or eq)
    dd = (eq - peak) / peak * 100 if peak else 0.0
    w(("| سرمایهٔ مجازی | اوج | افت از اوج | سیگنال | بسته | باز |" if fa else
       "| equity | peak | drawdown | signals | closed | open |"))
    w("|---|---:|---:|---:|---:|---:|")
    w(f"| {eq:,.2f}$ | {peak:,.2f}$ | {dd:.2f}% | {report['opens']} | "
      f"{report['closes']} | {report['open_now']} |")
    w("")

    w(("## کدام الگوریتم، چند سیگنال\n" if fa else "## Signals per algorithm\n"))
    w(("| الگوریتم | سیگنال | بسته | نرخ برد | انتظار (R) | سود | الگوی ورود |" if fa else
       "| algorithm | signals | closed | win rate | expectancy R | PnL | entry patterns |"))
    w("|---|---:|---:|---:|---:|---:|---|")
    for a, d in sorted(report["by_algorithm"].items()):
        wr = "—" if d["win_rate"] is None else f"{d['win_rate'] * 100:.1f}%"
        ex = "—" if d["expectancy_r"] is None else f"{d['expectancy_r']:+.3f}"
        pats = ", ".join(f"{k}×{v}" for k, v in (d["patterns"] or {}).items()) or "—"
        w(f"| `{a}` | {d['signals']} | {d['closed']} | {wr} | {ex} | "
          f"{d['pnl']:+.2f}$ | {pats} |")
    w("")

    w(("## کدام قاعده بست — و آیا برای کم‌کردن ضرر بود\n" if fa else
       "## Which rule closed it\n"))
    w(("| قاعده | تعداد | سهم | برای کم‌کردن ضرر؟ | سود |" if fa else
       "| rule | count | share | risk control? | PnL |"))
    w("|---|---:|---:|---:|---:|")
    for k, e in sorted(report["by_rule"].items(), key=lambda kv: -kv[1]["count"]):
        risk = "✅ بله" if e["is_risk_control"] else "—"
        if not fa:
            risk = "✅ yes" if e["is_risk_control"] else "—"
        w(f"| `{k}` | {e['count']} | {(e['share'] or 0) * 100:.0f}% | {risk} | "
          f"{e['pnl']:+.2f}$ |")
    w("")

    if any((report.get("vetoes") or {}).values()):
        w(("## سیگنال‌هایی که رد شدند (چرا وارد نشد)\n" if fa else
           "## Blocked signals (why no entry)\n"))
        w(("| دلیل | تعداد |" if fa else "| reason | count |"))
        w("|---|---:|")
        for k, v in sorted(report["vetoes"].items(), key=lambda kv: -kv[1]):
            if not v:
                continue                      # فقط دلیل‌هایی که واقعاً رخ دادند
            w(f"| `{k}` — {VETO_FA.get(k, k) if fa else k} | {v} |")
        w("")

    if report.get("recent"):
        w(("## آخرین سیگنال‌های بسته‌شده (سیگنال ← قاعده)\n" if fa else
           "## Last closed signals (signal → rule)\n"))
        w(("| سیگنال | نماد | ورود | خروج | R | سود | بست با | ضدضرر؟ |" if fa else
           "| signal | symbol | entry | exit | R | PnL | closed by | risk? |"))
        w("|---|---|---:|---:|---:|---:|---|---|")
        for r_ in report["recent"][:12]:
            sid_ = (r_["signal_id"] or "").replace(":closed", "")
            if r_["symbol"] and sid_.startswith(str(r_["symbol"]) + ":"):
                sid_ = sid_[len(str(r_["symbol"])) + 1:]      # نماد در ستون خودش هست
            rv = "—" if r_["r_multiple"] is None else f"{float(r_['r_multiple']):+.2f}"
            ev = "—" if r_["entry"] is None else f"{float(r_['entry']):g}"
            xv = "—" if r_["exit"] is None else f"{float(r_['exit']):g}"
            pv = "—" if r_["pnl"] is None else f"{float(r_['pnl']):+.2f}$"
            risk = ("✅" if r_["is_risk_control"] else "—")
            w(f"| `{sid_}` | {r_['symbol']} | {ev} | {xv} | {rv} | {pv} | "
              f"`{r_['rule']}` | {risk} |")
        w("")

    if report.get("open_positions"):
        w(("## سیگنال‌های باز (با انتساب)\n" if fa else "## Open signals (attributed)\n"))
        w(("| نماد | جهت | ورود | استاپ | از | الگو | الگوریتم |" if fa else
           "| symbol | side | entry | stop | since | pattern | algorithm |"))
        w("|---|---|---:|---:|---|---|---|")
        for p_ in report["open_positions"]:
            since = time.strftime("%Y-%m-%d %H:%M", time.gmtime((p_["open_ts"] or 0) / 1000))
            w(f"| {p_['symbol']} | {p_['side']} | {p_['entry']} | {p_['stop']} | "
              f"{since} | {p_['mode']} | `{p_['algorithm']}` |")
        w("")

    if report.get("by_entry_pattern"):
        w(("## الگوی ورود در برابر نتیجه\n" if fa else "## Entry pattern vs outcome\n"))
        w(("| الگو | بسته | نرخ برد | سود | با قاعدهٔ ضدضرر بسته شد |" if fa else
           "| pattern | closed | win rate | PnL | closed by a risk rule |"))
        w("|---|---:|---:|---:|---:|")
        for k, v in sorted(report["by_entry_pattern"].items()):
            wr = f"{v['wins'] / v['closed'] * 100:.0f}%" if v["closed"] else "—"
            rs = f"{v['risk_closed']}/{v['closed']}"
            w(f"| `{k}` | {v['closed']} | {wr} | {v['pnl']:+.2f}$ | {rs} |")
        w("")

    if fa:
        w("> این گزارش فقط از ژورنال ساخته می‌شود — یعنی هر عددی که می‌بینید، "
          "به یک سیگنال مشخص با شناسهٔ یکتا وصل است. اگر عددی عجیب بود، "
          "همان شناسه را در `journal.jsonl` جست‌وجو کنید.\n")
    return "\n".join(L) + "\n"


def open_positions_from_journal(journal: Sequence[dict],
                                state: dict) -> List[dict]:
    """سیگنال‌های بازِ فعلی، از حالت (نه از ژورنال — چون حالت منبع حقیقت است)."""
    opens = {r["id"]: r for r in journal if r.get("type") == "open"}
    out = []
    for p in state.get("open") or []:
        sid = f"{p.get('symbol')}:{_variant_of(state)}:{p.get('open_ts')}"
        o = opens.get(sid) or {}
        ep = (o.get("entry_pattern") or {})
        out.append({
            "symbol": p.get("symbol"), "open_ts": p.get("open_ts"),
            "side": "LONG" if (p.get("direction") or 0) > 0 else "SHORT",
            "entry": round(float(p.get("entry") or 0), 6),
            "stop": round(float(p.get("stop_current") or 0), 6),
            "mode": ep.get("mode", "?"),
            "algorithm": (o.get("algorithm") or {}).get("id", _variant_of(state)),
            "signal_id": sid,
        })
    return out


def _variant_of(state: dict) -> str:
    return ((state.get("algorithm") or {}).get("id")) or state.get("variant") or "?"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def default_fetch(symbol: str, tf: str, days: int) -> List[Candle]:
    """کندل‌های عمومی Bybit — فقط کندل‌های **بسته‌شده**."""
    from .bybit_public import fetch_klines_range
    return fetch_klines_range(symbol, tf, days=days, cache_dir="data",
                              progress=False, save_csv=False)


def live_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .autoscan import set_lang, _t
    from .sweep import deliver

    p = argparse.ArgumentParser(
        prog="mtflab live",
        description="اتوترید مجازی: هر سیگنال و هر بستن با انتساب کامل ثبت می‌شود")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--symbols", nargs="+", default=None,
                   help="پیش‌فرض: همان ۲۰ نماد استاندارد پروژه")
    p.add_argument("--variant", default="trend",
                   choices=["trend", "base", "trend_tp", "pullback", "climax"])
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--days", type=int, default=240, help="پنجرهٔ داده برای گرم‌کردن")
    p.add_argument("--backfill", type=int, default=120,
                   help="اولین اجرا: چند کندل گذشته را بازسازی کن (۰ = از همین حالا)")
    p.add_argument("--state", default="results/live/state.json")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--tag", default="")
    p.add_argument("--status", action="store_true", help="فقط وضعیت، بدون شبکه")
    p.add_argument("--offline", action="store_true",
                   help="از کش محلی بخوان، به شبکه نرو")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)
    set_lang(a.lang)

    symbols = a.symbols or _default_symbols()

    if a.status:
        st = load_state(a.state)
        if st.get("equity") is None:      # اولین بار: حساب مجازی پیش‌فرض
            st["equity"] = st["peak_equity"] = float(MTFConfig().initial_equity)
        jr = read_journal(a.journal)
        rep = summarize(jr)
        rep["open_positions"] = open_positions_from_journal(jr, st)
        rep["vetoes"] = ((st.get("engine") or {}).get("veto_stats") or {})
        md = render(rep, st, lang=a.lang)
        print(md)
        return 0

    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=a.tf, tf_filter=a.tf_filter, tf_bias=a.tf_bias,
                  verbose=False, forensics=False, run_id="", symbol="")
    from .autoscan import variants_for
    by_id = {v[0]: v for v in variants_for(a.tf, a.tf_filter, a.tf_bias)}
    if a.variant not in by_id:
        print(_t(f"❌ نسخهٔ ناشناخته. مجاز: {', '.join(sorted(by_id))}",
                 f"❌ unknown variant. allowed: {', '.join(sorted(by_id))}"))
        return 2
    vid, label, overrides = by_id[a.variant]
    cfg = replace(cfg, **overrides)

    runner = LiveRunner(cfg, vid, label, overrides, a.state, a.journal, lang=a.lang)
    runner.state["variant"] = vid
    runner.state["algorithm"] = {"id": vid, "label": label,
                                 "cfg_digest": cfg_digest(overrides)}

    print("=" * 70)
    print(_t(f"اتوترید مجازی · الگوریتم {vid} · {a.tf}/{a.tf_filter}/{a.tf_bias} · "
             f"{len(symbols)} نماد",
             f"PAPER live · algorithm {vid} · {a.tf}/{a.tf_filter}/{a.tf_bias} · "
             f"{len(symbols)} symbols"))
    print("=" * 70)

    fetch_fn: Callable = (lambda sym, tf, days: _from_cache(a.data_dir, sym, tf)
                          if a.offline else default_fetch(sym, tf, days))
    total_new = total_open = total_close = 0
    errors = []
    for n, sym in enumerate(symbols, 1):
        try:
            cs = fetch_fn(sym, a.tf, a.days)
        except Exception as e:                                   # noqa: BLE001
            errors.append((sym, str(e)[:70]))
            print(f"[{n}/{len(symbols)}] {sym}  ❌ {str(e)[:60]}")
            continue
        if not cs or len(cs) < 60:
            print(f"[{n}/{len(symbols)}] {sym}  ⚠️  "
                  + _t("دادهٔ کافی نبود", "not enough candles"))
            continue
        r = runner.run_symbol(sym, cs, backfill=a.backfill)
        total_new += r["new_bars"]
        total_open += r["opened"]
        total_close += r["closed"]
        print(f"[{n}/{len(symbols)}] {sym:11s} bars={r['new_bars']:4d} "
              f"open={r['opened']:2d} close={r['closed']:2d}")
        runner.save()                    # بعد از هر نماد: قطعی، کار از دست نرود

    runner.save()
    jr = read_journal(a.journal)
    rep = summarize(jr)
    rep["open_positions"] = open_positions_from_journal(jr, runner.state)
    rep["vetoes"] = ((runner.state.get("engine") or {}).get("veto_stats") or {})
    md = render(rep, runner.state, lang=a.lang)

    os.makedirs(a.out_dir, exist_ok=True)
    tag = f"_{a.tag}" if a.tag else ""
    md_path = os.path.join(a.out_dir, f"live_report{tag}.md")
    js_path = os.path.join(a.out_dir, f"live_report{tag}.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump({"report": rep, "state": runner.state}, f,
                  ensure_ascii=False, indent=1, default=str)

    print("\n" + "=" * 70)
    print(_t(f"کندل تازه: {total_new} · سیگنال تازه: {total_open} · "
             f"بسته‌شده: {total_close}",
             f"new bars: {total_new} · new signals: {total_open} · "
             f"closed: {total_close}"))
    if errors:
        print(_t(f"⚠️  {len(errors)} نماد خطا داد (بقیه ادامه یافتند)",
                 f"⚠️  {len(errors)} symbols failed (others continued)"))
    print("\n" + md)
    print(f"📄 {os.path.abspath(md_path)}\n🗂 {os.path.abspath(js_path)}")
    print(_t(f"📓 ژورنال: {os.path.abspath(a.journal)}",
             f"📓 journal: {os.path.abspath(a.journal)}"))
    deliver([md_path, js_path], a.out_dir, lang=a.lang)
    return 0


def _from_cache(data_dir: str, symbol: str, tf: str) -> List[Candle]:
    """بازخوانی از کش JSON (برای اجرای آفلاین و تست)."""
    from .autoscan import candles_from_json
    for cand in (os.path.join(data_dir, "json", f"{symbol.lower()}_{tf}.json"),
                 os.path.join(data_dir, f"{symbol.lower()}_{tf}.json")):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                return candles_from_json(json.load(f))
    raise FileNotFoundError(f"no cached {symbol} {tf} bundle")


def _default_symbols() -> List[str]:
    """همان ۲۰ نمادی که همهٔ اجراهای گوشی با آن انجام شد."""
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
            "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
            "TRXUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
            "SUIUSDT", "TONUSDT"]

