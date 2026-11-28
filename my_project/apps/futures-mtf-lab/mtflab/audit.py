"""بازبینی سلامت معاملات — «این ضرر، خطا بود یا کارِ سیستم؟»

سؤال کاربر: «سه سیگنال گرفتم و همه ضرر شدند؛ اشتباه کرده یا باید الگو را
بهینه کرد؟» پاسخ بدون داده ممکن نیست، ولی بخش زیادی از پاسخ **مکانیکی** است:
هر ضرر باید حدود **۱R** باشد و با یک قاعدهٔ ضدضرر بسته شده باشد. اگر ضرری
۱.۵R شد، یا با «سقف زمان» بسته شد، یا بدون حد ضرر ماند — آن‌وقت خطاست، نه بازار.

این ماژول همان بازبینی را روی ژورنال انجام می‌دهد و هیچ معامله‌ای نمی‌کند.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .rules import rule_meta

#: تحمل خطای اجرا: هزینه/لغزش می‌تواند ضرر را کمی از ۱R بیشتر کند.
LOSS_TOLERANCE_R = 0.35


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
            except ValueError:
                continue          # خط نیمه‌کاره: رد شود، نه این‌که همه دور بریزد
    return out


def _pairs(journal: List[dict]) -> List[dict]:
    """هر «باز» را با «بسته»اش جفت می‌کند."""
    opens: Dict[str, dict] = {}
    out: List[dict] = []
    for r in journal:
        if r.get("type") == "open":
            opens[str(r.get("id"))] = r
        elif r.get("type") == "close":
            o = opens.get(str(r.get("open_id")))
            if not o:
                continue
            res = r.get("result") or {}
            meta = rule_meta((r.get("closed_by") or {}).get("rule")
                             or res.get("reason") or "")
            out.append({
                "symbol": o.get("symbol"),
                "side": (o.get("order") or {}).get("side"),
                "pattern": (o.get("entry_pattern") or {}).get("mode"),
                "rule": meta["rule"], "rule_fa": meta["fa"],
                "is_risk_control": meta["is_risk_control"],
                "r": float(res.get("r_multiple") or 0.0),
                "pnl": float(res.get("pnl") or 0.0),
                "bars": int(res.get("bars_held") or 0),
                "entry": (o.get("order") or {}).get("entry"),
                "exit": res.get("exit"),
                "stop": (o.get("order") or {}).get("stop"),
                "mae_pct": res.get("mae_pct"), "mfe_pct": res.get("mfe_pct"),
            })
    return out


def audit(journal_path: str) -> dict:
    trades = _pairs(read_journal(journal_path))
    flags: List[dict] = []
    for t in trades:
        if t["r"] < -(1.0 + LOSS_TOLERANCE_R) and t["is_risk_control"]:
            flags.append({"id": "loss_beyond_risk", "symbol": t["symbol"], "r": t["r"],
                          "fa": f"ضرر {t['r']:.2f}R از ۱R بیشتر است — لغزش/گپ؟"})
        if not t["is_risk_control"] and t["r"] < 0:
            flags.append({"id": "loss_not_risk_rule", "symbol": t["symbol"],
                          "rule": t["rule"], "r": t["r"],
                          "fa": f"ضرر با قاعدهٔ غیرضدضرر بسته شد ({t['rule_fa']})"})
        if t["rule"] == "end_of_data":
            flags.append({"id": "end_of_data", "symbol": t["symbol"],
                          "fa": "با پایان داده بسته شد — در رصد زنده نباید رخ دهد"})
        if t["bars"] == 0:
            flags.append({"id": "zero_bars", "symbol": t["symbol"],
                          "fa": "صفر کندل نگه داشته شده — بررسی داده/زمان"})

    n = len(trades)
    wins = [t for t in trades if t["r"] > 0]
    losses = [t for t in trades if t["r"] <= 0]
    r_sum = sum(t["r"] for t in trades)

    # بلندترین رشتهٔ ضرر — برای این‌که «۳ ضرر پشت‌سرهم» غیرعادی به نظر نرسد
    streak = worst = 0
    for t in trades:
        streak = streak + 1 if t["r"] <= 0 else 0
        worst = max(worst, streak)

    # ریسک هر معامله از خود ژورنال (نه حدس)
    risks = []
    for r in read_journal(journal_path):
        if r.get("type") == "open":
            amt = (r.get("order") or {}).get("risk_amount")
            if amt:
                risks.append(float(amt))

    checks = [
        {"id": "each_loss_is_about_1r",
         "fa": "هر ضرر ≈ ۱R",
         "ok": all(t["r"] >= -(1.0 + LOSS_TOLERANCE_R) for t in losses),
         "detail": (f"بدترین ضرر {min([t['r'] for t in losses] or [0]):.2f}R")},
        {"id": "losses_closed_by_risk_rule",
         "fa": "همهٔ ضررها با قاعدهٔ ضدضرر بسته شدند",
         "ok": all(t["is_risk_control"] for t in losses),
         "detail": ", ".join(sorted({t["rule"] for t in losses})) or "—"},
        {"id": "no_end_of_data_in_live",
         "fa": "هیچ معامله‌ای «پایان داده» نبست",
         "ok": not any(t["rule"] == "end_of_data" for t in trades),
         "detail": f"{sum(1 for t in trades if t['rule'] == 'end_of_data')} مورد"},
        {"id": "enough_sample",
         "fa": "نمونه برای قضاوت کافی است",
         "ok": n >= 30,
         "detail": f"n={n}" + ("" if n >= 30 else " — با این تعداد هیچ نتیجه‌ای نگیر")},
    ]
    return {
        "journal": os.path.abspath(journal_path),
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "expectancy_r": round(r_sum / n, 4) if n else None,
        "r_sum": round(r_sum, 3),
        "pnl": round(sum(t["pnl"] for t in trades), 2),
        "risk_per_trade": round(sum(risks) / len(risks), 2) if risks else None,
        "worst_loss_r": round(min([t["r"] for t in losses]), 3) if losses else None,
        "best_win_r": round(max([t["r"] for t in wins]), 3) if wins else None,
        "longest_loss_streak": worst,
        "by_rule": _by(trades, "rule", "rule_fa"),
        "by_pattern": _by(trades, "pattern"),
        "by_symbol": _by(trades, "symbol"),
        "checks": checks,
        "flags": flags,
        "trades": trades,
    }


def _by(trades: List[dict], key: str, label_key: Optional[str] = None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for t in trades:
        k = str(t.get(key) or "?")
        d = out.setdefault(k, {"n": 0, "r_sum": 0.0, "pnl": 0.0, "wins": 0})
        d["n"] += 1
        d["r_sum"] += t["r"]
        d["pnl"] += t["pnl"]
        d["wins"] += 1 if t["r"] > 0 else 0
        if label_key:
            d["fa"] = t.get(label_key)
    for d in out.values():
        d["expectancy_r"] = round(d["r_sum"] / d["n"], 3) if d["n"] else None
        d["win_rate"] = round(d["wins"] / d["n"], 3) if d["n"] else None
        d["pnl"] = round(d["pnl"], 2)
    return out


def render(rep: dict, lang: str = "fa") -> str:
    fa = lang != "en"
    L: List[str] = []
    L.append("🩺 بازبینی سلامت معاملات\n" if fa else "🩺 trade integrity audit\n")
    if not rep["n"]:
        L.append("هنوز معاملهٔ بسته‌ای در ژورنال نیست." if fa else "no closed trades yet.")
        return "\n".join(L) + "\n"
    L.append(f"- معاملهٔ بسته‌شده: **{rep['n']}** · برد {rep['wins']} · باخت {rep['losses']}")
    L.append(f"- expectancy: **{rep['expectancy_r']:+.3f}R** · جمع R: {rep['r_sum']:+.2f} · سود: {rep['pnl']:+.2f}$")
    if rep["risk_per_trade"]:
        L.append(f"- ریسک هر معامله (از ژورنال): {rep['risk_per_trade']:.2f}$")
    L.append(f"- بدترین ضرر: {rep['worst_loss_r']}R · بهترین برد: {rep['best_win_r']}R")
    L.append(f"- بلندترین رشتهٔ ضرر: {rep['longest_loss_streak']}\n")

    L.append("| بررسی | نتیجه | جزئیات |")
    L.append("|---|---|---|")
    for c in rep["checks"]:
        L.append(f"| {c['fa']} | {'✅' if c['ok'] else '❌'} | {c['detail']} |")
    L.append("")

    if rep["by_rule"]:
        L.append("| قاعدهٔ بست | تعداد | expectancy (R) | سود |")
        L.append("|---|---:|---:|---:|")
        for k, d in sorted(rep["by_rule"].items(), key=lambda x: -x[1]["n"]):
            L.append(f"| {d.get('fa') or k} | {d['n']} | {d['expectancy_r']:+.3f} | {d['pnl']:+.2f}$ |")
        L.append("")

    if rep["flags"]:
        L.append("⚠️ نشانه‌های نیازمند بررسی:")
        for fl in rep["flags"][:10]:
            L.append(f"   • {fl.get('symbol') or '—'}: {fl['fa']}")
        L.append("")
    else:
        L.append("✅ هیچ ناهنجاری مکانیکی پیدا نشد: هر ضرر ≈ ۱R و با قاعدهٔ ضدضرر بسته شده."
                 if fa else "✅ no mechanical anomaly found.")
        L.append("")
    if rep["n"] < 30:
        L.append("⚠️ تعداد معامله کم است: این گزارش سلامتِ **مکانیکی** را می‌گوید، نه خوب/بد بودن الگو را.")
    return "\n".join(L) + "\n"
