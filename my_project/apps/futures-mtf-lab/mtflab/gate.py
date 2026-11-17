"""دروازهٔ پذیرش — «کجای کاریم و برای عبور دقیقاً چه لازم است».

**چرا:** گزارش اسکن یک خط `FAIL` می‌دهد، ولی `FAIL` می‌تواند هزار معنی داشته باشد:
«۴ نماد داشتی» با «استراتژی ضرر می‌دهد» یکی نیست. این ماژول همان گزارش
(`results/auto_scan_*.json`) را می‌خواند و هر شرط دروازه را با عدد نشان می‌دهد:
چه چیزی پاس شده، چه چیزی نه، و **چقدر** کم است.

نکتهٔ کلیدی که خیلی‌ها از دست می‌دهند: آزمون علامت با n نماد، کمینه‌ی
p = ۲/۲ⁿ دارد. با ۴ نماد کمینه **۰٫۱۲۵** است ⇒ شرط `p ≤ 0.10` **ریاضیاتاً
ناممکن** است، نه اینکه «نتیجه ضعیف بود». این را صریح می‌نویسیم.

**چه نمی‌کند:** هیچ عددی را بازحساب نمی‌کند و هیچ آستانه‌ای را عوض نمی‌کند؛
فقط `gate` و `aggregate` همان فایل را می‌خواند. تست/آمار تازه هم نمی‌سازد.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional

VERSION = "1"

#: اگر در فایل نبود، از همین پیش‌فرض‌ها استفاده می‌شود (همان دروازهٔ ثبت‌شده).
DEFAULT_GATE = {"min_symbols": 8, "min_profitable_symbols_pct": 60.0,
                "min_positive_years_pct": 60.0, "min_median_pf": 1.05,
                "min_sign_test_p": 0.1, "min_trades": 100}


def min_sign_p(n_symbols: int) -> float:
    """کمینهٔ ممکن p در آزمون علامت دوطرفه با n نماد (۲ × ۰٫۵ⁿ)."""
    n = max(0, int(n_symbols))
    return min(1.0, 2.0 * (0.5 ** n))


def latest_report(results_dir: str = "results", tag: str = "") -> str:
    """تازه‌ترین `auto_scan_*.json` (یا `*<tag>*.json`) را پیدا می‌کند."""
    pat = os.path.join(results_dir, f"auto_scan_*{tag}*.json" if tag
                       else "auto_scan_*.json")
    files = sorted(glob.glob(pat), key=os.path.getmtime)
    return files[-1] if files else ""


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def readiness(rep: dict) -> dict:
    """برای هر نسخه: هر شرط با عدد واقعی/لازم + پاسخ «ممکن است یا نه»."""
    gate = dict(DEFAULT_GATE)
    gate.update(rep.get("gate") or {})
    agg = rep.get("aggregate") or {}
    settings = rep.get("settings") or {}
    n_symbols = int(settings.get("symbols") and len(settings["symbols"]) or 0)
    if not n_symbols and agg:
        n_symbols = int((next(iter(agg.values())) or {}).get("n_symbols") or 0)

    out: List[dict] = []
    for vid, a in agg.items():
        checks: List[dict] = []
        checks.append({
            "name": "نماد",
            "actual": a.get("n_symbols"), "need": f"≥ {gate['min_symbols']}",
            "ok": bool(a.get("checks", {}).get("symbols")),
            "hint": (f"{gate['min_symbols'] - int(a.get('n_symbols') or 0)} نماد دیگر لازم است"
                     if not a.get("checks", {}).get("symbols") else ""),
        })
        checks.append({
            "name": "معامله",
            "actual": a.get("total_trades"), "need": f"≥ {gate['min_trades']}",
            "ok": bool(a.get("checks", {}).get("trades")),
            "hint": (f"{gate['min_trades'] - int(a.get('total_trades') or 0)} معامله دیگر"
                     if not a.get("checks", {}).get("trades") else ""),
        })
        checks.append({
            "name": "نمادهای سودده",
            "actual": f"{a.get('profitable_symbols_pct')}%",
            "need": f"≥ {gate['min_profitable_symbols_pct']}%",
            "ok": bool(a.get("checks", {}).get("profitable_symbols")), "hint": "",
        })
        checks.append({
            "name": "سال‌های مثبت",
            "actual": f"{a.get('positive_years_pct')}%",
            "need": f"≥ {gate['min_positive_years_pct']}%",
            "ok": bool(a.get("checks", {}).get("positive_years")), "hint": "",
        })
        checks.append({
            "name": "میانهٔ PF",
            "actual": a.get("median_pf"), "need": f"≥ {gate['min_median_pf']}",
            "ok": bool(a.get("checks", {}).get("median_pf")), "hint": "",
        })
        sign = a.get("sign_vs_base") or {}
        p = sign.get("p_value")
        floor = min_sign_p(n_symbols)
        sig_ok = bool(a.get("checks", {}).get("significance"))
        hint = ""
        if vid == "base":
            hint = "نسخهٔ پایه؛ مقایسه با خودش معنا ندارد"
        elif p is not None and not sig_ok:
            if floor > gate["min_sign_test_p"]:
                hint = (f"کمینهٔ ممکن p با {n_symbols} نماد = {floor:.3f} ⇒ "
                        f"با این تعداد نماد، p≤{gate['min_sign_test_p']} ناممکن است")
            else:
                hint = "اختلاف با پایه به‌اندازهٔ کافی یک‌طرفه نیست"
        checks.append({
            "name": "معناداری (در برابر پایه)",
            "actual": (f"p={p}" if p is not None else "—"),
            "need": f"p ≤ {gate['min_sign_test_p']}",
            "ok": sig_ok, "hint": hint,
        })
        out.append({
            "variant": vid,
            "trades": a.get("total_trades"),
            "median_pf": a.get("median_pf"),
            "expectancy": a.get("median_expectancy"),
            "total_pnl": a.get("total_pnl"),
            "survived": bool(a.get("survived")),
            "checks": checks,
            "failed": [c["name"] for c in checks if not c["ok"]],
        })

    best = max(out, key=lambda v: (v.get("expectancy") or -1e9), default=None)
    return {
        "version": VERSION,
        "gate": gate,
        "n_symbols": n_symbols,
        "days": settings.get("days"),
        "source": settings.get("source"),
        "sign_p_floor": min_sign_p(n_symbols),
        "variants": out,
        "best": best,
        "survived": [v["variant"] for v in out if v["survived"]],
    }


def _next_steps(r: dict) -> List[str]:
    """جمله‌های «برای عبور چه کن» — فقط از همان اعداد."""
    steps: List[str] = []
    g = r["gate"]
    n = int(r["n_symbols"] or 0)
    best = r.get("best") or {}
    if n < g["min_symbols"]:
        need = g["min_symbols"] - n
        per = ((best.get("trades") or 0) / n) if n else 0
        est = int(round(per * g["min_symbols"])) if per else 0
        steps.append(f"- **{need} نماد** دیگر لازم است (الان {n}، شرط {g['min_symbols']}). "
                     f"با همان نرخ، {g['min_symbols']} نماد حدوداً **{est}** معامله می‌دهد.")
    if r["sign_p_floor"] > g["min_sign_test_p"]:
        floor8 = min_sign_p(g["min_symbols"])
        steps.append(f"- **معناداری با {n} نماد ناممکن است**: کمینهٔ p = "
                     f"۲×۰٫۵^{n} = **{r['sign_p_floor']:.3f}** > {g['min_sign_test_p']}. "
                     f"با {g['min_symbols']} نماد کمینه **{floor8:.4f}** می‌شود.")
    if (best.get("trades") or 0) < g["min_trades"]:
        steps.append(f"- **{g['min_trades'] - int(best.get('trades') or 0)} معامله** کم است "
                     f"({best.get('trades')} از {g['min_trades']}); با نماد بیشتر یا "
                     f"پنجرهٔ بلندتر (`--days 730`) جبران می‌شود.")
    if (r.get("days") or 0) < 400:
        steps.append(f"- پنجرهٔ فعلی **{r.get('days')} روز** است؛ یک سالِ تنها یعنی یک رژیم. "
                     f"برای سال‌های مثبتِ معنادار: `--days 730` یا بیشتر.")
    if best.get("failed") and set(best["failed"]) <= {"نماد", "معامله",
                                                      "معناداری (در برابر پایه)"}:
        steps.append(f"- بقیهٔ شرط‌ها برای **{best['variant']}** پاس شده‌اند؛ "
                     f"تنها سد، «اندازهٔ نمونه» است — نه بدبودن نتیجه.")
    if not steps:
        steps.append("- همهٔ شرط‌ها پاس شده‌اند.")
    return steps


def render_text(rep: dict, path: str = "") -> str:
    r = readiness(rep)
    g = r["gate"]
    L: List[str] = []
    L.append("# دروازهٔ پذیرش — کجای کاریم؟")
    L.append("")
    if path:
        L.append(f"منبع: `{os.path.basename(path)}` · پنجره: {r.get('days')} روز · "
                 f"منبع داده: {r.get('source')} · نماد: {r['n_symbols']}")
        L.append("")
    L.append("## ۱) شرط‌ها")
    L.append("")
    L.append(f"پیش‌ثبت‌شده: نماد ≥ {g['min_symbols']} · معامله ≥ {g['min_trades']} · "
             f"نماد سودده ≥ {g['min_profitable_symbols_pct']}% · "
             f"سال مثبت ≥ {g['min_positive_years_pct']}% · "
             f"میانهٔ PF ≥ {g['min_median_pf']} · p ≤ {g['min_sign_test_p']}")
    L.append("")
    L.append("| نسخه | معامله | میانهٔ PF | expectancy | وضعیت | شرط‌های ردشده |")
    L.append("|---|---:|---:|---:|---|---|")
    for v in r["variants"]:
        L.append(f"| `{v['variant']}` | {v['trades']} | {v['median_pf']} | "
                 f"{v['expectancy']} | {'✅ قبول' if v['survived'] else '❌ رد'} | "
                 f"{'، '.join(v['failed']) or '—'} |")
    L.append("")
    best = r.get("best")
    if best:
        L.append(f"## ۲) جزئیاتِ بهترین نسخه (`{best['variant']}`)")
        L.append("")
        L.append("| شرط | واقعی | لازم | نتیجه | توضیح |")
        L.append("|---|---|---|---|---|")
        for c in best["checks"]:
            L.append(f"| {c['name']} | {c['actual']} | {c['need']} | "
                     f"{'✅' if c['ok'] else '❌'} | {c['hint'] or '—'} |")
        L.append("")
    L.append("## ۳) برای عبور از دروازه")
    L.append("")
    L.extend(_next_steps(r))
    L.append("")
    L.append(f"_حداقل p ممکن با {r['n_symbols']} نماد: {r['sign_p_floor']:.4f} — "
             "این ریاضیات آزمون علامت است، نه نظر._")
    L.append("")
    return "\n".join(L)


def gate_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="mtflab gate",
                                description="دروازهٔ پذیرش: چه چیزی مانع است؟")
    p.add_argument("path", nargs="?", default="",
                   help="مسیر auto_scan_*.json (پیش‌فرض: تازه‌ترین در results/)")
    p.add_argument("--results-dir", default="results")
    p.add_argument("--tag", default="")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    path = a.path or latest_report(a.results_dir, a.tag)
    if not path or not os.path.isfile(path):
        print(f"❌ گزارش اسکنی پیدا نشد در {a.results_dir}/ — "
              "اول: bash run-auto.sh --source json --days 365 --tag year")
        return 2
    rep = load(path)
    if a.json:
        print(json.dumps(readiness(rep), ensure_ascii=False, indent=2))
    else:
        print(render_text(rep, path))
    return 0 if readiness(rep)["survived"] else 1
