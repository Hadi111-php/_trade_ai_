"""آمار پایهٔ معاملات — بدون وابستگی به موتور، داشبورد یا ژورنال.

این ماژول همان فرمول‌هایی است که داشبورد و API مستقل استفاده می‌کنند. عمداً
جدا شد تا هر جای دیگری هم که بخواهد آمار بگیرد، **همان** تعریف‌ها را داشته
باشد؛ نه نسخهٔ دومِ «تقریباً مشابه».
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence

from .data import Candle
from .rules import rule_meta

def positions_from_trades(trades: Sequence[dict], candles: Sequence[Candle]) -> List[dict]:
    """لگ‌های بک‌تست را به «پوزیشن» جمع می‌کند (برداشت جزئی یک معامله است، نه دو)."""
    groups: Dict[tuple, List[dict]] = {}
    for t in trades:
        key = (t.get("open_bar"), round(float(t.get("entry") or 0), 8))
        groups.setdefault(key, []).append(t)
    out = []
    for (open_bar, _), legs in groups.items():
        last = legs[-1]
        risk = float(last.get("risk_amount") or 0.0)
        pnl = sum(float(x.get("pnl") or 0.0) for x in legs)
        r = (pnl / risk) if risk > 0 else float(last.get("r_multiple") or 0.0)
        entry_ts = None
        try:
            if 0 <= int(open_bar) < len(candles):
                entry_ts = candles[int(open_bar)].open_time_ms
        except (TypeError, ValueError):
            entry_ts = None
        out.append({
            "symbol": last.get("symbol") or "",
            "entry_ts": entry_ts,
            "exit_ts": last.get("ts"),
            "mode": last.get("trigger_mode") or "?",
            "rule": last.get("reason") or "?",
            "pnl": round(pnl, 4),
            "r": round(r, 4),
            "bars": int(last.get("bars_held") or 0),
            "is_win": pnl > 0,
        })
    out.sort(key=lambda x: (x.get("exit_ts") or 0))
    return out


def metrics(rows: Sequence[dict], initial_equity: float = 1000.0) -> dict:
    """سنجه‌های اصلی از فهرست پوزیشن‌ها."""
    n = len(rows)
    if not n:
        return {"n": 0, "win_rate": None, "expectancy_r": None, "pnl": 0.0,
                "profit_factor": None, "max_dd_pct": None, "avg_win": None,
                "avg_loss": None, "median_bars": None, "r_sum": 0.0}
    rs = [float(x["r"]) for x in rows]
    pnls = [float(x["pnl"]) for x in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    eq = initial_equity
    peak, maxdd = eq, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, (eq - peak) / peak * 100.0)
    bars = sorted(int(x["bars"]) for x in rows)
    return {
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "expectancy_r": round(sum(rs) / n, 4),
        "r_sum": round(sum(rs), 3),
        "pnl": round(sum(pnls), 2),
        "profit_factor": round(gross_w / gross_l, 3) if gross_l > 0 else None,
        "max_dd_pct": round(maxdd, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "median_bars": bars[len(bars) // 2] if bars else None,
        "equity": round(eq, 2),
    }


def breakdown(rows: Sequence[dict], key: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for x in rows:
        k = str(x.get(key) or "?")
        d = out.setdefault(k, {"n": 0, "r_sum": 0.0, "pnl": 0.0, "wins": 0})
        d["n"] += 1
        d["r_sum"] += float(x["r"])
        d["pnl"] += float(x["pnl"])
        d["wins"] += 1 if x["is_win"] else 0
    for d in out.values():
        d["expectancy_r"] = round(d["r_sum"] / d["n"], 4) if d["n"] else None
        d["win_rate"] = round(d["wins"] / d["n"], 4) if d["n"] else None
        d["pnl"] = round(d["pnl"], 2)
    return out


def rule_breakdown(rows: Sequence[dict]) -> Dict[str, dict]:
    out = breakdown(rows, "rule")
    for k in list(out):
        meta = rule_meta(k)
        out[k]["fa"] = meta["fa"]
        out[k]["is_risk_control"] = meta["is_risk_control"]
    return out


#: نام قدیمی، برای سازگاری با کدهای قبلی
_positions_from_trades = positions_from_trades
