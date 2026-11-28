"""چشم شکارچی — برنده‌ها را از بازنده‌ها روی «زمینهٔ لحظهٔ ورود» جدا می‌کند.

## این فایل چه می‌کند و چه نمی‌کند

**می‌کند:** ژورنال معاملات را می‌خواند، زمینهٔ ثبت‌شده در `context.py` را با
نتیجهٔ هر معامله جفت می‌کند، و برای هر ویژگی می‌گوید «بردها در این ویژگی از
باخت‌ها جدا بودند یا نه» — با سه محافظ:

1. **AUC** به‌جای میانگین: مقیاس‌پذیر و مقاوم به داده‌های پرت. ۰.۵ = بی‌تفاوت.
2. **آزمون جایگشتی** (permutation) به‌جای p-value فرمولی: هیچ فرض توزیعی ندارد.
3. **تأیید بیرون‌نمونه** + **اصلاح بونفرونی** برای تعداد ویژگی‌های آزمون‌شده.

**نمی‌کند:** هیچ پارامتری را خودش عوض نمی‌کند، هیچ سیگنالی نمی‌سازد، هیچ تصمیمی
نمی‌گیرد. خروجی‌اش «نامزد برای آزمون در آزمایشگاه» است، نه «تنظیم جدید».
این همان قاعده‌ای است که از اول گذاشتیم: موتور قاعده تصمیم می‌گیرد، ابزار فقط
نگاه می‌کند.

## چرا این سه محافظ لازم است

اگر ۱۸ ویژگی را روی ۶۰ معامله آزمون کنی، به‌طور تصادفی چندتایی «معنادار» می‌شوند.
بدون بونفرونی و بدون تأیید بیرون‌نمونه، نتیجهٔ این فایل تبدیل می‌شود به همان
دامی که کل پروژه را زمین زد: بهینه‌سازی روی نویز.
"""
from __future__ import annotations

import json
import math
import os
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .context import FEATURE_FA, FEATURES, NEUTRAL

VERSION = "1.0"

#: حداقل تعداد معاملهٔ بسته‌شده برای اینکه اصلاً حرف بزنیم.
MIN_N = 40
#: درصد دادهٔ اول برای «کشف»، بقیه برای «تأیید».
DEV_FRAC = 0.60
#: تعداد جایگشت‌ها و دانهٔ ثابت (نتیجه تکرارپذیر).
N_PERM = 2000
SEED = 7
#: حداقل «بزرگی اثر»: فاصلهٔ AUC از ۰.۵. با n بزرگ، تفاوت‌های ناچیز هم
#: «معنادار» می‌شوند؛ این آستانه جلوی آن را می‌گیرد (۰.۰۸ ≈ ۵۴٪ در برابر ۴۶٪).
EFFECT_MIN = 0.08


# ══════════════════════════════════════════════════════════════════════════
#  خواندن ژورنال
# ══════════════════════════════════════════════════════════════════════════
def read_journal(path: str) -> List[dict]:
    """جفت‌کردن رکورد باز/بسته و برگرداندن معاملاتِ بسته‌شده."""
    if not path or not os.path.exists(path):
        return []
    opens: Dict[str, dict] = {}
    trades: List[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue                        # خط نیمه‌کاره نباید کل گزارش را بکشد
            t = rec.get("type")
            rid = rec.get("id")
            if t == "open" and rid:
                opens[rid] = rec
            elif t == "close":
                oid = rec.get("open_id") or ""
                o = opens.get(oid)
                res = rec.get("result") or {}
                r = res.get("r_multiple")
                if r is None:
                    continue
                ctx = dict((o or {}).get("context") or {})
                trades.append({
                    "id": oid,
                    "symbol": rec.get("symbol") or (o or {}).get("symbol"),
                    "ts": (o or {}).get("ts") or rec.get("ts"),
                    "r": float(r),
                    "is_win": bool(res.get("is_win", float(r) > 0)),
                    "pnl": res.get("pnl"),
                    "bars": res.get("bars_held"),
                    "mfe": res.get("mfe_pct"),
                    "mae": res.get("mae_pct"),
                    "rule": ((rec.get("closed_by") or {}).get("fa")
                             or (rec.get("closed_by") or {}).get("id")),
                    "is_risk_control": bool((rec.get("closed_by") or {})
                                            .get("is_risk_control")),
                    "algorithm": ((rec.get("algorithm") or {}).get("id")),
                    "pattern": (((o or {}).get("entry_pattern") or {}).get("mode")),
                    "context": ctx,
                })
    trades.sort(key=lambda t: t.get("ts") or 0)
    return trades


# ══════════════════════════════════════════════════════════════════════════
#  آماری که خودمان می‌نویسیم (بدون numpy)
# ══════════════════════════════════════════════════════════════════════════
def auc(pos: Sequence[float], neg: Sequence[float]) -> Optional[float]:
    """مساحت زیر ROC با رتبه‌ها. ۰.۵ = جداکننده نیست، ۱ = کامل جدا می‌کند."""
    n1, n2 = len(pos), len(neg)
    if n1 == 0 or n2 == 0:
        return None
    pairs = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda x: x[0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0            # رتبهٔ میانگین برای مقادیر مساوی
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    s = sum(r for r, p in zip(ranks, pairs) if p[1] == 1)
    return (s - n1 * (n1 + 1) / 2.0) / (n1 * n2)


def permutation_p(pos: Sequence[float], neg: Sequence[float],
                  observed: float, n_perm: int = N_PERM, seed: int = SEED) -> Optional[float]:
    """p دوطرفه برای «AUC دور از ۰.۵» با جایگشت برچسب‌ها."""
    if observed is None or not pos or not neg:
        return None
    rng = random.Random(seed)
    pool = list(pos) + list(neg)
    n1 = len(pos)
    dev = abs(observed - 0.5)
    hits = 0
    for _ in range(int(n_perm)):
        rng.shuffle(pool)
        a = auc(pool[:n1], pool[n1:])
        if a is not None and abs(a - 0.5) >= dev - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def _median(xs: Sequence[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# ══════════════════════════════════════════════════════════════════════════
#  تحلیل
# ══════════════════════════════════════════════════════════════════════════
def analyze(trades: Sequence[dict], min_n: int = MIN_N,
            dev_frac: float = DEV_FRAC, n_perm: int = N_PERM,
            seed: int = SEED) -> dict:
    """گزارش کامل: توزیع نتیجه، رشتهٔ ضرر، و جدول ویژگی‌ها با سه محافظ."""
    ts = [t for t in trades if t.get("r") is not None]
    n = len(ts)
    wins = [t for t in ts if t["r"] > 0]
    losses = [t for t in ts if t["r"] <= 0]
    rs = [t["r"] for t in ts]

    # ── توزیع نتیجه (برد و باخت با هم — نه فقط سود) ─────────────────────
    dist = {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / n) if n else None,
        "expectancy_r": (sum(rs) / n) if n else None,
        "r_sum": sum(rs) if rs else 0.0,
        "best_r": max(rs) if rs else None,
        "worst_r": min(rs) if rs else None,
        "pnl": sum(float(t.get("pnl") or 0) for t in ts) if ts else 0.0,
        "avg_win_r": (sum(t["r"] for t in wins) / len(wins)) if wins else None,
        "avg_loss_r": (sum(t["r"] for t in losses) / len(losses)) if losses else None,
        "risk_control_share": (sum(1 for t in losses if t.get("is_risk_control"))
                               / len(losses)) if losses else None,
        "longest_loss_streak": _longest_loss_streak(rs),
        "max_drawdown_r": _max_drawdown(rs),
    }

    # ── جدول ویژگی‌ها ────────────────────────────────────────────────────
    keys = [k for k, _ in FEATURES]
    have = [k for k in keys if any((t["context"] or {}).get(k) is not None
                                   for t in ts)]
    k_tests = len(have)
    alpha = 0.05
    bonf = (alpha / k_tests) if k_tests else alpha

    # تقسیم زمانی: اول برای کشف، آخر برای تأیید
    cut = int(len(ts) * float(dev_frac))
    dev, hold = ts[:cut], ts[cut:]

    rows: List[dict] = []
    for key in have:
        vals = [(float(t["context"][key]), t["r"] > 0) for t in ts
                if (t["context"] or {}).get(key) is not None]
        if len(vals) < max(12, min_n // 2):
            rows.append({"key": key, "fa": FEATURE_FA.get(key, key),
                         "n": len(vals), "auc": None, "p": None,
                         "verdict": "نمونه کم", "note": ""})
            continue
        pos = [v for v, w in vals if w]
        neg = [v for v, w in vals if not w]
        a = auc(pos, neg)
        p = permutation_p(pos, neg, a, n_perm, seed)

        d_pos = [float(t["context"][key]) for t in dev
                 if t["r"] > 0 and (t["context"] or {}).get(key) is not None]
        d_neg = [float(t["context"][key]) for t in dev
                 if t["r"] <= 0 and (t["context"] or {}).get(key) is not None]
        h_pos = [float(t["context"][key]) for t in hold
                 if t["r"] > 0 and (t["context"] or {}).get(key) is not None]
        h_neg = [float(t["context"][key]) for t in hold
                 if t["r"] <= 0 and (t["context"] or {}).get(key) is not None]
        a_dev = auc(d_pos, d_neg)
        a_hold = auc(h_pos, h_neg)

        agrees = (a_dev is not None and a_hold is not None
                  and (a_dev - 0.5) * (a_hold - 0.5) > 0)
        strong = (p is not None and p < bonf)
        enough = len(vals) >= min_n
        effect = abs((a or 0.5) - 0.5)
        big_enough = effect >= EFFECT_MIN
        if strong and agrees and enough and big_enough:
            verdict = "قابل بررسی"
        elif strong and not agrees:
            verdict = "احتمالاً نویز (بیرون‌نمونه تأیید نکرد)"
        elif strong and not enough:
            verdict = "نمونه کم"
        elif strong and not big_enough:
            verdict = "معنادار ولی ناچیز"
        elif agrees and effect >= 0.06:
            verdict = "ضعیف ولی هم‌جهت"
        else:
            verdict = "نویز"

        rows.append({
            "key": key, "fa": FEATURE_FA.get(key, key), "n": len(vals),
            "auc": a, "auc_dev": a_dev, "auc_hold": a_hold, "p": p,
            "median_win": _median(pos), "median_loss": _median(neg),
            "neutral": key in NEUTRAL,
            "verdict": verdict,
            "note": ("ویژگی زمان/تقویم — فقط برای تفکیک، نه «بیشتر بهتر»"
                     if key in NEUTRAL else ""),
        })

    rows.sort(key=lambda r: (r["verdict"] != "قابل بررسی",
                             -(abs((r["auc"] or 0.5) - 0.5))))
    candidates = [r for r in rows if r["verdict"] == "قابل بررسی"]

    warnings: List[str] = []
    if n < min_n:
        warnings.append(f"n={n} کمتر از {min_n} است — این گزارش **فقط برای دیدن "
                        "ساختار** است، نه نتیجه. الگوی «قابل بررسی» هم با این "
                        "تعداد، هنوز نامزد است، نه یافته.")
    if not have:
        warnings.append("هیچ ویژگی زمینه‌ای در ژورنال نیست. ژورنال‌های قدیمی "
                        "قبل از نسخهٔ context ثبت شده‌اند؛ بعد از یک دور اجرای "
                        "تازه دوباره امتحان کن.")
    if k_tests:
        warnings.append(f"{k_tests} ویژگی آزموده شد؛ آستانهٔ معناداری با اصلاح "
                        f"بونفرونی = {bonf:.4f} (نه ۰.۰۵). با ۰.۰۵ خام، به‌طور "
                        "تصادفی چندتایی «کشف» می‌شد.")

    return {
        "version": VERSION,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dist": dist,
        "split": {"dev_n": len(dev), "hold_n": len(hold),
                  "dev_frac": dev_frac, "bonferroni": bonf, "k_tests": k_tests,
                  "effect_min": EFFECT_MIN},
        "features": rows,
        "candidates": [r["key"] for r in candidates],
        "warnings": warnings,
    }


def _longest_loss_streak(rs: Sequence[float]) -> int:
    best = cur = 0
    for r in rs:
        if r <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _max_drawdown(rs: Sequence[float]) -> float:
    """بیشترین افت منحنی سرمایه به واحد R."""
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dd


# ══════════════════════════════════════════════════════════════════════════
#  گزارش فارسی
# ══════════════════════════════════════════════════════════════════════════
def _p(x, nd=2, suffix=""):
    return "—" if x is None else f"{x:.{nd}f}{suffix}"


def render(rep: dict, lang: str = "fa") -> str:
    fa = lang != "en"
    d = rep["dist"]
    L: List[str] = []
    L.append("# چشم شکارچی — برنده‌ها در برابر بازنده‌ها\n" if fa else
             "# Hunter's eye\n")
    L.append(f"*{rep['created_utc']}* · نسخهٔ {rep['version']}\n")
    L.append("> این گزارش **هیچ پارامتری را عوض نمی‌کند**. فقط می‌گوید در چه "
             "زمینه‌هایی بردها از باخت‌ها جدا بودند. هر «قابل بررسی» یعنی "
             "«این را در آزمایشگاه با دروازهٔ ازپیش‌نوشته آزمون کن»، نه «این را "
             "اعمال کن».\n" if fa else "> read-only report\n")

    L.append("## ۱) نتیجه، با برد و باخت با هم\n" if fa else "## 1) Results\n")
    L.append("| سنجه | مقدار |" if fa else "| metric | value |")
    L.append("|---|---:|")
    L.append(f"| معاملهٔ بسته‌شده | **{d['n']}** |")
    L.append(f"| برد / باخت | {d['wins']} / {d['losses']} |")
    L.append(f"| نرخ برد | {_p((d['win_rate'] or 0) * 100, 1, '٪')} |")
    L.append(f"| expectancy | **{_p(d['expectancy_r'], 3, 'R')}** |")
    L.append(f"| جمع R | {_p(d['r_sum'], 2, 'R')} |")
    L.append(f"| سود/زیان | {_p(d['pnl'], 2, '$')} |")
    L.append(f"| میانگین برد / باخت | {_p(d['avg_win_r'], 2, 'R')} / {_p(d['avg_loss_r'], 2, 'R')} |")
    L.append(f"| بهترین / بدترین | {_p(d['best_r'], 2, 'R')} / {_p(d['worst_r'], 2, 'R')} |")
    L.append(f"| بلندترین رشتهٔ ضرر | {d['longest_loss_streak']} |")
    L.append(f"| بیشترین افت (R) | {_p(d['max_drawdown_r'], 2, 'R')} |")
    L.append(f"| ضررها با قاعدهٔ ضدضرر | {_p((d['risk_control_share'] or 0) * 100, 0, '٪')} |")
    L.append("")
    if d["n"]:
        L.append(("**چطور بخوانیم:** با نرخ برد زیر ۵۰٪، سیستم سالم هم سه تا پنج "
                  "باخت پشت‌سرهم می‌دهد. آنچه سیستم را سالم نگه می‌دارد این است "
                  "که میانگین باخت ≈ ۱R بماند و میانگین برد بزرگ‌تر از آن باشد — "
                  "نه اینکه هیچ باختی نباشد.\n") if fa else "")
    L.append("## ۲) کدام ویژگی، برد را از باخت جدا می‌کند\n" if fa else "## 2) Features\n")
    L.append(f"کشف روی {rep['split']['dev_n']} معاملهٔ اول · تأیید روی "
             f"{rep['split']['hold_n']} معاملهٔ آخر · آستانهٔ بونفرونی "
             f"**{rep['split']['bonferroni']:.4f}** (برای {rep['split']['k_tests']} ویژگی) · "
             f"حداقل بزرگی اثر **{rep['split'].get('effect_min', EFFECT_MIN):.2f}** "
             f"فاصلهٔ AUC از ۰.۵\n"
             if fa else "split\n")
    L.append("| ویژگی | n | AUC | p | AUC کشف | AUC تأیید | میانهٔ برد | میانهٔ باخت | حکم |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rep["features"]:
        pv = "—" if r["p"] is None else f"{r['p']:.4f}"
        L.append(f"| {r['fa']} | {r['n']} | {_p(r['auc'], 3)} | {pv} | "
                 f"{_p(r.get('auc_dev'), 3)} | {_p(r.get('auc_hold'), 3)} | "
                 f"{_p(r.get('median_win'), 3)} | {_p(r.get('median_loss'), 3)} | "
                 f"{r['verdict']} |")
    L.append("")
    if rep["candidates"]:
        L.append("**نامزدها برای آزمون در آزمایشگاه:** " +
                 "، ".join(f"`{c}`" for c in rep["candidates"]) + "\n")
        L.append("برای هرکدام یک فرضیهٔ یک‌خطی و یک دروازه بنویس، بعد **یک** "
                 "پارامتر را عوض کن. اگر همان دروازه پاس نشد، نامزد رد است — "
                 "نه اینکه دروازه را عوض کنیم.\n" if fa else "")
    else:
        L.append("**هیچ ویژگی‌ای به مرحلهٔ «قابل بررسی» نرسید.** این خودش یک "
                 "نتیجه است: یا نمونه کم است، یا تفاوت واقعی نیست. در هر دو "
                 "حالت، تغییر پارامتر بر اساس این داده، نویز‌فروشی است.\n"
                 if fa else "no candidates\n")

    if rep["warnings"]:
        L.append("## هشدارها\n" if fa else "## Warnings\n")
        for w in rep["warnings"]:
            L.append(f"- ⚠️ {w}")
        L.append("")
    L.append("## محدودیت‌ها\n" if fa else "## Limits\n")
    L.append("- «جداکردن» با AUC یعنی همبستگی، نه علت. حتی نامزدِ تأییدشده هم "
             "باید در آزمایشگاه با OOS سنجیده شود." if fa else "- correlation")
    L.append("- ویژگی‌های زمینه فقط از همان لحظهٔ ورود ثبت می‌شوند؛ چیزی که بعد "
             "از ورود رخ داد در این جدول نیست (وگرنه تقلب بود)." if fa else "")
    L.append("- اگر ژورنال چند الگو/نماد را قاطی کرده باشد، تفاوت‌ها می‌توانند "
             "از تفاوت الگوها بیایند نه از زمینه. تفکیک نمادی در `--audit` است."
             if fa else "")
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════
def hunter_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab hunter",
        description="چشم شکارچی: مقایسهٔ زمینهٔ سیگنال‌ها در برد و باخت (فقط خواندن)")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--out", default="results/hunter_fa.md")
    p.add_argument("--json", action="store_true")
    p.add_argument("--min-n", type=int, default=MIN_N)
    p.add_argument("--perm", type=int, default=N_PERM)
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)

    trades = read_journal(a.journal)
    rep = analyze(trades, min_n=a.min_n, n_perm=a.perm)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
        return 0
    md = render(rep)
    print(md)
    if trades:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\n📄 {os.path.abspath(a.out)}")
        try:
            from .sweep import deliver
            deliver([a.out], os.path.dirname(a.out) or "results", lang=a.lang)
        except Exception:                                        # noqa: BLE001
            pass
    else:
        print("\n(ژورنال معاملهٔ بسته‌شده ندارد — اول `bash run-auto.sh --live` "
              "را چند بار اجرا کن.)")
        return 2
    return 0
