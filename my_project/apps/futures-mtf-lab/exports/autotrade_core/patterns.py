"""«تیم‌ها» / الگوهای قابل مقایسه — همه روی یک تایم‌فریم.

چرا جدا: هم داشبورد و هم API مستقل باید **همان** فهرست الگوها را ببینند. اگر
فهرست در دو جا نوشته شود، دیر یا زود با هم فرق می‌کنند.
"""
from __future__ import annotations

from typing import List, Tuple

from .config import PRESETS

def variants_for(tf_trigger: str, tf_filter: str, tf_bias: str) -> List[Tuple[str, str, dict]]:
    """نسخه‌ها: (شناسه، برچسب، overrides).

    همه روی **همان** تایم‌فریم اجرا می‌شوند تا اختلاف فقط از «منطق» بیاید، نه از
    تعداد معامله یا هزینه. این نکته‌ای است که در آزمون‌های قبلی رعایت نشده بود.
    """
    base_tf = {"tf_trigger": tf_trigger, "tf_filter": tf_filter, "tf_bias": tf_bias}
    preset_trend = dict(PRESETS["trend_4h"])
    # پریست trend_4h تایم‌فریم خودش را دارد؛ اینجا به تایم‌فریم اسکن تحمیل می‌شود
    preset_trend.pop("tf_trigger", None)
    preset_trend.pop("tf_filter", None)
    preset_trend.pop("tf_bias", None)

    return [
        ("base", "پایه (همان تایم‌فریم اسکن)", dict(base_tf)),
        ("trend", "روندکاوی: شکست + بدون TP + تریل باز",
         dict(base_tf, **preset_trend)),
        ("trend_tp", "روندکاوی + TP ثابت 6×ATR (برای سنجش اثر TP)",
         dict(base_tf, **dict(preset_trend, take_profit_atr_mult=6.0))),
        ("pullback", "فقط pullback (فرضیهٔ ۱ ساله — باید رد شود)",
         dict(base_tf, trigger_entry_modes=["pullback"])),
        ("climax", "ردِ کندل اوج (فرضیهٔ ۱ ساله — باید رد شود)",
         dict(base_tf, trigger_max_range_atr=1.0)),
    ]
