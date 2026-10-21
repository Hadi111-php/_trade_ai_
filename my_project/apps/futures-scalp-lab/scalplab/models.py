"""خانواده‌های مدل سیگنال — عمداً متنوع تا «توافق» معنادار باشد.

هر مدل فقط از اسنپ‌شات لحظهٔ t (و نه آینده) استفاده می‌کند و
(direction ∈ {-1,0,1}, confidence ∈ [0,1], reason) برمی‌گرداند.
مدل random_control به‌عنوان خط پایهٔ آماری همیشه حضور دارد.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

MODEL_VERSION = "2026-08-26.1"


@dataclass
class Signal:
    i: int
    ts: int
    model_id: str
    family: str
    direction: int
    confidence: float
    reason: str
    entry_price: float
    snapshot: dict
    params: dict = field(default_factory=dict)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


class BaseModel:
    id = "base"
    family = "base"

    def __init__(self, params: dict, rng: random.Random):
        self.params = params
        self.rng = rng

    def maybe_signal(self, i: int, ts: int, snap: dict, prev: Optional[dict],
                     price: float) -> Optional[Tuple[int, float, str]]:
        raise NotImplementedError


class EmaCross(BaseModel):
    id, family = "ema_cross", "trend"

    def maybe_signal(self, i, ts, snap, prev, price):
        gap = (snap["ema_fast"] - snap["ema_slow"]) / price
        scale = max(snap["atr_pct"] / 100, 1e-6)
        if abs(gap) < 0.25 * scale:
            return None
        d = 1 if gap > 0 else -1
        return d, _clip(0.5 + abs(gap) / (2 * scale)), "ema gap"


class RsiReversion(BaseModel):
    id, family = "rsi_reversion", "meanrev"

    def maybe_signal(self, i, ts, snap, prev, price):
        r = snap["rsi"]
        lo, hi = self.params["rsi_low"], self.params["rsi_high"]
        if r <= lo:
            return 1, _clip(0.5 + (lo - r) / 40), "rsi oversold"
        if r >= hi:
            return -1, _clip(0.5 + (r - hi) / 40), "rsi overbought"
        return None


class DonchianBreakout(BaseModel):
    id, family = "donchian_breakout", "momentum"

    def maybe_signal(self, i, ts, snap, prev, price):
        atr_abs = snap["atr_pct"] / 100 * price
        if price > snap["donch_up"]:
            m = (price - snap["donch_up"]) / atr_abs if atr_abs else 0
            return 1, _clip(0.55 + 0.2 * m), "breakout up"
        if price < snap["donch_dn"]:
            m = (snap["donch_dn"] - price) / atr_abs if atr_abs else 0
            return -1, _clip(0.55 + 0.2 * m), "breakout down"
        return None


class BollingerSqueeze(BaseModel):
    id, family = "bb_squeeze", "volatility"

    def __init__(self, params, rng):
        super().__init__(params, rng)
        self.widths: List[float] = []

    def maybe_signal(self, i, ts, snap, prev, price):
        self.widths.append(snap["bb_width"])
        if len(self.widths) > self.params["bb_lookback"]:
            self.widths.pop(0)
        if len(self.widths) < self.params["bb_lookback"]:
            return None
        rank = sorted(self.widths).index(snap["bb_width"]) / len(self.widths)
        if rank > 0.25:                      # فقط وقتی پیچش volatilite جدی است
            return None
        d = 1 if snap["bb_pos"] > 0.5 else -1
        return d, _clip(0.55 + 0.4 * (0.25 - rank)), "vol squeeze"


class MacdFlip(BaseModel):
    id, family = "macd_flip", "trend"

    def maybe_signal(self, i, ts, snap, prev, price):
        h, hp = snap.get("macd_hist"), prev.get("macd_hist") if prev else None
        if h is None or hp is None:
            return None
        scale = max(snap["atr_pct"] / 100 * price, 1e-9)
        if hp <= 0 < h:
            return 1, _clip(0.5 + abs(h) / scale * 0.5), "macd flip up"
        if hp >= 0 > h:
            return -1, _clip(0.5 + abs(h) / scale * 0.5), "macd flip down"
        return None


class RandomControl(BaseModel):
    """خط پایه: جهت تصادفی با کادنس مشابه؛ هر برتری باید از این بهتر باشد."""
    id, family = "random_control", "control"

    def maybe_signal(self, i, ts, snap, prev, price):
        if self.rng.random() > self.params["control_rate"]:
            return None
        d = 1 if self.rng.random() < 0.5 else -1
        return d, 0.5 + 0.5 * self.rng.random(), "coin flip"


REAL_MODELS = [EmaCross, RsiReversion, DonchianBreakout, BollingerSqueeze, MacdFlip]
ALL_MODELS = REAL_MODELS + [RandomControl]


def build_models(params: dict, seed: int) -> List[BaseModel]:
    import zlib  # seed پایدار بین اجراها (hash رشته در پایتون salt دارد!)
    return [cls(params, random.Random(seed + zlib.crc32(cls.id.encode())))
            for cls in ALL_MODELS]
