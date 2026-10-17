"""حلقهٔ walk-forward: صدور سیگنال چندمدلی، ثبت کامل، ارزیابی پیامد، اعتبارسنجی.

علی بودن تضمین می‌شود: اسنپ‌شات t فقط از دادهٔ <= t ساخته شده؛
پیامد سیگنال فقط از کندل‌های > t محاسبه می‌شود.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from . import __version__
from .config import LabConfig
from .data import Candle, load_candles
from .indicators import build_snapshot
from .logger import JsonlWriter, signal_to_record
from .models import Signal, build_models
from .validation import calibration, metrics, rank_methods

DEFAULT_PARAMS = {
    "ema_fast": 9, "ema_slow": 21,
    "rsi_period": 14, "rsi_low": 32, "rsi_high": 68,
    "atr_period": 14, "bb_window": 20, "bb_lookback": 100,
    "donchian_window": 20, "vol_window": 50, "control_rate": 0.05,
}


def _params(cfg: LabConfig) -> dict:
    p = dict(DEFAULT_PARAMS)
    p["model_version"] = __version__
    return p


def run_one_seed(cfg: LabConfig, seed: int, signals_w: JsonlWriter,
                 outcomes_w: JsonlWriter) -> Tuple[List[dict], Dict[str, List[dict]]]:
    candles = load_candles(cfg, seed)
    n = len(candles)
    params = _params(cfg)
    snaps = build_snapshot(candles, params)
    models = build_models(params, seed)
    real_ids = [m.id for m in models if m.id != "random_control"]
    control = [m for m in models if m.id == "random_control"][0]

    from collections import defaultdict
    h = cfg.horizon
    fee_frac = 2 * cfg.fee_bps / 10_000          # ورود + خروج
    last_fire = defaultdict(lambda: -10**9)      # شامل idهای consensus هم می‌شود
    for m in models:
        last_fire[m.id] = -10**9

    signals: List[dict] = []
    per_method_outcomes: Dict[str, List[dict]] = {}

    def emit(model_id, family, d, conf, reason, i, snap):
        sig = Signal(i=i, ts=candles[i].ts, model_id=model_id, family=family,
                     direction=d, confidence=conf, reason=reason,
                     entry_price=candles[i].c, snapshot=snap, params=params)
        rec = signal_to_record(sig, cfg, seed)
        signals_w.write(rec)
        signals.append(rec)
        return sig

    def evaluate(sig: Signal) -> Optional[dict]:
        i = sig.i
        if i + h >= n:
            return None
        entry = sig.entry_price
        d = sig.direction
        path = []
        for j in range(i + 1, i + h + 1):
            r = d * (candles[j].c - entry) / entry
            path.append(r)
        ret_gross = path[-1]
        ret_net = ret_gross - fee_frac
        o = {
            "signal_i": i, "ts": sig.ts, "model_id": sig.model_id,
            "direction": d, "confidence": sig.confidence,
            "horizon": h,
            "ret_gross_bps": round(ret_gross * 10_000, 2),
            "ret_net_bps": round(ret_net * 10_000, 2),
            "hit_gross": ret_gross > 0, "hit_net": ret_net > 0,
            "mae_bps": round(min(min(path), 0.0) * 10_000, 2),
            "mfe_bps": round(max(max(path), 0.0) * 10_000, 2),
        }
        outcomes_w.write({**o, "run_id": cfg.run_id, "seed": seed,
                          "symbol": cfg.symbol, "timeframe": cfg.timeframe,
                          "data_mode": cfg.data_mode})
        return o

    logged: List[Signal] = []
    for i in range(n):
        snap = snaps[i]
        if snap is None:
            continue
        prev = snaps[i - 1] if i > 0 else None

        # رأی خام همهٔ مدل‌های واقعی در هر کندل (برای تحلیل توافق)
        votes = []
        for m in models:
            if m.id == "random_control":
                continue
            res = m.maybe_signal(i, candles[i].ts, snap, prev, candles[i].c)
            if res:
                votes.append((m.id, m.family, res[0], res[1], res[2]))
                if i - last_fire[m.id] >= cfg.cooldown:
                    last_fire[m.id] = i
                    logged.append(emit(m.id, m.family, res[0], res[1], res[2], i, snap))

        # توافق k از M به‌عنوان روش‌های اعتبارسنجی جدا (k = agree_min تا M)
        for k in range(cfg.agree_min, len(real_ids) + 1):
            pos = [v for v in votes if v[2] == 1]
            neg = [v for v in votes if v[2] == -1]
            d = 0
            conf = 0.0
            if len(pos) >= k and len(pos) > len(neg):
                d, conf = 1, sum(v[3] for v in pos) / len(pos)
            elif len(neg) >= k and len(neg) > len(pos):
                d, conf = -1, sum(v[3] for v in neg) / len(neg)
            mid = f"consensus_k{k}"
            if d and i - last_fire[mid] >= cfg.cooldown:
                last_fire[mid] = i
                logged.append(emit(mid, "ensemble", d, conf,
                                   f"{len(pos) if d == 1 else len(neg)}/{len(real_ids)} agree",
                                   i, snap))

        # خط پایهٔ تصادفی
        cres = control.maybe_signal(i, candles[i].ts, snap, prev, candles[i].c)
        if cres and i - last_fire[control.id] >= cfg.cooldown:
            last_fire[control.id] = i
            logged.append(emit(control.id, "control", cres[0], cres[1], cres[2], i, snap))

    for sig in logged:
        o = evaluate(sig)
        if o:
            per_method_outcomes.setdefault(sig.model_id, []).append(o)

    return signals, per_method_outcomes


def run_lab(cfg: LabConfig) -> dict:
    os.makedirs(cfg.out_dir, exist_ok=True)
    sig_path = os.path.join(cfg.out_dir, f"signals_{cfg.run_id}.jsonl")
    out_path = os.path.join(cfg.out_dir, f"outcomes_{cfg.run_id}.jsonl")
    sw, ow = JsonlWriter(sig_path), JsonlWriter(out_path)

    per_seed: Dict[int, Dict[str, dict]] = {}
    pooled: Dict[str, List[dict]] = {}
    all_signals_count = 0

    for seed in cfg.seeds:
        _, per_method = run_one_seed(cfg, seed, sw, ow)
        per_seed[seed] = {mid: metrics(ocs) for mid, ocs in per_method.items()}
        for mid, ocs in per_method.items():
            pooled.setdefault(mid, []).extend(ocs)
        all_signals_count += sum(len(v) for v in per_method.values())

    sw.close()
    ow.close()

    pooled_metrics = {mid: metrics(ocs) for mid, ocs in pooled.items()}
    ranking = rank_methods(pooled_metrics)
    control_m = pooled_metrics.get("random_control", {})

    calib = calibration([o for ocs in pooled.values() for o in ocs
                         if o["model_id"] not in ("random_control",) and
                         not o["model_id"].startswith("consensus")])

    report = {
        "run_id": cfg.run_id,
        "lab_version": __version__,
        "config": cfg.to_dict(),
        "data_mode": cfg.data_mode,
        "label": ("دادهٔ مصنوعی — فقط اعتبارسنجی مکانیزم؛ NOT real market"
                  if cfg.data_mode == "synthetic" else
                  f"بازپخش دادهٔ {cfg.data_mode} — هنوز نه سود زنده"),
        "total_signals": all_signals_count,
        "per_seed": per_seed,
        "pooled_metrics": pooled_metrics,
        "ranking_by_net_expectancy": ranking,
        "control": control_m,
        "calibration_conf_vs_hit": calib,
        "files": {"signals": sig_path, "outcomes": out_path},
    }

    with open(os.path.join(cfg.out_dir, f"report_{cfg.run_id}.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    from .report import write_markdown
    write_markdown(report, os.path.join(cfg.out_dir, f"report_{cfg.run_id}.md"))
    return report
