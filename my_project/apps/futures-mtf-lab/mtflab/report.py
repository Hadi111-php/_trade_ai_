"""نوشتن گزارش JSON + Markdown برای هر run (هم‌سبک با سناریوی قدیم)."""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from . import __scenario__, __version__


def _fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        if v == float("inf"):
            return "∞"
        return f"{v:.{nd}f}"
    return str(v)


def write_reports(cfg, res: dict) -> dict:
    """`results/mtf_report_<run_id>.json` و `.md` را می‌نویسد."""
    os.makedirs(cfg.out_dir, exist_ok=True)
    rid = res.get("run_id") or cfg.run_id
    base = os.path.join(cfg.out_dir, f"mtf_report_{rid}")
    s = res["summary"]
    h = res["health"]

    payload = {
        "run_id": rid,
        "app": "futures-mtf-lab",
        "lab_version": __version__,
        "scenario": __scenario__,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "label": cfg.label(),
        "config": res.get("config") or cfg.to_dict(),
        "meta": res.get("meta", {}),
        "summary": s,
        "health": h,
        "trades_count": len(res["trades"]),
    }
    if res.get("validation"):
        payload["validation"] = res["validation"]

    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    md = _markdown(cfg, res, payload)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(md)

    res["files"] = {"json": base + ".json", "md": base + ".md"}
    return res["files"]


def _markdown(cfg, res: dict, payload: dict) -> str:
    s = res["summary"]
    h = res["health"]
    m = res.get("meta", {})
    L: list = []
    L.append(f"# گزارش سناریوی چندتایم‌فریمی — {cfg.symbol} ({cfg.run_id})\n")
    L.append(f"- نسخه: `{__version__}` · سناریو: `{__scenario__}`")
    L.append(f"- برچسب داده: **{cfg.label()}**")
    L.append(f"- لایه‌ها: تریگر `{cfg.tf_trigger}` / فیلتر `{cfg.tf_filter}` / "
             f"بایاس `{cfg.tf_bias if cfg.bias_enabled else '—'}` · "
             f"نسخهٔ هم‌راستایی: **{cfg.alignment_version}**")
    L.append(f"- منبع: trigger=`{m.get('sources', {}).get('trigger', '—')}` · "
             f"filter=`{m.get('sources', {}).get('filter', '—')}` · "
             f"bias=`{m.get('sources', {}).get('bias', '—')}`")
    L.append(f"- هزینه: {cfg.fee_bps}bps + {cfg.slippage_pct}% اسلیپیج هر طرف "
             f"→ رفت‌وبرگشت **{_fmt(h.get('round_trip_cost_pct'), 4)}%** · "
             f"حداقل edge = {cfg.min_edge_multiplier}×\n")

    L.append("## خلاصهٔ عملکرد\n")
    L.append("| معیار | مقدار |")
    L.append("|---|---|")
    for k, lab in [("trades", "معاملات"), ("wins", "سودده"), ("losses", "زیان‌ده"),
                   ("win_rate", "نرخ برد"), ("profit_factor", "Profit Factor"),
                   ("expectancy", "Expectancy (USDT)"), ("expectancy_r", "Expectancy (R)"),
                   ("total_pnl", "کل PnL"), ("total_fees", "کل کارمزد"),
                   ("equity", "موجودی نهایی"), ("return_pct", "بازده %"),
                   ("max_drawdown_pct", "Max Drawdown %"), ("avg_bars_held", "میانگین کندلِ نگهداری"),
                   ("avg_mfe_pct", "میانگین MFE %"), ("avg_mae_pct", "میانگین MAE %")]:
        L.append(f"| {lab} | {_fmt(s.get(k))} |")

    L.append("\n## سلامت هم‌ترازی (ضد lookahead)\n")
    cov = h.get("alignment_coverage", {})
    aud = h.get("leakage_audit", {})
    L.append(f"- کندل‌های تریگر: **{h.get('bars', 0)}** · پوشش فیلتر: "
             f"**{_fmt(cov.get('filter_coverage', 0) * 100, 2)}%** · پوشش بایاس: "
             f"**{_fmt(cov.get('bias_coverage', 0) * 100, 2)}%**")
    L.append(f"- حسابرسی نشتی: {'✅ پاک' if aud.get('clean') else '❌ نقض'} "
             f"({aud.get('violations', 0)} مورد از {aud.get('bars_checked', 0)} کندل)")
    gaps = m.get("gaps", {})
    if gaps:
        L.append("\n### گپ‌های داده (بدون پرکردن)\n")
        L.append("| لایه | کندل | گم‌شده | درصد |")
        L.append("|---|---|---|---|")
        for layer, g in gaps.items():
            L.append(f"| {layer} ({g.get('tf')}) | {g.get('candles')} | "
                     f"{g.get('missing_candles')} | {_fmt(g.get('missing_pct'), 3)}% |")

    L.append("\n## وتوها (چرا معامله نکرد؟)\n")
    L.append("| دلیل | تعداد |")
    L.append("|---|---|")
    for k, v in sorted(s.get("veto_stats", {}).items(), key=lambda kv: -kv[1]):
        if v:
            L.append(f"| {k} | {v} |")
    L.append("\n| حالت تریگر | تعداد |")
    L.append("|---|---|")
    for k, v in s.get("trigger_stats", {}).items():
        L.append(f"| {k} | {v} |")

    v = res.get("validation")
    if v:
        L.append("\n## اعتبارسنجی\n")
        L.append("### split سه‌بخشی\n")
        L.append("| بخش | کندل | معاملات | Win% | PF | Expectancy | MaxDD% |")
        L.append("|---|---|---|---|---|---|---|")
        for seg in v["split"]["segments"]:
            L.append(f"| {seg['segment']} | {seg['candles']} | {seg['n']} | "
                     f"{_fmt(seg['win_rate'] * 100, 1)} | {_fmt(seg['profit_factor'])} | "
                     f"{_fmt(seg['expectancy'])} | {_fmt(seg['max_drawdown_pct'])} |")
        L.append(f"\n- افت train→OOS: {_fmt(v['split'].get('degradation_train_to_oos'))} · "
                 f"{v['split'].get('verdict', {}).get('note', '')}")

        L.append("\n### walk-forward\n")
        L.append("| پنجره | کندل test | معاملات | Win% | PF | Expectancy | ADX انتخابی |")
        L.append("|---|---|---|---|---|---|---|")
        for w in v["walk_forward"].get("windows", []):
            L.append(f"| {w['window']} | {w['test_candles']} | {w['n']} | "
                     f"{_fmt(w['win_rate'] * 100, 1)} | {_fmt(w['profit_factor'])} | "
                     f"{_fmt(w['expectancy'])} | {_fmt(w.get('selected_adx_min'), 1)} |")
        wf = v["walk_forward"]
        L.append(f"\n- پنجره‌های سودده: **{wf.get('profitable_windows', 0)}/{wf.get('n_windows', 0)}** · "
                 f"میانگین expectancy={_fmt(wf.get('mean_expectancy'))} · "
                 f"انحراف={_fmt(wf.get('std_expectancy'))} · {wf.get('verdict', '')}")

        mc = v["monte_carlo"]
        if mc.get("simulations"):
            L.append("\n### مونت‌کارلو\n")
            L.append(f"- {mc['simulations']} شبیه‌سازی bootstrap روی {mc['trades_per_sim']} معامله")
            L.append(f"- **P(سود) = {_fmt(mc['p_profit'])}** · P(ورشکستگی {mc['ruin_threshold_pct']}%) = "
                     f"{_fmt(mc['p_ruin'])}")
            L.append(f"- کل PnL: p5={_fmt(mc['total_pnl_p5'])} · میانه={_fmt(mc['total_pnl_median'])} · "
                     f"p95={_fmt(mc['total_pnl_p95'])}")

        L.append("\n### خط‌های پایه\n")
        b = v["baselines"]
        L.append("| روش | معاملات | Win% | PF | Expectancy | بازده% | MaxDD% |")
        L.append("|---|---|---|---|---|---|---|")
        ov = v["overall"]
        L.append(f"| **سناریوی MTF (نسخه {cfg.alignment_version})** | {ov['n']} | "
                 f"{_fmt(ov['win_rate'] * 100, 1)} | {_fmt(ov['profit_factor'])} | "
                 f"{_fmt(ov['expectancy'])} | {_fmt(ov['return_pct'])} | {_fmt(ov['max_drawdown_pct'])} |")
        st = b["single_timeframe"]
        L.append(f"| تک‌تایم‌فریم (بدون فیلتر/بایاس) | {st['n']} | {_fmt(st['win_rate'] * 100, 1)} | "
                 f"{_fmt(st['profit_factor'])} | {_fmt(st['expectancy'])} | "
                 f"{_fmt(st['return_pct'])} | {_fmt(st['max_drawdown_pct'])} |")
        rc = b["random_control"]
        L.append(f"| کنترل تصادفی | {rc.get('n', 0)} | {_fmt(rc.get('win_rate', 0) * 100, 1)} | "
                 f"{_fmt(rc.get('profit_factor'))} | {_fmt(rc.get('expectancy'))} | "
                 f"{_fmt(rc.get('return_pct'))} | {_fmt(rc.get('max_drawdown_pct'))} |")
        bh = b["buy_hold"]
        L.append(f"| Buy & Hold | — | — | — | — | {_fmt(bh.get('return_pct'))} | "
                 f"{_fmt(bh.get('max_drawdown_pct'))} |")

        sens = v.get("sensitivity", {})
        if sens.get("grid"):
            L.append(f"\n### حساسیت پارامتر ({sens.get('trials', 0)} آزمایش)\n")
            for name, rows in sens["grid"].items():
                L.append(f"- **{name}**: " + " · ".join(
                    f"{r['value']} → n={r['n']}, PF={_fmt(r['profit_factor'])}, exp={_fmt(r['expectancy'])}"
                    for r in rows))
            L.append(f"\n- گسترهٔ PF: {_fmt(sens.get('pf_min'))} … {_fmt(sens.get('pf_max'))} "
                     f"(spread={_fmt(sens.get('pf_spread'))}) · {sens.get('note', '')}")

        L.append("\n### چک‌لیست overfit\n")
        L.append("| # | بررسی | نتیجه | جزئیات |")
        L.append("|---|---|---|---|")
        for i, c in enumerate(v["overfit"]["checks"], 1):
            L.append(f"| {i} | {c['name']} | {'✅' if c['pass'] else '❌'} | {c['detail']} |")
        o = v["overfit"]
        L.append(f"\n**امتیاز: {o['passed']}/{o['total']}** → {o['verdict']}")

    L.append("\n---\n> ⚠️ این گزارش PAPER است. هیچ عددی «سود واقعی» نیست مگر روی دادهٔ "
             "واقعی out-of-sample و پس از کسر هزینه ثابت شده باشد.\n")
    return "\n".join(L) + "\n"
