"""نظاره‌گر — پلِ **یک‌طرفه** از اتوترید به مغز.

قاعدهٔ معماری: الگوریتم‌یاب حاکم است. این کلاس فقط دو کار می‌کند:

  • دیدگاه مغز را برای یک نماد/کندل می‌خواند (`view`) تا در ژورنال **ثبت** شود.
  • وضعیت فعلی همهٔ نمادها را برای «قبل از سیگنال» می‌دهد (`views_now`).

و یک کار را هرگز نمی‌کند: **تصمیم را عوض نمی‌کند.** هیچ تابع تصمیم‌گیری این
کلاس را صدا نمی‌زند؛ فقط `live.py` هنگام ساختن رکورد `open` از آن می‌خواند.
تست `test_brain_observer_is_read_only` ثابت می‌کند حتی دیدگاه‌های افراطی هم
یک معامله را جابه‌جا نمی‌کنند.

همچنین این لایه ضدخطاست: هر استثنایی در مغز، به یک رکورد
`{"available": False, "reason": ...}` تبدیل می‌شود، هرگز به خطای معامله.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .brainview import build_arrays, load_model, view_at, view_now
from .config import MTFConfig
from .data import Candle

OFF = {"available": False, "reason": "observer-off"}
NO_MODEL = {"available": False, "reason": "no-model"}


class BrainObserver:
    """قرائت‌کنندهٔ فقط‌خواندنیِ دیدگاه مغز (با کش، بدون شبکه، بدون خطا)."""

    def __init__(self, model_path: str = "results/brain_model.json",
                 cfg: Optional[MTFConfig] = None):
        self.model_path = model_path
        self.cfg = cfg
        self.model = load_model(model_path) if model_path else None
        self.errors = 0
        self.calls = 0
        self._arr: Dict[str, tuple] = {}

    @property
    def available(self) -> bool:
        return self.model is not None

    def describe(self) -> str:
        if not self.available:
            return "مغز در دسترس نیست (مدل ساخته نشده)"
        m = self.model
        oof = (m.get("oof") or {})
        return (f"مغز فعال · brainview {m.get('version')} · "
                f"آموزش تا {m.get('trained_through_ts')} · "
                f"AUC بیرون‌نمونه {oof.get('auc')}")

    # -- داخلی -------------------------------------------------------------
    def _arrays(self, symbol: str, candles: Sequence[Candle]):
        if not candles:
            return None
        key = (len(candles), candles[-1].open_time_ms)
        hit = self._arr.get(symbol)
        if hit and hit[0] == key:
            return hit[1]
        arr = build_arrays(candles, self.cfg)
        self._arr[symbol] = (key, arr)
        return arr

    # -- عمومی -------------------------------------------------------------
    def view(self, symbol: str, candles: Sequence[Candle], i: int) -> dict:
        """دیدگاه در خانهٔ i. هر خطایی ⇒ رکورد «در دسترس نیست»، نه استثنا."""
        if not self.available:
            return dict(NO_MODEL)
        self.calls += 1
        try:
            arr = self._arrays(symbol, candles)
            if arr is None:
                return {"available": False, "reason": "no-candles"}
            v = view_at(self.model, arr, i)
            if v is None:
                return {"available": False, "reason": "warmup"}
            return v
        except Exception as e:                                     # noqa: BLE001
            self.errors += 1
            return {"available": False, "reason": f"error:{type(e).__name__}"}

    def views_now(self, universe: Dict[str, Sequence[Candle]]) -> Dict[str, dict]:
        """دیدگاه روی آخرین کندل بستهٔ هر نماد — «ایدهٔ قبل از سیگنال»."""
        out: Dict[str, dict] = {}
        for sym in sorted(universe):
            cs = universe[sym]
            if not self.available:
                out[sym] = dict(NO_MODEL)
                continue
            try:
                out[sym] = view_now(self.model, cs, self.cfg)
            except Exception as e:                                 # noqa: BLE001
                self.errors += 1
                out[sym] = {"available": False, "reason": f"error:{type(e).__name__}"}
        return out

    def stats(self) -> dict:
        return {"available": self.available, "calls": self.calls,
                "errors": self.errors,
                "model": (self.model or {}).get("version")}
