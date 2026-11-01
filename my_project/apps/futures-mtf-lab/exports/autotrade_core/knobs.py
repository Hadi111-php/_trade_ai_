"""تنظیماتی که کاربر می‌تواند دست بزند — بدون هیچ وابستگی به موتور یا داشبورد.

این ماژول عمداً «فقط داده و تبدیل نوع» است تا:

  • داشبورد و API و بستهٔ مستقل همه از **یک** فهرست بخوانند (یک منبع حقیقت)،
  • و کسی که فقط می‌خواهد الگوریتم‌ها را به داشبورد خودش وصل کند، مجبور نباشد
    کل کارگاه را import کند.

هر کلید بیرون این فهرست نادیده گرفته می‌شود؛ هر مقدار بیرون بازه به بازه برمی‌گردد.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

KNOBS: List[dict] = [
    # ── ریسک و اندازه ────────────────────────────────────────────────────
    dict(k="risk_per_trade_pct", fa="ریسک هر معامله (٪ موجودی)", g="ریسک",
         t="float", lo=0.1, hi=5.0, st=0.1, unit="%",
         note="بزرگ‌تر = سود و ضرر هر دو بزرگ‌تر؛ روی تعداد معامله اثری ندارد."),
    dict(k="max_concurrent", fa="حداکثر پوزیشن هم‌زمان", g="ریسک",
         t="int", lo=1, hi=5, st=1, unit="",
         note="۱ = تک‌پوزیشن. بالا بردنش سیگنال‌های بیشتری را می‌گیرد ولی ریسک را جمع می‌کند."),
    dict(k="daily_loss_limit_pct", fa="سقف ضرر روزانه", g="ریسک",
         t="float", lo=0.0, hi=50.0, st=0.5, unit="%",
         note="۰ = خاموش."),
    dict(k="cb_losses", fa="فیوز: چند ضرر پیاپی", g="ریسک",
         t="int", lo=1, hi=10, st=1, unit="ضرر", note=""),
    dict(k="cb_cooldown_bars", fa="فیوز: چند کندل توقف", g="ریسک",
         t="int", lo=0, hi=100, st=1, unit="کندل", note=""),
    dict(k="cooldown_bars_after_loss", fa="استراحت بعد از هر ضرر", g="ریسک",
         t="int", lo=0, hi=50, st=1, unit="کندل", note=""),
    # ── خروج ─────────────────────────────────────────────────────────────
    dict(k="stop_atr_mult", fa="حد ضرر (×ATR)", g="خروج",
         t="float", lo=0.3, hi=5.0, st=0.1, unit="ATR",
         note="کوچک‌تر = ضرر کمتر ولی استاپ‌خوردن بیشتر (نویز)."),
    dict(k="trail_enabled", fa="تریلینگ استاپ روشن", g="خروج", t="bool", note=""),
    dict(k="trail_atr_mult", fa="فاصلهٔ تریلینگ (×ATR)", g="خروج",
         t="float", lo=0.5, hi=10.0, st=0.5, unit="ATR",
         note="تنگ‌تر = سود زودتر قفل می‌شود و روندهای بزرگ قطع می‌شوند."),
    dict(k="trail_start_r", fa="تریلینگ از چند R", g="خروج",
         t="float", lo=0.0, hi=5.0, st=0.5, unit="R", note=""),
    dict(k="take_profit_atr_mult", fa="حد سود (×ATR)", g="خروج",
         t="float", lo=1.0, hi=60.0, st=1.0, unit="ATR",
         note="۵۰ = عملاً خاموش. با این ساختار «قرعه‌کشی»، حد سود سخت برنده‌ها را می‌کشد."),
    dict(k="breakeven_at_r", fa="انتقال استاپ به سربه‌سر در R", g="خروج",
         t="float", lo=0.0, hi=5.0, st=0.5, unit="R", note="۰ = خاموش."),
    dict(k="partial_take_r", fa="برداشت جزئی در R", g="خروج",
         t="float", lo=0.0, hi=5.0, st=0.5, unit="R", note="۰ = خاموش."),
    dict(k="partial_take_frac", fa="کسر برداشت جزئی", g="خروج",
         t="float", lo=0.1, hi=0.9, st=0.1, unit="", note=""),
    dict(k="max_holding_bars", fa="سقف زمان نگه‌داری", g="خروج",
         t="int", lo=0, hi=200, st=10, unit="کندل", note="۰ = بدون سقف."),
    dict(k="giveback_arm_r", fa="قاعدهٔ افت سود: مسلح‌شدن در R", g="خروج",
         t="float", lo=0.0, hi=10.0, st=0.5, unit="R",
         note="۰ = خاموش. (در آزمون قبلی ۱۰× تنگ‌تر از تریلینگ بود و سود را نابود کرد.)"),
    dict(k="giveback_frac", fa="قاعدهٔ افت سود: کسر اوج", g="خروج",
         t="float", lo=0.0, hi=0.95, st=0.05, unit="", note=""),
    dict(k="regime_change_exit", fa="خروج با چرخش رژیم", g="خروج", t="bool", note=""),
    # ── فیلترها و ورود ───────────────────────────────────────────────────
    dict(k="filter_adx_min", fa="حداقل ADX فیلتر", g="ورود",
         t="float", lo=0.0, hi=50.0, st=1.0, unit="",
         note="۰ = خاموش. بالاتر = فقط روندهای قوی."),
    dict(k="filter_slope_min_pct", fa="حداقل شیب EMA (٪)", g="ورود",
         t="float", lo=0.0, hi=3.0, st=0.05, unit="%", note=""),
    dict(k="min_edge_multiplier", fa="حداقل لبه نسبت به هزینه", g="ورود",
         t="float", lo=0.0, hi=5.0, st=0.25, unit="×",
         note="کمتر از ۱ یعنی سیگنالی که هزینه‌اش را هم درنمی‌آورد رد نمی‌شود."),
    dict(k="min_confidence", fa="حداقل اطمینان تصمیم", g="ورود",
         t="float", lo=0.0, hi=1.0, st=0.05, unit="", note=""),
    dict(k="trigger_max_range_atr", fa="سقف دامنهٔ کندل تریگر (×ATR)", g="ورود",
         t="float", lo=0.0, hi=6.0, st=0.1, unit="ATR",
         note="۰ = خاموش. ۰.۵ = جلوی ورود در کندل‌های انفجاری را می‌گیرد."),
    dict(k="entry_on_next_open", fa="ورود در open کندل بعد", g="ورود", t="bool",
         note="محافظه‌کارانه‌تر (بدون فرض اجرا در close همان کندل)."),
    # ── ساختار ───────────────────────────────────────────────────────────
    dict(k="alignment_version", fa="نسخهٔ هم‌راستایی", g="ساختار", t="choice",
         choices=["A", "B", "C"],
         note="A سخت‌گیر، B امتیازی، C فقط فیلتر رژیم (بیشترین سیگنال)."),
    dict(k="bias_enabled", fa="لایهٔ بایاس روشن", g="ساختار", t="bool", note=""),
    dict(k="trigger_entry_modes", fa="الگوی ورود", g="ساختار", t="modes",
         note="breakout = شکست؛ pullback = بازگشت به میانگین."),
]

KNOB_INDEX = {k["k"]: k for k in KNOBS}


def _coerce(knob: dict, raw) -> Optional[object]:
    """مقدار ورودی کاربر را به نوع درست تبدیل و در بازهٔ مجاز نگه می‌دارد."""
    t = knob["t"]
    try:
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "on", "yes", "بله")
        if t == "int":
            v = int(round(float(raw)))
        elif t == "float":
            v = float(raw)
        elif t == "choice":
            v = str(raw).strip().upper()
            return v if v in knob["choices"] else None
        elif t == "modes":
            if isinstance(raw, str):
                raw = [x for x in raw.replace("،", ",").split(",") if x.strip()]
            out = [str(x).strip() for x in raw if str(x).strip() in ("breakout", "pullback")]
            return sorted(set(out)) or None
        else:
            return None
    except (TypeError, ValueError):
        return None
    if t in ("int", "float"):
        return max(knob["lo"], min(knob["hi"], v))
    return v


def sanitize_overrides(raw: dict) -> Tuple[dict, List[str]]:
    """فقط کلیدهای مجاز؛ بقیه با هشدار برگردانده می‌شوند (نادیده گرفته می‌شوند)."""
    clean, ignored = {}, []
    for k, v in (raw or {}).items():
        knob = KNOB_INDEX.get(k)
        if not knob:
            ignored.append(k)
            continue
        val = _coerce(knob, v)
        if val is not None:
            clean[k] = val
    return clean, ignored
