"""اعتبارسنجی علمی سناریوی جدید — طبق docs/validation_plan.md.

شامل:
1. split سه‌بخشی train / validation / out-of-sample (نسبت‌ها از کانفیگ)
2. walk-forward با پنجره‌های غلتان (+ انتخاب مجدد آستانه روی train هر پنجره)
3. مونت‌کارلو (bootstrap روی پیامد معاملات) → P(سود)، صدک ۵، توزیع MaxDD، ریسک ورشکستگی
4. خط‌های پایه: Buy&Hold، تک‌تایم‌فریم (بدون فیلتر/بایاس)، کنترل تصادفی
5. تحلیل حساسیت روی پارامترهای کلیدی + معیارهای overfit

همهٔ توابع فقط از کتابخانهٔ استاندارد استفاده می‌کنند.
"""
from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import MTFConfig
from .data import Candle
from .engine import run_backtest


# ----------------------------------------------------------------------------
# ابزارهای عمومی
# ----------------------------------------------------------------------------
def _quiet(cfg: MTFConfig, **over) -> MTFConfig:
    return replace(cfg, verbose=False, forensics=False, run_id="", **over)


def _slice_layers(layers: Dict[str, List[Candle]], cfg: MTFConfig,
                  start_ts: int, end_ts: int) -> Dict[str, List[Candle]]:
    """برش زمانی: تریگر فقط در بازه؛ فیلتر/بایاس همهٔ تاریخِ <= انتهای بازه.

    چرا فیلتر/بایاس از ابتدای داده نگه داشته می‌شوند؟ چون warmup اندیکاتور
    (EMA200 و ADX) نیاز به تاریخ دارد و دادهٔ گذشته «آینده» نیست → نشتی ندارد.
    """
    trig = [c for c in layers["trigger"] if start_ts <= c.open_time_ms <= end_ts]
    filt = [c for c in layers["filter"] if c.open_time_ms <= end_ts]
    bias = [c for c in layers["bias"] if c.open_time_ms <= end_ts]
    return {"trigger": trig, "filter": filt, "bias": bias}


def _run(cfg: MTFConfig, layers) -> dict:
    res = run_backtest(_quiet(cfg), layers)
    return res


def metrics(trades: Sequence[dict], initial_equity: float = 1000.0) -> dict:
    """معیارهای استاندارد روی لیست معاملات بسته‌شده."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
                "expectancy_r": 0.0, "total_pnl": 0.0, "return_pct": 0.0,
                "max_drawdown_pct": 0.0, "avg_bars_held": 0.0}
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gw / gl if gl > 0 else (float("inf") if gw > 0 else 0.0)
    total = sum(t["pnl"] for t in trades)

    eq = initial_equity
    peak = eq
    mdd = 0.0
    for t in sorted(trades, key=lambda x: x["ts"]):
        eq += t["pnl"]
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, (eq - peak) / peak * 100.0)

    return {
        "n": n,
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n, 4),
        "profit_factor": round(pf, 4) if math.isfinite(pf) else None,
        "expectancy": round(total / n, 4),
        "expectancy_r": round(sum(t.get("r_multiple", 0.0) for t in trades) / n, 4),
        "total_pnl": round(total, 4),
        "total_fees": round(sum(t.get("fees", 0.0) for t in trades), 4),
        "return_pct": round(total / initial_equity * 100.0, 4),
        "max_drawdown_pct": round(mdd, 4),
        "avg_bars_held": round(sum(t.get("bars_held", 0) for t in trades) / n, 2),
        "best": round(max(t["pnl"] for t in trades), 4),
        "worst": round(min(t["pnl"] for t in trades), 4),
    }


def wilson_ci(hits: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def split_boundaries(n: int, train_ratio: float, val_ratio: float) -> Tuple[int, int]:
    """ایندکس‌های مرز train/val/OOS روی `n` کندل تریگر."""
    i1 = int(n * train_ratio)
    i2 = int(n * (train_ratio + val_ratio))
    return max(1, i1), max(i1 + 1, i2)


# ----------------------------------------------------------------------------
# ۱) split سه‌بخشی
# ----------------------------------------------------------------------------
def run_split(cfg: MTFConfig, layers: Dict[str, List[Candle]]) -> dict:
    trig = layers["trigger"]
    n = len(trig)
    i1, i2 = split_boundaries(n, cfg.train_ratio, cfg.validation_ratio)
    out: Dict[str, dict] = {"ratios": {"train": cfg.train_ratio, "validation": cfg.validation_ratio,
                                       "out_of_sample": cfg.out_of_sample_ratio},
                            "segments": []}
    segs = [("TRAIN", trig[0].open_time_ms, trig[i1 - 1].open_time_ms, i1 - 0),
            ("VALIDATION", trig[i1].open_time_ms, trig[i2 - 1].open_time_ms, i2 - i1),
            ("OUT_OF_SAMPLE", trig[i2].open_time_ms, trig[-1].open_time_ms, n - i2)]
    for label, s, e, cnt in segs:
        sub = _slice_layers(layers, cfg, s, e)
        res = _run(cfg, sub)
        m = metrics(res["trades"], cfg.initial_equity)
        m.update({"segment": label, "candles": cnt, "start_ts": s, "end_ts": e})
        out["segments"].append(m)

    tr = out["segments"][0]
    oos = out["segments"][2]
    deg = None
    if tr["n"] >= 5 and oos["n"] >= 5 and tr["expectancy"]:
        deg = round((oos["expectancy"] - tr["expectancy"]) / abs(tr["expectancy"]), 4)
    out["degradation_train_to_oos"] = deg
    out["verdict"] = _verdict_split(tr, out["segments"][1], oos)
    return out


def _verdict_split(tr: dict, va: dict, oos: dict) -> dict:
    ok_oos = oos["n"] >= 20 and (oos["profit_factor"] or 0) >= 1.0 and oos["expectancy"] > 0
    consistent = (tr["expectancy"] > 0) == (oos["expectancy"] > 0) if tr["n"] and oos["n"] else False
    return {
        "oos_profitable": bool(ok_oos),
        "train_oos_consistent_sign": bool(consistent),
        "min_samples_met": bool(tr["n"] >= 30 and va["n"] >= 15 and oos["n"] >= 15),
        "pass": bool(ok_oos and consistent),
        "note": ("✅ OOS سودده و هم‌علامت با train" if ok_oos and consistent else
                 "❌ شواهد کافی برای «edge واقعی» نیست — به tuning بیشتر یا دادهٔ بیشتر نیاز دارد"),
    }


# ----------------------------------------------------------------------------
# ۲) walk-forward
# ----------------------------------------------------------------------------
def walk_forward(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                 windows: Optional[int] = None) -> dict:
    """پنجره‌های غلتان: در هر پنجره یک بخش train و یک بخش test.

    اگر `walk_forward_reselect` روشن باشد، آستانهٔ ADX (و در نسخهٔ B آستانهٔ
    امتیاز) فقط روی بخش train همان پنجره انتخاب می‌شود و به test منتقل می‌شود.
    این کار دقیقاً همان چیزی است که overfitting را لو می‌دهد: اگر آستانه‌های
    «بهینهٔ محلی» پایدار نباشند، عملکرد test پراکنده می‌شود.
    """
    w = int(windows or cfg.walk_forward_windows)
    trig = layers["trigger"]
    n = len(trig)
    if w < 2 or n < w * 50:
        return {"windows": [], "note": "داده برای walk-forward کافی نیست"}

    block = n // (w + 1)          # w پنجرهٔ test، هرکدام با یک block train قبلش
    rows: List[dict] = []
    grid = [18.0, 22.0, 26.0, 30.0]
    for k in range(w):
        tr_s = k * block
        tr_e = (k + 1) * block - 1
        te_s = (k + 1) * block
        te_e = min((k + 2) * block - 1, n - 1)
        if te_s >= n or te_e <= te_s:
            break
        train_sub = _slice_layers(layers, cfg, trig[tr_s].open_time_ms, trig[tr_e].open_time_ms)
        test_sub = _slice_layers(layers, cfg, trig[te_s].open_time_ms, trig[te_e].open_time_ms)

        chosen = {"filter_adx_min": cfg.filter_adx_min, "score_min": cfg.score_min}
        if cfg.walk_forward_reselect:
            best = None
            for adx in grid:
                res = _run(replace(cfg, filter_adx_min=adx), train_sub)
                m = metrics(res["trades"], cfg.initial_equity)
                key = (m["expectancy"], m["n"])
                if m["n"] >= 5 and (best is None or key > best[0]):
                    best = (key, adx)
            if best:
                chosen["filter_adx_min"] = best[1]

        c2 = replace(cfg, **chosen)
        res = _run(c2, test_sub)
        m = metrics(res["trades"], cfg.initial_equity)
        m.update({"window": k + 1, "train_candles": tr_e - tr_s + 1,
                  "test_candles": te_e - te_s + 1,
                  "test_start_ts": trig[te_s].open_time_ms, "test_end_ts": trig[te_e].open_time_ms,
                  "selected_adx_min": chosen["filter_adx_min"]})
        rows.append(m)

    tested = [r for r in rows if r["n"] >= 5]          # پنجره‌هایی که نمونهٔ قابل‌قضاوت دارند
    exps = [r["expectancy"] for r in tested]
    pfs = [r["profit_factor"] for r in tested if r["profit_factor"] is not None]
    mean_e = sum(exps) / len(exps) if exps else 0.0
    std_e = (sum((x - mean_e) ** 2 for x in exps) / len(exps)) ** 0.5 if len(exps) > 1 else 0.0
    prof = sum(1 for x in exps if x > 0)
    need = max(1, math.ceil(len(tested) * 0.6))
    if not tested:
        verdict = "⚠️ هیچ پنجره‌ای نمونهٔ کافی نداشت (معاملات کم — warmup یا فیلترهای سخت‌گیرانه)"
    elif prof >= need:
        verdict = f"✅ پایدار: {prof} از {len(tested)} پنجرهٔ آزمون‌شده سودده"
    else:
        verdict = f"❌ ناپایدار: فقط {prof} از {len(tested)} پنجرهٔ آزمون‌شده سودده"
    return {
        "windows": rows,
        "n_windows": len(rows),
        "tested_windows": len(tested),
        "profitable_windows": prof,
        "mean_expectancy": round(mean_e, 4),
        "std_expectancy": round(std_e, 4),
        "stability": round(1.0 - min(std_e / abs(mean_e), 1.0), 4) if mean_e else 0.0,
        "mean_pf": round(sum(pfs) / len(pfs), 4) if pfs else None,
        "reselect_enabled": bool(cfg.walk_forward_reselect),
        "verdict": verdict,
    }


# ----------------------------------------------------------------------------
# ۳) مونت‌کارلو
# ----------------------------------------------------------------------------
def monte_carlo(trades: Sequence[dict], simulations: int = 1000, seed: int = 42,
                initial_equity: float = 1000.0, ruin_threshold_pct: float = 50.0) -> dict:
    """bootstrap با جایگذاری روی پیامد معاملات → توزیع نتیجه.

    این روش فرض می‌کند ترتیبِ معاملات تصادفی است (که برای برآوردِ ریسکِ
    drawdown منطقی است) ولی **تعداد** معاملات را ثابت نگه می‌دارد.
    """
    pnls = [t["pnl"] for t in trades]
    n = len(pnls)
    if n < 10:
        return {"simulations": 0, "note": "معاملات کافی برای مونت‌کارلو نیست (<10)"}
    rng = random.Random(seed)
    totals: List[float] = []
    mdds: List[float] = []
    ruins = 0
    profits = 0
    sims = max(10, int(simulations))
    for _ in range(sims):
        eq = initial_equity
        peak = eq
        mdd = 0.0
        tot = 0.0
        for _j in range(n):
            p = pnls[rng.randrange(n)]
            eq += p
            tot += p
            peak = max(peak, eq)
            if peak > 0:
                mdd = min(mdd, (eq - peak) / peak * 100.0)
            if eq <= initial_equity * (1 - ruin_threshold_pct / 100.0):
                ruins += 1
                break
        totals.append(tot)
        mdds.append(mdd)
        if tot > 0:
            profits += 1

    totals.sort()
    mdds.sort()

    def pct(arr, q):
        if not arr:
            return 0.0
        i = min(len(arr) - 1, max(0, int(q * (len(arr) - 1))))
        return round(arr[i], 4)

    return {
        "simulations": sims, "trades_per_sim": n, "seed": seed,
        "p_profit": round(profits / sims, 4),
        "p_ruin": round(ruins / sims, 4),
        "total_pnl_p5": pct(totals, 0.05), "total_pnl_median": pct(totals, 0.50),
        "total_pnl_p95": pct(totals, 0.95),
        "total_pnl_mean": round(sum(totals) / len(totals), 4),
        "max_dd_p50": pct(mdds, 0.50), "max_dd_p95": pct(mdds, 0.05),
        "ruin_threshold_pct": ruin_threshold_pct,
        "histogram": _histogram(totals, bins=12),
    }


def _histogram(values: Sequence[float], bins: int = 12) -> List[dict]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [{"lo": round(lo, 2), "hi": round(hi, 2), "count": len(values)}]
    step = (hi - lo) / bins
    out = [{"lo": round(lo + i * step, 2), "hi": round(lo + (i + 1) * step, 2), "count": 0}
           for i in range(bins)]
    for v in values:
        idx = min(bins - 1, int((v - lo) / step))
        out[idx]["count"] += 1
    return out


# ----------------------------------------------------------------------------
# ۴) خط‌های پایه (baselines)
# ----------------------------------------------------------------------------
def buy_and_hold(layers: Dict[str, List[Candle]], cfg: MTFConfig) -> dict:
    trig = layers["trigger"]
    if len(trig) < 2:
        return {"n": 0}
    p0, p1 = trig[0].open, trig[-1].close
    ret = (p1 / p0 - 1) * 100 if p0 else 0.0
    eq = cfg.initial_equity
    peak = eq
    mdd = 0.0
    for c in trig:
        eq = cfg.initial_equity * (c.close / p0)
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak * 100.0)
    return {"start_price": p0, "end_price": p1, "return_pct": round(ret, 4),
            "total_pnl": round(cfg.initial_equity * ret / 100.0, 4),
            "max_drawdown_pct": round(mdd, 4), "candles": len(trig),
            "note": "بدون اهرم، بدون کارمزد (مرجعِ بازار)"}


def single_timeframe_baseline(cfg: MTFConfig, layers: Dict[str, List[Candle]]) -> dict:
    """همان تریگر ولی **بدون** لایهٔ فیلتر و بایاس — یعنی ارزش افزودهٔ MTF چقدر است؟

    برای اینکه فیلتر واقعاً حذف شود، `filter_adx_min` روی صفر و نسخهٔ C گذاشته
    می‌شود و بایاس خاموش می‌شود؛ در نتیجه تنها شرطِ جهت، خودِ تریگر است.
    """
    c2 = replace(cfg, alignment_version="C", bias_enabled=False, filter_adx_min=0.0,
                 filter_slope_min_pct=0.0, filter_confirm_bars=1)
    res = _run(c2, layers)
    m = metrics(res["trades"], cfg.initial_equity)
    m["label"] = "تک‌تایم‌فریم (بدون فیلتر/بایاس)"
    return m


def random_control(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                   n_trades: int = 60, seed: int = 7) -> dict:
    """کنترل تصادفی: ورود در کندل‌های تصادفی با همان قواعد خروج/ریسک.

    هر استراتژی که از این کنترل بهتر نباشد، ارزشی اضافه نکرده است.
    پیاده‌سازی: نسخهٔ C با آستانه‌های کاملاً باز (ADX=0، تأیید=1) و
    `min_confidence` روی مقدار تصادفی‌ساز → عملاً تصادفی نیست، پس به‌جای آن
    یک موتورِ تصادفیِ صریح با همان rules خروج اجرا می‌شود.
    """
    rng = random.Random(seed)
    trig = layers["trigger"]
    n = len(trig)
    if n < 200:
        return {"n": 0, "note": "داده کافی نیست"}
    idxs = sorted(rng.sample(range(150, n - 5), min(n_trades * 3, n - 200)))

    # شبیه‌سازی ساده با همان پارامترهای ریسک/خروج (stop/take بر پایهٔ ATR)
    from .signals import TFContext
    ctx = TFContext(trig, cfg, "trigger")
    eq = float(cfg.initial_equity)
    peak = eq
    mdd = 0.0
    out: List[dict] = []
    fee_frac = (cfg.fee_bps / 10_000 + cfg.slippage_pct / 100) * 2
    i = 150
    pos = None
    for i in range(150, n):
        c = trig[i]
        if pos is not None:
            a = ctx.atr[i] or pos["atr"]
            hit_stop = (c.low <= pos["stop"]) if pos["dir"] == 1 else (c.high >= pos["stop"])
            hit_take = (c.high >= pos["take"]) if pos["dir"] == 1 else (c.low <= pos["take"])
            exit_px = None
            reason = ""
            if hit_stop:
                exit_px, reason = pos["stop"], "stop_loss"
            elif hit_take:
                exit_px, reason = pos["take"], "take_profit"
            elif i - pos["i"] >= (cfg.max_holding_bars or 96):
                exit_px, reason = c.close, "time_stop"
            if exit_px is not None:
                slip = cfg.slippage_pct / 100
                fill = exit_px * (1 - slip) if pos["dir"] == 1 else exit_px * (1 + slip)
                pnl = pos["dir"] * (fill - pos["entry"]) * pos["qty"] - pos["fee"]
                eq += pnl
                peak = max(peak, eq)
                mdd = min(mdd, (eq - peak) / peak * 100)
                out.append({"ts": c.open_time_ms, "pnl": pnl, "is_win": pnl > 0,
                            "reason": reason, "bars_held": i - pos["i"],
                            "r_multiple": pnl / pos["risk"] if pos["risk"] else 0.0,
                            "fees": pos["fee"]})
                pos = None
        if pos is None and i in idxs:
            if ctx.atr[i] is None or ctx.atr[i] <= 0:
                continue
            direction = rng.choice([1, -1])
            entry = c.close * (1 + direction * cfg.slippage_pct / 100)
            sd = ctx.atr[i] * cfg.stop_atr_mult
            risk = cfg.fixed_risk if cfg.fixed_risk > 0 else eq * cfg.risk_per_trade_pct / 100
            qty = risk / sd if sd else 0
            notional = qty * entry
            if notional > eq * cfg.max_leverage:
                qty = eq * cfg.max_leverage / entry
                notional = qty * entry
            pos = {"dir": direction, "entry": entry, "qty": qty, "i": i, "atr": ctx.atr[i],
                   "stop": entry - direction * sd, "take": entry + direction * sd * cfg.rr,
                   "fee": notional * fee_frac, "risk": risk}

    m = metrics(out, cfg.initial_equity)
    m.update({"equity": round(eq, 4), "max_drawdown_pct": round(mdd, 4),
              "label": "کنترل تصادفی (همان قواعد خروج/ریسک)"})
    return m


# ----------------------------------------------------------------------------
# ۵) تحلیل حساسیت + معیارهای overfit
# ----------------------------------------------------------------------------
SENSITIVITY_PARAMS: List[Tuple[str, List[float]]] = [
    ("filter_adx_min", [18.0, 22.0, 26.0, 30.0]),
    ("stop_atr_mult", [1.2, 1.5, 2.0]),
    ("take_profit_atr_mult", [2.4, 3.0, 4.0]),
    ("min_edge_multiplier", [1.0, 1.5, 2.5]),
    ("trigger_vol_z_min", [0.6, 1.2, 2.0]),
]


def sensitivity(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                grid: Optional[List[Tuple[str, List[float]]]] = None) -> dict:
    """اگر نتیجه با تغییر پارامتر «جهش» دارد → overfit؛ اگر صاف است → robust."""
    grid = grid or SENSITIVITY_PARAMS
    rows: Dict[str, List[dict]] = {}
    trials = 0
    all_pf: List[float] = []
    for name, values in grid:
        rows[name] = []
        for v in values:
            res = _run(replace(cfg, **{name: v}), layers)
            m = metrics(res["trades"], cfg.initial_equity)
            m["value"] = v
            rows[name].append(m)
            trials += 1
            if m["n"] and m["profit_factor"] is not None:
                all_pf.append(m["profit_factor"])
    spread = (max(all_pf) - min(all_pf)) if all_pf else 0.0
    return {
        "grid": rows, "trials": trials,
        "pf_min": round(min(all_pf), 4) if all_pf else None,
        "pf_max": round(max(all_pf), 4) if all_pf else None,
        "pf_spread": round(spread, 4),
        "robust": bool(all_pf and spread <= 0.6 and min(all_pf) >= 0.7),
        "note": ("✅ حساسیت پایین → robust" if all_pf and spread <= 0.6 else
                 "⚠️ حساسیت بالا → نتیجه به پارامتر وابسته است (خطر overfit)"),
    }


def overfit_checks(split_res: dict, wf_res: dict, mc_res: dict, sens_res: dict,
                   base_res: dict, random_res: dict, strat: dict,
                   single_res: Optional[dict] = None) -> dict:
    """چک‌لیست نهایی overfit — هر مورد صریح pass/fail."""
    checks: List[dict] = []

    oos = next((s for s in split_res.get("segments", []) if s["segment"] == "OUT_OF_SAMPLE"), {})
    tr = next((s for s in split_res.get("segments", []) if s["segment"] == "TRAIN"), {})
    checks.append({
        "name": "OOS سودده است (PF≥1 و expectancy>0)",
        "pass": bool(oos.get("n", 0) >= 20 and (oos.get("profit_factor") or 0) >= 1.0
                     and oos.get("expectancy", 0) > 0),
        "detail": f"OOS: n={oos.get('n', 0)} PF={oos.get('profit_factor')} exp={oos.get('expectancy')}",
    })
    checks.append({
        "name": "افت train→OOS کمتر از ۵۰٪",
        "pass": bool(split_res.get("degradation_train_to_oos") is not None
                     and split_res["degradation_train_to_oos"] > -0.5),
        "detail": f"degradation={split_res.get('degradation_train_to_oos')}",
    })
    _tested = wf_res.get("tested_windows") or 0
    checks.append({
        "name": "walk-forward پایدار (≥۶۰٪ پنجره‌های آزمون‌شده سودده)",
        "pass": bool(_tested >= 3 and wf_res.get("profitable_windows", 0) >= 0.6 * _tested),
        "detail": f"{wf_res.get('profitable_windows', 0)}/{_tested} پنجرهٔ آزمون‌شده سودده "
                  f"(از {wf_res.get('n_windows', 0)} پنجره)",
    })
    checks.append({
        "name": "مونت‌کارلو: P(سود) ≥ ۰.۶ و P(ورشکستگی) ≤ ۰.۱",
        "pass": bool(mc_res.get("simulations") and mc_res.get("p_profit", 0) >= 0.6
                     and mc_res.get("p_ruin", 1) <= 0.1),
        "detail": f"P(profit)={mc_res.get('p_profit')} P(ruin)={mc_res.get('p_ruin')}",
    })
    checks.append({
        "name": "بهتر از Buy&Hold (بازده ریسک‌پذیر کمتر)",
        "pass": bool(strat.get("n", 0) and base_res.get("max_drawdown_pct") is not None and
                     abs(strat.get("max_drawdown_pct", 0)) <= abs(base_res["max_drawdown_pct"]) and
                     strat.get("return_pct", 0) > base_res.get("return_pct", -1e9)),
        "detail": f"strat ret={strat.get('return_pct')}% DD={strat.get('max_drawdown_pct')}% | "
                  f"B&H ret={base_res.get('return_pct')}% DD={base_res.get('max_drawdown_pct')}%",
    })
    checks.append({
        "name": "بهتر از کنترل تصادفی (همان قواعد خروج)",
        "pass": bool(strat.get("n", 0) and random_res.get("n", 0) and
                     strat.get("expectancy", -1e9) > random_res.get("expectancy", 1e9)),
        "detail": f"strat exp={strat.get('expectancy')} در برابر "
                  f"random exp={random_res.get('expectancy')} (n={random_res.get('n', 0)})",
    })
    if single_res is not None:
        checks.append({
            "name": "بهتر از نسخهٔ تک‌تایم‌فریم (ارزش افزودهٔ لایه‌های MTF)",
            "pass": bool(strat.get("n", 0) and single_res.get("n", 0) and
                         strat.get("expectancy", -1e9) >= single_res.get("expectancy", 1e9)),
            "detail": f"MTF exp={strat.get('expectancy')} (n={strat.get('n', 0)}) در برابر "
                      f"تک‌لایه exp={single_res.get('expectancy')} (n={single_res.get('n', 0)})",
        })
    checks.append({
        "name": "حساسیت پارامتر پایین (spread PF ≤ ۰.۶)",
        "pass": bool(sens_res.get("pf_spread") is not None and sens_res["pf_spread"] <= 0.6),
        "detail": f"spread={sens_res.get('pf_spread')} در {sens_res.get('trials', 0)} آزمایش",
    })
    checks.append({
        "name": "تعداد نمونهٔ کافی (≥۳۰ معامله در هر بخش)",
        "pass": bool(min([s.get("n", 0) for s in split_res.get("segments", [])] or [0]) >= 30),
        "detail": ", ".join(f"{s['segment']}={s.get('n',0)}" for s in split_res.get("segments", [])),
    })
    checks.append({
        "name": "هزینه لحاظ شده (کارمزد کل > ۰ و در گزارش ثبت شده)",
        "pass": bool(strat.get("total_fees", 0) > 0),
        "detail": f"fees={strat.get('total_fees')}",
    })
    passed = sum(1 for c in checks if c["pass"])
    return {"checks": checks, "passed": passed, "total": len(checks),
            "score": round(passed / len(checks), 4) if checks else 0.0,
            "verdict": ("✅ شواهد کافی برای ادامه (نه هنوز LIVE)" if passed >= len(checks) - 1 else
                        "⚠️ شواهد ناقص — فقط PAPER بماند" if passed >= len(checks) // 2 else
                        "❌ edge اثبات نشد — این سناریو را به LIVE نبر")}


# ----------------------------------------------------------------------------
# اجرای کامل اعتبارسنجی
# ----------------------------------------------------------------------------
def full_validation(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                    progress: bool = True) -> dict:
    """همهٔ مراحل اعتبارسنجی؛ خروجی در گزارش JSON/MD و داشبورد می‌آید."""
    base_res = _run(cfg, layers)
    strat = metrics(base_res["trades"], cfg.initial_equity)
    strat["health"] = base_res["health"]

    if progress:
        print("🔬 اعتبارسنجی: split …")
    split_res = run_split(cfg, layers)
    if progress:
        print("🔬 اعتبارسنجی: walk-forward …")
    wf_res = walk_forward(cfg, layers)
    if progress:
        print("🔬 اعتبارسنجی: monte-carlo …")
    mc_res = monte_carlo(base_res["trades"], cfg.monte_carlo_simulations, cfg.seed,
                         cfg.initial_equity)
    if progress:
        print("🔬 اعتبارسنجی: baselines …")
    bh = buy_and_hold(layers, cfg)
    single = single_timeframe_baseline(cfg, layers)
    rnd = random_control(cfg, layers, seed=cfg.seed + 1)
    sens: dict = {"grid": {}, "trials": 0, "note": "غیرفعال"}
    if cfg.sensitivity_grid:
        if progress:
            print("🔬 اعتبارسنجی: sensitivity …")
        sens = sensitivity(cfg, layers)

    overfit = overfit_checks(split_res, wf_res, mc_res, sens, bh, rnd, strat, single)
    return {
        "overall": strat,
        "split": split_res,
        "walk_forward": wf_res,
        "monte_carlo": mc_res,
        "baselines": {"buy_hold": bh, "single_timeframe": single, "random_control": rnd},
        "sensitivity": sens,
        "overfit": overfit,
    }
