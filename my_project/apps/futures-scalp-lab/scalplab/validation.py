"""معیارهای اعتبارسنجی و تحلیل توافق/کالیبراسیون.

هیچ چیزی اینجا «سود واقعی» نیست؛ همهٔ اعداد روی دادهٔ ورودیِ همان run
(مصنوعی/بازپخش) محاسبه می‌شوند و در گزارش صریح برچسب می‌خورند.
"""
from __future__ import annotations

import math
from typing import Dict, List


def wilson_ci(hits: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def metrics(outcomes: List[dict]) -> dict:
    n = len(outcomes)
    if n == 0:
        return {"n": 0}
    hg = sum(1 for o in outcomes if o["hit_gross"])
    hn = sum(1 for o in outcomes if o["hit_net"])
    nets = [o["ret_net_bps"] for o in outcomes]
    pos = sum(x for x in nets if x > 0)
    neg = -sum(x for x in nets if x < 0)
    avg_net = sum(nets) / n
    lo, hi = wilson_ci(hn, n)
    return {
        "n": n,
        "hit_gross": round(hg / n, 4),
        "hit_net": round(hn / n, 4),
        "hit_net_ci95": [lo, hi],
        "avg_net_bps": round(avg_net, 2),
        "expectancy_bps": round(avg_net, 2),
        "profit_factor": round(pos / neg, 2) if neg > 0 else float("inf"),
        "avg_mae_bps": round(sum(o["mae_bps"] for o in outcomes) / n, 2),
        "avg_mfe_bps": round(sum(o["mfe_bps"] for o in outcomes) / n, 2),
    }


def calibration(outcomes: List[dict], buckets=5) -> List[dict]:
    """آیا confidence بالاتر واقعاً hit-rate بالاتر می‌دهد؟"""
    rows = []
    for b in range(buckets):
        lo_c = 0.5 + b * 0.5 / buckets
        hi_c = 0.5 + (b + 1) * 0.5 / buckets
        sub = [o for o in outcomes if lo_c <= o["confidence"] < hi_c + (1e-9 if b == buckets - 1 else 0)]
        m = metrics(sub)
        rows.append({"conf_range": [round(lo_c, 2), round(hi_c, 2)], **m})
    return rows


def rank_methods(per_method: Dict[str, dict]) -> List[str]:
    """رتبه‌بندی روش‌های اعتبارسنجی بر اساس expectancy خالص (با حداقل نمونه)."""
    valid = [(k, v) for k, v in per_method.items()
             if v.get("n", 0) >= 30 and k != "random_control"]
    valid.sort(key=lambda kv: (kv[1]["avg_net_bps"], kv[1]["hit_net"]), reverse=True)
    return [k for k, _ in valid]
