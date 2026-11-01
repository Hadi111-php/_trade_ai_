"""API مستقل اتوترید — برای وصل‌کردن همان الگوها به هر داشبورد دیگر.

**این فایل قرارداد است، نه موتور.** منطق معامله در `engine.py`/`signals.py` است و
دست نمی‌خورد؛ این‌جا فقط یک لایهٔ نازک و پایدار می‌گذاریم تا یک برنامهٔ دیگر
(وب، موبایل، ربات تلگرام، هر چیز) بدون دانستن جزئیات داخلی، همان چیزها را ببیند:

    from mtflab import autotrade_api as api
    api.schema()                              # الگوها + کلیدهای تنظیمات + پیش‌فرض‌ها
    api.run(candles_by_symbol, variant="trend", overrides={"trail_atr_mult": 4})
    api.signals_now(candles_by_symbol, variant="trend")   # سیگنال کندل آخر

قاعده‌هایی که این لایه تضمین می‌کند (و تست دارند):

  ۱. **هیچ تصمیم تازه‌ای** این‌جا گرفته نمی‌شود؛ همه‌چیز از همان موتور می‌آید.
  ۲. **همان تعریف‌های آماری**: `stats.metrics` — نه نسخهٔ دوم «تقریباً مشابه».
  ۳. **همان فهرست الگوها**: `patterns.variants_for` — پنج تیم، بدون نسخهٔ موازی.
  ۴. **همان انتساب**: هر معامله با قاعدهٔ بست و نوع آن (`rules.rule_meta`).

ورودی/خروجی همه‌جا «داده‌های سادهٔ پایتون» است: dict/list/float. نه شیء مهتور،
نه کلاس مخفی — تا هر زبانی بتواند از خروجی JSON استفاده کند.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import MTFConfig, load_config
from .data import Candle, build_layers, tf_to_minutes
from .engine import run_backtest
from .knobs import KNOBS, sanitize_overrides
from .patterns import variants_for
from .rules import cfg_digest
from .stats import breakdown, metrics, positions_from_trades, rule_breakdown

API_VERSION = "1.0"


# ══════════════════════════════════════════════════════════════════════════
#  ورودی: کندل‌ها
# ══════════════════════════════════════════════════════════════════════════
def to_candles(rows: Sequence) -> List[Candle]:
    """تبدیل ورودی ساده به کندل.

    دو قالب پذیرفته می‌شود (همان چیزی که از یک API یا فایل JSON می‌آید):

      • `[[ts, open, high, low, close, volume], ...]`
      • `[{"ts": ..., "o": ..., "h": ..., "l": ..., "c": ..., "v": ...}, ...]`

    نام‌های بلند (`open_time_ms`, `open`, …) هم پذیرفته می‌شوند.
    """
    out: List[Candle] = []
    for r in rows:
        if isinstance(r, (list, tuple)):
            if len(r) < 5:
                raise ValueError("ردیف کندل باید حداقل ۵ عضو داشته باشد")
            ts, o, h, lo, c = r[:5]
            v = r[5] if len(r) > 5 else 0.0
        elif isinstance(r, dict):
            ts = r.get("ts", r.get("open_time_ms", r.get("t")))
            o = r.get("o", r.get("open"))
            h = r.get("h", r.get("high"))
            lo = r.get("l", r.get("low"))
            c = r.get("c", r.get("close"))
            v = r.get("v", r.get("volume", 0.0))
        else:
            raise TypeError(f"کندل نامفهوم: {type(r).__name__}")
        if ts is None or None in (o, h, lo, c):
            raise ValueError(f"کندل ناقص: {r!r}")
        out.append(Candle(int(ts), float(o), float(h), float(lo), float(c), float(v or 0.0)))
    return out


def _dataset(dataset: Dict[str, Sequence]) -> Dict[str, List[Candle]]:
    """هر نماد را به فهرست کندل تبدیل می‌کند (ورودی خام یا Candle)."""
    out: Dict[str, List[Candle]] = {}
    for sym, rows in (dataset or {}).items():
        cs = [r if isinstance(r, Candle) else None for r in rows]
        out[str(sym).upper()] = (list(rows) if all(cs) else to_candles(rows))
    return out


# ══════════════════════════════════════════════════════════════════════════
#  الگوها و تنظیمات
# ══════════════════════════════════════════════════════════════════════════
def variants(tf_trigger: str = "4h", tf_filter: str = "1d",
             tf_bias: str = "1d") -> List[dict]:
    """تیم‌ها/الگوهای موجود — همان فهرستی که داشبورد استفاده می‌کند."""
    return [{"id": v[0], "label": v[1], "overrides": dict(v[2])}
            for v in variants_for(tf_trigger, tf_filter, tf_bias)]


def variant_def(variant: Optional[str] = None,
                tf_trigger: str = "4h", tf_filter: str = "1d",
                tf_bias: str = "1d") -> Tuple[str, str, dict]:
    """(شناسه، برچسب، overrides) — با برگشت بی‌صدا به تیم پیش‌فرض اگر ناشناس بود."""
    items = variants(tf_trigger, tf_filter, tf_bias)
    by_id = {v["id"]: v for v in items}
    if variant in by_id:
        v = by_id[variant]
    else:
        v = by_id.get("trend") or items[0]
    return v["id"], v["label"], dict(v["overrides"])


def config_for(variant: Optional[str] = None,
               overrides: Optional[dict] = None,
               tf_trigger: str = "4h", tf_filter: str = "1d", tf_bias: str = "1d",
               symbol: str = "", initial_equity: float = 1000.0,
               fee_bps: Optional[float] = None,
               slippage_pct: Optional[float] = None) -> MTFConfig:
    """کانفیگ آمادهٔ اجرا: پیش‌فرض‌های پروژه ← تنظیمات تیم ← تنظیمات کاربر."""
    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=tf_trigger, tf_filter=tf_filter, tf_bias=tf_bias,
                  verbose=False, forensics=False, run_id="", symbol=symbol)
    cfg = replace(cfg, **variant_def(variant, tf_trigger, tf_filter, tf_bias)[2])
    if overrides:
        cfg = replace(cfg, **overrides)
    if initial_equity:
        cfg = replace(cfg, initial_equity=float(initial_equity))
    if fee_bps is not None:
        cfg = replace(cfg, fee_bps=float(fee_bps))
    if slippage_pct is not None:
        cfg = replace(cfg, slippage_pct=float(slippage_pct))
    return cfg


def schema(tf_trigger: str = "4h", tf_filter: str = "1d",
           tf_bias: str = "1d") -> dict:
    """همه‌چیزی که یک داشبورد برای ساختن فرم لازم دارد."""
    items = []
    for v in variants(tf_trigger, tf_filter, tf_bias):
        cfg = config_for(v["id"], None, tf_trigger, tf_filter, tf_bias)
        items.append({**v,
                      "values": {k["k"]: getattr(cfg, k["k"], None) for k in KNOBS}})
    base = config_for("trend", None, tf_trigger, tf_filter, tf_bias)
    return {
        "api": API_VERSION,
        "tf": {"trigger": tf_trigger, "filter": tf_filter, "bias": tf_bias},
        "variants": items,
        "knobs": KNOBS,
        "defaults": {k["k"]: getattr(base, k["k"], None) for k in KNOBS},
        "notes": [
            "هر کلید بیرون فهرست knobs نادیده گرفته می‌شود.",
            "هر مقدار بیرون بازه به نزدیک‌ترین مرز برمی‌گردد.",
            "خروجی هیچ‌جا «توصیهٔ معامله» نیست؛ نتیجهٔ آزمون روی داده است.",
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
#  اجرا
# ══════════════════════════════════════════════════════════════════════════
def run(dataset: Dict[str, Sequence],
        variant: Optional[str] = None,
        overrides: Optional[dict] = None,
        tf_trigger: str = "4h", tf_filter: str = "1d", tf_bias: str = "1d",
        oos_frac: float = 0.30,
        initial_equity: float = 1000.0,
        fee_bps: Optional[float] = None,
        slippage_pct: Optional[float] = None) -> dict:
    """بک‌تست همهٔ نمادها با یک تیم و برگرداندن گزارش ساده.

    `oos_frac` = کسر پایانی بازه که «بیرون‌نمونه» شمرده می‌شود (۰ = خاموش).
    پوزیشن‌های بازِ آخر داده در سنجه‌ها نمی‌آیند (فقط شمرده می‌شوند) — وگرنه
    هر تیمی که آخرِ بازه لانگ باشد پاداش می‌گیرد.
    """
    clean, ignored = sanitize_overrides(overrides or {})
    data = _dataset(dataset)
    vid, label, _vov = variant_def(variant, tf_trigger, tf_filter, tf_bias)
    cfg0 = config_for(vid, clean, tf_trigger, tf_filter, tf_bias,
                      initial_equity=initial_equity, fee_bps=fee_bps,
                      slippage_pct=slippage_pct)

    rows: List[dict] = []
    errors: List[str] = []
    bars: Dict[str, int] = {}
    stamps: List[int] = []
    for sym, cs in data.items():
        bars[sym] = len(cs)
        if cs:
            stamps.extend([cs[0].open_time_ms, cs[-1].open_time_ms])
        try:
            layers = build_layers(cs, tf_trigger, tf_filter, tf_bias,
                                  bias_enabled=cfg0.bias_enabled)
            res = run_backtest(replace(cfg0, symbol=sym), layers)
            rows.extend(positions_from_trades(res["trades"], layers["trigger"]))
        except Exception as e:                                     # noqa: BLE001
            errors.append(f"{sym}: {type(e).__name__}: {str(e)[:80]}")

    open_at_end = sum(1 for x in rows if x.get("rule") == "end_of_data")
    rows = [x for x in rows if x.get("rule") != "end_of_data"]

    if oos_frac and stamps:
        t0, t1 = min(stamps), max(stamps)
        cut = t0 + (t1 - t0) * (1.0 - float(oos_frac))
    else:
        t0 = min(stamps) if stamps else 0
        t1 = max(stamps) if stamps else 0
        cut = t1
    ins = [x for x in rows if (x.get("entry_ts") or 0) < cut]
    oos = [x for x in rows if (x.get("entry_ts") or 0) >= cut]

    m = metrics(rows, float(cfg0.initial_equity))
    m["open_at_end"] = open_at_end
    return {
        "api": API_VERSION,
        "variant": vid,
        "variant_label": label,
        "overrides": clean,
        "ignored_keys": ignored,
        "digest": cfg_digest(clean),
        "tf": {"trigger": tf_trigger, "filter": tf_filter, "bias": tf_bias},
        "symbols": sorted(data),
        "bars": bars,
        "span": [t0, t1],
        "cut_ts": int(cut),
        "metrics": m,
        "in_sample": metrics(ins, float(cfg0.initial_equity)),
        "out_of_sample": metrics(oos, float(cfg0.initial_equity)),
        "by_rule": rule_breakdown(rows),
        "by_pattern": breakdown(rows, "mode"),
        "by_symbol": breakdown(rows, "symbol"),
        "trades": rows,
        "errors": errors,
        # هزینهٔ رفت‌وبرگشت به درصد — همان فرمول engine.health
        "cost_pct": round((cfg0.fee_bps / 10_000 + cfg0.slippage_pct / 100) * 2 * 100, 5),
    }


def signals_now(dataset: Dict[str, Sequence],
                variant: Optional[str] = None,
                overrides: Optional[dict] = None,
                tf_trigger: str = "4h", tf_filter: str = "1d", tf_bias: str = "1d",
                bars_ago: int = 0) -> List[dict]:
    """سیگنال‌هایی که روی `bars_ago` کندل آخر باز شده‌اند (۰ = کندل بستهٔ آخر).

    توجه: این «پیش‌بینی» نیست؛ همان تصمیم موتور روی کندل بستهٔ آخر است. اگر
    کندل جدید بسته شود، ممکن است تصمیم عوض شود — دقیقاً مثل اتوترید.
    """
    clean, _ = sanitize_overrides(overrides or {})
    data = _dataset(dataset)
    vid, _label, _vov = variant_def(variant, tf_trigger, tf_filter, tf_bias)
    cfg0 = config_for(vid, clean, tf_trigger, tf_filter, tf_bias)
    out: List[dict] = []
    for sym, cs in data.items():
        if not cs:
            continue
        try:
            layers = build_layers(cs, tf_trigger, tf_filter, tf_bias,
                                  bias_enabled=cfg0.bias_enabled)
            res = run_backtest(replace(cfg0, symbol=sym), layers)
        except Exception as e:                                     # noqa: BLE001
            out.append({"symbol": sym, "available": False,
                        "reason": f"{type(e).__name__}: {str(e)[:60]}"})
            continue
        last_ts = cs[-1].open_time_ms
        cutoff = cs[max(0, len(cs) - 1 - int(bars_ago))].open_time_ms
        pos = [p for p in positions_from_trades(res["trades"], layers["trigger"])
               if (p.get("entry_ts") or 0) >= cutoff]
        if not pos:
            out.append({"symbol": sym, "available": True, "signal": None,
                        "last_ts": last_ts, "bars": len(cs)})
            continue
        for p in pos:
            out.append({"symbol": sym, "available": True, "last_ts": last_ts,
                        "bars": len(cs), "signal": {**p,
                        "variant": vid,
                        "rule_meta": _rule_meta(p.get("rule"))}})
    return out


def _rule_meta(rule: Optional[str]) -> dict:
    from .rules import rule_meta
    return rule_meta(str(rule or ""))


def to_json(report: dict) -> str:
    """خروجی JSON آمادهٔ فرستادن به هر داشبورد/زبانی."""
    return json.dumps(report, ensure_ascii=False, default=str)
