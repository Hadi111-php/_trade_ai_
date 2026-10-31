"""تحلیل هم‌حرکتی بین نمادها (co-movement) — آیا ارزها «با هم» حرکت می‌کنند؟

### مسئله‌ای که این ماژول حل می‌کند

همهٔ آزمون‌های قبلی، هر نماد را **جدا** می‌دیدند: «آیا استراتژی روی این نماد سود
می‌دهد؟» و نتیجه این شد که چند سکه همهٔ سود را می‌سازند. سؤال درست‌تر این است:

> آیا ارزها **پشت صحنه** با هم رابطه دارند؟ و آیا این رابطه در سال‌های مختلف
> **پایدار** است؟ (با کنار گذاشتن عامل مشترک بازار/اخبار)

### چرا روی قیمت ماهانه، نه PnL سالانه

تحلیل روی PnL سالانه یعنی ۴ نقطه برای هر نماد. با ۴ نقطه، ضریب همبستگی رتبه‌ای
مقادیر گسستهٔ محدودی می‌گیرد (±۱ خیلی راحت می‌آید) و **هر نتیجه‌ای شانسی است**.
با قیمت ماهانه، ۳۶ تا ۸۴ نقطه داریم — که آزمون واقعی است.

### دو فرضیهٔ از پیش ثبت‌شده

- **H1 — رابطهٔ پنهان:** پس از حذف عامل بازار (میانگین مقطعی هر ماه)، همبستگی
  باقیمانده‌ها بیش از حالت تصادفی است. آزمون: جایگشت، p < 0.05.
- **H2 — پایداری:** گروه‌بندی نمادها در نیمهٔ اول تاریخ با نیمهٔ دوم یکی است.
  آزمون: ARI > 0.30 و جایگشت p < 0.05.

اگر هر دو رد شوند ⇒ «ارزها یک عامل + نویز هستند»، و هیچ گروه‌بندی پنهانی وجود ندارد.
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics as st
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Candle, tf_to_minutes

VERSION = "1.0"
_LANG = "fa"


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = "en" if str(lang).lower().startswith("en") else "fa"


def _t(fa: str, en: str) -> str:
    return en if _LANG == "en" else fa


# ----------------------------------------------------------------------------
# آمار پایه (بدون numpy — Termux هیچ بسته‌ای ندارد)
# ----------------------------------------------------------------------------
def rank(values: Sequence[float]) -> List[float]:
    """رتبه با میانگین‌گیری در برابر مقادیر مساوی (rank ties)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    ma, mb = st.fmean(a[:n]), st.fmean(b[:n])
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    return pearson(rank(a), rank(b))


# ----------------------------------------------------------------------------
# آماده‌سازی داده
# ----------------------------------------------------------------------------
def load_cached(data_dir: str, tf: str = "4h") -> Dict[str, List[Candle]]:
    """خواندن همهٔ فایل‌های کش JSON برای یک تایم‌فریم (خروجی autoscan)."""
    from .autoscan import candles_from_json
    folder = os.path.join(data_dir, "json")
    out: Dict[str, List[Candle]] = {}
    if not os.path.isdir(folder):
        return out
    suffix = f"_{tf}.json"
    for name in sorted(os.listdir(folder)):
        if not name.endswith(suffix):
            continue
        sym = name[: -len(suffix)].upper()
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                cs = candles_from_json(json.load(f))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if len(cs) > 1:
            out[sym] = cs
    return out


def monthly_returns(candles: Sequence[Candle]) -> Dict[str, float]:
    """بازده ماهانه از قیمت بستهٔ آخرین کندل هر ماه."""
    closes: Dict[str, float] = {}
    for c in candles:
        t = time.gmtime(c.open_time_ms / 1000)
        closes[f"{t.tm_year:04d}-{t.tm_mon:02d}"] = c.close
    months = sorted(closes)
    out: Dict[str, float] = {}
    for i in range(1, len(months)):
        prev, cur = closes[months[i - 1]], closes[months[i]]
        if prev > 0:
            out[months[i]] = (cur / prev) - 1.0
    return out


def build_panel(returns: Dict[str, Dict[str, float]], min_months: int = 24,
                min_coverage: float = 0.8) -> Tuple[List[str], Dict[str, List[float]]]:
    """ماتریس ماه × نماد. فقط ماه‌هایی که اکثر نمادها داده دارند."""
    if not returns:
        return [], {}
    all_months = sorted({m for r in returns.values() for m in r})
    n = len(returns)
    keep = [m for m in all_months
            if sum(1 for r in returns.values() if m in r) >= min_coverage * n]
    if len(keep) < min_months:
        keep = all_months
    panel: Dict[str, List[float]] = {}
    for sym in sorted(returns):
        row = [returns[sym][m] for m in keep if m in returns[sym]]
        if len(row) >= min_months:
            panel[sym] = row
    return keep, panel


def demean_by_month(panel: Dict[str, List[float]]) -> Dict[str, List[float]]:
    """حذف «عامل بازار»: در هر ماه میانگین مقطعی کم می‌شود.

    چرا: اگر همه با هم بالا بروند (اخبار/روند کل بازار)، همبستگی مصنوعی می‌شود.
    بعد از این حذف، آنچه می‌ماند «حرکت نسبی هر سکه در برابر بقیه» است — همان
    رابطهٔ پنهانی که دنبالش هستیم.
    """
    syms = [s for s, v in panel.items() if v]
    if not syms:
        return {}
    n = min(len(v) for v in panel.values())
    out = {s: [] for s in syms}
    for i in range(n):
        col = [panel[s][i] for s in syms]
        m = st.fmean(col)
        for s in syms:
            out[s].append(panel[s][i] - m)
    return out


# ----------------------------------------------------------------------------
# خوشه‌بندی سلسله‌مراتبی (average linkage)
# ----------------------------------------------------------------------------
def corr_matrix(panel: Dict[str, List[float]],
                method: str = "spearman") -> Tuple[List[str], List[List[float]]]:
    syms = sorted(panel)
    fn = spearman if method == "spearman" else pearson
    m = [[0.0] * len(syms) for _ in syms]
    for i, a in enumerate(syms):
        for j, b in enumerate(syms):
            if j > i:
                m[i][j] = m[j][i] = fn(panel[a], panel[b])
            elif i == j:
                m[i][j] = 1.0
    return syms, m


def _avg_linkage(corr: List[List[float]], a: List[int], b: List[int]) -> float:
    vals = [corr[i][j] for i in a for j in b]
    return st.fmean(vals) if vals else 0.0


def cluster(corr: List[List[float]], k: int = 2) -> List[List[int]]:
    """خوشه‌بندی حریصانه با پیوند میانگین بر پایهٔ همبستگی (بزرگ‌تر = نزدیک‌تر)."""
    n = len(corr)
    groups: List[List[int]] = [[i] for i in range(n)]
    while len(groups) > k:
        best, bi, bj = -2.0, 0, 1
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                s = _avg_linkage(corr, groups[i], groups[j])
                if s > best:
                    best, bi, bj = s, i, j
        groups[bi] = groups[bi] + groups[bj]
        groups.pop(bj)
    return sorted([sorted(g) for g in groups], key=lambda g: -len(g))


def labels_of(groups: List[List[int]]) -> List[int]:
    lab = [0] * sum(len(g) for g in groups)
    for gi, g in enumerate(groups):
        for i in g:
            lab[i] = gi
    return lab


def adjusted_rand(a: Sequence[int], b: Sequence[int]) -> float:
    """ARI — توافق دو خوشه‌بندی، تصحیح‌شده برای شانس. ۱=یکسان، ۰=تصادفی."""
    n = len(a)
    if n < 2:
        return 0.0

    def comb2(x: float) -> float:
        return x * (x - 1) / 2.0

    def pairs(lab: Sequence[int]) -> Dict[Tuple[int, int], int]:
        d: Dict[Tuple[int, int], int] = {}
        for x, y in zip(a, b):
            d[(x, y)] = d.get((x, y), 0) + 1
        return d

    cont = pairs((a, b))
    sum_ij = sum(comb2(v) for v in cont.values())
    from collections import Counter
    ra, rb = Counter(a), Counter(b)
    sum_a = sum(comb2(v) for v in ra.values())
    sum_b = sum(comb2(v) for v in rb.values())
    total = comb2(n)
    if total == 0:
        return 0.0
    expected = (sum_a * sum_b) / total
    max_idx = 0.5 * (sum_a + sum_b)
    denom = max_idx - expected
    return (sum_ij - expected) / denom if denom else 0.0


# ----------------------------------------------------------------------------
# فرضیه‌ها
# ----------------------------------------------------------------------------
def mean_abs_corr(corr: List[List[float]]) -> float:
    n = len(corr)
    vals = [abs(corr[i][j]) for i in range(n) for j in range(i + 1, n)]
    return st.fmean(vals) if vals else 0.0


def permutation_h1(panel: Dict[str, List[float]], obs: float,
                   n_iter: int = 1000, seed: int = 17) -> dict:
    """H1: آیا |همبستگی| باقیمانده‌ها بیش از تصادف است؟

    ⚠️ **دامی که یک‌بار خوردیم:** جایگشت «درون هر نماد» غلط است. چون باقیمانده‌ها
    در هر ماه جمعشان صفر است، همبستگی‌ها ناگزیر کمی منفی‌اند؛ جایگشت درون‌نمادی
    این قید را می‌شکند و آستانهٔ تصادفی را **پایین‌تر** از واقعیت می‌آورد ⇒ نویز
    خالص «ساختار» نشان می‌دهد (آزمون منفی شکست می‌خورد).

    جایگشت درست: **در هر ماه، مقدارها بین نمادها جابه‌جا می‌شوند**. این کار قید
    «جمع صفر» و توزیع هر ماه را حفظ می‌کند و فقط «هویت نماد» را می‌شکند.
    """
    rng = random.Random(seed)
    syms = sorted(panel)
    n = min(len(v) for v in panel.values())
    cols = [[panel[s][i] for s in syms] for i in range(n)]
    null: List[float] = []
    for _ in range(n_iter):
        shuffled: Dict[str, List[float]] = {s: [] for s in syms}
        for col in cols:
            c = list(col)
            rng.shuffle(c)
            for k, s in enumerate(syms):
                shuffled[s].append(c[k])
        _, m = corr_matrix(shuffled)
        null.append(mean_abs_corr(m))
    null.sort()
    p = (sum(1 for x in null if x >= obs) + 1) / (len(null) + 1)
    return {"observed": round(obs, 4),
            "null_median": round(st.median(null), 4),
            "null_p95": round(null[int(0.95 * (len(null) - 1))], 4),
            "p_value": round(p, 4), "n_iter": n_iter,
            "supported": p < 0.05}


def _pair_vector(corr: List[List[float]]) -> List[float]:
    n = len(corr)
    return [corr[i][j] for i in range(n) for j in range(i + 1, n)]


def stability_h2(panel: Dict[str, List[float]], k: int = 3,
                 n_iter: int = 500, seed: int = 23) -> dict:
    """H2: آیا ساختار همبستگی نیمهٔ اول با نیمهٔ دوم یکی است؟ (آزمون Mantel)

    ⚠️ **دام دومی که خوردیم:** با ARI و ۲ گروه ۳ نفره، ۱۰٪ جایگشت‌ها همان
    افراز را بازتولید می‌کنند ⇒ کمترین p ممکن ۰.۱ می‌شود و حتی ساختار کاملاً
    پایدار هم «رد» می‌شود. راه‌حل: آمارهٔ پیوستهٔ Mantel — همبستگی بین بردار
    جفت‌همبستگی‌های دو نیمه. جایگشت: جای عوض کردن نمادها در نیمهٔ دوم.
    """
    syms = sorted(panel)
    half = min(len(panel[s]) for s in syms) // 2
    if half < 6:
        return {"ok": False, "note": "داده برای دو نیمه کافی نیست"}
    first = {s: panel[s][:half] for s in syms}
    second = {s: panel[s][half:2 * half] for s in syms}
    _, c1 = corr_matrix(first)
    _, c2 = corr_matrix(second)
    v1, v2 = _pair_vector(c1), _pair_vector(c2)
    obs = pearson(v1, v2)

    rng = random.Random(seed)
    n = len(syms)
    null: List[float] = []
    for _ in range(n_iter):
        perm = list(range(n))
        rng.shuffle(perm)
        cp = [[c2[perm[i]][perm[j]] for j in range(n)] for i in range(n)]
        null.append(pearson(v1, _pair_vector(cp)))
    null.sort()
    p = (sum(1 for x in null if x >= obs) + 1) / (len(null) + 1)

    a = labels_of(cluster(c1, k))
    b = labels_of(cluster(c2, k))
    return {"ok": True, "k": k, "months_half": half,
            "mantel_r": round(obs, 4), "p_value": round(p, 4),
            "ari": round(adjusted_rand(a, b), 4),
            "supported": (obs > 0.30 and p < 0.05)}


# ----------------------------------------------------------------------------
# اجرای کامل
# ----------------------------------------------------------------------------
def run_comove(data_dir: str = "data", tf: str = "4h", min_months: int = 24,
               k: int = 3, n_iter: int = 1000, progress: bool = True,
               panel_override: Optional[Dict[str, List[float]]] = None) -> dict:
    t0 = time.time()
    if panel_override is not None:
        panel_raw = panel_override
        months = [f"M{i:03d}" for i in range(min(len(v) for v in panel_raw.values()))]
    else:
        cached = load_cached(data_dir, tf)
        if len(cached) < 3:
            raise RuntimeError(
                f"کمتر از ۳ نماد در {data_dir}/json برای {tf} پیدا شد. "
                f"یک‌بار autoscan را اجرا کنید.")
        rets = {s: monthly_returns(cs) for s, cs in cached.items()}
        months, panel_raw = build_panel(rets)
        if len(panel_raw) < 3:
            raise RuntimeError("دادهٔ ماهانهٔ کافی برای مقایسهٔ نمادها نیست.")

    if len(panel_raw) < 3:
        raise RuntimeError(
            "برای حذف عامل بازار حداقل ۳ نماد لازم است. با ۲ نماد، باقیمانده‌ها "
            "همیشه ±قرینه می‌شوند و همبستگی مصنوعاً ۱- یا ۱ می‌شود.")

    cutoff = min(len(v) for v in panel_raw.values())
    panel_raw = {s: v[-cutoff:] for s, v in panel_raw.items()}
    panel_res = demean_by_month(panel_raw)
    syms = sorted(panel_raw)
    _, c_raw = corr_matrix(panel_raw)
    _, c_res = corr_matrix(panel_res)

    obs = mean_abs_corr(c_res)
    h1 = permutation_h1(panel_res, obs, n_iter=n_iter)
    h2 = stability_h2(panel_res, k=k)

    groups = cluster(c_res, k=min(k, len(syms)))
    named = [[syms[i] for i in g] for g in groups]

    if progress:
        print(_t(f"🧩 {len(syms)} نماد · {cutoff} ماه · خوشه‌بندی به {len(named)} گروه",
                 f"🧩 {len(syms)} symbols · {cutoff} months · {len(named)} clusters"))
        for gi, g in enumerate(named, 1):
            print(f"   {gi}) " + " · ".join(g))

    return {
        "version": VERSION,
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "settings": {"tf": tf, "months": cutoff, "k": k,
                     "min_months": min_months, "n_iter": n_iter,
                     "n_symbols": len(syms), "months_label": months[-cutoff:]},
        "symbols": syms,
        "corr_raw": c_raw,
        "corr_residual": c_res,
        "clusters": named,
        "hypothesis_h1": h1,
        "hypothesis_h2": h2,
        "mean_abs_corr_raw": round(mean_abs_corr(c_raw), 4),
        "mean_abs_corr_residual": round(obs, 4),
        "verdict": {
            "hidden_structure": bool(h1["supported"]),
            "stable_groups": bool(h2.get("supported")),
        },
    }


# ----------------------------------------------------------------------------
# گزارش
# ----------------------------------------------------------------------------
def _f(x, d: int = 2) -> str:
    try:
        return f"{float(x):+.{d}f}"
    except (TypeError, ValueError):
        return "—"


def render_report(res: dict) -> str:
    L: List[str] = []
    w = L.append
    st_ = res["settings"]
    h1, h2 = res["hypothesis_h1"], res["hypothesis_h2"]

    w("# تحلیل هم‌حرکتی ارزها (Co-movement)\n")
    w(f"*ساخته‌شده: {res['generated_at']} · نسخهٔ {res['version']} · "
      f"{res['elapsed_s']} ثانیه*\n")
    w(f"- نمادها: **{st_['n_symbols']}** · بازهٔ ماهانه: **{st_['months']}** ماه "
      f"· تایم‌فریم داده: `{st_['tf']}`\n")

    w("## ۱) حکم\n")
    if h1["supported"] and h2.get("supported"):
        w("✅ **هر دو فرضیه تأیید شد:** رابطهٔ پنهان وجود دارد و گروه‌بندی پایدار است.\n")
    elif h1["supported"]:
        w("🟡 **رابطهٔ پنهان هست، ولی پایدار نیست.** یعنی در یک دوره گروه‌هایی "
          "شکل می‌گیرند و در دورهٔ بعد عوض می‌شوند ⇒ قابل استفاده برای آینده نیست.\n")
    else:
        w("❌ **هیچ رابطهٔ پنهانی پیدا نشد.** بعد از حذف عامل بازار، آنچه می‌ماند "
          "نویز است. ارزها عملاً «یک عامل مشترک + نویز» هستند.\n")

    w("## ۲) فرضیهٔ H1 — آیا رابطهٔ پنهان وجود دارد؟\n")
    w("| | مقدار |")
    w("|---|---:|")
    w(f"| میانگین |همبستگی| خام | {h1['observed']:.4f} |")
    w(f"| میانگین |همبستگی| تصادفی (میانه) | {h1['null_median']:.4f} |")
    w(f"| آستانهٔ ۹۵٪ تصادفی | {h1['null_p95']:.4f} |")
    w(f"| **p** | **{h1['p_value']}** |")
    w(f"| نتیجه | {'✅ تأیید' if h1['supported'] else '❌ رد'} |")
    w("")
    w("> آماره روی **باقیمانده** محاسبه شده (پس از حذف میانگین مقطعی هر ماه). "
      f"آزمون با {h1['n_iter']} جایگشت.\n")

    w("## ۳) فرضیهٔ H2 — آیا گروه‌بندی پایدار است؟\n")
    if not h2.get("ok"):
        w(f"⚠️ {h2.get('note', '')}\n")
    else:
        w("| | مقدار |")
        w("|---|---:|")
        w(f"| طول هر نیمه | {h2['months_half']} ماه |")
        w(f"| **Mantel r** (توافق ساختار) | **{h2['mantel_r']}** |")
        w(f"| p | {h2['p_value']} |")
        w(f"| ARI (توافق افراز) | {h2['ari']} |")
        w(f"| نتیجه | {'✅ پایدار' if h2['supported'] else '❌ ناپایدار'} |")
        w("")
        w("> Mantel r = همبستگی بین بردار جفت‌همبستگی‌های دو نیمه. ۱ یعنی ساختار "
          "کاملاً یکسان، ۰ یعنی بی‌ربط. شرط از پیش ثبت‌شده: r > ۰.۳۰ و p < ۰.۰۵.\n")

    w("## ۴) گروه‌های پیدا‌شده (روی باقیمانده)\n")
    for gi, g in enumerate(res["clusters"], 1):
        w(f"| گروه {gi} | {' · '.join(g)} |")
        w("|---:|---|")
    w("")
    w("> این گروه‌بندی **توصیفی** است. برای استفادهٔ عملی، باید در دورهٔ بعد هم "
      "تکرار شود — که همان آزمون H2 است.\n")

    w("## ۵) محدودیت‌ها\n")
    w("- همبستگی ≠ علیت. دو سکه می‌توانند هم‌حرکت باشند چون هر دو به یک عامل سوم "
      "وابسته‌اند.")
    w("- بازار کریپتو در دورهٔ رکود، همبستگی همه را به ۱ می‌برد؛ به همین دلیل "
      "عامل بازار حذف شده است.")
    w("- تعداد ماه‌ها محدود است؛ با دادهٔ بیشتر نتیجه می‌تواند تغییر کند.")
    w("- این تحلیل PAPER است و توصیهٔ معاملاتی نیست.\n")
    w("---\n_آزمون دادهٔ تاریخی، توصیهٔ معاملاتی نیست._")
    return "\n".join(L) + "\n"


def render_report_en(res: dict) -> str:
    L: List[str] = []
    w = L.append
    st_ = res["settings"]
    h1, h2 = res["hypothesis_h1"], res["hypothesis_h2"]

    w("# Cross-asset co-movement analysis\n")
    w(f"*generated: {res['generated_at']} · v{res['version']} · {res['elapsed_s']}s*\n")
    w(f"- symbols: **{st_['n_symbols']}** · monthly span: **{st_['months']}** months "
      f"· source tf: `{st_['tf']}`\n")

    w("## 1) Verdict\n")
    if h1["supported"] and h2.get("supported"):
        w("PASS: **both hypotheses hold** — hidden co-movement exists and the "
          "grouping is stable across halves.\n")
    elif h1["supported"]:
        w("PARTIAL: **co-movement exists but is not stable.** Groups form in one "
          "period and dissolve in the next, so it is not usable forward.\n")
    else:
        w("FAIL: **no hidden structure.** After removing the market factor the "
          "residual is noise. Coins behave as one common factor plus noise.\n")

    w("## 2) H1 — is there hidden co-movement?\n")
    w("| | value |")
    w("|---|---:|")
    w(f"| mean abs corr (raw) | {h1['observed']:.4f} |")
    w(f"| mean abs corr (shuffled) | {h1['null_median']:.4f} |")
    w(f"| 95% null threshold | {h1['null_p95']:.4f} |")
    w(f"| **p** | **{h1['p_value']}** |")
    w(f"| result | {'PASS' if h1['supported'] else 'FAIL'} |")
    w("")
    w(f"> Statistic computed on **residuals** (cross-sectional monthly mean "
      f"removed). {h1['n_iter']} permutations.\n")

    w("## 3) H2 — is the grouping stable?\n")
    if not h2.get("ok"):
        w(f"{h2.get('note', '')}\n")
    else:
        w("| | value |")
        w("|---|---:|")
        w(f"| months per half | {h2['months_half']} |")
        w(f"| ARI (agreement) | **{h2['ari']}** |")
        w(f"| p | {h2['p_value']} |")
        w(f"| result | {'PASS (stable)' if h2['supported'] else 'FAIL (unstable)'} |")
        w("")
        w("> ARI=1 means identical grouping; ARI~0 means random.\n")

    w("## 4) Clusters (on residuals)\n")
    w("| cluster | members |")
    w("|---:|---|")
    for gi, g in enumerate(res["clusters"], 1):
        w(f"| {gi} | {' · '.join(g)} |")
    w("")
    w("> Descriptive only. To be usable the grouping must repeat in the next "
      "period — which is exactly what H2 tests.\n")

    w("## 5) Limitations\n")
    w("- Correlation is not causation; two coins can co-move via a third factor.")
    w("- In a broad sell-off everything correlates near 1, hence the market "
      "factor is removed first.")
    w("- Monthly count is limited; more data may change the picture.")
    w("- PAPER analysis, not trading advice.\n")
    w("---\n_Backtest on historical data, not trading advice._")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def comove_command(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="mtflab comove",
        description="تحلیل هم‌حرکتی ارزها: آیا رابطهٔ پنهان و پایدار وجود دارد؟")
    p.add_argument("--data-dir", default="data", help="پوشهٔ داده (json/)")
    p.add_argument("--tf", default="4h", help="تایم‌فریم کش (پیش‌فرض 4h)")
    p.add_argument("--min-months", type=int, default=24)
    p.add_argument("--k", type=int, default=3, help="تعداد گروه‌ها")
    p.add_argument("--iter", type=int, default=1000, help="تعداد جایگشت")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--tag", default="")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    known = p.parse_args(argv)
    set_lang(known.lang)

    try:
        res = run_comove(known.data_dir, known.tf, known.min_months,
                         known.k, known.iter)
    except RuntimeError as e:
        print(f"❌ {e}")
        print("   bash run-auto.sh        # یک‌بار داده بگیرید")
        return 2

    os.makedirs(known.out_dir, exist_ok=True)
    tag = f"_{known.tag}" if known.tag else ""
    md = os.path.join(known.out_dir, f"comove{tag}.md")
    js = os.path.join(known.out_dir, f"comove{tag}.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(render_report_en(res) if _LANG == "en" else render_report(res))
    with open(js, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)

    h1, h2 = res["hypothesis_h1"], res["hypothesis_h2"]
    print()
    print("=" * 66)
    print(_t("📊 نتیجه", "📊 RESULT"))
    print(_t(f"  H1 رابطهٔ پنهان : p={h1['p_value']} → "
             f"{'تأیید' if h1['supported'] else 'رد'}",
             f"  H1 hidden co-movement: p={h1['p_value']} -> "
             f"{'PASS' if h1['supported'] else 'FAIL'}"))
    if h2.get("ok"):
        print(_t(f"  H2 پایداری      : Mantel r={h2['mantel_r']} p={h2['p_value']} "
                 f"ARI={h2['ari']} → {'پایدار' if h2['supported'] else 'ناپایدار'}",
                 f"  H2 stability        : Mantel r={h2['mantel_r']} p={h2['p_value']} "
                 f"ARI={h2['ari']} -> {'stable' if h2['supported'] else 'unstable'}"))
    for gi, g in enumerate(res["clusters"], 1):
        print(f"  {gi}) " + " · ".join(g))
    print("=" * 66)
    print(_t(f"📄 گزارش   : {md}", f"📄 report   : {md}"))
    print(_t(f"🗂 داده خام: {js}", f"🗂 data pack: {js}"))
    print(_t("👉 همین دو فایل را بفرستید.", "👉 Send these two files back."))
    return 0
