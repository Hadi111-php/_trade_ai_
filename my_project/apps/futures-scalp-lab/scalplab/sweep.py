"""سویپ چند تایم‌فریم × چند افق — پیدا کردن سناریوی بهتر روی داده.

برای synthetic، تایم‌فریم بالاتر با resample (ادغام f کندل) ساخته می‌شود.
برای binance، کندل واقعیِ همان اینتروال خوانده می‌شود.
خروجی: جدول رتبه‌بندی (tf × horizon × روش) بر پایهٔ خالص پس از کارمزد.
"""
from __future__ import annotations

from typing import Dict, List

from . import __version__
from .config import LabConfig
from .data import Candle, load_candles
from .indicators import build_snapshot
from .models import build_models
from .runner import DEFAULT_PARAMS
from .validation import metrics


def resample(candles: List[Candle], f: int) -> List[Candle]:
    if f <= 1:
        return candles
    out = []
    for i in range(0, len(candles) - f + 1, f):
        chunk = candles[i:i + f]
        out.append(Candle(chunk[0].ts, chunk[0].o, max(c.h for c in chunk),
                          min(c.l for c in chunk), chunk[-1].c,
                          sum(c.v for c in chunk)))
    return out


def eval_candles(candles: List[Candle], cfg: LabConfig, horizon: int,
                 seed: int) -> Dict[str, List[dict]]:
    params = dict(DEFAULT_PARAMS)
    params["model_version"] = __version__
    snaps = build_snapshot(candles, params)
    models = build_models(params, seed)
    n = len(candles)
    fee_frac = 2 * cfg.fee_bps / 10_000
    last_fire: Dict[str, int] = {}
    per: Dict[str, List[dict]] = {}

    for i in range(n):
        snap = snaps[i]
        if snap is None or i + horizon >= n:
            continue
        prev = snaps[i - 1] if i > 0 else None
        votes = []
        for m in models:
            if m.id == "random_control":
                continue
            r = m.maybe_signal(i, candles[i].ts, snap, prev, candles[i].c)
            if r:
                votes.append((m.id, r[0], r[1]))
                if i - last_fire.get(m.id, -10**9) >= cfg.cooldown:
                    last_fire[m.id] = i
                    _eval(per, m.id, r[0], r[1], candles, i, horizon, fee_frac)
        for k in range(cfg.agree_min, len(votes) + 1):
            pos = [v for v in votes if v[1] == 1]
            neg = [v for v in votes if v[1] == -1]
            d = conf = 0
            if len(pos) >= k and len(pos) > len(neg):
                d, conf = 1, sum(v[2] for v in pos) / len(pos)
            elif len(neg) >= k and len(neg) > len(pos):
                d, conf = -1, sum(v[2] for v in neg) / len(neg)
            mid = f"consensus_k{k}"
            if d and i - last_fire.get(mid, -10**9) >= cfg.cooldown:
                last_fire[mid] = i
                _eval(per, mid, d, conf, candles, i, horizon, fee_frac)
    return per


def _eval(per, mid, d, conf, candles, i, h, fee_frac):
    entry = candles[i].c
    path = [d * (candles[j].c - entry) / entry for j in range(i + 1, i + h + 1)]
    rg = path[-1]
    rn = rg - fee_frac
    per.setdefault(mid, []).append({
        "model_id": mid, "confidence": conf,
        "hit_gross": rg > 0, "hit_net": rn > 0,
        "ret_net_bps": round(rn * 10_000, 2),
        "mae_bps": round(min(min(path), 0) * 10_000, 2),
        "mfe_bps": round(max(max(path), 0) * 10_000, 2),
    })


def run_sweep(cfg: LabConfig) -> dict:
    import json, os
    tfs = cfg.sweep_tfs or [1, 5, 15]
    horizons = cfg.sweep_horizons or [4, 8, 16]
    rows = []
    for tf in tfs:
        if cfg.data_mode in ("binance", "bybit"):
            cfg.timeframe = f"{tf}m"
            candles = load_candles(cfg, cfg.seeds[0])
        else:
            base = load_candles(cfg, cfg.seeds[0])
            candles = resample(base, tf)
        for h in horizons:
            per = eval_candles(candles, cfg, h, cfg.seeds[0])
            for mid, ocs in per.items():
                m = metrics(ocs)
                if m.get("n", 0) >= 5:
                    rows.append({"tf": f"{tf}m", "horizon": h, "method": mid, **m})
    rows.sort(key=lambda r: r["avg_net_bps"], reverse=True)
    rep = {"run_id": cfg.run_id, "lab_version": __version__,
           "data_mode": cfg.data_mode, "label":
           ("دادهٔ واقعی Binance" if cfg.data_mode == "binance"
            else "دادهٔ مصنوعی resample‌شده — فقط رتبه‌بندی مکانیزم"),
           "rows": rows}
    os.makedirs(cfg.out_dir, exist_ok=True)
    with open(os.path.join(cfg.out_dir, f"sweep_{cfg.run_id}.json"), "w",
              encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"\n=== SWEEP ({cfg.data_mode}) — رتبهٔ خالص پس از کارمزد ===")
    for r in rows[:15]:
        print(f"  {r['tf']:>4} h={r['horizon']:<3} {r['method']:18s} "
              f"n={r['n']:4d} hit_net={r['hit_net']:.3f} net={r['avg_net_bps']:+.2f}")
    return rep
