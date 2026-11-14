"""V10 Pro — بازگشت به میانگین با تأیید «دو کندل بازگشتی» (BB + RSI + حجم).

## این ماژول چیست

پیاده‌سازی **دقیقِ** پروپوزالی که کاربر آورد (نسخهٔ «V10 Pro»):

| قاعده | مقدار |
|---|---|
| ورود لانگ | بستهٔ کندل قبل < باند پایین · بستهٔ کندل جاری > باند پایین · کندل صعودی · `RSI[i-1] ≤ 30` · `حجم ≥ 1.35×SMA20` · حرکت مورد انتظار ≥ ۰.۳۵٪ |
| ورود شورت | آینهٔ همان با باند بالا و `RSI ≥ 70` |
| حد ضرر | کفِ دو کندل − ۰.۱×ATR (شورت: سقف + ۰.۱×ATR) |
| حد سود | ۲.۵× فاصلهٔ ریسک |
| سپر سربه‌سر | در ۱R سود، استاپ به نقطهٔ ورود (با پوشش هزینه) |
| خروج پویا | بازگشت به باند میانی |
| سقف زمان | ۱۶ کندل |

## سه جا که از پروپوزال فاصله گرفتم (همه به نفع صداقت، نه به نفع عدد)

۱. **ورود واقع‌گرایانه.** پروپوزال با «بستهٔ همان کندل» وارد می‌شود؛ ولی تأییدِ
   الگو فقط **در بسته‌شدن** معلوم می‌شود. پس پیش‌فرض من `entry="next_open"` است
   (پر شدن روی بازِ کندل بعد). نسخهٔ خوش‌بینانه هم موجود است (`entry="close"`)
   و در گزارش کنار هم می‌آید — تا معلوم شود چقدر از سود، محصول همین فرض است.
۲. **ترتیب SL/TP در یک کندل.** با OHLC نمی‌دانیم داخل کندل اول به کدام رسیدیم.
   فرض **بدبینانه**: اگر هم SL و هم TP در یک کندل لمس شدند، **SL** حساب می‌شود.
   (`same_bar="optimistic"` هم برای مقایسه هست.)
۳. **هزینه همیشه کسر می‌شود** (۰.۰۵۵٪ کارمزد + ۰.۰۲٪ اسلیپیج، هر طرف) و در
   گزارش ستون «هزینه به‌عنوان ٪ سود ناخالص» می‌آید.

## دربارهٔ اعداد پروپوزال

«OOS +۰.۶۵٪ در هر پنجره، شارپ ۱.۲۵، ۷۹ معامله» — این اعداد **ورودی** هستند، نه
یافتهٔ ما. تا وقتی با کد خودمان روی دادهٔ Bybit بازتولید نشوند، در گزارش‌ها با
برچسب «ادعای پروپوزال، تأیید نشده» می‌آیند.

## اجرا

```
python3 -m mtflab v10 --download --days 365          # بک‌تست روی دادهٔ واقعی
python3 -m mtflab v10 --compare                      # مقایسه با الگوهای MTF
python3 -m mtflab v10 --proximity                    # چقدر به سیگنال نزدیک‌ایم
```
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Sequence

from . import indicators as ind
from .data import Candle, tf_to_minutes

VERSION = "1.0"

#: پارامترهای «ثابتِ» پروپوزال (همان JSON که کاربر داد).
PARAMS: Dict[str, float] = {
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "volume_multiplier": 1.35,
    "bb_period": 20,
    "bb_std": 2.0,
    "atr_period": 14,
    "rr_ratio": 2.5,
    "atr_buffer": 0.1,
    "time_stop_bars": 16,
    "bb_mid_exit": True,         # خروج پویا در باند میانی (کلید مقایسه)
    "min_reward_pct": 0.35,      # ٪ — فیلتر هزینهٔ پروپوزال
    "fee_rate": 0.00055,         # هر طرف
    "slippage": 0.0002,          # هر طرف
}

EXIT_FA = {"TP": "حد سود", "SL": "حد ضرر", "BE": "سربه‌سر",
           "BB_MID": "بازگشت به میانگین", "TIME": "سقف زمان",
           "END": "پایان داده"}


# ══════════════════════════════════════════════════════════════════════════
#  سیگنال (علی: فقط کندل i-1 و i)
# ══════════════════════════════════════════════════════════════════════════
def _sma(vals: Sequence[float], period: int) -> List[Optional[float]]:
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    if n < period:
        return out
    s = sum(vals[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += vals[i] - vals[i - period]
        out[i] = s / period
    return out


def _arrays(candles: Sequence[Candle], p: Dict[str, float]) -> dict:
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]
    bb = ind.bollinger(closes, int(p["bb_period"]), float(p["bb_std"]))
    return {
        "closes": closes,
        "vols": vols,
        "bb": bb,
        "rsi": ind.rsi(closes, int(p["atr_period"])),
        "atr": ind.atr(candles, int(p["atr_period"])),
        "vol_sma": _sma(vols, 20),
    }


def signal_at(candles: Sequence[Candle], i: int, p: Optional[Dict] = None,
              arr: Optional[dict] = None) -> Optional[dict]:
    """سیگنال در کندل `i` یا `None`. فقط از کندل‌های `i-1` و `i` می‌خواند."""
    p = dict(PARAMS, **(p or {}))
    if i < 1 or i >= len(candles):
        return None
    a = arr or _arrays(candles, p)
    bb, rsi, atr, vol_sma = a["bb"], a["rsi"], a["atr"], a["vol_sma"]
    if i - 1 >= len(bb) or bb[i]["lower"] is None or bb[i - 1]["lower"] is None:
        return None
    if rsi[i - 1] is None or atr[i] is None or atr[i] <= 0:
        return None
    if vol_sma[i] is None or vol_sma[i] <= 0:
        return None

    cur, prev = candles[i], candles[i - 1]
    vol_ok = cur.volume >= float(p["volume_multiplier"]) * vol_sma[i]
    if not vol_ok:
        return None

    cost_side = float(p["fee_rate"]) + float(p["slippage"])

    # ── LONG ────────────────────────────────────────────────────────────
    if (prev.close < bb[i - 1]["lower"]
            and cur.close > bb[i]["lower"]
            and cur.close > cur.open
            and rsi[i - 1] <= float(p["rsi_oversold"])):
        entry = cur.close * (1.0 + cost_side)
        pattern_low = min(prev.low, cur.low)
        sl = pattern_low - float(p["atr_buffer"]) * atr[i]
        risk = entry - sl
        if risk > 0:
            reward = risk * float(p["rr_ratio"])
            if (reward / cur.close) * 100.0 >= float(p["min_reward_pct"]):
                return {"side": "LONG", "i": i, "ts": cur.open_time_ms,
                        "entry": entry, "sl": sl, "tp": entry + reward,
                        "risk": risk, "rr": float(p["rr_ratio"]),
                        "bb_mid": bb[i]["mid"], "atr": atr[i],
                        "rsi_prev": rsi[i - 1], "vol_ratio": cur.volume / vol_sma[i]}

    # ── SHORT ───────────────────────────────────────────────────────────
    if (prev.close > bb[i - 1]["upper"]
            and cur.close < bb[i]["upper"]
            and cur.close < cur.open
            and rsi[i - 1] >= float(p["rsi_overbought"])):
        entry = cur.close * (1.0 - cost_side)
        pattern_high = max(prev.high, cur.high)
        sl = pattern_high + float(p["atr_buffer"]) * atr[i]
        risk = sl - entry
        if risk > 0:
            reward = risk * float(p["rr_ratio"])
            if (reward / cur.close) * 100.0 >= float(p["min_reward_pct"]):
                return {"side": "SHORT", "i": i, "ts": cur.open_time_ms,
                        "entry": entry, "sl": sl, "tp": entry - reward,
                        "risk": risk, "rr": float(p["rr_ratio"]),
                        "bb_mid": bb[i]["mid"], "atr": atr[i],
                        "rsi_prev": rsi[i - 1], "vol_ratio": cur.volume / vol_sma[i]}
    return None


def scan_signals(candles: Sequence[Candle],
                 p: Optional[Dict] = None) -> List[dict]:
    """همهٔ سیگنال‌های یک سری — اندیکاتورها **یک‌بار** حساب می‌شوند.

    چرا این تابع لازم است: `signal_at` بدون `arr` هر بار همهٔ اندیکاتورها را از نو
    می‌سازد (O(n²)). در حلقهٔ بک‌تست مشکلی نیست چون `arr` می‌دهیم، ولی هر مصرف‌کنندهٔ
    بیرونی باید از این تابع استفاده کند وگرنه روی ۴۰۰۰ کندل دقیقه‌ها طول می‌کشد.
    """
    p = dict(PARAMS, **(p or {}))
    arr = _arrays(candles, p)
    out: List[dict] = []
    for i in range(1, len(candles)):
        s = signal_at(candles, i, p, arr)
        if s:
            out.append(s)
    return out


def proximity(candles: Sequence[Candle], p: Optional[Dict] = None) -> Optional[dict]:
    """چقدر به سیگنال نزدیکیم (۰..۱۰۰ برای لانگ و شورت) + تفکیک شرط‌ها.

    فرمول همان پروپوزال است؛ فقط با اندیکاتورهای خودمان و **بدون** نگاه به آینده.
    """
    p = dict(PARAMS, **(p or {}))
    if len(candles) < 30:
        return None
    a = _arrays(candles, p)
    i = len(candles) - 1
    bb, rsi, vol_sma, atr = a["bb"], a["rsi"], a["vol_sma"], a["atr"]
    price = a["closes"][i]
    if bb[i]["lower"] is None or rsi[i] is None or not vol_sma[i]:
        return None
    vol_ratio = (a["vols"][i] / vol_sma[i]) if vol_sma[i] else 0.0

    def _near_band(dist_pct: float) -> float:
        if dist_pct <= 0:
            return 100.0
        return max(0.0, 100.0 - dist_pct * 20_000.0)     # ۰.۵٪ ⇒ صفر

    lo = bb[i]["lower"]
    up = bb[i]["upper"]
    long_c = {
        "نزدیک باند پایین": _near_band((price - lo) / price * 100.0),
        "RSI اشباع فروش": (100.0 if rsi[i] <= p["rsi_oversold"] else
                          max(0.0, 100.0 - (rsi[i] - p["rsi_oversold"]) / 15.0 * 100.0)),
        "جهش حجم": min(100.0, (vol_ratio / p["volume_multiplier"]) * 100.0),
        "الگوی دو کندل": _pattern_score(candles, a, i, "LONG"),
    }
    short_c = {
        "نزدیک باند بالا": _near_band((up - price) / price * 100.0),
        "RSI اشباع خرید": (100.0 if rsi[i] >= p["rsi_overbought"] else
                           max(0.0, 100.0 - (p["rsi_overbought"] - rsi[i]) / 15.0 * 100.0)),
        "جهش حجم": long_c["جهش حجم"],
        "الگوی دو کندل": _pattern_score(candles, a, i, "SHORT"),
    }
    ready = signal_at(candles, i, p, a)
    return {
        "symbol": None,
        "price": round(price, 6),
        "rsi": round(rsi[i], 2),
        "vol_ratio": round(vol_ratio, 3),
        "bb_upper": round(up, 6), "bb_mid": round(bb[i]["mid"], 6),
        "bb_lower": round(lo, 6), "atr": (round(atr[i], 6) if atr[i] else None),
        "long_score": round(sum(long_c.values()) / 4.0, 1),
        "short_score": round(sum(short_c.values()) / 4.0, 1),
        "long_breakdown": {k: round(v, 1) for k, v in long_c.items()},
        "short_breakdown": {k: round(v, 1) for k, v in short_c.items()},
        "signal": (None if not ready else
                   {"side": ready["side"], "entry": round(ready["entry"], 6),
                    "sl": round(ready["sl"], 6), "tp": round(ready["tp"], 6)}),
    }


def _pattern_score(candles: Sequence[Candle], a: dict, i: int, side: str) -> float:
    bb = a["bb"]
    if i < 1 or bb[i - 1]["lower"] is None:
        return 0.0
    prev, cur = candles[i - 1], candles[i]
    if side == "LONG":
        if prev.close < bb[i - 1]["lower"] and cur.close > bb[i]["lower"] and cur.close > cur.open:
            return 100.0
        return 50.0 if prev.close < bb[i - 1]["lower"] else 0.0
    if prev.close > bb[i - 1]["upper"] and cur.close < bb[i]["upper"] and cur.close < cur.open:
        return 100.0
    return 50.0 if prev.close > bb[i - 1]["upper"] else 0.0


# ══════════════════════════════════════════════════════════════════════════
#  بک‌تست
# ══════════════════════════════════════════════════════════════════════════
def backtest(candles: Sequence[Candle], p: Optional[Dict] = None,
             entry: str = "next_open", same_bar: str = "pessimistic",
             initial_equity: float = 1000.0, risk_pct: float = 1.0,
             symbol: str = "") -> dict:
    """شبیه‌سازی کامل قواعد پروپوزال روی یک نماد.

    :param entry: `next_open` (پیش‌فرض، واقع‌گرا) یا `close` (مثل پروپوزال)
    :param same_bar: `pessimistic` (SL اول) یا `optimistic` (TP اول)
    """
    p = dict(PARAMS, **(p or {}))
    arr = _arrays(candles, p)
    cost_side = float(p["fee_rate"]) + float(p["slippage"])
    trades: List[dict] = []
    equity = float(initial_equity)
    eq_curve = [equity]
    pos: Optional[dict] = None
    i = 1
    n = len(candles)
    # کندلی که همین حالا از آن خارج شدیم؛ روی آن دوباره وارد نمی‌شویم
    # (وگرنه در حالت entry="close" حلقه بی‌نهایت می‌شد)
    no_entry_i = -1

    while i < n:
        if pos is None:
            if i == no_entry_i:
                i += 1
                continue
            sig = signal_at(candles, i, p, arr)
            if not sig:
                i += 1
                continue
            if entry == "close":
                fill = sig["entry"]                       # همان چیزی که پروپوزال می‌گوید
                open_i = i
            else:
                if i + 1 >= n:
                    break
                open_i = i + 1
                px = candles[open_i].open
                fill = px * (1.0 + cost_side) if sig["side"] == "LONG" \
                    else px * (1.0 - cost_side)
            if sig["side"] == "LONG":
                risk = fill - sig["sl"]
                tp = fill + risk * float(p["rr_ratio"])
            else:
                risk = sig["sl"] - fill
                tp = fill - risk * float(p["rr_ratio"])
            if risk > 0:
                pos = {"side": sig["side"], "entry": fill, "sl": sig["sl"],
                       "tp": tp, "risk": risk, "be": False, "bar": open_i,
                       "sig_i": i, "bb_mid": sig["bb_mid"],
                       "signal": sig}
                # کندلِ ورود خودش هم باید بررسی شود: ممکن است همان کندل حد ضرر
                # یا حد سود را لمس کند. (این باگ قبلاً یک کندل را رد می‌کرد.)
                i = open_i
            else:
                i += 1
                continue

        c = candles[i]
        hit: Optional[str] = None
        px: Optional[float] = None
        long = pos["side"] == "LONG"

        # ۱) حد ضرر (بدبینانه: قبل از حد سود چک می‌شود)
        sl_hit = (c.low <= pos["sl"]) if long else (c.high >= pos["sl"])
        tp_hit = (c.high >= pos["tp"]) if long else (c.low <= pos["tp"])
        if sl_hit and tp_hit and same_bar == "optimistic":
            sl_hit, tp_hit = False, True
        if sl_hit:
            hit, px = ("BE" if pos["be"] else "SL"), pos["sl"]
        elif tp_hit:
            hit, px = "TP", pos["tp"]
        elif p["bb_mid_exit"]:
            # ۲) خروج پویا در باند میانی — این خروج بردها را «سقف‌دار» می‌کند،
            # پس با `bb_mid_exit=False` می‌شود فهمید چه قدر سود را می‌بلعد.
            mid = arr["bb"][i]["mid"]
            if mid is not None:
                if (long and c.high >= mid) or ((not long) and c.low <= mid):
                    hit, px = "BB_MID", mid
        # ۳) سپر سربه‌سر
        if hit is None and not pos["be"]:
            fav = ((c.high - pos["entry"]) if long else (pos["entry"] - c.low))
            if fav >= pos["risk"]:
                pos["be"] = True
                pos["sl"] = (pos["entry"] * (1.0 + cost_side * 2) if long
                             else pos["entry"] * (1.0 - cost_side * 2))
        # ۴) سقف زمان
        if hit is None and (i - pos["bar"]) >= int(p["time_stop_bars"]):
            hit, px = "TIME", c.close
        if hit is None and i == n - 1:
            hit, px = "END", c.close

        if hit:
            exit_px = float(px)
            gross = ((exit_px - pos["entry"]) if long
                     else (pos["entry"] - exit_px)) / pos["entry"] * 100.0
            fees_pct = 2.0 * cost_side * 100.0          # ورود و خروج
            net_pct = gross - fees_pct
            # حجم طوری که فاصلهٔ ورود→استاپ دقیقاً risk_pct از سرمایه باشد
            qty = (equity * float(risk_pct) / 100.0) / pos["risk"]
            pnl = (exit_px - pos["entry"]) * qty if long else (pos["entry"] - exit_px) * qty
            pnl -= (pos["entry"] * qty) * fees_pct / 100.0
            r_mult = (net_pct / 100.0) * pos["entry"] / pos["risk"]
            equity += pnl
            eq_curve.append(round(equity, 2))
            trades.append({
                "symbol": symbol, "side": pos["side"],
                "entry_ts": candles[pos["bar"]].open_time_ms,
                "exit_ts": c.open_time_ms,
                "entry": round(pos["entry"], 6), "exit": round(exit_px, 6),
                "sl_initial": round(pos["signal"]["sl"], 6),
                "tp": round(pos["tp"], 6),
                "reason": hit, "reason_fa": EXIT_FA[hit],
                "bars": i - pos["bar"], "be": pos["be"],
                "gross_pct": round(gross, 4), "fees_pct": round(fees_pct, 4),
                "net_pct": round(net_pct, 4), "r": round(r_mult, 4),
                "pnl": round(pnl, 4), "equity": round(equity, 2),
                "is_win": pnl > 0,
            })
            pos = None
            no_entry_i = i
            i += 1
            continue
        i += 1

    return {"symbol": symbol, "trades": trades, "equity": eq_curve[-1],
            "equity_curve": eq_curve, "params": p, "entry": entry,
            "same_bar": same_bar, "risk_pct": risk_pct,
            "open_at_end": 1 if pos else 0}


def summarize(res: dict) -> dict:
    """سنجه‌های استاندارد پروژه (تا با الگوهای MTF قابل مقایسه باشد)."""
    ts = res.get("trades") or []
    rs = [t["r"] for t in ts]
    wins = [t for t in ts if t["pnl"] > 0]
    losses = [t for t in ts if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    eq = res.get("equity_curve") or [0]
    if len(eq) < 2 and ts:
        # چند نماد = چند منحنی جدا؛ برای افتِ «همه با هم» منحنی را از pnl می‌سازیم
        eq = [eq[0]]
        for t in sorted(ts, key=lambda x: x.get("exit_ts") or 0):
            eq.append(eq[-1] + float(t.get("pnl") or 0.0))
    peak, dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        dd = min(dd, v - peak)
    fees = sum(abs(t["fees_pct"]) for t in ts)
    gross_pct = sum(t["gross_pct"] for t in ts)
    by_reason: Dict[str, int] = {}
    for t in ts:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
    return {
        "n": len(ts),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(ts) * 100.0) if ts else None,
        "expectancy_r": (sum(rs) / len(rs)) if rs else None,
        "r_sum": round(sum(rs), 3) if rs else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "avg_win_r": (sum(t["r"] for t in wins) / len(wins)) if wins else None,
        "avg_loss_r": (sum(t["r"] for t in losses) / len(losses)) if losses else None,
        "net_pct": round(sum(t["net_pct"] for t in ts), 3) if ts else 0.0,
        "fees_pct_total": round(fees, 3),
        "fee_share": (round(fees / gross_pct * 100.0, 1)
                      if gross_pct > 0 else None),
        "max_dd_pct": round(dd / eq[0] * 100.0, 2) if eq and eq[0] else None,
        "by_reason": by_reason,
        "avg_bars": (round(sum(t["bars"] for t in ts) / len(ts), 1) if ts else None),
    }


# ══════════════════════════════════════════════════════════════════════════
#  مقایسه با الگوهای MTF موجود
# ══════════════════════════════════════════════════════════════════════════
def compare_with_mtf(universe: Dict[str, Sequence[Candle]], tf: str = "15m",
                     risk_pct: float = 1.0, variant: str = "trend") -> dict:
    """V10 Pro را با موتور MTF روی **همان داده** می‌سنجد.

    هر دو با همان هزینه و همان سرمایه. خروجی برای پاسخ به «کدام الگو بهتر
    عمل می‌کند» است — نه برای انتخاب بهترین و اعلام برنده؛ نمونه و دروازه لازم است.
    """
    v10_trades: List[dict] = []
    for sym, cs in (universe or {}).items():
        r = backtest(cs, entry="next_open", risk_pct=risk_pct, symbol=sym)
        v10_trades.extend(r["trades"])
    v10 = summarize({"trades": v10_trades,
                     "equity_curve": [1000.0]})
    v10["n"] = len(v10_trades)

    mtf = None
    try:
        from dataclasses import replace
        from .config import MTFConfig
        from .engine import run_backtest
        from .data import build_layers
        from .patterns import variants_for
        from .stats import metrics

        cfg = MTFConfig(tf_trigger=tf, tf_filter=tf, tf_bias=tf, bias_enabled=False)
        for vid, _label, ov in variants_for(tf, tf, tf) or []:
            if vid == variant:
                for k, v in (ov or {}).items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
                break
        rows: List[dict] = []
        for sym, cs in (universe or {}).items():
            layers = build_layers(cs, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                                  bias_enabled=cfg.bias_enabled)
            res = run_backtest(replace(cfg, symbol=sym), layers)
            rows.extend(res.get("trades") or [])
        # `metrics` روی «پوزیشن» کار می‌کند، نه لگ‌های خام؛ تبدیل لازم است.
        try:
            from .stats import positions_from_trades
            pos: List[dict] = []
            for sym, cs in (universe or {}).items():
                layers = build_layers(cs, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                                      bias_enabled=cfg.bias_enabled)
                res = run_backtest(replace(cfg, symbol=sym), layers)
                pos.extend(positions_from_trades(res.get("trades") or [],
                                                 layers["trigger"]))
            agg = metrics(pos)
        except Exception:                                          # noqa: BLE001
            agg = metrics(rows)
        mtf = {"n": len(rows),
               "win_rate": (None if agg.get("win_rate") is None
                            else agg["win_rate"] * 100.0),
               "expectancy_r": agg.get("expectancy_r"),
               "profit_factor": agg.get("profit_factor"),
               "net_pct": agg.get("pnl"),
               "by_reason": {}}
    except Exception as e:                                         # noqa: BLE001
        mtf = {"error": f"{type(e).__name__}: {str(e)[:140]}"}

    return {"v10": v10, "mtf": mtf, "variant": variant, "tf": tf,
            "symbols": sorted(universe or {}),
            "note": ("مقایسه روی همان داده و همان هزینه است، ولی **حکم** نمی‌دهد؛ "
                     "برای حکم: n کافی + تقسیم بیرون‌نمونه + دروازهٔ ازپیش‌نوشته.")}


def _provenance(data_dir: str, tf: str, symbols: Sequence[str]) -> dict:
    """منبع و بازهٔ دادهٔ کش‌شده — تا هیچ‌وقت دادهٔ ساختگی با بازار واقعی قاطی نشود."""
    jdir = os.path.join(data_dir, "json")
    srcs, starts, ends, total = set(), [], [], 0
    for sym in symbols:
        fp = os.path.join(jdir, f"{sym.lower()}_{tf}.json")
        try:
            with open(fp, encoding="utf-8") as f:
                meta = (json.load(f) or {}).get("meta") or {}
        except (OSError, ValueError):
            continue
        src = meta.get("source")
        if not src and meta.get("base_url"):
            src = "bybit (base_url ثبت‌شده)"
        srcs.add(str(src or "unlabeled"))
        if meta.get("start"):
            starts.append(str(meta["start"]))
        if meta.get("end"):
            ends.append(str(meta["end"]))
        try:
            total += int(meta.get("n") or 0)
        except (TypeError, ValueError):
            pass
    return {"sources": sorted(srcs), "start": min(starts) if starts else None,
            "end": max(ends) if ends else None, "bars": total,
            "labeled": bool(srcs) and "unlabeled" not in srcs}


def render(rep: dict, lang: str = "fa") -> str:
    s = rep["summary"]
    L = ["# V10 Pro — بازگشت به میانگین (BB + RSI + حجم)\n"]
    L.append(f"*{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}* · "
             f"نماد `{rep.get('symbol')}` · تایم‌فریم `{rep.get('tf')}` · "
             f"ورود `{rep['entry']}` · فرض روبارِ هم‌کندل `{rep['same_bar']}`\n")
    d = rep.get("data") or {}
    if d:
        src = "، ".join(d.get("sources") or []) or "نامشخص"
        flag = "" if d.get("labeled") else "  ← ⚠️ منبع برچسب ندارد"
        L.append(f"داده: {d.get('bars')} کندل · `{d.get('start')}` → `{d.get('end')}` · "
                 f"منبع: **{src}**{flag}\n")
    L.append("> اعداد پروپوزال (OOS +۰.۶۵٪، شارپ ۱.۲۵) **ادعای تأییدنشده** است. "
             "آنچه این‌جا می‌آید نتیجهٔ اجرای خودمان روی دادهٔ موجود است.\n")
    L.append("## سنجه‌ها\n")
    L.append("| سنجه | مقدار |")
    L.append("|---|---:|")
    L.append(f"| معامله | {s['n']} |")
    L.append(f"| برد / باخت | {s['wins']} / {s['losses']} |")
    L.append(f"| نرخ برد | {_p(s['win_rate'], 1, '٪')} |")
    L.append(f"| expectancy | **{_p(s['expectancy_r'], 3, 'R')}** |")
    L.append(f"| جمع R | {s['r_sum']}R |")
    L.append(f"| ضریب سود | {_p(s['profit_factor'], 2)} |")
    L.append(f"| میانگین برد / باخت | {_p(s['avg_win_r'], 2, 'R')} / {_p(s['avg_loss_r'], 2, 'R')} |")
    L.append(f"| سود خالص | {_p(s['net_pct'], 2, '٪')} |")
    L.append(f"| هزینهٔ کل | {s['fees_pct_total']}٪ |")
    L.append(f"| سهم هزینه از سود ناخالص | {_p(s['fee_share'], 1, '٪')} |")
    L.append(f"| بیشترین افت | {_p(s['max_dd_pct'], 2, '٪')} |")
    L.append(f"| میانگین عمر معامله | {_p(s['avg_bars'], 1, ' کندل')} |")
    L.append("")
    if s["by_reason"]:
        L.append("## با چه قاعده‌ای بسته شدند\n")
        L.append("| قاعده | تعداد |")
        L.append("|---|---:|")
        for k, v in sorted(s["by_reason"].items(), key=lambda kv: -kv[1]):
            L.append(f"| {EXIT_FA.get(k, k)} | {v} |")
        L.append("")
    if rep.get("alternative"):
        alt = rep["alternative"]
        L.append("## اگر با بستهٔ همان کندل وارد می‌شدیم (فرض پروپوزال)\n")
        L.append("| ورود | معامله | expectancy | نرخ برد |")
        L.append("|---|---:|---:|---:|")
        L.append(f"| `next_open` (واقع‌گرا) | {s['n']} | {_p(s['expectancy_r'], 3, 'R')} | {_p(s['win_rate'], 1, '٪')} |")
        L.append(f"| `close` (پروپوزال) | {alt['n']} | {_p(alt['expectancy_r'], 3, 'R')} | {_p(alt['win_rate'], 1, '٪')} |")
        L.append("")
        L.append("اگر تفاوت این دو زیاد باشد، بخشی از سود پروپوزال محصول **فرض ورود** "
                 "است، نه لبه.\n")
    nb = rep.get("no_bb_exit")
    if nb and nb.get("n"):
        L.append("## اگر خروجِ «بازگشت به میانگین» را برداریم\n")
        L.append("| حالت | معامله | نرخ برد | expectancy | میانگین برد | چرا بسته شد |")
        L.append("|---|---:|---:|---:|---:|---|")
        L.append(f"| با خروج باند میانی | {s['n']} | {_p(s['win_rate'], 1, '٪')} | "
                 f"{_p(s['expectancy_r'], 3, 'R')} | {_p(s['avg_win_r'], 2, 'R')} | "
                 + "، ".join(f"{EXIT_FA.get(k, k)} {v}" for k, v in
                             sorted(s['by_reason'].items(), key=lambda kv: -kv[1])) + " |")
        L.append(f"| بدون آن (TP/SL/زمان) | {nb['n']} | {_p(nb['win_rate'], 1, '٪')} | "
                 f"{_p(nb['expectancy_r'], 3, 'R')} | {_p(nb['avg_win_r'], 2, 'R')} | "
                 + "، ".join(f"{EXIT_FA.get(k, k)} {v}" for k, v in
                             sorted(nb['by_reason'].items(), key=lambda kv: -kv[1])) + " |")
        L.append("")
        L.append("خروج در باند میانی بردها را **کوچک** می‌کند (میانگین برد پایین‌تر) "
                 "ولی نرخ برد را بالا می‌برد. کدام بهتر است را فقط ستون expectancy "
                 "می‌گوید؛ هر دو حالت با همان داده و همان هزینه اجرا شده‌اند.\n")

    L.append("## محدودیت‌ها\n")
    L.append("- با OHLC می‌دانیم داخل کندل چه شد، نه به چه ترتیبی؛ فرض ما بدبینانه است.")
    L.append("- اسپرد لحظهٔ انفجار مدل نشده؛ ستون هزینه فقط کارمزد و اسلیپیج ثابت است.")
    L.append("- یک نماد، یک بازه = یک آزمون. حکم فقط با تقسیم بیرون‌نمونه و نمونهٔ کافی.")
    return "\n".join(L)


def _p(x, nd=2, suf=""):
    return "—" if x is None else f"{x:.{nd}f}{suf}"


# ══════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════
def v10_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab v10",
        description="V10 Pro: بازگشت به میانگین BB+RSI+حجم (بک‌تست/مقایسه/نزدیکی)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--tf", default="15m")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--download", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--compare", action="store_true", help="مقایسه با الگوهای MTF")
    p.add_argument("--proximity", action="store_true",
                   help="جدول نزدیکی به سیگنال (قابل ترکیب با بقیه)")
    p.add_argument("--proximity-only", action="store_true",
                   help="فقط جدول نزدیکی، بدون بک‌تست")
    p.add_argument("--entry", choices=["next_open", "close"], default="next_open")
    p.add_argument("--same-bar", choices=["pessimistic", "optimistic"],
                   default="pessimistic")
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)

    from .live import _default_symbols
    from .desk import load_universe

    syms = a.symbols or _default_symbols()
    universe: Dict[str, List[Candle]] = {}
    if a.download:
        from .autoscan import fetch_or_load, pick_base_url
        base = pick_base_url(progress=True)
        for sym in syms:
            try:
                cs, _ = fetch_or_load(sym, a.tf, a.days, a.data_dir,
                                      base_url=base, refresh=a.refresh,
                                      progress=False)
                if cs:
                    universe[sym] = cs
            except Exception as e:                                 # noqa: BLE001
                print(f"⚠️ {sym}: {type(e).__name__}")
    else:
        universe = load_universe(a.data_dir, a.tf, syms)
        if not universe:
            print("❌ دادهٔ کش‌شده نیست.\n   این را بزن: "
                  "python3 -m mtflab v10 --download --days 180")
            return 2

    os.makedirs(a.out_dir, exist_ok=True)

    # ── جدول نزدیکی ─────────────────────────────────────────────────────
    if a.proximity or a.proximity_only:
        rows = []
        for sym, cs in universe.items():
            pr = proximity(cs)
            if pr:
                pr["symbol"] = sym
                rows.append(pr)
        rows.sort(key=lambda r: -max(r["long_score"], r["short_score"]))
        print("| نماد | قیمت | LONG | SHORT | RSI | حجم× | سیگنال |")
        print("|---|---:|---:|---:|---:|---:|---|")
        for r in rows:
            sig = r["signal"]["side"] if r["signal"] else "—"
            print(f"| {r['symbol']} | {r['price']} | {r['long_score']}٪ | "
                  f"{r['short_score']}٪ | {r['rsi']} | {r['vol_ratio']} | {sig} |")
        with open(os.path.join(a.out_dir, "v10_proximity.json"), "w",
                  encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1, default=str)
        if a.proximity_only:
            print(f"\n📄 {os.path.abspath(os.path.join(a.out_dir, 'v10_proximity.json'))}")
            return 0
        print()

    # ── بک‌تست ──────────────────────────────────────────────────────────
    all_trades: List[dict] = []
    per_symbol: Dict[str, dict] = {}
    for sym, cs in universe.items():
        r = backtest(cs, entry=a.entry, same_bar=a.same_bar,
                     risk_pct=a.risk_pct, symbol=sym)
        # منحنی سرمایهٔ تجمعی برای سنجهٔ افت
        per_symbol[sym] = summarize(r)
        all_trades.extend(r["trades"])
    combined = summarize({"trades": all_trades, "equity_curve": [1000.0]})
    rep = {"symbol": "همه" if len(universe) > 1 else next(iter(universe)),
           "tf": a.tf, "entry": a.entry, "same_bar": a.same_bar,
           "data": _provenance(a.data_dir, a.tf, list(universe)),
           "summary": combined, "per_symbol": per_symbol,
           "trades": all_trades[-500:]}

    # نسخهٔ خوش‌بینانه (فرض پروپوزال) برای مقایسه
    alt_trades: List[dict] = []
    for sym, cs in universe.items():
        alt_trades.extend(backtest(cs, entry="close", same_bar=a.same_bar,
                                   risk_pct=a.risk_pct, symbol=sym)["trades"])
    rep["alternative"] = summarize({"trades": alt_trades,
                                    "equity_curve": [1000.0]})

    # نسخهٔ بدون خروج «بازگشت به میانگین»: می‌خواهیم بدانیم این خروج چه قدر
    # از سود را می‌بلعد (بردها را سقف‌دار می‌کند).
    nb_trades: List[dict] = []
    for sym, cs in universe.items():
        nb_trades.extend(backtest(cs, {"bb_mid_exit": False}, entry=a.entry,
                                  same_bar=a.same_bar, risk_pct=a.risk_pct,
                                  symbol=sym)["trades"])
    rep["no_bb_exit"] = summarize({"trades": nb_trades,
                                   "equity_curve": [1000.0]})

    md = render(rep)
    print(md)
    path = os.path.join(a.out_dir, "v10_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(a.out_dir, "v10_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)

    if a.compare:
        cmp_ = compare_with_mtf(universe, a.tf, a.risk_pct)
        print("\n## مقایسه با الگوهای MTF\n")
        print("| موتور | معامله | نرخ برد | expectancy R | ضریب سود |")
        print("|---|---:|---:|---:|---:|")
        v, m = cmp_["v10"], cmp_["mtf"]
        print(f"| V10 Pro | {v['n']} | {_p(v['win_rate'], 1, '٪')} | "
              f"{_p(v['expectancy_r'], 3)} | {_p(v['profit_factor'], 2)} |")
        if m and "error" not in m:
            print(f"| MTF `{cmp_['variant']}` | {m['n']} | "
                  f"{_p(m['win_rate'], 1, '٪')} | {_p(m['expectancy_r'], 3)} | "
                  f"{_p(m['profit_factor'], 2)} |")
        else:
            print(f"| MTF | — | — | — | — |  ← {m.get('error') if m else ''}")
        print(f"\n{cmp_['note']}")
        with open(os.path.join(a.out_dir, "v10_vs_mtf.json"), "w",
                  encoding="utf-8") as f:
            json.dump({k: v for k, v in cmp_.items()}, f, ensure_ascii=False,
                      indent=1, default=str)

    print(f"\n📄 {os.path.abspath(path)}")
    try:
        from .sweep import deliver
        deliver([path], a.out_dir, lang=a.lang)
    except Exception:                                              # noqa: BLE001
        pass
    return 0
