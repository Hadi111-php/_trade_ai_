"""ریاضیات کوچکِ مدل — مشترک بین «آزمون مغز» و «چشم مغز».

این‌جا هیچ دانشی از معامله نیست: فقط استانداردسازی، رگرسیون لجستیک با L2،
و AUC. عمداً خالص پایتون و قطعی (بدون تصادف) است تا هر عددی که در گزارش
می‌آید، با همان ورودی دقیقاً تکرار شود.

توجه: `brain.py` (آزمون «مغز دوم») هنوز نسخهٔ خودش از همین توابع را دارد.
عمداً دست نخورد: اعداد آن آزمون و دروازهٔ شش‌شرطی در `docs/SUMMARY.md` §۲۶ ثبت
شده‌اند و یکسان‌سازی پیاده‌سازی، آن اعداد را با اختلاف ممیز شناور جابه‌جا
می‌کند. هر وقت `brain.py` بازاجرا شد، آن‌وقت هر دو روی همین ماژول می‌آیند.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple


def standardize_fit(rows: Sequence[dict], names: Sequence[str]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """میانگین و انحراف معیارِ **فقط دادهٔ آموزش** (جلوگیری از نشت)."""
    means, stds = {}, {}
    for name in names:
        vals = [float(r.get(name) or 0.0) for r in rows]
        m = sum(vals) / len(vals) if vals else 0.0
        var = sum((v - m) ** 2 for v in vals) / len(vals) if vals else 0.0
        means[name] = m
        stds[name] = math.sqrt(var) or 1.0
    return means, stds


def to_vector(row: dict, names: Sequence[str], means: Dict[str, float],
              stds: Dict[str, float]) -> List[float]:
    return [(float(row.get(n) or 0.0) - means[n]) / stds[n] for n in names]


def fit_logistic(X: Sequence[Sequence[float]], y: Sequence[int],
                 l2: float = 0.5, epochs: int = 400,
                 lr: float = 0.2) -> Tuple[List[float], float]:
    """گرادیان کاهشی ساده با تنظیم L2. قطعی و تکرارپذیر."""
    d = len(X[0]) if X else 0
    w, b = [0.0] * d, 0.0
    n = max(1, len(X))
    for _ in range(epochs):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
        b -= lr * gb / n
    return w, b


def predict_proba(w: Sequence[float], b: float, X: Sequence[Sequence[float]]) -> List[float]:
    out = []
    for xi in X:
        z = b + sum(wj * xj for wj, xj in zip(w, xi))
        out.append(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))))
    return out


def auc_score(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    """AUC رتبه‌ای (Mann–Whitney) با میانگین‌دهی روی تساوی‌ها. ۰.۵ = سکه."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    allv = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg], key=lambda x: x[0])
    ranks = [0.0] * len(allv)
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_pos = sum(ranks[k] for k in range(len(allv)) if allv[k][1] == 1)
    return round((r_pos - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)), 4)
