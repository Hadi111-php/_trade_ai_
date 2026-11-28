"""«مغز دوم» — یک مدل کوچک و **قابل تفسیر** کنار اتوترید (PAPER).

**ایدهٔ کاربر:** سه سال داده داریم؛ یک مدل روی آن آموزش بدهیم و کنار الگوی
قاعده‌محور بگذاریم تا مثل مشاور عمل کند.

**چرا این‌طور ساخته شد:** مدل بزرگ روی ~۴۰۰ معامله = ماشین overfit. پس این
ماژول عمداً سه محدودیت سخت دارد:

  ۱. **مدل کوچک و خطی** (رگرسیون لجستیک با L2). نه شبکهٔ عصبی، نه درخت عمیق.
     دلیل: با ۴۰۰ نمونه، هر پارامتر اضافه یک درِ تازه برای نویز است — و کاربر
     حق دارد بپرسد «چرا این سیگنال را رد کردی؟»؛ ضریبِ خطی جواب دارد.
  ۲. **اعتبارسنجی راه‌رونده (walk-forward)**: آموزش فقط روی گذشته، آزمون روی
     بلوکِ بعدی. هیچ پیش‌بینی‌ای از مدلی که آینده را دیده باشد پذیرفته نیست.
  ۳. **دروازهٔ ازپیش‌نوشته** قبل از دیدن نتیجه؛ اگر پاس نشد، مدل وارد سیستم
     **نمی‌شود** — حتی اگر AUC خوب باشد.

کاربردش هم عمداً محدود است: مدل **سیگنال نمی‌سازد**. فقط سیگنال‌های موجود را
رتبه می‌دهد (کدام را بگیریم وقتی یک جایگاه داریم) و می‌تواند کم‌اعتمادترین‌ها
را رد کند. ورودِ تازه ساختن با مدل، مرحلهٔ بعد و فقط بعد از پاس‌شدن دروازه است.

اجرا: `python3 -m mtflab brain`  (یا `bash run-auto.sh --brain`)
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .autoscan import build_layers
from .config import MTFConfig, load_config
from .data import Candle
from .desk import load_universe
from .engine import run_backtest

VERSION = "1.0"

#: ویژگی‌ها **قبل از دیدن نتیجه** انتخاب شدند و تغییر نمی‌کنند.
#: (نام، توضیح فارسی، منبع)
FEATURES: List[Tuple[str, str]] = [
    ("atr_pct", "نوسان کندل ورود (ATR٪)"),
    ("adx", "قدرت روند (ADX)"),
    ("rsi", "اشباع (RSI)"),
    ("don_pos", "جایگاه در کانال دانچیان"),
    ("bb_pos", "جایگاه در باند بولینگر"),
    ("bb_width", "پهنای باند (فشردگی)"),
    ("vol_z", "حجم نسبت به نرمال (z)"),
    ("structure_score", "امتیاز ساختار"),
    ("slope", "شیب EMA تریگر (٪)"),
    ("slope_filter", "شیب EMA فیلتر (٪)"),
    ("confidence", "اطمینان تصمیم"),
    ("mode_breakout", "الگو: شکست (۱) یا بازگشت (۰)"),
]

#: دروازهٔ قبولی — از قبل نوشته شده؛ بعد از دیدن نتیجه عوض نمی‌شود.
GATE = {
    "min_oof": 150,            # حداقل پیش‌بینی بیرون‌نمونه
    "min_quartile_gap_r": 0.30,  # اختلاف انتظار چهارکِ بالا و پایین
    "min_top_quartile_r": 0.0,   # خودِ چهارکِ بالا هم باید سودده باشد، نه فقط "بهتر"
    "min_keep_frac": 0.50,     # فیلتر نباید بیشتر از این را دور بریزد
    "require_ci": True,        # Δ فیلتر باید بازهٔ اطمینان منفی‌نشده داشته باشد
    "min_sign_stability": 0.66,  # پایداری علامت ضرایب در فولدها
}


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ساخت مجموعه داده از همان معاملاتی که موتور می‌گیرد
# ══════════════════════════════════════════════════════════════════════════
def _feat_row(t: dict) -> Optional[dict]:
    """یک معاملهٔ موتور → یک ردیف ویژگی (همه از «لحظهٔ ورود»، بدون آینده)."""
    ind = t.get("indicators_entry") or {}
    fnd = t.get("indicators_filter_entry") or {}
    if not ind:
        return None
    def f(d: dict, k: str, dflt: float = 0.0) -> float:
        try:
            v = d.get(k)
            return float(v) if v is not None and not isinstance(v, bool) else dflt
        except (TypeError, ValueError):
            return dflt
    return {
        "atr_pct": f(ind, "atr_pct"),
        "adx": f(ind, "adx"),
        "rsi": f(ind, "rsi"),
        "don_pos": f(ind, "don_pos"),
        "bb_pos": f(ind, "bb_pos"),
        "bb_width": f(ind, "bb_width"),
        "vol_z": f(ind, "vol_z"),
        "structure_score": f(ind, "structure_score"),
        "slope": f(ind, "ema_main_slope_pct"),
        "slope_filter": f(fnd, "ema_main_slope_pct"),
        "confidence": float(t.get("confidence_entry") or 0.0),
        "mode_breakout": 1.0 if (t.get("trigger_mode") == "breakout") else 0.0,
    }


def build_dataset(universe: Dict[str, Sequence[Candle]], cfg: MTFConfig,
                  tf: str, tf_filter: str, tf_bias: str) -> List[dict]:
    """هر معاملهٔ بک‌تست → ردیف با ویژگی + برچسب + نتیجهٔ واقعی."""
    rows: List[dict] = []
    for sym in sorted(universe):
        cs = universe[sym]
        if len(cs) < 120:
            continue
        try:
            layers = build_layers(cs, tf, tf_filter, tf_bias,
                                  bias_enabled=cfg.bias_enabled)
            res = run_backtest(replace(cfg, symbol=sym), layers)
        except Exception:                                          # noqa: BLE001
            continue
        trig = layers["trigger"]
        for t in res["trades"]:
            if t.get("partial"):            # لگ‌های برداشت جزئی، معاملهٔ جدا نیستند
                continue
            if str(t.get("reason") or "") == "end_of_data":
                continue
            feats = _feat_row(t)
            if feats is None:
                continue
            try:
                ob = int(t.get("open_bar"))
                entry_ts = trig[ob].open_time_ms if 0 <= ob < len(trig) else int(t.get("ts") or 0)
            except (TypeError, ValueError):
                entry_ts = int(t.get("ts") or 0)
            r = float(t.get("r_multiple") or 0.0)
            feats.update({
                "symbol": sym,
                "entry_ts": entry_ts,
                "exit_ts": t.get("ts"),
                "r": round(r, 4),
                "pnl": round(float(t.get("position_pnl") or t.get("pnl") or 0.0), 4),
                "y": 1 if r > 0 else 0,
                "rule": t.get("reason"),
                "bars": t.get("bars_held"),
            })
            rows.append(feats)
    rows.sort(key=lambda x: x["entry_ts"])
    return rows


def split_blocks(rows: Sequence[dict], folds: int) -> List[List[dict]]:
    """تقسیم زمانی به بلوک‌های هم‌اندازه (نه تصادفی — زمان مهم است)."""
    n = len(rows)
    folds = max(2, min(int(folds), 6))
    if n < folds * 5:
        folds = max(2, n // 5)
    out, start = [], 0
    for i in range(folds):
        end = n if i == folds - 1 else start + n // folds
        out.append(list(rows[start:end]))
        start = end
    return [b for b in out if b]


# ══════════════════════════════════════════════════════════════════════════
#  ۲) مدل: رگرسیون لجستیک با L2 (خالص پایتون)
# ══════════════════════════════════════════════════════════════════════════
def _scale_fit(rows: Sequence[dict]) -> Tuple[Dict[str, float], Dict[str, float]]:
    means, stds = {}, {}
    for name, _ in FEATURES:
        vals = [float(r.get(name) or 0.0) for r in rows]
        m = sum(vals) / len(vals) if vals else 0.0
        var = sum((v - m) ** 2 for v in vals) / len(vals) if vals else 0.0
        means[name] = m
        stds[name] = math.sqrt(var) or 1.0
    return means, stds


def _vector(r: dict, means: Dict[str, float], stds: Dict[str, float]) -> List[float]:
    return [(float(r.get(n) or 0.0) - means[n]) / stds[n] for n, _ in FEATURES]


def fit_logistic(X: Sequence[Sequence[float]], y: Sequence[int],
                 l2: float = 0.5, epochs: int = 400, lr: float = 0.2) -> Tuple[List[float], float]:
    """گرادیان کاهشی ساده؛ قطعی (بدون تصادف) تا نتیجه تکرارپذیر باشد."""
    d = len(X[0]) if X else 0
    w, b = [0.0] * d, 0.0
    n = max(1, len(X))
    for _ in range(epochs):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
        b -= lr * gb / n
    return w, b


def predict(w: Sequence[float], b: float, X: Sequence[Sequence[float]]) -> List[float]:
    out = []
    for xi in X:
        z = b + sum(wj * xj for wj, xj in zip(w, xi))
        out.append(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))))
    return out


def walk_forward(rows: Sequence[dict], folds: int) -> Tuple[List[dict], List[dict], List[Tuple[int, List[float]]]]:
    """آموزش روی بلوک‌های گذشته، پیش‌بینی بلوک بعد. برگشت: (پیش‌بینی‌ها، فولدها، ضرایب)."""
    if len(rows) < 120:
        raise ValueError(f"برای walk-forward دست‌کم ۱۲۰ معامله لازم است ({len(rows)} داریم)")
    blocks = split_blocks(rows, folds)
    preds: List[dict] = []
    coefs: List[Tuple[int, List[float]]] = []
    for i in range(1, len(blocks)):
        train = [r for blk in blocks[:i] for r in blk]
        test = blocks[i]
        if len(train) < 30 or len(test) < 5:
            continue
        means, stds = _scale_fit(train)
        Xtr = [_vector(r, means, stds) for r in train]
        ytr = [int(r["y"]) for r in train]
        w, b = fit_logistic(Xtr, ytr)
        Xte = [_vector(r, means, stds) for r in test]
        ps = predict(w, b, Xte)
        coefs.append((i, list(w)))
        for r, p in zip(test, ps):
            preds.append(dict(r, p=round(p, 6), fold=i))
    return preds, blocks, coefs


# ══════════════════════════════════════════════════════════════════════════
#  ۳) سنجه‌ها و دروازه
# ══════════════════════════════════════════════════════════════════════════
def _mean(v: Sequence[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def auc(preds: Sequence[dict]) -> Optional[float]:
    """AUC با روش رتبه‌ای (Mann–Whitney)؛ ۰.۵ = سکهٔ منصف. تساوی‌ها میانگین رتبه."""
    pos = [p["p"] for p in preds if p["y"] == 1]
    neg = [p["p"] for p in preds if p["y"] == 0]
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda x: x[0])
    ranks = [0.0] * len(allv)
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0               # میانگین رتبهٔ گروهِ تساوی
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_pos = sum(ranks[k] for k in range(len(allv)) if allv[k][1] == 1)
    return round((r_pos - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)), 4)


def bucket_table(preds: Sequence[dict], parts: int = 4) -> List[dict]:
    s = sorted(preds, key=lambda x: x["p"])
    n = len(s)
    out = []
    for i in range(parts):
        a, b = int(i * n / parts), int((i + 1) * n / parts)
        chunk = s[a:b]
        if not chunk:
            continue
        out.append({
            "part": i + 1,
            "n": len(chunk),
            "p_lo": round(chunk[0]["p"], 3),
            "p_hi": round(chunk[-1]["p"], 3),
            "expectancy_r": round(_mean([x["r"] for x in chunk]), 4),
            "win_rate": round(_mean([x["y"] for x in chunk]), 4),
            "pnl": round(sum(x["pnl"] for x in chunk), 2),
        })
    return out


def filter_test(preds: Sequence[dict], skip_frac: float = 0.30) -> dict:
    """اگر کم‌اعتمادترین‌ها را رد کنیم، expectancy بهتر می‌شود؟"""
    s = sorted(preds, key=lambda x: x["p"])
    cut = max(1, int(len(s) * skip_frac))
    dropped, kept = s[:cut], s[cut:]
    if len(kept) < 20 or len(dropped) < 10:
        return {"ok": False, "note": "نمونه کم است"}
    a = [x["r"] for x in kept]
    b = [x["r"] for x in dropped]
    from .evolve import bootstrap_ci
    ci = bootstrap_ci(a, b, level=0.90, sims=1000)
    return {
        "ok": True, "skip_frac": skip_frac, "n_kept": len(kept), "n_dropped": len(dropped),
        "expectancy_kept": round(_mean(a), 4),
        "expectancy_dropped": round(_mean(b), 4),
        "expectancy_all": round(_mean([x["r"] for x in preds]), 4),
        "delta_kept_vs_all": round(_mean(a) - _mean([x["r"] for x in preds]), 4),
        "pnl_delta": round(sum(x["pnl"] for x in kept) -
                           sum(x["pnl"] for x in preds), 2),
        "ci": ci,
    }


def sign_stability(coefs: Sequence[Tuple[int, List[float]]]) -> List[dict]:
    """پایداری علامت هر ضریب در فولدها (مقاوم به بردارهای کوتاه)."""
    out = []
    width = max((len(c[1]) for c in coefs), default=0)
    names = [(FEATURES[j] if j < len(FEATURES) else (f"f{j}", f"ویژگی {j}"))
             for j in range(width)]
    for j, (name, fa) in enumerate(names):
        signs = [1 if (j < len(c[1]) and c[1][j] > 0)
                 else (-1 if (j < len(c[1]) and c[1][j] < 0) else 0) for c in coefs]
        if not signs:
            out.append({"name": name, "fa": fa, "stability": None, "sign": 0,
                        "mean_coef": None})
            continue
        maj = max(set(signs), key=signs.count)
        stab = sum(1 for s in signs if s == maj) / len(signs)
        out.append({
            "name": name, "fa": fa, "sign": maj, "stability": round(stab, 3),
            "mean_coef": round(_mean([c[1][j] if j < len(c[1]) else 0.0 for c in coefs]), 4),
            "per_fold": [round(c[1][j] if j < len(c[1]) else 0.0, 3) for c in coefs],
        })
    out.sort(key=lambda x: -abs(x["mean_coef"] or 0))
    return out


def judge(res: dict) -> dict:
    """حکم بر اساس دروازهٔ ازپیش‌نوشته — نه بر اساس حس خوب از AUC."""
    checks = []
    oof = res["n_oof"]
    checks.append({"fa": f"پیش‌بینی بیرون‌نمونه ≥ {GATE['min_oof']}",
                   "got": oof, "ok": oof >= GATE["min_oof"]})
    buckets = res.get("buckets") or []
    gap = None
    if len(buckets) >= 4:
        gap = round(buckets[-1]["expectancy_r"] - buckets[0]["expectancy_r"], 4)
    checks.append({"fa": f"اختلاف چهارک بالا−پایین ≥ {GATE['min_quartile_gap_r']}R",
                   "got": gap, "ok": gap is not None and gap >= GATE["min_quartile_gap_r"]})
    top = buckets[-1]["expectancy_r"] if buckets else None
    checks.append({"fa": f"خودِ چهارکِ بالا ≥ {GATE['min_top_quartile_r']:+.2f}R",
                   "got": top,
                   "ok": top is not None and top >= GATE["min_top_quartile_r"]})
    ft = res.get("filter") or {}
    ok_ci = bool(ft.get("ok") and (ft.get("ci") or {}).get("significant")
                 and (ft.get("ci") or {}).get("observed", 0) > 0)
    checks.append({"fa": "Δ فیلتر معنادار و مثبت (بازهٔ ۹۰٪)",
                   "got": (ft.get("ci") or {}).get("ci"), "ok": ok_ci})
    checks.append({"fa": f"فیلتر حداقل {int(GATE['min_keep_frac'] * 100)}٪ را نگه دارد",
                   "got": (round(ft.get("n_kept", 0) / max(1, oof), 3) if ft.get("ok") else None),
                   "ok": bool(ft.get("ok") and ft.get("n_kept", 0) / max(1, oof) >= GATE["min_keep_frac"])})
    stab = [s for s in res.get("coefficients") or [] if s.get("stability") is not None][:3]
    stable = bool(stab) and all(s["stability"] >= GATE["min_sign_stability"] for s in stab)
    checks.append({"fa": f"پایداری علامت سه ضریب اصلی ≥ {GATE['min_sign_stability']}",
                   "got": [s.get("stability") for s in stab] or None, "ok": stable})
    passed = all(c["ok"] for c in checks)
    return {"checks": checks, "passed": passed,
            "verdict": ("✅ مدل حق دارد وارد سیستم شود (فقط به‌عنوان رتبه‌دهنده/فیلتر)" if passed
                        else "❌ مدل وارد سیستم نمی‌شود — افزایش AUC کافی نیست")}


# ══════════════════════════════════════════════════════════════════════════
#  ۴) گزارش
# ══════════════════════════════════════════════════════════════════════════
def render(rep: dict, lang: str = "fa") -> str:
    L: List[str] = []
    w = L.append
    w("# مغز دوم — آزمون صادقانهٔ یک مدل کنار اتوترید\n")
    w(f"*{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}*\n")
    w(f"- نمادها: **{rep['n_symbols']}** · معاملهٔ قابل‌استفاده: **{rep['n_trades']}** · "
      f"نرخ برد پایه: **{rep['base_win_rate'] * 100:.1f}%** · expectancy پایه: "
      f"**{rep['base_expectancy_r']:+.3f}R**")
    w(f"- بازه: {rep['span'][0]} تا {rep['span'][1]}")
    w(f"- مدل: رگرسیون لجستیک با L2 · {len(FEATURES)} ویژگی ثابت · "
      f"{rep['folds']} بلوک زمانی (walk-forward)\n")

    w("## دروازه — قبل از دیدن نتیجه\n")
    w("| شرط | حد | نتیجه | وضعیت |")
    w("|---|---|---|---|")
    for c in rep["judge"]["checks"]:
        got = c["got"]
        if isinstance(got, list):
            got = "[" + ", ".join("—" if g is None else f"{g:g}" for g in got) + "]"
        elif isinstance(got, float):
            got = f"{got:g}"
        w(f"| {c['fa']} | — | {got} | {'✅' if c['ok'] else '❌'} |")
    w("")
    w(f"### حکم: {rep['judge']['verdict']}\n")

    w("## پیش‌بینی بیرون‌نمونه، به تفکیک چهارک\n")
    w("| چهارک | تعداد | بازهٔ احتمال | expectancy (R) | نرخ برد | سود |")
    w("|---|---:|---|---:|---:|---:|")
    for b in rep["buckets"]:
        w(f"| {b['part']} | {b['n']} | {b['p_lo']:.2f}–{b['p_hi']:.2f} | "
          f"{b['expectancy_r']:+.3f} | {b['win_rate'] * 100:.1f}% | {b['pnl']:+.2f}$ |")
    w("")
    w(f"AUC بیرون‌نمونه: **{rep['auc'] if rep['auc'] is not None else '—'}** "
      f"(۰.۵ = سکهٔ منصف)\n")

    ft = rep.get("filter") or {}
    if ft.get("ok"):
        w("## آزمون فیلتر — «کم‌اعتمادترین‌ها را رد کن»\n")
        w(f"- نگه‌داشته: **{ft['n_kept']}** معامله · expectancy **{ft['expectancy_kept']:+.3f}R**")
        w(f"- ردشده: **{ft['n_dropped']}** معامله · expectancy **{ft['expectancy_dropped']:+.3f}R**")
        w(f"- همه: **{ft['expectancy_all']:+.3f}R** · Δ نگه‌داشته نسبت به همه: "
          f"**{ft['delta_kept_vs_all']:+.3f}R** · Δ سود: **{ft['pnl_delta']:+.2f}$**")
        ci = ft.get("ci") or {}
        w(f"- بازهٔ اطمینان ۹۰٪ اختلاف: **{ci.get('ci')}** — {ci.get('note', '')}\n")
    else:
        w(f"## آزمون فیلتر\n\n{ft.get('note', 'انجام نشد')}\n")

    w("## ضرایب مدل و پایداری‌شان\n")
    w("| ویژگی | توضیح | علامت | پایداری در فولدها | ضریب میانگین |")
    w("|---|---|---|---:|---:|")
    for s in rep["coefficients"]:
        sign = "＋" if (s.get("sign") or 0) > 0 else ("－" if (s.get("sign") or 0) < 0 else "۰")
        st = "—" if s.get("stability") is None else f"{s['stability'] * 100:.0f}%"
        mc = "—" if s.get("mean_coef") is None else f"{s['mean_coef']:+.3f}"
        w(f"| `{s['name']}` | {s['fa']} | {sign} | {st} | {mc} |")
    w("")
    w("> علامت ＋ یعنی «احتمال برد بیشتر». اگر پایداری زیر ۶۶٪ است، آن ویژگی "
      "در فولدهای مختلف جهت عوض کرده — یعنی نویز است، نه دانش.\n")
    w("## چه چیزی این‌جا اثبات نشد\n")
    w("- این آزمون روی **همان داده‌ای** است که همهٔ تصمیم‌های قبلی روی آن گرفته شد. "
      "حتی اگر پاس شود، «فرضیهٔ قوی» است نه اثبات. اثبات فقط با دادهٔ ندیده می‌آید.")
    w("- مدل **سیگنال نمی‌سازد**؛ در بهترین حالت مجوز دارد سیگنال‌های موجود را "
      "رتبه بدهد یا کم‌اعتمادها را رد کند.")
    w("- هر تغییر بعدی در ویژگی‌ها = آزمایش جدید با شمارندهٔ تازه.\n")
    return "\n".join(L) + "\n"


# ══════════════════════════════════════════════════════════════════════════
#  ۵) CLI
# ══════════════════════════════════════════════════════════════════════════
def brain_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .autoscan import set_lang, _t, variants_for
    from .sweep import deliver

    p = argparse.ArgumentParser(
        prog="mtflab brain",
        description="آزمون صادقانهٔ یک مدل کوچک کنار اتوترید (روی دادهٔ کش‌شده)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--symbols", nargs="+", default=None)
    p.add_argument("--variant", default="trend")
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--folds", type=int, default=4)
    p.add_argument("--skip-frac", type=float, default=0.30)
    p.add_argument("--dataset", default="results/brain_dataset.jsonl",
                   help="مسیر ذخیرهٔ مجموعه داده (برای اجرای بعدی بدون بک‌تست)")
    p.add_argument("--from-dataset", default="",
                   help="از مجموعه دادهٔ ذخیره‌شده بخوان (بدون بک‌تست)")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)
    set_lang(a.lang)

    if a.from_dataset:
        rows = []
        with open(a.from_dataset, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    else:
        universe = load_universe(a.data_dir, a.tf, a.symbols)
        if not universe:
            print(_t("❌ هیچ داده‌ای در کش نیست. اول `bash run-auto.sh --live` یا "
                     "دانلود داده را اجرا کن.",
                     "❌ no cached data. Run `bash run-auto.sh --live` first."))
            return 2
        cfg = load_config(["--data", "synthetic", "--quiet"])
        cfg = replace(cfg, tf_trigger=a.tf, tf_filter=a.tf_filter, tf_bias=a.tf_bias,
                      verbose=False, forensics=False, run_id="", symbol="")
        by_id = {v[0]: v for v in variants_for(a.tf, a.tf_filter, a.tf_bias)}
        vid = a.variant if a.variant in by_id else "trend"
        cfg = replace(cfg, **by_id[vid][2])
        print(_t(f"⏳ ساخت مجموعه داده از {len(universe)} نماد …",
                 f"⏳ building dataset from {len(universe)} symbols …"))
        rows = build_dataset(universe, cfg, a.tf, a.tf_filter, a.tf_bias)
        os.makedirs(os.path.dirname(os.path.abspath(a.dataset)) or ".", exist_ok=True)
        with open(a.dataset, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(_t(f"   ✅ {len(rows)} معامله ذخیره شد: {a.dataset}",
                 f"   ✅ {len(rows)} trades saved: {a.dataset}"))

    if len(rows) < 60:
        print(_t(f"❌ نمونه کافی نیست ({len(rows)} معامله). حداقل ~۶۰ لازم است.",
                 f"❌ too few trades ({len(rows)})."))
        return 2

    try:
        preds, blocks, coefs = walk_forward(rows, a.folds)
    except ValueError as e:
        print(_t(f"❌ {e}", f"❌ {e}"))
        return 2
    if not preds:
        print(_t("❌ walk-forward هیچ پیش‌بینی‌ای نساخت (فولدها کوچک‌اند).",
                 "❌ walk-forward produced no predictions."))
        return 2
    rep = {
        "version": VERSION,
        "n_symbols": len({r.get("symbol") for r in rows}),
        "n_trades": len(rows),
        "n_oof": len(preds),
        "folds": len(blocks),
        "span": [time.strftime("%Y-%m-%d", time.gmtime(rows[0]["entry_ts"] / 1000)),
                 time.strftime("%Y-%m-%d", time.gmtime(rows[-1]["entry_ts"] / 1000))],
        "base_win_rate": round(_mean([r["y"] for r in rows]), 4),
        "base_expectancy_r": round(_mean([r["r"] for r in rows]), 4),
        "auc": auc(preds),
        "buckets": bucket_table(preds, 4),
        "filter": filter_test(preds, a.skip_frac),
        "coefficients": sign_stability(coefs),
        "features": [{"name": n, "fa": fa} for n, fa in FEATURES],
        "gate": GATE,
    }
    rep["judge"] = judge(rep)
    md = render(rep, a.lang)
    os.makedirs(a.out_dir, exist_ok=True)
    md_path = os.path.join(a.out_dir, "brain_report.md")
    js_path = os.path.join(a.out_dir, "brain_report.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    print("\n" + md)
    print(f"📄 {os.path.abspath(md_path)}\n🗂 {os.path.abspath(js_path)}")
    deliver([md_path, js_path], a.out_dir, lang=a.lang)
    return 0
