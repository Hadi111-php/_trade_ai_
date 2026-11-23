"""اختیاری: امتیازدهندهٔ Adaptive Hunter با به‌روزرسانی علّی وزن‌ها.

هر یادگیری فقط هنگام رسیدن کندل پایان افق همان پیش‌بینی انجام می‌شود؛
قبل از آن هیچ پیامد آینده‌ای برای امتیازدهی در دسترس نیست.
"""
from __future__ import annotations

import math
from typing import Dict, List


class AdaptiveHunter:
    def __init__(self, model_ids, learning_rate: float = 0.12,
                 min_weight: float = 0.25, max_weight: float = 4.0,
                 min_score: float = 0.55):
        self.weights: Dict[str, float] = {model_id: 1.0 for model_id in model_ids}
        self.learning_rate = learning_rate
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.min_score = min_score
        self.pending: List[dict] = []
        self.updates: List[dict] = []

    def queue(self, signal_i: int, model_id: str, direction: int, entry: float,
              horizon: int, fee_frac: float, candle_count: int) -> None:
        due_i = signal_i + horizon
        if due_i < candle_count:
            self.pending.append({"signal_i": signal_i, "due_i": due_i,
                                 "model_id": model_id, "direction": direction,
                                 "entry": entry, "fee_frac": fee_frac})

    def advance(self, i: int, candles) -> List[dict]:
        """Resolve only labels whose full horizon has elapsed by bar i."""
        matured, waiting = [], []
        for item in self.pending:
            (matured if item["due_i"] <= i else waiting).append(item)
        self.pending = waiting
        resolved = []
        for item in matured:
            before = self.weights[item["model_id"]]
            exit_price = candles[item["due_i"]].c
            ret_net_bps = (item["direction"] *
                           (exit_price - item["entry"]) / item["entry"] -
                           item["fee_frac"]) * 10_000
            # Bounded multiplicative update, so a single outlier cannot dominate.
            reward = max(-1.0, min(1.0, ret_net_bps / 100.0))
            after = max(self.min_weight, min(self.max_weight,
                          before * math.exp(self.learning_rate * reward)))
            self.weights[item["model_id"]] = after
            event = {"model_id": item["model_id"], "signal_i": item["signal_i"],
                     "outcome_i": item["due_i"], "updated_at_i": i,
                     "ret_net_bps": round(ret_net_bps, 4),
                     "weight_before": round(before, 6),
                     "weight_after": round(after, 6)}
            self.updates.append(event)
            resolved.append(event)
        return resolved

    def score(self, votes):
        """votes: tuples (model_id, direction, confidence). Returns side, score."""
        usable = [(mid, direction, confidence) for mid, direction, confidence in votes
                  if direction in (-1, 1) and mid in self.weights]
        denom = sum(self.weights[mid] * max(0.0, confidence)
                    for mid, _, confidence in usable)
        if denom <= 0:
            return 0, 0.0
        signed = sum(self.weights[mid] * max(0.0, confidence) * direction
                     for mid, direction, confidence in usable)
        strength = abs(signed) / denom
        if strength < self.min_score:
            return 0, round(strength * 100, 2)
        return (1 if signed > 0 else -1), round(strength * 100, 2)
