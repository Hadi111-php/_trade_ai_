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
                 outcomes_w: JsonlWriter):
    candles = load_candles(cfg, seed)
    n = len(candles)
    params = _params(cfg)
    snaps = build_snapshot(candles, params)
    models = build_models(params, seed)
    real_models = [m for m in models if m.id != "random_control"]
    real_ids = [m.id for m in real_models]
    control = [m for m in models if m.id == "random_control"][0]

    from collections import defaultdict
    from .hunter import AdaptiveHunter
    h = cfg.horizon
    fee_frac = 2 * cfg.fee_bps / 10_000
    last_fire = defaultdict(lambda: -10**9)
    for m in models:
        last_fire[m.id] = -10**9
    hunter = AdaptiveHunter(real_ids, min_score=cfg.hunter_min_score)

    signals: List[dict] = []
    per_method_outcomes: Dict[str, List[dict]] = {}
    logged: List[Signal] = []

    def emit(model_id, family, d, conf, reason, i, snap):
        sig = Signal(i=i, ts=candles[i].ts, model_id=model_id, family=family,
                     direction=d, confidence=conf, reason=reason,
                     entry_price=candles[i].c, snapshot=snap, params=params)
        rec = signal_to_record(sig, cfg, seed)
        signals_w.write(rec)
        signals.append(rec)
        return sig

    def evaluate(sig: Signal, write=True) -> Optional[dict]:
        i = sig.i
        if i + h >= n:
            return None
        entry = sig.entry_price
        d = sig.direction
        path = [d * (candles[j].c - entry) / entry
                for j in range(i + 1, i + h + 1)]
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
        if write:
            outcomes_w.write({**o, "run_id": cfg.run_id, "seed": seed,
                              "symbol": cfg.symbol, "timeframe": cfg.timeframe,
                              "data_mode": cfg.data_mode})
        return o

    for i in range(n):
        # Resolve matured training labels before scoring bar i. Nothing from i+h is
        # visible before that bar has arrived.
        if cfg.adaptive_hunter:
            hunter.advance(i, candles)
        snap = snaps[i]
        if snap is None:
            continue
        prev = snaps[i - 1] if i > 0 else None

        votes = []
        for m in real_models:
            res = m.maybe_signal(i, candles[i].ts, snap, prev, candles[i].c)
            if res:
                votes.append((m.id, m.family, res[0], res[1], res[2]))
                if i - last_fire[m.id] >= cfg.cooldown:
                    last_fire[m.id] = i
                    logged.append(emit(m.id, m.family, res[0], res[1], res[2], i, snap))
                    if cfg.adaptive_hunter:
                        hunter.queue(i, m.id, res[0], candles[i].c, h, fee_frac, n)

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

        if cfg.adaptive_hunter and len(votes) >= cfg.agree_min:
            side, score = hunter.score([(v[0], v[2], v[3]) for v in votes])
            if side and i - last_fire["adaptive_hunter"] >= cfg.cooldown:
                last_fire["adaptive_hunter"] = i
                contributors = ",".join(v[0] for v in votes if v[2] == side)
                logged.append(emit("adaptive_hunter", "adaptive_ensemble", side,
                                   score / 100.0,
                                   f"weighted alignment={score:.2f}; contributors={contributors}",
                                   i, snap))

        cres = control.maybe_signal(i, candles[i].ts, snap, prev, candles[i].c)
        if cres and i - last_fire[control.id] >= cfg.cooldown:
            last_fire[control.id] = i
            logged.append(emit(control.id, "control", cres[0], cres[1], cres[2], i, snap))

    for sig in logged:
        o = evaluate(sig)
        if o:
            per_method_outcomes.setdefault(sig.model_id, []).append(o)

    diag = {"enabled": cfg.adaptive_hunter,
            "updates": hunter.updates if cfg.adaptive_hunter else [],
            "final_weights": hunter.weights if cfg.adaptive_hunter else {}}
    return signals, per_method_outcomes, diag


def run_lab(cfg: LabConfig) -> dict:
    os.makedirs(cfg.out_dir, exist_ok=True)
    sig_path = os.path.join(cfg.out_dir, f"signals_{cfg.run_id}.jsonl")
    out_path = os.path.join(cfg.out_dir, f"outcomes_{cfg.run_id}.jsonl")
    sw, ow = JsonlWriter(sig_path), JsonlWriter(out_path)

    per_seed: Dict[int, Dict[str, dict]] = {}
    pooled: Dict[str, List[dict]] = {}
    all_signals_count = 0
    hunter_by_seed = {}

    for seed in cfg.seeds:
        _, per_method, hunter_diag = run_one_seed(cfg, seed, sw, ow)
        per_seed[seed] = {mid: metrics(ocs) for mid, ocs in per_method.items()}
        hunter_by_seed[seed] = hunter_diag
        for mid, ocs in per_method.items():
            pooled.setdefault(mid, []).extend(ocs)
        all_signals_count += sum(len(v) for v in per_method.values())

    sw.close()
    ow.close()

    pooled_metrics = {mid: metrics(ocs) for mid, ocs in pooled.items()}
    ranking = rank_methods(pooled_metrics)
    control_m = pooled_metrics.get("random_control", {})
    hunter_m = pooled_metrics.get("adaptive_hunter", {})
    baseline_candidates = {k: v for k, v in pooled_metrics.items()
                           if k not in ("random_control", "adaptive_hunter")
                           and not k.startswith("consensus_")}
    baseline_consensus_id = f"consensus_k{cfg.agree_min}"
    baseline_id = (baseline_consensus_id if baseline_consensus_id in baseline_candidates
                   else max(baseline_candidates,
                            key=lambda k: baseline_candidates[k].get("avg_net_bps", float("-inf")),
                            default=None))
    comparison = {
        "baseline_method": baseline_id,
        "baseline": pooled_metrics.get(baseline_id, {}),
        "adaptive_hunter": hunter_m,
        "random_control": control_m,
        "hunter_minus_baseline_avg_net_bps": (
            round(hunter_m.get("avg_net_bps", 0) - pooled_metrics[baseline_id].get("avg_net_bps", 0), 2)
            if baseline_id and hunter_m.get("n") else None),
        "hunter_minus_control_avg_net_bps": (
            round(hunter_m.get("avg_net_bps", 0) - control_m.get("avg_net_bps", 0), 2)
            if hunter_m.get("n") and control_m.get("n") else None),
    }

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
        "adaptive_hunter": {"enabled": cfg.adaptive_hunter,
                            "min_score": cfg.hunter_min_score,
                            "comparison": comparison,
                            "per_seed": hunter_by_seed},
        "calibration_conf_vs_hit": calib,
        "files": {"signals": sig_path, "outcomes": out_path},
    }

    with open(os.path.join(cfg.out_dir, f"report_{cfg.run_id}.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    from .report import write_markdown
    write_markdown(report, os.path.join(cfg.out_dir, f"report_{cfg.run_id}.md"))
    return report
