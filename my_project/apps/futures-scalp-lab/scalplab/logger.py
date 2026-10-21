"""ثبت کامل سیگنال‌ها و پیامدها در JSONL — هر سیگنال با تمام اطلاعات لحظهٔ صدور."""
from __future__ import annotations

import json
import os
from typing import List

from .models import Signal


class JsonlWriter:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")

    def write(self, obj: dict):
        self.f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def close(self):
        self.f.close()


def signal_to_record(sig: Signal, cfg, seed: int) -> dict:
    return {
        "run_id": cfg.run_id, "seed": seed,
        "data_mode": cfg.data_mode, "symbol": cfg.symbol, "timeframe": cfg.timeframe,
        "i": sig.i, "ts": sig.ts,
        "model_id": sig.model_id, "model_family": sig.family,
        "model_version": sig.params.get("model_version"),
        "direction": sig.direction, "confidence": round(sig.confidence, 4),
        "reason": sig.reason, "entry_price": sig.entry_price,
        "fee_bps": cfg.fee_bps, "horizon": cfg.horizon,
        "indicators": sig.snapshot, "params": sig.params,
    }
