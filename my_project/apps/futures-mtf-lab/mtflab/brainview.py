"""«چشم مغز» — یک دیدگاهِ ساده و مستقل دربارهٔ هر نماد، در هر کندل.

**جای این ماژول در معماری:** الگوریتم قاعده‌محور **حاکم** است و تصمیم می‌گیرد.
این ماژول فقط «نگاه» می‌اندازد: با احتمال می‌گوید حرکتِ یک روزِ آیندهٔ این نماد
بیشتر از هزینهٔ رفت‌وبرگشت است یا نه، و مهم‌ترین محرک‌هایش را هم می‌گوید.

**چرا مستقل:** این فایل هیچ چیزی از موتور معامله (`engine`)، از اتوترید
(`live`)، یا از قواعد ورود/خروج نمی‌داند. فقط `indicators` و `data` را می‌شناسد.
دلیلش دو چیز است:

  ۱. **نظاره‌گری بدون دخالت**: اگر لایهٔ دید به موتور وابسته باشد، وسوسه می‌شود
     روزی «کمک» کند و تصمیم را عوض کند. با این مرز، عوض کردن تصمیم بدون
     نوشتن کد تازه ممکن نیست.
  ۲. **تست‌پذیری**: می‌شود ثابت کرد که حضور مغز، حتی با دیدگاه‌های افراطی،
     هیچ معامله‌ای را تغییر نمی‌دهد.

این دیدگاه **قبل از سیگنال** هم قابل پرسیدن است (`view_now`) تا الگوریتم‌یاب
بداند مغز روی هر نماد چه فکری دارد — ولی هیچ‌جا به‌عنوان شرط ورود استفاده
نمی‌شود؛ فقط در ژورنال ثبت می‌شود تا بعداً بتوان سنجید که آیا ارزش داشت یا نه.

اجرا: `python3 -m mtflab view [--train]`  ·  `bash run-auto.sh --brain-view`
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

from . import indicators as ind
from .config import MTFConfig
from .data import Candle
from .mlfit import (auc_score, fit_logistic, predict_proba, standardize_fit,
                    to_vector)

VERSION = "1.0"

#: ویژگی‌های دیدگاه — **قبل از دیدن نتیجه** انتخاب شده و تغییر نمی‌کنند.
FEATURES: List[Tuple[str, str]] = [
    ("atr_pct", "نوسان (ATR٪)"),
    ("adx", "قدرت روند"),
    ("rsi", "RSI"),
    ("don_pos", "جایگاه در کانال دانچیان"),
    ("bb_pos", "جایگاه در باند"),
    ("bb_width", "پهنای باند"),
    ("vol_z", "حجم (z)"),
    ("structure_score", "ساختار"),
    ("slope", "شیب EMA٪"),
    ("ema_dist", "فاصله از EMA (×ATR)"),
]
NAMES = [n for n, _ in FEATURES]
FA = dict(FEATURES)


# ---------------------------------------------------------------------------
# ۱) اندیکاتورها (یک‌بار برای هر نماد) — همه علّی، بدون نگاه به آینده
# ---------------------------------------------------------------------------
def build_arrays(candles: Sequence[Candle], cfg: MTFConfig) -> dict:
    """آرایه‌های اندیکاتور؛ هر مقدار در خانهٔ i فقط از کندل‌های ≤ i ساخته شده."""
    closes = [c.close for c in candles]
    ema_main = ind.ema(closes, cfg.trigger_ema_period)
    return {
        "candles": list(candles),
        "closes": closes,
        "ema": ema_main,
        "slope": ind.slope_pct(ema_main, 3),
        "rsi": ind.rsi(closes, cfg.trigger_rsi_period),
        "atr": ind.atr(candles, cfg.trigger_atr_period),
        "atr_pct": ind.atr_pct(candles, cfg.trigger_atr_period),
        "adx": ind.adx(candles, cfg.filter_adx_period),
        "don": ind.donchian(candles, cfg.trigger_donchian_window),
        "bb": ind.bollinger(closes, 20),
        "volz": ind.volume_z(candles, cfg.trigger_vol_window),
        "struct": ind.market_structure(candles, cfg.trigger_donchian_window),
    }


def _num(x, dflt: float = 0.0) -> float:
    try:
        return float(x) if x is not None else dflt
    except (TypeError, ValueError):
        return dflt


def features_at(arrays: dict, i: int) -> Optional[dict]:
    """ویژگی‌های خانهٔ i، یا None اگر warmup تمام نشده باشد."""
    n = len(arrays["closes"])
    if i < 0 or i >= n:
        return None
    ema = arrays["ema"][i]
    atr = arrays["atr"][i]
    don = arrays["don"][i] if i < len(arrays["don"]) else {}
    bb = arrays["bb"][i] if i < len(arrays["bb"]) else {}
    if ema is None or atr is None or not don or don.get("pos") is None \
            or not bb or bb.get("pos") is None:
        return None
    close = arrays["closes"][i]
    struct = arrays["struct"][i] if i < len(arrays["struct"]) else {}
    return {
        "atr_pct": _num(arrays["atr_pct"][i]),
        "adx": _num(arrays["adx"][i]),
        "rsi": _num(arrays["rsi"][i], 50.0),
        "don_pos": _num(don.get("pos")),
        "bb_pos": _num(bb.get("pos")),
        "bb_width": _num(bb.get("width")),
        "vol_z": _num(arrays["volz"][i]),
        "structure_score": _num((struct or {}).get("score")),
        "slope": _num(arrays["slope"][i]),
        "ema_dist": ((close - float(ema)) / float(atr)) if atr else 0.0,
    }


# ---------------------------------------------------------------------------
# ۲) مجموعه دادهٔ دیدگاه: هر کندل → «حرکت یک روز بعد از هزینه بیشتر بود؟»
# ---------------------------------------------------------------------------
def cost_frac(cfg: MTFConfig) -> float:
    """هزینهٔ رفت‌وبرگشت به کسر قیمت (کارمزد + اسلیپیج، دو طرف)."""
    return (cfg.fee_bps * 2 + cfg.slippage_pct * 2 * 100.0) / 10_000.0


def build_rows(universe: Dict[str, Sequence[Candle]], cfg: MTFConfig,
               horizon: int = 6, cost: Optional[float] = None,
               max_rows: int = 20000) -> List[dict]:
    """ویژگی + برچسب برای هر کندل (با stride تا روی گوشی هم سریع بماند).

    اگر ۲۰ نماد × ۶۰۰۰ کندل را کامل برداریم، آموزش در پایتون خالص دقیقه‌ها
    طول می‌کشد. نمونه‌گیریِ یکنواخت (هر k اُمین کندل) هم ارزان‌تر است و هم
    توزیع زمانی را به‌هم نمی‌زند. `max_rows=0` یعنی بدون نمونه‌گیری.
    """
    cf = cost_frac(cfg) if cost is None else float(cost)
    est = sum(max(0, len(cs) - 60 - horizon) for cs in universe.values())
    stride = max(1, est // max_rows) if max_rows and est > max_rows else 1
    rows: List[dict] = []
    for sym in sorted(universe):
        cs = universe[sym]
        if len(cs) < 120:
            continue
        arr = build_arrays(cs, cfg)
        closes = arr["closes"]
        for i in range(60, len(cs) - horizon, stride):
            f = features_at(arr, i)
            if f is None:
                continue
            fut = closes[i + horizon] / closes[i] - 1.0
            f.update({
                "symbol": sym,
                "ts": cs[i].open_time_ms,
                "fwd_ret": round(fut, 6),
                "y": 1 if fut > cf else 0,
            })
            rows.append(f)
    rows.sort(key=lambda r: (r["ts"], r["symbol"]))
    return rows


def _blocks(rows: Sequence[dict], folds: int) -> List[List[dict]]:
    n = len(rows)
    folds = max(2, min(int(folds), 6))
    out, start = [], 0
    for i in range(folds):
        end = n if i == folds - 1 else start + n // folds
        out.append(list(rows[start:end]))
        start = end
    return [b for b in out if b]


def train(universe: Dict[str, Sequence[Candle]], cfg: MTFConfig,
          horizon: int = 6, folds: int = 4, max_rows: int = 20000,
          epochs: int = 120) -> Tuple[dict, dict]:
    """آموزش با ارزیابی راه‌رونده؛ برگشت: (مدل نهایی، گزارش ارزیابی)."""
    rows = build_rows(universe, cfg, horizon=horizon, max_rows=max_rows)
    if len(rows) < 500:
        raise ValueError(f"دادهٔ کافی برای آموزش نیست ({len(rows)} ردیف، حداقل ۵۰۰)")
    cf = cost_frac(cfg)
    blocks = _blocks(rows, folds)
    fold_reports = []
    oof_scores: List[float] = []
    oof_labels: List[int] = []
    for k in range(1, len(blocks)):
        train_rows = [r for blk in blocks[:k] for r in blk]
        test_rows = blocks[k]
        means, stds = standardize_fit(train_rows, NAMES)
        Xtr = [to_vector(r, NAMES, means, stds) for r in train_rows]
        ytr = [int(r["y"]) for r in train_rows]
        w, b = fit_logistic(Xtr, ytr, epochs=epochs)
        Xte = [to_vector(r, NAMES, means, stds) for r in test_rows]
        ps = predict_proba(w, b, Xte)
        ys = [int(r["y"]) for r in test_rows]
        acc = sum(1 for p, y in zip(ps, ys) if (p > 0.5) == bool(y)) / max(1, len(ys))
        fold_reports.append({
            "fold": k,
            "n_train": len(train_rows),
            "n_test": len(test_rows),
            "auc": auc_score(ps, ys),
            "acc": round(acc, 4),
            "base_rate": round(sum(ys) / max(1, len(ys)), 4),
        })
        oof_scores += ps
        oof_labels += ys

    means, stds = standardize_fit(rows, NAMES)
    X = [to_vector(r, NAMES, means, stds) for r in rows]
    y = [int(r["y"]) for r in rows]
    w, b = fit_logistic(X, y, epochs=epochs)
    model = {
        "version": VERSION,
        "kind": "brainview",
        "features": NAMES,
        "fa": FA,
        "means": {k: round(v, 8) for k, v in means.items()},
        "stds": {k: round(v, 8) for k, v in stds.items()},
        "w": [round(v, 8) for v in w],
        "b": round(b, 8),
        "horizon_bars": int(horizon),
        "cost_frac": round(cf, 8),
        "trained_rows": len(rows),
        "stride_note": "نمونه‌گیری یکنواخت برای سرعت (max_rows)",
        "trained_through_ts": rows[-1]["ts"],
        "trained_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "symbols": sorted({r["symbol"] for r in rows}),
        "oof": {
            "auc": auc_score(oof_scores, oof_labels),
            "acc": round(sum(1 for p, yv in zip(oof_scores, oof_labels)
                             if (p > 0.5) == bool(yv)) / max(1, len(oof_labels)), 4),
            "base_rate": round(sum(oof_labels) / max(1, len(oof_labels)), 4),
            "majority_acc": round(max(sum(oof_labels), len(oof_labels) - sum(oof_labels))
                                  / max(1, len(oof_labels)), 4),
            "n": len(oof_labels),
        },
    }
    report = {
        "rows": len(rows),
        "symbols": len(model["symbols"]),
        "base_rate": round(sum(y) / len(y), 4),
        "horizon_bars": int(horizon),
        "cost_frac": round(cf, 6),
        "folds": fold_reports,
        "oof": model["oof"],
        "trained_through": time.strftime("%Y-%m-%d", time.gmtime(rows[-1]["ts"] / 1000)),
    }
    return model, report


# ---------------------------------------------------------------------------
# ۳) ذخیره/بارگذاری مدل
# ---------------------------------------------------------------------------
def save_model(model: dict, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_model(path: str) -> Optional[dict]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("kind") != "brainview" or not m.get("w"):
            return None
        return m
    except (OSError, ValueError):
        return None


def model_digest(model: dict) -> str:
    import hashlib
    key = json.dumps({k: model.get(k) for k in ("w", "b", "means", "stds",
                                                "features", "horizon_bars")},
                     sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:10]


# ---------------------------------------------------------------------------
# ۴) دیدگاه در یک کندل مشخص (بدون نگاه به آینده)
# ---------------------------------------------------------------------------
def lean_label(p: float, lo: float = 0.55, hi: float = 0.45) -> str:
    if p >= lo:
        return "long"
    if p <= hi:
        return "short"
    return "neutral"


def view_at(model: dict, arrays: dict, i: int, top: int = 3) -> Optional[dict]:
    """دیدگاه مغز در خانهٔ i — فقط دادهٔ تا همان کندل."""
    feats = features_at(arrays, i)
    if feats is None:
        return None
    means, stds = model["means"], model["stds"]
    x = to_vector(feats, model["features"], means, stds)
    p = predict_proba(model["w"], model["b"], [x])[0]
    contrib = sorted(
        ({"name": n, "fa": FA.get(n, n), "value": round(float(feats.get(n) or 0.0), 6),
          "contrib": round(float(wj * xj), 4)}
         for n, wj, xj in zip(model["features"], model["w"], x)),
        key=lambda d: -abs(d["contrib"]))[:top]
    return {
        "available": True,
        "p_up": round(float(p), 4),
        "lean": lean_label(p),
        "confidence": round(max(p, 1 - p), 4),
        "horizon_bars": model.get("horizon_bars"),
        "model": f"brainview/{VERSION}",
        "model_digest": model_digest(model),
        "ts": arrays["candles"][i].open_time_ms,
        "drivers": contrib,
    }


def view_now(model: Optional[dict], candles: Sequence[Candle], cfg: MTFConfig,
             top: int = 3) -> dict:
    """دیدگاه روی آخرین کندلِ بسته — برای «قبل از سیگنال‌گیری»."""
    if not model:
        return {"available": False, "reason": "no-model"}
    if len(candles) < 80:
        return {"available": False, "reason": "not-enough-candles"}
    arr = build_arrays(candles, cfg)
    v = view_at(model, arr, len(candles) - 1, top=top)
    if v is None:
        return {"available": False, "reason": "warmup"}
    v["close"] = round(float(candles[-1].close), 6)
    return v


# ---------------------------------------------------------------------------
# ۵) گزارش متنی
# ---------------------------------------------------------------------------
def render_table(views: Dict[str, dict]) -> str:
    lines = ["| نماد | دیدگاه | احتمال صعود | اطمینان | مهم‌ترین محرک‌ها |",
             "|---|---|---:|---:|---|"]
    for sym in sorted(views):
        v = views[sym]
        if not v.get("available"):
            lines.append(f"| {sym} | — | — | — | {v.get('reason', '')} |")
            continue
        lean_fa = {"long": "🟢 صعودی", "short": "🔴 نزولی", "neutral": "⚪ بی‌طرف"}[v["lean"]]
        drv = " · ".join(f"{d['fa']} {d['contrib']:+.2f}" for d in v.get("drivers") or [])
        lines.append(f"| {sym} | {lean_fa} | {v['p_up'] * 100:.1f}% | "
                     f"{v['confidence'] * 100:.1f}% | {drv} |")
    return "\n".join(lines)
