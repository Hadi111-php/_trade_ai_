"""خروجی Markdown گزارش — با برچسب صریح منبع داده."""
from __future__ import annotations


def _fmt_ci(m: dict) -> str:
    ci = m.get("hit_net_ci95")
    return f"[{ci[0]:.2f},{ci[1]:.2f}]" if ci else "—"


def write_markdown(report: dict, path: str):
    L = []
    L.append("# گزارش Futures Scalp Lab\n")
    L.append(f"- run_id: `{report['run_id']}` | نسخهٔ lab: `{report['lab_version']}`")
    L.append(f"- **برچسب داده: {report['label']}**")
    cfg = report["config"]
    L.append(f"- symbol={cfg['symbol']} tf={cfg['timeframe']} horizon={cfg['horizon']} "
             f"fee={cfg['fee_bps']}bps cooldown={cfg['cooldown']} seeds={cfg['seeds']}")
    L.append(f"- کل سیگنال‌های ثبت‌شده: **{report['total_signals']}** "
             f"(هر سیگنال با اسنپ‌شات کامل اندیکاتورها در `signals_*.jsonl`)")
    L.append("")
    L.append("## روش‌های اعتبارسنجی (pooled روی همهٔ seedها)\n")
    L.append("| روش | n | hit_gross | hit_net | CI95(hit_net) | خالص(bps) | PF | MAE | MFE |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    pm = report["pooled_metrics"]
    best_id = report["ranking_by_net_expectancy"][0] if report["ranking_by_net_expectancy"] else None
    for mid in report["ranking_by_net_expectancy"] + ["random_control"]:
        m = pm.get(mid)
        if not m or not m.get("n"):
            continue
        star = " ⭐" if mid == best_id else ""
        L.append(f"| {mid}{star} | {m['n']} | {m['hit_gross']:.3f} | {m['hit_net']:.3f} | "
                 f"{_fmt_ci(m)} | {m['avg_net_bps']:+.2f} | {m['profit_factor']} | "
                 f"{m['avg_mae_bps']:.1f} | {m['avg_mfe_bps']:.1f} |")
    L.append("")
    L.append("## رتبه‌بندی: " + (" > ".join(report["ranking_by_net_expectancy"]) or "—"))
    ctl = report.get("control", {})
    if report["ranking_by_net_expectancy"] and ctl.get("n"):
        best = pm[report["ranking_by_net_expectancy"][0]]
        L.append(f"\nحاشیهٔ روش برتر نسبت به کنترل تصادفی: "
                 f"{best['avg_net_bps'] - ctl.get('avg_net_bps', 0):+.2f} bps به‌ازای هر سیگنال.")
    L.append("")
    L.append("## کالیبراسیون: آیا confidence بالاتر یعنی hit بالاتر؟\n")
    L.append("| بازهٔ conf | n | hit_net |")
    L.append("|---|---|---|")
    for row in report["calibration_conf_vs_hit"]:
        L.append(f"| {row['conf_range'][0]}–{row['conf_range'][1]} | {row['n']} | "
                 f"{row.get('hit_net', 0):.3f} |")
    L.append("")
    L.append("## تفکیک seed\n")
    for seed, per in report["per_seed"].items():
        L.append(f"- seed={seed}: " + ", ".join(
            f"{mid}: n={m['n']} hit_net={m.get('hit_net', 0):.3f}"
            for mid, m in sorted(per.items()) if m.get("n")))
    L.append("")
    L.append("---")
    L.append("یادآوری علمی: این اعداد فقط روی همین دادهٔ ورودی معتبرند. "
             "برای ادعای واقعی، همین pipeline باید روی دادهٔ واقعی (csv/binance) و "
             "ترجیحاً out-of-sample اجرا شود. هیچ عددی اینجا «سود واقعی» نیست.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
