"""دفتر سایهٔ خبر — «این سیگنال خبری چقدر معتبر بود؟» (فقط اعتبارسنجی)

**چرا این ماژول:** کاربر می‌گوید گاهی خبری می‌آید و بازار زیر و رو می‌شود؛ در آن
لحظه می‌خواهد یک سیگنال **کاغذی** بزند و بعد ببیند «آن منبع سیگنال» راست می‌گفت
یا نه. این با اتوترید معمولی دو فرق بنیادی دارد:

  ۱) **همان لحظه** زده می‌شود، نه وقتی کندل بسته شد و شرط‌ها جور شد. پس ممکن است
     موتور هیچ سیگنالی نداشته باشد؛ ثبت می‌شود ولی با برچسب «خبری».
  ۲) **نباید روی سیستم اثر بگذارد.** نه سرمایهٔ مجازی را کم می‌کند، نه اسلات
     را اشغال می‌کند، نه در آمار ژورنال و اعتبارسنجی می‌آید، نه در کارنامهٔ
     الگوها. یک دفتر **جدا** با فایل جدا (`results/live/shadow.jsonl`).

**خروج خودکار با همان تنظیمات:** حد ضرر/حد سود/سربه‌سر/تریل/سقف زمانی همه از
همان `MTFConfig` می‌آیند (همان اعدادی که موتور اصلی می‌زند). چیزی که شبیه‌سازی
نمی‌شود: خروج به‌خاطر «برگشت رژیم» یا سیگنال مخالف — چون آن‌ها به وضعیت کامل
لایه‌ها وابسته‌اند. همین‌جا صادقانه در خروجی نوشته می‌شود، تا کسی خیال نکند
عدد سایه دقیقاً همان عدد اتوترید است.

**قاعدهٔ طلایی:** این ماژول هیچ‌چیز را در `state.json`/`journal.jsonl` نمی‌نویسد.
یک تست این را تضمین می‌کند (`tests/test_shadow.py`).
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Candle
from .indicators import atr as atr_series

SHADOW_VERSION = 1
MIN_STOP_PCT = 0.0015        # اگر ATR صفر بود (دادهٔ کم)، حداقل ۰.۱۵٪ فاصله
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
#: برچسب گروهی که هیچ الگویی رأی نداده بود (خبرِ خالی از تأیید الگو)
NONE_VOTE_LABEL = "بدون رأی الگو"


def _now_utc() -> str:
    return time.strftime(TIME_FORMAT, time.gmtime())


def _f(x, n: int = 8) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if abs(v) < 1e-9:
        return 0.0
    return float(f"{v:.{n}g}")


def _side_sign(side: str) -> int:
    s = str(side or "").strip().upper()
    if s in ("BUY", "LONG", "+1"):
        return 1
    if s in ("SELL", "SHORT", "-1"):
        return -1
    raise ValueError("جهت باید BUY/LONG یا SELL/SHORT باشد")


def _candle_dict(c: Candle) -> dict:
    return {"ts": int(c.open_time_ms), "open": _f(c.open), "high": _f(c.high),
            "low": _f(c.low), "close": _f(c.close), "volume": _f(c.volume)}


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ساخت یک سیگنال خبری (فقط ثبت، بدون هیچ اثر روی سیستم)
# ══════════════════════════════════════════════════════════════════════════
def open_trade(symbol: str, side: str, candles: Sequence[Candle], cfg,
               price: Optional[float] = None,
               price_source: str = "last_close",
               note: str = "", tf: str = "4h",
               votes: Optional[dict] = None,
               bias: Optional[int] = None,
               engine_signal: Optional[dict] = None,
               bias_is_reference: bool = False,
               wall_clock_ms: Optional[int] = None) -> dict:
    """یک رکورد «open» برای دفتر سایه بساز.

    :param price: قیمت لحظهٔ خبر. اگر نباشد، بستهٔ آخرین کندل بسته‌شده.
    :param price_source: `ticker` (قیمت زندهٔ بازار) یا `last_close` — در پرونده
        می‌نشیند تا بعداً بدانی عدد از کجا آمده.
    """
    if len(candles) < 30:
        raise ValueError(f"کندل کافی نیست ({len(candles)})")
    sign = _side_sign(side)
    last = candles[-1]
    entry = float(price if price is not None else last.close)
    if entry <= 0:
        raise ValueError("قیمت ورود نامعتبر")

    atr_vals = atr_series(candles, int(getattr(cfg, "trigger_atr_period", 14) or 14))
    atr_last = float(atr_vals[-1] or 0.0)
    atr_use = atr_last if atr_last > 0 else entry * 0.005      # fallback شفاف
    stop_mult = float(getattr(cfg, "stop_atr_mult", 1.5) or 1.5)
    stop_dist = max(stop_mult * atr_use, entry * MIN_STOP_PCT)

    tp_mult = float(getattr(cfg, "take_profit_atr_mult", 0.0) or 0.0)
    take_dist = (tp_mult * atr_use) if 0 < tp_mult < 50 else None

    stop = entry - sign * stop_dist
    take = (entry + sign * take_dist) if take_dist else None

    bar_ts = int(last.open_time_ms)
    rec = {
        "type": "open", "version": SHADOW_VERSION, "shadow": True,
        "id": f"sh{bar_ts}-{symbol.upper()}-{('L' if sign > 0 else 'S')}",
        "created_utc": _now_utc(),
        "wall_clock_ms": int(wall_clock_ms if wall_clock_ms is not None
                             else time.time() * 1000),
        "symbol": symbol.upper(), "tf": tf, "side": "LONG" if sign > 0 else "SHORT",
        "note": str(note or "")[:280],
        "entry": _f(entry), "price_source": price_source,
        "bar_ts": bar_ts,
        "atr": _f(atr_last), "atr_used": _f(atr_use),
        "stop": _f(stop), "take": (_f(take) if take is not None else None),
        "stop_dist": _f(stop_dist), "rr": (_f(take_dist / stop_dist, 3) if take_dist else None),
        "entry_candle": _candle_dict(last),
        "source": {
            "votes": votes or {"available": False, "ids": [], "n": 0},
            "bias": (None if bias is None else
                     ("LONG" if bias > 0 else ("SHORT" if bias < 0 else "UNKNOWN"))),
            "agree": (None if bias in (None, 0) else (bias == sign)),
            "bias_is_reference": bool(bias_is_reference),
            "engine_signal": engine_signal,
        },
    }
    return rec


# ══════════════════════════════════════════════════════════════════════════
#  ۲) بازپخش رویدادها و بستن خودکار با همان تنظیمات
# ══════════════════════════════════════════════════════════════════════════
def replay(events: Sequence[dict]) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """(سیگنال‌های باز، سیگنال‌های بسته) از روی رویدادهای دفتر."""
    opens: Dict[str, dict] = {}
    closes: Dict[str, dict] = {}
    for e in events:
        t = e.get("type")
        if t == "open" and e.get("id"):
            opens[str(e["id"])] = e
        elif t == "close" and e.get("open_id"):
            closes[str(e["open_id"])] = e
    return opens, closes


def _walk_exit(rec: dict, candles: Sequence[Candle], cfg) -> Optional[dict]:
    """کندل‌به‌کندل جلو برو تا حد ضرر/سود/سقف زمانی بخورد.

    ترتیب احتیاطی: اگر در یک کندل هم حد ضرر و هم حد سود لمس شد، **حد ضرر**
    فرض می‌شود (بدبینانه‌ترین حالت). هیچ‌جا از کندلِ ورود استفاده نمی‌شود.
    """
    sign = _side_sign(rec["side"])
    entry = float(rec["entry"])
    stop = float(rec["stop"])
    take = (float(rec["take"]) if rec.get("take") is not None else None)
    bar_ts = int(rec.get("bar_ts") or 0)
    after = [c for c in candles if int(c.open_time_ms) > bar_ts]
    if not after:
        return None

    atr_vals = atr_series(list(candles), int(getattr(cfg, "trigger_atr_period", 14) or 14))
    idx_of = {int(c.open_time_ms): i for i, c in enumerate(candles)}

    be_r = float(getattr(cfg, "breakeven_at_r", 0.0) or 0.0)
    trail_on = bool(getattr(cfg, "trail_enabled", False))
    trail_start = float(getattr(cfg, "trail_start_r", 0.0) or 0.0)
    trail_mult = float(getattr(cfg, "trail_atr_mult", 0.0) or 0.0)
    max_bars = int(getattr(cfg, "max_holding_bars", 0) or 0)

    mfe = 0.0
    mae = 0.0
    for i, c in enumerate(after):
        hi, lo = float(c.high), float(c.low)
        fav = (hi - entry) if sign > 0 else (entry - lo)
        adv = (entry - lo) if sign > 0 else (hi - entry)
        mfe = max(mfe, fav / entry * 100.0)
        mae = max(mae, adv / entry * 100.0)

        # سربه‌سر: وقتی سود به R مشخص رسید، حد ضرر به نقطهٔ ورود منتقل می‌شود
        if be_r > 0 and (fav >= be_r * float(rec["stop_dist"])):
            stop = entry if sign > 0 else entry
        # تریل ATR (فقط اگر روشن و از آستانه گذشته باشد)
        if trail_on and trail_mult > 0:
            j = idx_of.get(int(c.open_time_ms))
            a = float(atr_vals[j] or 0.0) if j is not None else 0.0
            if a > 0 and fav >= trail_start * float(rec["stop_dist"]):
                moved = (hi - trail_mult * a) if sign > 0 else (lo + trail_mult * a)
                stop = max(stop, moved) if sign > 0 else min(stop, moved)

        hit_stop = (lo <= stop) if sign > 0 else (hi >= stop)
        hit_take = False
        if take is not None:
            hit_take = (hi >= take) if sign > 0 else (lo <= take)

        exit_px = None
        reason = ""
        if hit_stop:                                  # احتیاط: اول حد ضرر
            exit_px, reason = stop, "stop"
        elif hit_take:
            exit_px, reason = take, "take"
        elif max_bars > 0 and (i + 1) >= max_bars:
            exit_px, reason = float(c.close), "time_stop"

        if exit_px is None:
            continue

        fee_pct = 2.0 * (float(getattr(cfg, "fee_bps", 5.5)) / 10000.0) * 100.0
        slip_pct = 2.0 * float(getattr(cfg, "slippage_pct", 0.0))
        gross = sign * (exit_px - entry) / entry * 100.0
        net = gross - fee_pct - slip_pct
        stop_dist = float(rec["stop_dist"]) or (entry * MIN_STOP_PCT)
        return {
            "type": "close", "version": SHADOW_VERSION, "shadow": True,
            "id": f"{rec['id']}-c", "open_id": rec["id"],
            "closed_utc": _now_utc(),
            "symbol": rec["symbol"], "side": rec["side"],
            "reason": reason,
            "exit": _f(exit_px),
            "exit_candle": _candle_dict(c),
            "bars_held": i + 1,
            "gross_pct": _f(gross, 4),
            "net_pct": _f(net, 4),
            "fee_pct": _f(fee_pct, 4), "slip_pct": _f(slip_pct, 4),
            "r_multiple": _f(sign * (exit_px - entry) / stop_dist, 3),
            "mfe_pct": _f(mfe, 3), "mae_pct": _f(mae, 3),
            "is_win": bool(net > 0),
            "stop_final": _f(stop),
        }
    return None


def evaluate(events: List[dict], candles_by_symbol: Dict[str, Sequence[Candle]],
             cfg, persist: bool = True) -> Tuple[List[dict], List[dict]]:
    """همهٔ سیگنال‌های باز را با کندل‌های موجود بسنج.

    :return: (ردیف‌های کامل، رکوردهای بستِ تازه‌ساخته‌شده)
    """
    opens, closes = replay(events)
    fresh: List[dict] = []
    rows: List[dict] = []
    for tid, rec in opens.items():
        cs = candles_by_symbol.get(rec.get("symbol", "")) or []
        close_rec = closes.get(tid)
        if close_rec is None and cs:
            close_rec = _walk_exit(rec, cs, cfg)
            if close_rec is not None:
                fresh.append(close_rec)
        row = dict(rec)
        row.pop("type", None)
        if close_rec:
            row.update({k: v for k, v in close_rec.items()
                        if k not in ("type", "open_id", "id")})
            row["status"] = "closed"
            row["close_id"] = close_rec.get("id")
        else:
            last_px = float(cs[-1].close) if cs else None
            row["status"] = "open"
            if last_px:
                sign = _side_sign(rec["side"])
                gross = sign * (last_px - float(rec["entry"])) / float(rec["entry"]) * 100.0
                row["mark"] = _f(last_px)
                row["unrealized_pct"] = _f(gross, 4)
                row["unrealized_r"] = _f(sign * (last_px - float(rec["entry"]))
                                         / (float(rec["stop_dist"]) or 1.0), 3)
        rows.append(row)
    rows.sort(key=lambda r: (-int(r.get("bar_ts") or 0), r.get("symbol", "")))
    rows = rows[:200]
    if persist and fresh:
        for rec in fresh:
            events.append(rec)
    return rows, fresh


# ══════════════════════════════════════════════════════════════════════════
#  ۳) کارنامهٔ منبع: «آن منبع چقدر معتبر بود؟»
# ══════════════════════════════════════════════════════════════════════════
def _stats(rs: Sequence[float]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0, "wins": 0, "win_rate": None, "expectancy_r": None,
                "r_sum": 0.0}
    wins = [r for r in rs if r > 0]
    return {"n": n, "wins": len(wins),
            "win_rate": round(len(wins) / n * 100.0, 1),
            "expectancy_r": round(sum(rs) / n, 3),
            "r_sum": round(sum(rs), 3)}


def scorecard(rows: Sequence[dict], min_n: int = 10) -> dict:
    """کارنامهٔ «منبع»: کل، به‌تفکیک الگوهایی که آن لحظه رأی دادند، و هم‌جهتی با بایاس."""
    closed = [r for r in rows if r.get("status") == "closed"
              and r.get("r_multiple") is not None]
    all_r = [float(r["r_multiple"]) for r in closed]
    _ov = _stats(all_r)
    _ov["verdict"] = _verdict(_ov, min_n)       # حکم همیشه هست، حتی «داده کافی نیست»
    out: dict = {
        "overall": _ov,
        "open_n": sum(1 for r in rows if r.get("status") == "open"),
        "min_n": int(min_n),
        "by_source": [], "by_agreement": [], "by_side": [],
        "note": "",
    }

    by_id: Dict[str, List[float]] = {}
    for r in closed:
        votes = ((r.get("source") or {}).get("votes") or {})
        credited = False
        for p in (votes.get("patterns") or []):
            if p.get("side") and p.get("side") != r.get("side"):
                continue                    # الگویی که جهت مخالف می‌گفت، منبع این سیگنال نیست
            credited = True
            by_id.setdefault(str(p.get("id")), []).append(float(r["r_multiple"]))
        if not credited:
            # سیگنال خبری که هیچ الگویی تأییدش نکرد — این گروه خودش یک یافته است.
            by_id.setdefault(NONE_VOTE_LABEL, []).append(float(r["r_multiple"]))
    for pid, rs in sorted(by_id.items(), key=lambda kv: -len(kv[1])):
        st = _stats(rs)
        st["id"] = pid
        st["verdict"] = _verdict(st, min_n)
        out["by_source"].append(st)

    groups = {"هم‌جهت با بایاس": [], "خلاف بایاس": [], "بایاس نامشخص": []}
    for r in closed:
        agree = (r.get("source") or {}).get("agree")
        key = ("هم‌جهت با بایاس" if agree is True else
               ("خلاف بایاس" if agree is False else "بایاس نامشخص"))
        groups[key].append(float(r["r_multiple"]))
    for k, rs in groups.items():
        st = _stats(rs)
        st["label"] = k
        st["verdict"] = _verdict(st, min_n)
        out["by_agreement"].append(st)

    for side in ("LONG", "SHORT"):
        st = _stats([float(r["r_multiple"]) for r in closed if r.get("side") == side])
        st["side"] = side
        out["by_side"].append(st)

    if "بدون رأی الگو" in by_id:
        out["unvoted"] = _stats(by_id["بدون رأی الگو"])
        out["unvoted"]["verdict"] = _verdict(out["unvoted"], min_n)
    if not closed:
        out["note"] = "هنوز هیچ سیگنال خبری بسته نشده — حکمی در کار نیست."
    elif len(closed) < min_n:
        out["note"] = (f"فقط {len(closed)} سیگنال بسته شده؛ زیر {min_n} حکم "
                       "نمی‌دهیم (قاعدهٔ ازپیش‌نوشتهٔ پروژه).")
    else:
        out["verdict"] = _ov["verdict"]
        out["note"] = "با نمونهٔ کافی می‌شود دربارهٔ اعتبار منبع حرف زد."
    return out


def _verdict(st: dict, min_n: int) -> dict:
    n = int(st.get("n") or 0)
    exp = st.get("expectancy_r")
    if n < int(min_n) or exp is None:
        return {"code": "need_more", "label": "داده کافی نیست"}
    if exp > 0:
        return {"code": "keep", "label": "منبع معتبر"}
    return {"code": "drop", "label": "منبع بی‌اعتبار"}


# ══════════════════════════════════════════════════════════════════════════
#  ۴) دفتر (فایل جدا از ژورنال اصلی)
# ══════════════════════════════════════════════════════════════════════════
class ShadowBook:
    """دفتر سایه: JSONL افزودنی. هیچ‌چیز پاک یا بازنویسی نمی‌شود."""

    def __init__(self, path: str):
        self.path = path

    def events(self) -> List[dict]:
        out: List[dict] = []
        if not os.path.exists(self.path):
            return out
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def append(self, rec: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def book(self, candles_by_symbol: Dict[str, Sequence[Candle]], cfg) -> dict:
        """ردیف‌ها + کارنامه + بستن‌های تازه (همه در همان فایل)."""
        events = self.events()
        rows, fresh = evaluate(events, candles_by_symbol, cfg, persist=False)
        for rec in fresh:
            self.append(rec)
        return {"rows": rows, "fresh_closes": len(fresh),
                "scorecard": scorecard(rows),
                "path": self.path,
                "version": SHADOW_VERSION,
                "created_utc": _now_utc()}

    def close_manual(self, trade_id: str, price: Optional[float] = None,
                     candles: Optional[Sequence[Candle]] = None,
                     cfg=None) -> dict:
        """بستن دستی یک سیگنال سایه (اگر کاربر خودش بخواهد)."""
        opens, closes = replay(self.events())
        rec = opens.get(trade_id)
        if rec is None:
            raise KeyError("سیگنال سایه با این شناسه پیدا نشد")
        if trade_id in closes:
            raise ValueError("این سیگنال قبلاً بسته شده")
        px = float(price if price is not None else (candles[-1].close if candles else 0))
        if px <= 0:
            raise ValueError("قیمت بستن نامعتبر")
        sign = _side_sign(rec["side"])
        entry = float(rec["entry"])
        fee_pct = 2.0 * float(getattr(cfg, "fee_bps", 5.5)) / 10000.0 * 100.0
        slip_pct = 2.0 * float(getattr(cfg, "slippage_pct", 0.0))
        gross = sign * (px - entry) / entry * 100.0
        rec_close = {
            "type": "close", "version": SHADOW_VERSION, "shadow": True,
            "id": f"{trade_id}-c{int(time.time() * 1000)}", "open_id": trade_id,
            "closed_utc": _now_utc(), "symbol": rec["symbol"],
            "side": rec["side"], "reason": "manual", "exit": _f(px),
            "exit_candle": _candle_dict(candles[-1]) if candles else None,
            "bars_held": None, "gross_pct": _f(gross, 4),
            "net_pct": _f(gross - fee_pct - slip_pct, 4),
            "fee_pct": _f(fee_pct, 4), "slip_pct": _f(slip_pct, 4),
            "r_multiple": _f(sign * (px - entry) / (float(rec["stop_dist"]) or 1.0), 3),
            "is_win": bool(gross - fee_pct - slip_pct > 0),
            "stop_final": rec.get("stop"),
        }
        self.append(rec_close)
        return rec_close


# ══════════════════════════════════════════════════════════════════════════
#  ۵) خروجی متنی و CLI
# ══════════════════════════════════════════════════════════════════════════
def render_text(book: dict) -> str:
    sc = book.get("scorecard") or {}
    ov = sc.get("overall") or {}
    lines = ["# دفتر سایهٔ خبر — اعتبار منبع", ""]
    wr = ov.get("win_rate")
    ex = ov.get("expectancy_r")
    lines.append(f"سیگنال بسته‌شده: {ov.get('n', 0)} · باز: {sc.get('open_n', 0)}"
                 f" · نرخ برد: {wr if wr is not None else '—'}٪ · expectancy:"
                 f" {ex if ex is not None else '—'} R")
    if sc.get("note"):
        lines.append(f"_{sc['note']}_")
    lines.append("")
    rows = book.get("rows") or []
    if rows:
        lines.append("| نماد | جهت | ورود | حد ضرر | حد سود | وضعیت | R | % | منبع |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in rows[:20]:
            votes = ((r.get("source") or {}).get("votes") or {}).get("ids") or []
            lines.append(
                f"| {r.get('symbol')} | {r.get('side')} | {r.get('entry')} | "
                f"{r.get('stop')} | {r.get('take') or '—'} | "
                f"{'بسته' if r.get('status') == 'closed' else 'باز'} | "
                f"{r.get('r_multiple', r.get('unrealized_r', '—'))} | "
                f"{r.get('net_pct', r.get('unrealized_pct', '—'))} | "
                f"{', '.join(votes) if votes else '—'} |")
        lines.append("")
    if sc.get("by_source"):
        lines.append("## به تفکیک منبع (الگویی که همان لحظه رأی داد)")
        for st in sc["by_source"]:
            if st["id"] == NONE_VOTE_LABEL:
                continue                      # جداگانه در بخش پایین می‌آید
            lines.append(f"- `{st['id']}`: n={st['n']} · برد {st['win_rate']}٪ · "
                         f"expectancy {st['expectancy_r']} R ⇒ "
                         f"{(st.get('verdict') or {}).get('label')}")
        lines.append("")
    if sc.get("unvoted"):
        st = sc["unvoted"]
        if st.get("n"):
            lines.append("## سیگنال‌هایی که هیچ الگویی تأییدشان نکرد")
            lines.append(f"- n={st['n']} · برد {st['win_rate']}٪ · expectancy "
                         f"{st['expectancy_r']} R ⇒ {(st.get('verdict') or {}).get('label')}")
            lines.append("")
    if sc.get("by_agreement"):
        lines.append("## هم‌جهتی با بایاس")
        for st in sc["by_agreement"]:
            if st["n"]:
                lines.append(f"- {st['label']}: n={st['n']} · برد {st['win_rate']}٪ · "
                             f"expectancy {st['expectancy_r']} R")
        lines.append("")
    lines.append("_این دفتر فقط برای اعتبارسنجی است: نه سرمایه را عوض می‌کند، نه "
                 "اسلات می‌گیرد، نه در آمار اصلی می‌آید._")
    return "\n".join(lines)


def shadow_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from dataclasses import replace

    from .config import load_config
    from .desk import load_universe

    p = argparse.ArgumentParser(
        prog="mtflab shadow",
        description="دفتر سایهٔ خبر: سیگنال خبری کاغذی + کارنامهٔ اعتبار منبع")
    p.add_argument("--book", default="results/live/shadow.jsonl")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h")
    p.add_argument("--symbols", default="")
    p.add_argument("--variant", default="trend",
                   help="همان الگوی داشبورد (base/trend/trend_tp/pullback/climax)")
    p.add_argument("--note", default="")
    p.add_argument("--open", default="", metavar="SYMBOL",
                   help="همین حالا یک سیگنال خبری ثبت کن (جهت با --side)")
    p.add_argument("--side", default="", help="LONG/BUY یا SHORT/SELL")
    p.add_argument("--offline", action="store_true",
                   help="قیمت زنده نگیر؛ بستهٔ آخرین کندل را استفاده کن")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out-dir", default="results")
    args = p.parse_args(argv)

    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, verbose=False, forensics=False, run_id="", symbol="",
                  tf_trigger=args.tf)
    try:                                  # همان overrides الگوی داشبورد
        from .patterns import variants_for
        for vid, _label, ov in variants_for(args.tf, "1d", "1d"):
            if vid == args.variant:
                cfg = replace(cfg, **{k: v for k, v in (ov or {}).items()
                                      if k in cfg.__dataclass_fields__})
                break
    except Exception:                                          # noqa: BLE001
        pass
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None
    uni = load_universe(args.data_dir, args.tf, syms)
    book = ShadowBook(args.book)

    if args.open:
        from .shadow import open_trade as _open            # خودارجاعی امن
        sym = args.open.upper()
        cs = uni.get(sym) or []
        if not cs:
            print(f"داده‌ای برای {sym} در {args.data_dir} نیست.")
            return 2
        side = args.side or "LONG"
        rec = _open(sym, side, cs, cfg, note=args.note, tf=args.tf)
        book.append(rec)
        print(f"✅ سیگنال خبری ثبت شد: {sym} {rec['side']} @ {rec['entry']}"
              f" · حد ضرر {rec['stop']} · حد سود {rec['take']}")

    data = book.book(uni, cfg)
    if args.json:
        os.makedirs(args.out_dir, exist_ok=True)
        path = os.path.join(args.out_dir, "shadow_book.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ {path}")
    print(render_text(data))
    return 0
