"""کاتالوگ الگوریتم‌ها — «هر الگو دقیقاً چه می‌کند و با چه عددی؟»

چرا این فایل: کاربر باید بتواند بدون خواندن کد ببیند هر الگو چه فرمولی دارد و
**مقدار الانِ** پارامترهایش چقدر است. اگر این متن دستی نوشته شود، بعد از هر تغییر
پارامتر از واقعیت جدا می‌شود؛ پس همه‌چیز از خودِ کد خوانده می‌شود:

* الگوهای MTF → `patterns.variants_for` + `MTFConfig` واقعی
* V10 Pro → `v10pro.PARAMS` (و اگر `config/v10_settings.json` باشد، همان)
* قواعد بستن → `rules.RULE_META`
* پامپ و دامپ → `pumpdump.DEFAULTS`

فرمول‌ها به دو شکل می‌آیند: `expr` (نمادین) و `values` (با عدد واقعیِ همین حالا).
هیچ‌کدام ادعای سود نیستند؛ فقط «سیستم چه می‌کند» را نشان می‌دهند.
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Dict, List, Optional

VERSION = "1.0"


def _fmt(x) -> str:
    if isinstance(x, bool):
        return "روشن" if x else "خاموش"
    if isinstance(x, float):
        if abs(x) >= 100:
            return f"{x:,.2f}"
        return f"{x:.4g}"
    if x is None:
        return "—"
    return str(x)


def _tp_text(v) -> str:
    """حد سود را صادقانه بنویس: ۰ = خاموش، ۵۰×ATR = عملاً خاموش."""
    v = float(v or 0)
    if v <= 0:
        return "بدون TP"
    if v >= 50:
        return f"{_fmt(v)}×ATR (عملاً بدون TP)"
    return f"{_fmt(v)}×ATR"


def _lim(x, off_word: str = "خاموش") -> str:
    """پارامتر «آستانه‌ای» که صفر یعنی خاموش — تا «۰×ATR» گمراه‌کننده نباشد."""
    try:
        if float(x) == 0:
            return off_word
    except (TypeError, ValueError):
        pass
    return _fmt(x)


def _params(cfg, names: List[str]) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for n in names:
        if hasattr(cfg, n):
            out[n] = getattr(cfg, n)
    return out


# ══════════════════════════════════════════════════════════════════════════
#  الگوهای MTF
# ══════════════════════════════════════════════════════════════════════════
_MTF_NOTES = {
    "base": ("پایه", "همان تصمیم موتور با تنظیمات پیش‌فرض روی همین تایم‌فریم. "
                     "خط پایهٔ مقایسه است: هر الگوی دیگر باید از این بهتر باشد."),
    "trend": ("روندکاوی", "بدون حد سود ثابت؛ برداشتن سود با تریلینگ استاپ. "
                           "فرض: روندهای بزرگ را کامل بگیریم."),
    "trend_tp": ("روندکاوی + TP", "همان روندکاوی با حد سود ثابت ۶×ATR — "
                                    "برای سنجش اینکه TP سود را می‌کشد یا نجات می‌دهد."),
    "pullback": ("فقط pullback", "فقط ورود در پولبک به میانگین؛ شکست‌ها را رد می‌کند. "
                                  "فرضیهٔ آزمایشی — اگر رد شود، حذف می‌شود."),
    "climax": ("ردِ کندل اوج", "کندلی که خودش بیشترِ حرکت را کرده وارد نمی‌شود "
                               "(ضد دنبال‌کردن قیمت). فرضیهٔ آزمایشی."),
}


def _mtf_section(cfg, variants, trend_preset: Optional[dict] = None) -> dict:
    items: List[dict] = []
    for vid, label, ov in variants:
        c = replace(cfg, **{k: v for k, v in (ov or {}).items()
                            if k in cfg.__dataclass_fields__})
        short, summary = _MTF_NOTES.get(vid, (label, "—"))
        formulas = [
            {"title": "۱) لایهٔ بایاس (جهت کلان)",
             "expr": ("bias.dir = جهت EMA روی تایم‌فریم بالا، اگر شیب ≥ آستانه؛ "
                      "وگرنه رژیم unknown"),
             "values": (f"EMA {c.bias_ema_period} · شیب {c.bias_slope_bars} کندل ≥ "
                        f"{_fmt(c.bias_slope_min_pct)}٪ · "
                        f"Donchian {c.bias_donchian_window} · "
                        f"{'فعال' if c.bias_enabled else 'خاموش'}")},
            {"title": "۲) لایهٔ فیلتر (رژیم)",
             "expr": "filter.dir = جهت رژیم؛ رژیم از ADX و شیب میانگین",
             "values": (f"ADX({c.filter_adx_period}) ≥ {_fmt(c.filter_adx_min)} · "
                        f"EMA {c.filter_ema_fast_period}/{c.filter_ema_period} · "
                        f"شیب {c.filter_slope_bars} کندل ≥ "
                        f"{_fmt(c.filter_slope_min_pct)}٪ · "
                        f"تأیید {c.filter_confirm_bars} کندل")},
            {"title": "۳) لایهٔ تریگر (نقطهٔ ورود)",
             "expr": ("pullback: |close − EMA| ≤ k×ATR و RSI در محدوده\n"
                      "breakout: شکست کانال Donchian(20) با تأیید حجم"),
             "values": (f"k = {_fmt(c.trigger_pullback_atr)}×ATR({c.trigger_atr_period}) · "
                        f"EMA {c.trigger_ema_period} · "
                        f"RSI({c.trigger_rsi_period}) خرید ≤ {_fmt(c.trigger_rsi_long_max)} / "
                        f"فروش ≥ {_fmt(c.trigger_rsi_short_min)} · "
                        f"Donchian {c.trigger_donchian_window} · "
                        f"z حجم ≥ {_fmt(c.trigger_vol_z_min)} · "
                        f"سقف دامنه {_lim(c.trigger_max_range_atr, 'بی‌سقف')}"
                        + ("×ATR" if float(c.trigger_max_range_atr or 0) else ""))},
            {"title": "۴) هم‌راستایی + دروازهٔ هزینه",
             "expr": ("ENTER اگر bias ∧ filter ∧ trigger هم‌جهت باشند\n"
                      "و حرکت مورد انتظار ≥ edge_mult × هزینهٔ رفت‌وبرگشت"),
             "values": (f"edge × {_fmt(c.edge_atr_mult)}·ATR · حداقل ضریب "
                        f"{_fmt(c.min_edge_multiplier)} · "
                        f"کارمزد {_fmt(getattr(c, 'fee_bps', None))}bps + "
                        f"اسلیپیج {_fmt(getattr(c, 'slippage_pct', None))}٪")},
            {"title": "۵) ریسک و خروج",
             "expr": ("حد ضرر = entry ∓ ATR_mult×ATR · حد سود = R×ریسک (اگر روشن) · "
                      "تریلینگ در R مشخص · سقف زمان = N کندل"),
             "values": (f"SL {_fmt(c.stop_atr_mult)}×ATR · "
                        f"TP {_tp_text(c.take_profit_atr_mult)} · "
                        f"تریل {'روشن' if c.trail_enabled else 'خاموش'} از "
                        f"{_fmt(c.trail_start_r)}R با {_fmt(c.trail_atr_mult)}×ATR · "
                        f"سربه‌سر {_fmt(c.breakeven_at_r)}R · "
                        f"برداشت جزئی {_lim(c.partial_take_r)}"
                        + (f"R/{_fmt(c.partial_take_frac)}" if float(c.partial_take_r or 0) else "")
                        + f" · سقف {_lim(c.max_holding_bars, 'بدون سقف')}"
                        + (" کندل" if int(c.max_holding_bars or 0) else ""))},
        ]
        items.append({
            "id": vid, "label": f"{label}", "short": short, "summary": summary,
            "kind": "ورود", "active": True,
            "formulas": formulas,
            "params": _params(c, ["trigger_entry_modes", "take_profit_atr_mult",
                                  "trail_enabled", "trail_start_r",
                                  "trail_atr_mult", "breakeven_at_r",
                                  "partial_take_r", "max_holding_bars",
                                  "stop_atr_mult", "trigger_max_range_atr"]),
            "source": "mtflab/signals.py → decide() · فهرست: mtflab/patterns.py",
        })
    return {"id": "mtf", "title": "الگوهای MTF (پنج نسخهٔ قابل مقایسه)",
            "note": ("همه روی همان تایم‌فریم و با همان هزینه اجرا می‌شوند تا اختلاف "
                     "فقط از منطق بیاید. «رأی» هر الگو در ژورنال ثبت می‌شود."),
            "items": items}


# ══════════════════════════════════════════════════════════════════════════
#  V10 Pro
# ══════════════════════════════════════════════════════════════════════════
def _v10_item() -> dict:
    from .v10pro import PARAMS, load_settings

    sett = load_settings("config/v10_settings.json")
    p = dict(PARAMS, **(sett.get("params") or {}))
    cost_side = float(p["fee_rate"]) + float(p["slippage"])
    formulas = [
        {"title": "۱) باند بولینگر",
         "expr": "mid = SMA(close, N) · σ = انحراف معیار(N) · upper/lower = mid ± k·σ",
         "values": f"N = {p['bb_period']} · k = {_fmt(float(p['bb_std']))}"},
        {"title": "۲) RSI وایلد‌ر",
         "expr": "RSI = 100 − 100/(1 + میانگین سود/میانگین ضرر)",
         "values": f"دوره = {p['rsi_period']} · آستانهٔ خرید ≤ {_fmt(float(p['rsi_oversold']))} · "
                   f"فروش ≥ {_fmt(float(p['rsi_overbought']))}"},
        {"title": "۳) شرط ورود (بازگشت به میانگین)",
         "expr": ("LONG: close[i−1] < lower[i−1] و close[i] > lower[i] و "
                  "close[i] > open[i] و RSI[i−1] ≤ OS و حجم[i] ≥ m×SMA(حجم)\n"
                  "SHORT: آینهٔ همان روی باند بالا"),
         "values": f"m = {_fmt(float(p['volume_multiplier']))}× · SMA حجم {p['vol_sma_period']} · "
                   f"حداقل پاداش {_fmt(float(p['min_reward_pct']))}٪"},
        {"title": "۴) حد ضرر و حد سود",
         "expr": ("SL(LONG) = min(low[i−1], low[i]) − b×ATR\n"
                  "SL(SHORT) = max(high[i−1], high[i]) + b×ATR\n"
                  "TP = entry ± R×|entry − SL|"),
         "values": f"b = {_fmt(float(p['atr_buffer']))}×ATR({p['atr_period']}) · "
                   f"R = {_fmt(float(p['rr_ratio']))}"},
        {"title": "۵) مدیریت خروج",
         "expr": ("سپر سربه‌سر در ۱R · خروج پویا در باند میانی · سقف زمان\n"
                  "هزینهٔ هر طرف = کارمزد + اسلیپیج"),
         "values": (f"سربه‌سر {_fmt(1.0)}R · باند میانی "
                    f"{'روشن' if p.get('bb_mid_exit') else 'خاموش'} · "
                    f"سقف {int(p['time_stop_bars'])} کندل · "
                    f"هزینه {_fmt(cost_side * 100)}٪ هر طرف")},
    ]
    return {
        "id": "v10pro", "label": "V10 Pro (بازگشت به میانگین)", "short": "V10",
        "summary": ("سناریوی بیرونی: قیمت از باند بیرون زده و با کندل بازگشتی و "
                    "حجم بالا برگشته داخل. دو جهت. پیش‌فرض با ورود در کندل بعد."),
        "kind": "ورود", "active": True, "formulas": formulas,
        "params": {k: v for k, v in p.items()},
        "source": "mtflab/v10pro.py · تنظیمات: config/v10_settings.json",
        "settings_found": bool(sett.get("found")),
    }


# ══════════════════════════════════════════════════════════════════════════
#  قواعد بستن
# ══════════════════════════════════════════════════════════════════════════
_EXIT_FORMULAS = {
    "stop_loss": ("قیمت ≤ SL (خرید) یا ≥ SL (فروش)", "SL = entry − mult×ATR"),
    "stop_trail": ("قیمت به استاپِ متحرک برسد", "trail = بهترین قیمت − k×ATR"),
    "breakeven": ("قیمت به entry برگردد بعد از رسیدن به آستانه", "SL → entry"),
    "giveback": ("سود شناور به‌اندازهٔ آستانه پس داده شود", "exit اگر (MFE − سود) ≥ g×R"),
    "regime_flip": ("رژیم لایهٔ فیلتر برعکس شود (تأییدشده)", "dir_filter تغییر کند"),
    "time_stop": ("تعداد کندل نگه‌داری از سقف بگذرد", "bars ≥ N"),
    "take_profit": ("قیمت به TP برسد", "TP = entry + R×risk"),
    "partial_take": ("قیمت به سطح برداشت جزئی برسد", "level = entry + r×risk"),
    "manual": ("کاربر دستی بست", "—"),
    "end_of_data": ("داده تمام شد", "—"),
}


def _exits_section(cfg) -> dict:
    from .rules import RULE_META

    items = []
    for key, (kind, fa, en, risk) in RULE_META.items():
        expr, values = _EXIT_FORMULAS.get(key, ("—", "—"))
        items.append({
            "id": key, "label": fa, "short": kind,
            "summary": ("قاعدهٔ کنترلی — برای کم‌کردن ضرر" if risk
                        else "قاعدهٔ خروج عادی"),
            "kind": "خروج", "active": True,
            "formulas": [{"title": fa, "expr": expr, "values": values}],
            "params": {"is_risk_control": risk},
            "source": "mtflab/engine.py manage_position · mtflab/rules.py",
        })
    return {"id": "exits", "title": "قواعد بستن معامله",
            "note": (f"سقف زمان فعلی "
                     + (f"{int(cfg.max_holding_bars)} کندل"
                        if int(cfg.max_holding_bars or 0) else "بدون سقف")
                     + f" · افت سود از {_lim(cfg.giveback_arm_r)}R با کسر "
                     f"{_fmt(cfg.giveback_frac)} · "
                     f"تریل از {_fmt(cfg.trail_start_r)}R"),
            "items": items}


# ══════════════════════════════════════════════════════════════════════════
#  پامپ و دامپ (مستقل)
# ══════════════════════════════════════════════════════════════════════════
def _pump_section() -> dict:
    try:
        from .pumpdump import DEFAULTS
    except Exception:                                              # noqa: BLE001
        return {"id": "pump", "title": "پامپ و دامپ", "items": [],
                "note": "ماژول در دسترس نیست"}
    d = dict(DEFAULTS)
    formulas = [
        {"title": "تشخیص رویداد",
         "expr": ("دامنه = high − low\n"
                  "پامپ: دامنه ≥ a×میانگین(lookback) و حجم ≥ b×میانگین و "
                  "close در بالای دامنه\nدامپ: آینهٔ همان"),
         "values": (f"a = {_fmt(d['range_mult'])}× · b = {_fmt(d['vol_mult'])}× · "
                    f"lookback {d['lookback']} کندل · "
                    f"موقعیت بسته {_fmt(d['close_pos'])}")},
        {"title": "اندازه‌گیری واکنش",
         "expr": "بازدهٔ افق‌های ازپیش‌تعیین‌شده منهای هزینهٔ رفت‌وبرگشت",
         "values": (f"افق‌ها {list(d['horizons'])} · افق اصلی {d['primary_horizon']} · "
                    f"هزینه {_fmt(float(d['cost_frac']) * 100)}٪")},
        {"title": "دروازهٔ پذیرش",
         "expr": "رویداد کافی + پوشش ماه/نماد",
         "values": (f"حداقل {d['min_events']} رویداد · "
                    f"{_fmt(float(d['min_months_pct']))}٪ ماه‌ها · "
                    f"{_fmt(float(d['min_symbols_pct']))}٪ نمادها")},
    ]
    return {"id": "pump", "title": "پامپ و دامپ (سیستم مستقل)",
            "note": "از موتور و الگوها چیزی ایمپورت نمی‌کند؛ فقط رصد و اندازه‌گیری.",
            "items": [{"id": "pumpdump", "label": "تشخیص رویداد و واکنش",
                       "short": "مستقل", "kind": "رصد", "active": True,
                       "summary": "پامپ/دامپ را جدا از معاملات علامت می‌زند تا "
                                  "ببینیم واکنش بازار واقعی است یا نه.",
                       "formulas": formulas, "params": d,
                       "source": "mtflab/pumpdump.py · bash run-auto.sh --pump"}]}


# ══════════════════════════════════════════════════════════════════════════
#  خروجی
# ══════════════════════════════════════════════════════════════════════════
def render_text(cat: dict) -> str:
    """نسخهٔ متنی برای ترمینال گوشی — همان چیزی که در داشبورد می‌بینی."""
    L = [f"# کاتالوگ الگوریتم‌ها · {cat['generated_utc']}",
         f"تایم‌فریم: {cat['tf']['trigger']}/{cat['tf']['filter']}/{cat['tf']['bias']}"
         f" · {cat['counts']['items']} مورد در {cat['counts']['sections']} بخش\n"]
    for sec in cat["sections"]:
        L.append(f"## {sec['title']}")
        if sec.get("note"):
            L.append(f"_{sec['note']}_")
        for it in sec["items"]:
            L.append(f"### {it['label']}  (`{it['id']}` · {it['kind']})")
            L.append(it["summary"])
            for f in it["formulas"]:
                L.append(f"- **{f['title']}**")
                L.append("  ```")
                for line in str(f["expr"]).splitlines():
                    L.append(f"  {line}")
                L.append("  ```")
                if f.get("values"):
                    L.append(f"  مقادیر فعلی: `{f['values']}`")
            L.append("")
    return "\n".join(L)


def catalog_command(argv=None) -> int:
    import argparse
    import json
    import os

    p = argparse.ArgumentParser(
        prog="mtflab algorithms",
        description="کاتالوگ الگوریتم‌ها: فرمول هر الگو با مقدار فعلی پارامترها")
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cat = catalog(a.tf, a.tf_filter, a.tf_bias)
    if not a.json:
        print(render_text(cat))
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, "algorithms_catalog.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=1, default=str)
    if not a.json:
        print(f"\n📄 {os.path.abspath(path)}")
    return 0


def catalog(tf_trigger: str = "4h", tf_filter: str = "1d",
            tf_bias: str = "1d") -> dict:
    """کاتالوگ کامل، با پارامترهای همین لحظهٔ سیستم."""
    from .config import load_config
    from .patterns import variants_for

    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=tf_trigger, tf_filter=tf_filter, tf_bias=tf_bias,
                  verbose=False, forensics=False, run_id="", symbol="")
    variants = variants_for(tf_trigger, tf_filter, tf_bias)

    sections = [
        _mtf_section(cfg, variants),
        {"id": "v10", "title": "V10 Pro — سناریوی جداگانه", "note": (
            "اعداد پروپوزال (OOS +۰.۶۵٪، شارپ ۱.۲۵) ادعای تأییدنشده است؛ "
            "اینجا فقط منطق و مقادیر فعلی نمایش داده می‌شود."),
         "items": [_v10_item()]},
        _exits_section(cfg),
        _pump_section(),
    ]
    return {
        "version": VERSION,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tf": {"trigger": tf_trigger, "filter": tf_filter, "bias": tf_bias},
        "sections": sections,
        "counts": {"sections": len(sections),
                   "items": sum(len(s["items"]) for s in sections)},
    }
