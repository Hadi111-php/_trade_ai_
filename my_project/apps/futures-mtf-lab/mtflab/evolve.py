"""حلقهٔ تطبیق زنده (evolve) — قهرمان/چالش‌گر با دروازهٔ ارتقای آماری.

ایدهٔ خام: «هر بار معامله بسته شد، تنظیمات را بازنویسی کن.» این ایده در عمل
روی نویز فیت می‌کند (هر معامله = یک نمونه). این ماژول همان ایده را به شکلی
می‌سازد که قابل دفاع باشد:

  ۱) بجای بازنویسی، دو لایهٔ تغییر داریم:
     - τ  : «خون‌سردی» — یک عدد پیوسته که فاصله‌ها را می‌کشد/جمع می‌کند
            (استاپ، TP، شروع تریل، حداقل edge). τ=۱ یعنی همان فرمول فعلی.
     - knob: حداکثر یک تغییر ساختاری از یک فهرست از پیش ثبت‌شده.
  ۲) انتخاب فقط روی گذشته انجام می‌شود؛ ارزیابی فقط روی آیندهٔ دیده‌نشده.
  ۳) ارتقا فقط با دروازهٔ آماری از پیش تعیین‌شده (نه چون «بهتر به‌نظر می‌رسد»).
  ۴) میخ‌کشی به فرمول فعلی: θ_new = θ + λ(θ'-θ) با λ کوچک → حرکت تدریجی.
  ۵) پلاسیبوی اجباری: همان حلقه با انتخاب تصادفی. اگر پلاسیبو هم سود داد،
     یعنی «یادگیری» نویز است و کل قابلیت بی‌ارزش.

همهٔ این‌ها با موتور واقعی بک‌تست اجرا می‌شوند (بدون شبیه‌ساز موازی و بدون
منطق خروجِ دست‌ساز دوم) تا نتیجه با بقیهٔ اپ قابل مقایسه بماند.
"""
from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import MTFConfig
from .data import Candle
from .diagnose import _position_pnls, _slice_layers
from .engine import run_backtest

# ----------------------------------------------------------------------------
# فضای جست‌وجو (کوچک و از پیش ثبت‌شده — عمداً کوچک)
# ----------------------------------------------------------------------------
TEMPERAMENTS: Tuple[float, ...] = (0.85, 1.0, 1.15)

#: کلیدهایی که τ آن‌ها را به‌طور یکنواخت می‌کشد/جمع می‌کند.
#: همه‌شان «فاصله» هستند (به ATR یا به R)، پس یک عدد می‌تواند هم‌زمان
#: بزرگ‌ترشان کند و معنایش یکی بماند: معاملهٔ صبورتر و سخت‌گیرتر.
DISTANCE_KEYS = ("stop_atr_mult", "take_profit_atr_mult", "trail_atr_mult",
                 "trail_start_r", "min_edge_multiplier")

#: تغییرات ساختاری مجاز — فقط سه گزینه، همه از یافته‌های داده‌محورِ diagnose.
SHALLOW_KNOBS: Tuple[Tuple[str, dict], ...] = (
    ("none", {}),
    ("pullback", {"trigger_entry_modes": ["pullback"]}),
    ("climax_1.0", {"trigger_max_range_atr": 1.0}),
)

DEFAULT_RULES = {
    "min_forward_trades": 12,
    "ci_level": 0.90,          # یک‌طرفه‌تر از ۹۵٪ تا با نمونهٔ کم عملاً بسته نباشد
    "max_dd_worsen_pct": 5.0,  # چالش‌گر نباید افت بیشتری از این حد داشته باشد
    "shrink_lambda": 0.5,      # ۰ = تغییر نکن، ۱ = کامل بپر
    "chunk_bars": 1800,        # ~۷۵ روز روی 1h
    "min_fit_trades": 10,
    "promotion_mode": "strict",  # strict = دروازهٔ آماری | rolling = ارتقای چرخشی
}

#: دو فلسفهٔ ارتقا، هر دو قابل آزمون (داده تصمیم می‌گیرد، نه سلیقه)
PROMOTION_MODES = {
    "strict": {
        "label": "سخت‌گیرانه (دروازهٔ آماری)",
        "note": "ارتقا فقط با معناداری آماری؛ عملاً به‌ندرت رخ می‌دهد.",
    },
    "rolling": {
        "label": "چرخشی (بهبود + بازگشت)",
        "note": "ارتقا با بهبود expectancy در بازهٔ forward و نمونهٔ کافی؛ "
                "اگر دو گام پیاپی از نسخهٔ ثابت بدتر باشیم، به ثابت برمی‌گردیم.",
    },
}


# ----------------------------------------------------------------------------
# τ → پیکربندی
# ----------------------------------------------------------------------------
def apply_temperament(cfg: MTFConfig, tau: float) -> MTFConfig:
    """τ را روی همهٔ «فاصله‌ها» اعمال می‌کند. τ=۱ ⇒ پیکربندی دست‌نخورده."""
    if abs(tau - 1.0) < 1e-12:
        return cfg
    over = {}
    for k in DISTANCE_KEYS:
        v = getattr(cfg, k, None)
        if isinstance(v, (int, float)) and v:
            over[k] = round(float(v) * tau, 6)
    return replace(cfg, **over)


def theta_to_cfg(cfg: MTFConfig, theta: dict) -> MTFConfig:
    c = apply_temperament(cfg, float(theta.get("tau", 1.0)))
    knob = theta.get("knob", "none")
    over = dict(SHALLOW_KNOBS)[knob]
    if over:
        c = replace(c, **over)
    return replace(c, verbose=False, forensics=False, run_id="")


def shrink(old: dict, new: dict, lam: float) -> dict:
    """میخ‌کشی: فرمول جدید فقط به‌اندازهٔ λ به سمت پیشنهاد حرکت می‌کند.

    برای knob (گزینهٔ گسسته) معنی «حرکت تدریجی» این است: تا وقتی λ کمتر از
    آستانهٔ ۰.۵ است، ساختار عوض نمی‌شود؛ فقط τ حرکت می‌کند. این عمدی است —
    تغییر ساختار باید سخت‌تر از تغییر فاصله‌ها باشد.
    """
    tau_old, tau_new = float(old.get("tau", 1.0)), float(new.get("tau", 1.0))
    tau = round(tau_old + lam * (tau_new - tau_old), 4)
    knob = new.get("knob", "none") if lam >= 0.5 else old.get("knob", "none")
    return {"tau": tau, "knob": knob}


# ----------------------------------------------------------------------------
# آمار
# ----------------------------------------------------------------------------
def _mean(v: Sequence[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def bootstrap_ci(a: Sequence[float], b: Sequence[float], level: float = 0.90,
                 sims: int = 1200, seed: int = 7) -> dict:
    """بازهٔ اطمینان بوت‌استرپ برای اختلاف میانگین (a − b)."""
    if len(a) < 4 or len(b) < 4:
        return {"ok": False, "note": "نمونه کم است"}
    rng = random.Random(seed)
    diffs = []
    for _ in range(sims):
        ma = sum(a[rng.randrange(len(a))] for _ in range(len(a))) / len(a)
        mb = sum(b[rng.randrange(len(b))] for _ in range(len(b))) / len(b)
        diffs.append(ma - mb)
    diffs.sort()
    lo_i = int((1 - level) / 2 * (len(diffs) - 1))
    hi_i = int((1 + level) / 2 * (len(diffs) - 1))
    lo, hi = diffs[lo_i], diffs[hi_i]
    return {"ok": True, "level": level, "observed": round(_mean(a) - _mean(b), 4),
            "ci": [round(lo, 4), round(hi, 4)],
            "significant": lo > 0 or hi < 0,
            "note": ("✅ بازه صفر را دربر نمی‌گیرد" if (lo > 0 or hi < 0)
                     else "⚠️ بازه شامل صفر است — تفاوت قابل اثبات نیست")}


def _metrics(res: dict) -> dict:
    trades = res["trades"]
    pnls = _position_pnls(res)
    wins = [p for p in pnls if p > 0]
    gross_w = sum(wins)
    gross_l = -sum(p for p in pnls if p <= 0)
    return {
        "n": len(pnls),
        "n_legs": len(trades),
        "pnl": round(sum(pnls), 4),
        "expectancy": round(_mean(pnls), 4),
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": (round(gross_w / gross_l, 4) if gross_l > 0 else None),
        "max_drawdown_pct": (res["summary"].get("max_drawdown_pct") if res.get("summary")
                             else None),
        "_pnls": pnls,
    }


def _clean(m: dict) -> dict:
    return {k: v for k, v in m.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# اجرای یک θ روی داده
# ----------------------------------------------------------------------------
def _run_on(cfg: MTFConfig, layers: Dict[str, List[Candle]], theta: dict) -> dict:
    c = theta_to_cfg(cfg, theta)
    res = run_backtest(c, layers)
    m = _metrics(res)
    return m


def _pool_metrics(per_symbol: Dict[str, dict]) -> dict:
    """معیارهای تجمیعی دو نماد: همان معامله‌ها، یک استخر (با نرمال‌سازی اندازه)."""
    all_p = []
    for m in per_symbol.values():
        all_p.extend(m["_pnls"])
    if not all_p:
        return {"n": 0, "expectancy": 0.0, "pnl": 0.0, "win_rate": 0.0,
                "profit_factor": None, "max_drawdown_pct": 0.0, "_pnls": []}
    wins = [p for p in all_p if p > 0]
    gross_w = sum(wins)
    gross_l = -sum(p for p in all_p if p <= 0)
    return {
        "n": len(all_p), "pnl": round(sum(all_p), 4),
        "expectancy": round(_mean(all_p), 4),
        "win_rate": round(len(wins) / len(all_p), 4),
        "profit_factor": (round(gross_w / gross_l, 4) if gross_l > 0 else None),
        "max_drawdown_pct": min((m.get("max_drawdown_pct") or 0.0)
                                for m in per_symbol.values()) if per_symbol else 0.0,
        "_pnls": all_p,
    }


# ----------------------------------------------------------------------------
# دروازهٔ ارتقا
# ----------------------------------------------------------------------------
def promotion_gate(champ: dict, chal: dict, rules: dict = None) -> dict:
    rules = dict(DEFAULT_RULES, **(rules or {}))
    ci = bootstrap_ci(chal.get("_pnls", []), champ.get("_pnls", []),
                      level=rules["ci_level"])
    champ_dd = champ.get("max_drawdown_pct") or 0.0
    chal_dd = chal.get("max_drawdown_pct") or 0.0
    checks = {
        "min_sample": chal.get("n", 0) >= rules["min_forward_trades"],
        "gain": chal.get("expectancy", 0.0) > champ.get("expectancy", 0.0),
        "ci_lower_positive": bool(ci.get("ok") and ci["ci"][0] > 0),
        # افت کمتر = عدد منفی‌تر؛ اجازه داریم کمی بدتر شود، نه خیلی
        "risk_tail": (chal_dd >= champ_dd - rules["max_dd_worsen_pct"]),
    }
    return {"promote": all(checks.values()), "checks": checks, "ci": ci,
            "n_champ": champ.get("n", 0), "n_chal": chal.get("n", 0)}


# ----------------------------------------------------------------------------
# حلقهٔ اصلی
# ----------------------------------------------------------------------------
def _chunks(trig: Sequence[Candle], chunk_bars: int) -> List[Tuple[int, int]]:
    n = len(trig)
    if n < chunk_bars * 2:
        return [(0, n - 1)]
    return [(i, min(i + chunk_bars - 1, n - 1))
            for i in range(0, n, chunk_bars)]


def run_evolve(cfg: MTFConfig,
               data: Dict[str, Dict[str, List[Candle]]],
               rules: Optional[dict] = None,
               placebo: bool = False,
               seed: int = 13,
               progress: bool = True) -> dict:
    """آزمون walk-forward: در هر گام، روی گذشته فیت می‌کنیم و روی آینده ارزیابی.

    `data` = {symbol: {"trigger": [...], "filter": [...], "bias": [...]}}
    هیچ‌جای این تابع به کندل‌هایی بعد از نقطهٔ تصمیم نگاه نمی‌کند؛ برای همین
    نتیجهٔ «سود تطبیق» قابل باور است.
    """
    rules = dict(DEFAULT_RULES, **(rules or {}))
    rng = random.Random(seed)
    symbols = list(data)
    trig0 = data[symbols[0]]["trigger"]
    chunks = _chunks(trig0, rules["chunk_bars"])

    theta = {"tau": 1.0, "knob": "none"}
    version = 1
    events: List[dict] = []
    champion_chunks: List[dict] = []
    consecutive_worse = 0

    for k in range(1, len(chunks)):
        fit_i0, fit_i1 = chunks[k - 1]
        ev_i0, ev_i1 = chunks[k]
        t_fit_end = trig0[fit_i1].open_time_ms
        t_ev_start = trig0[ev_i0].open_time_ms
        t_ev_end = trig0[ev_i1].open_time_ms

        # ── ۱) فیت روی پنجرهٔ گذشته (هیچ نگاهی به آینده) ────────────────────
        candidates = [{"tau": t, "knob": kn} for t in TEMPERAMENTS
                      for kn, _ in SHALLOW_KNOBS]
        scores = []
        for cand in candidates:
            pooled = {}
            for sym, layers in data.items():
                sub = _slice_layers(layers, cfg, trig0[fit_i0].open_time_ms, t_fit_end)
                pooled[sym] = _run_on(cfg, sub, cand)
            m = _pool_metrics(pooled)
            scores.append({"theta": cand, "n": m["n"], "expectancy": m["expectancy"],
                           "profit_factor": m["profit_factor"]})

        eligible = [s for s in scores if s["n"] >= rules["min_fit_trades"]]
        if placebo:
            pick = rng.choice(eligible) if eligible else None
        else:
            pick = max(eligible, key=lambda s: s["expectancy"]) if eligible else None

        proposal = pick["theta"] if pick else dict(theta)
        skipped = pick is None
        new_theta = theta if skipped else shrink(theta, proposal, rules["shrink_lambda"])

        # ── ۲) ارزیابی روی آیندهٔ دیده‌نشده: قهرمان در برابر چالش‌گر ────────
        champ_by_sym, chal_by_sym = {}, {}
        for sym, layers in data.items():
            sub = _slice_layers(layers, cfg, t_ev_start, t_ev_end)
            champ_by_sym[sym] = _run_on(cfg, sub, theta)
            chal_by_sym[sym] = _run_on(cfg, sub, new_theta)
        champ = _pool_metrics(champ_by_sym)
        chal = _pool_metrics(chal_by_sym)

        # نسخهٔ ثابت (τ=۱، بدون knob) هم هر گام اجرا می‌شود: خط پایهٔ بازگشت
        static_theta = {"tau": 1.0, "knob": "none"}
        static_by_sym = {}
        for sym, layers in data.items():
            sub = _slice_layers(layers, cfg, t_ev_start, t_ev_end)
            static_by_sym[sym] = _run_on(cfg, sub, static_theta)
        static_m = _pool_metrics(static_by_sym)

        gate = promotion_gate(champ, chal, rules)
        if rules.get("promotion_mode") == "rolling":
            # دروازهٔ سبک‌تر: نمونه + بهبود. بدون ادعای معناداری.
            light = (chal["n"] >= rules["min_forward_trades"]
                     and chal["expectancy"] > champ["expectancy"])
            worse_streak = 1 + consecutive_worse
            revert = (theta != static_theta and worse_streak >= 2)
            gate["rolling"] = {"light_promote": bool(light),
                               "revert_to_static": bool(revert),
                               "consecutive_worse_than_static": worse_streak}
            gate["promote"] = bool(light) or bool(revert)
            if revert:
                new_theta = static_theta
        promoted = bool(gate["promote"]) and new_theta != theta
        if promoted:
            version += 1
            prev_theta = theta
            theta = new_theta
        else:
            prev_theta = theta

        events.append({
            "step": k,
            "fit_window": [t_fit_end - (t_fit_end - trig0[fit_i0].open_time_ms), t_fit_end],
            "eval_window": [t_ev_start, t_ev_end],
            "candidates_tested": len(candidates),
            "skipped": skipped,
            "candidates_eligible": len(eligible),
            "proposal": proposal,
            "champion_theta": prev_theta,
            "challenger_theta": new_theta,
            "champion": _clean(champ),
            "challenger": _clean(chal),
            "gate": gate,
            "static": _clean(static_m),
            "promoted": promoted,
            "version_after": version,
            "placebo": placebo,
        })
        champion_chunks.append(_clean(champ))
        # اگر قهرمان از نسخهٔ ثابت بدتر بود، زنجیرهٔ «بدتر» را بلند کن
        consecutive_worse = (consecutive_worse + 1
                             if champ["expectancy"] < static_m["expectancy"] else 0)
        if progress:
            if skipped:
                print(f"  گام {k}: ⏭ نمونهٔ فیت کافی نبود "
                      f"(<{rules['min_fit_trades']}) → بدون پیشنهاد")
            print(f"  گام {k}: فیت {pick['n'] if pick else 0} معامله → "
                  f"پیشنهاد τ={proposal['tau']:.2f}/{proposal['knob']} · "
                  f"قهرمان {champ['expectancy']:+.2f}$ در برابر چالش‌گر "
                  f"{chal['expectancy']:+.2f}$ → "
                  f"{'✅ ارتقا' if promoted else ('⏭ رد شد' if skipped else '⛔ رد')}")

    # ── ۳) اجرای یکنواخت θ نهایی روی کل داده (برای گزارش) ──────────────────
    final_full = {}
    for sym, layers in data.items():
        final_full[sym] = _clean(_run_on(cfg, layers, theta))

    # ── ۴) خط پایه‌ها ────────────────────────────────────────────────────────
    baselines = {}
    for name, th in (("static_tau1", {"tau": 1.0, "knob": "none"}),
                     ("static_pullback", {"tau": 1.0, "knob": "pullback"}),
                     ("static_climax", {"tau": 1.0, "knob": "climax_1.0"})):
        pooled = {sym: _run_on(cfg, layers, th) for sym, layers in data.items()}
        baselines[name] = _clean(_pool_metrics(pooled))

    # «اوراکل»: بهترین گزینهٔ ثابت روی کل داده — انتخابِ پس‌ازواقع‌بینانه.
    # فقط به‌عنوان سقفِ خیالی گزارش می‌شود، نه به‌عنوان نتیجه.
    oracle = None
    best = -1e18
    for cand in [{"tau": t, "knob": kn} for t in TEMPERAMENTS for kn, _ in SHALLOW_KNOBS]:
        pooled = {sym: _run_on(cfg, layers, cand) for sym, layers in data.items()}
        m = _pool_metrics(pooled)
        if m["expectancy"] > best:
            best, oracle = m["expectancy"], dict(cand, expectancy=m["expectancy"],
                                                 n=m["n"])

    adaptive_pnls = [c["pnl"] for c in champion_chunks if c["n"]]
    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "placebo": placebo,
        "rules": rules,
        "chunks": len(chunks),
        "decisions": len(events),
        "symbols": symbols,
        "theta_final": theta,
        "version": version,
        "events": events,
        "champion_chunk_pnls": adaptive_pnls,
        "adaptive_total_pnl": round(sum(adaptive_pnls), 4),
        "adaptive_expectancy": round(_mean([x for e in events
                                            for x in e["champion"].get("_pnls", [])]), 4)
        if False else None,
        "final_full": final_full,
        "baselines": baselines,
        "oracle_ceiling": oracle,
        "promotions": sum(1 for e in events if e["promoted"]),
    }
    # expectancy تطبیقی = میانگین expectancy هر گام (وزن‌دار بر تعداد معامله)
    tot_n = sum(e["champion"]["n"] for e in events)
    if tot_n:
        result["adaptive_expectancy"] = round(
            sum(e["champion"]["expectancy"] * e["champion"]["n"] for e in events) / tot_n, 4)
    else:
        result["adaptive_expectancy"] = None
    result["adaptive_n"] = tot_n
    return result


# ----------------------------------------------------------------------------
# سنجش صادقانه: تطبیق در برابر بهترین ثابت
# ----------------------------------------------------------------------------
def verdict(result: dict) -> dict:
    """آیا تطبیق چیزی به بهترین «ثابت» اضافه کرد؟"""
    ad = result.get("adaptive_expectancy")
    best_name, best_exp = None, -1e18
    for name, b in result.get("baselines", {}).items():
        if b["n"] >= 10 and b["expectancy"] > best_exp:
            best_name, best_exp = name, b["expectancy"]
    if ad is None or best_name is None:
        return {"ok": False, "note": "نمونهٔ کافی برای حکم نیست", "winner": "unknown"}
    diff = ad - best_exp
    # آستانه: تطبیق باید حداقل ۱۰٪ بهتر از بهترین ثابت باشد تا «ارزش» داشته باشد
    threshold = max(0.10, abs(best_exp) * 0.10)
    useful = diff > threshold
    return {
        "ok": True,
        "adaptive_expectancy": ad,
        "best_static": best_name,
        "best_static_expectancy": round(best_exp, 4),
        "difference": round(diff, 4),
        "threshold": round(threshold, 4),
        "useful": useful,
        "winner": "adaptive" if useful else "static",
        "note": (f"تطبیق {diff:+.2f}$ بهتر از بهترین ثابت (`{best_name}`) بود → ارزش داشت"
                 if useful else
                 f"تطبیق {diff:+.2f}$ بهتر از بهترین ثابت (`{best_name}`) نبود "
                 f"→ ارزش قابل اثباتی نداشت"),
    }


# ----------------------------------------------------------------------------
# گزارش مارک‌داون
# ----------------------------------------------------------------------------
def _f(x, d: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+,.{d}f}" if isinstance(x, float) else str(x)


def run_evolve_with_placebo(cfg: MTFConfig,
                            data: Dict[str, Dict[str, List[Candle]]],
                            rules: Optional[dict] = None,
                            progress: bool = True) -> dict:
    """اجرای حلقه یک بار واقعی و یک بار پلاسیبو، سپس مقایسه.

    پرسش این تابع: «آیا اطلاعاتِ پشیمانی چیزی اضافه کرد؟» اگر نسخهٔ واقعی از
    پلاسیبو بهتر نبود، کل قابلیت فقط نویز تولید می‌کند و باید خاموش بماند.
    """
    if progress:
        print("🧠 اجرای واقعی …")
    real = run_evolve(cfg, data, rules=rules, placebo=False, seed=13, progress=progress)
    if progress:
        print("🧪 اجرای پلاسیبو (انتخاب تصادفی، همان ماشین) …")
    placebo = run_evolve(cfg, data, rules=rules, placebo=True, seed=13, progress=progress)

    a = real.get("adaptive_expectancy")
    b = placebo.get("adaptive_expectancy")
    cmp = {"ok": a is not None and b is not None,
           "real": a, "placebo": b,
           "difference": (round(a - b, 4) if (a is not None and b is not None) else None)}
    if cmp["ok"]:
        cmp["informative"] = cmp["difference"] > 0.0
        no_promo = (real.get("promotions", 0) == 0
                    and placebo.get("promotions", 0) == 0)
        if no_promo:
            cmp["informative"] = False
            cmp["degenerate"] = True
            cmp["note"] = ("⚠️ هیچ‌کدام از دو نسخه ارتقایی نداشتند؛ مقایسهٔ عددی "
                           "بی‌معنی است. خودِ «باز نشدن دروازه» نتیجه است: "
                           "با این حجم داده، تطبیق اجازهٔ عمل ندارد")
        elif cmp["informative"]:
            cmp["note"] = ("✅ نسخهٔ واقعی از پلاسیبو بهتر بود → سیگنال "
                           "(هرچند کوچک) وجود دارد")
        else:
            cmp["note"] = ("❌ نسخهٔ واقعی از پلاسیبو بهتر نبود → «یادگیری» از "
                           "نویز جدا نیست")
    real["placebo_run"] = {k: v for k, v in placebo.items()
                           if k in ("adaptive_expectancy", "adaptive_n", "promotions",
                                    "version", "theta_final")}
    real["placebo_comparison"] = cmp
    return real


def render_report(result: dict, out_path: str) -> str:
    L: List[str] = []
    w = L.append
    v = verdict(result)
    w("# گزارش تطبیق زنده (evolve): قهرمان در برابر چالش‌گر\n")
    if result["placebo"]:
        w("> 🧪 این اجرا **پلاسیبو** است: انتخاب‌ها تصادفی‌اند. اگر این نسخه هم "
          "به‌اندازهٔ نسخهٔ واقعی سود داد، یعنی «یادگیری» نویز بوده است.\n")
    w(f"- نمادها: {', '.join(result['symbols'])} · گام‌ها: {result['decisions']} · "
      f"نسخهٔ نهایی: v{result['version']} · {result['generated_at']}")
    w(f"- θ نهایی: `τ={result['theta_final']['tau']}` · "
      f"`knob={result['theta_final']['knob']}` · ارتقاها: {result['promotions']}")
    w(f"- قاعدهٔ دروازه: حداقل {result['rules']['min_forward_trades']} معاملهٔ forward، "
      f"CI{int(result['rules']['ci_level']*100)} کران‌پایین مثبت، افت بدتر از "
      f"{result['rules']['max_dd_worsen_pct']}٪ نه.\n")

    w("## ۱) حکم\n")
    if v.get("ok"):
        w(f"**{v['note']}.**\n")
        w(f"- تطبیق (میانگین وزنی گام‌ها): `{_f(v['adaptive_expectancy'])}$` "
          f"در {result['adaptive_n']} معامله")
        w(f"- بهترین ثابت (`{v['best_static']}`): `{_f(v['best_static_expectancy'])}$` "
          f"· اختلاف `{_f(v['difference'])}$` (آستانهٔ ارزش: {_f(v['threshold'])}$)")
    else:
        w(f"{v.get('note')}\n")

    w("## ۲) روند تصمیم‌ها\n")
    w("| گام | کاندید | پیشنهاد | قهرمان n/exp | چالش‌گر n/exp | دروازه | نتیجه |")
    w("|---:|---:|---|---|---|---|:--:|")
    for e in result["events"]:
        g = e["gate"]["checks"]
        failed = [k for k, ok in g.items() if not ok]
        w(f"| {e['step']} | {e['candidates_eligible']}/{e['candidates_tested']} | "
          f"τ={e['proposal']['tau']:.2f}·{e['proposal']['knob']} | "
          f"{e['champion']['n']} / {_f(e['champion']['expectancy'])} | "
          f"{e['challenger']['n']} / {_f(e['challenger']['expectancy'])} | "
          f"{'—' if not failed else '❌ ' + '، '.join(failed)} | "
          f"{'✅ v' + str(e['version_after']) if e['promoted'] else '⛔'} |")
    w("")

    pc = result.get("placebo_comparison")
    if pc:
        w("## ۲.۱) آزمون پلاسیبو (بدون آن، هیچ ادعای یادگیری معتبر نیست)\n")
        pr = result.get("placebo_run") or {}
        w("| نسخه | expectancy تطبیقی | ارتقا | نسخهٔ نهایی |")
        w("|---|---:|---:|:--:|")
        w(f"| واقعی | {_f(pc['real'])}$ | {result['promotions']} | "
          f"τ={result['theta_final']['tau']}·{result['theta_final']['knob']} |")
        w(f"| پلاسیبو (تصادفی) | {_f(pc['placebo'])}$ | {pr.get('promotions')} | "
          f"τ={(pr.get('theta_final') or {}).get('tau')}·"
          f"{(pr.get('theta_final') or {}).get('knob')} |")
        w("")
        w(f"**{pc['note']}** (اختلاف: {_f(pc['difference'])}$)\n")

    w("## ۳) خط پایه‌ها (همان داده، همان هزینه)\n")
    w("| نسخه | n | expectancy | PF | افت٪ |")
    w("|---|---:|---:|---:|---:|")
    for name, b in result.get("baselines", {}).items():
        w(f"| `{name}` | {b['n']} | {_f(b['expectancy'])}$ | "
          f"{b['profit_factor'] if b['profit_factor'] is not None else '—'} | "
          f"{_f(b['max_drawdown_pct'])}% |")
    fl = result.get("final_full") or {}
    for sym, m in fl.items():
        w(f"| θ نهایی روی {sym} | {m['n']} | {_f(m['expectancy'])}$ | "
          f"{m['profit_factor'] if m['profit_factor'] is not None else '—'} | "
          f"{_f(m['max_drawdown_pct'])}% |")
    orc = result.get("oracle_ceiling")
    if orc:
        w(f"| 🚨 «اوراکل» = بهترین عضوِ همین مجموعه با دانستن آینده | {orc['n']} | "
          f"{_f(orc['expectancy'])}$ | — | — |")
    w("")

    w("## ۴) خواندن این گزارش\n")
    w("- «اوراکل» یعنی بهترین عضوِ همین مجموعهٔ کوچک، انتخاب‌شده با دانستن آینده. "
      "این عدد نشان می‌دهد سقفِ خودِ مجموعه چقدر است: اگر بهترین ثابت هم فقط "
      "+۰.۲$ بدهد، هیچ روش انتخابی نمی‌تواند معجزه کند. (اوراکل واقعی، یعنی بهترین "
      "انتخاب برای هر معاملهٔ جداگانه، بسیار بالاتر است — ولی در زمان واقعی "
      "دست‌نیافتنی است و عمداً گزارش نمی‌شود تا توهم ایجاد نکند.)")
    w("- اگر تطبیق از بهترین ثابت بهتر نشد، نتیجهٔ درست «تطبیق بی‌فایده» است، نه "
      "«باید بیشتر تنظیم کنیم». با این حجم داده، این محتمل‌ترین نتیجه است.")
    w("- برای اجرای پلاسیبو: همان دستور با `--placebo`. حکم فقط وقتی معتبر است که "
      "نسخهٔ واقعی از پلاسیبو بهتر باشد.\n")
    w("_این گزارش PAPER است و توصیهٔ معاملاتی نیست._")
    text = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def rules_default_bars(known) -> int:
    return max(3000, (known.chunk_bars or DEFAULT_RULES["chunk_bars"]) * 4)


def evolve_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .config import load_config
    from .data import csv_candles, resample_up

    p = argparse.ArgumentParser(prog="mtflab evolve",
                                description="حلقهٔ تطبیق زنده: قهرمان/چالش‌گر با دروازهٔ آماری")
    p.add_argument("--csv", action="append", default=[],
                   help="CSV هر نماد: --csv BTCUSDT=path.csv (قابل تکرار)")
    p.add_argument("--csv-dir", default="../futures-scalp-lab/data")
    p.add_argument("--chunk-bars", type=int, default=0)
    p.add_argument("--placebo", action="store_true",
                   help="فقط نسخهٔ تصادفی را اجرا کن (برای دیدن رفتار پلاسیبو)")
    p.add_argument("--mode", choices=sorted(PROMOTION_MODES), default=None,
                   help="فلسفهٔ ارتقا: strict (آماری) یا rolling (چرخشی)")
    p.add_argument("--positive-control", action="store_true",
                   help="اجرا روی دادهٔ مصنوعی با تغییر رژیم نوسان (آزمون سلامت ماشین)")
    p.add_argument("--with-placebo", action="store_true",
                   help="هم واقعی و هم پلاسیبو + مقایسه (توصیه‌شده)")
    p.add_argument("--out", default="results/evolve_report.md")
    p.add_argument("--html", default="results/dash_evolve.html")
    p.add_argument("--json", default="")
    known, rest = p.parse_known_args(argv if argv is not None else None)

    specs: List[Tuple[str, str]] = []
    for item in known.csv:
        if "=" in item:
            sym, path = item.split("=", 1)
            specs.append((sym.strip().upper(), path.strip()))
        else:
            specs.append((cfg.symbol, item))
    if not specs:
        # پیش‌فرض: دو نماد موجود در ریپو
        for sym, fn in (("BTCUSDT", "btcusdt_1h_lastyear.csv"),
                        ("ETHUSDT", "ethusdt_1h_lastyear.csv")):
            path = os.path.join(known.csv_dir, fn)
            if os.path.exists(path):
                specs.append((sym, path))
    if not specs:
        print("❌ هیچ CSV‌ای پیدا نشد. با --csv SYMBOL=path بدهید.")
        return 2

    # اعتبارسنجی کانفیگ به یک --csv نیاز دارد؛ اولین فایل را به آن می‌دهیم
    if "--csv" not in rest:
        rest = list(rest) + ["--csv", specs[0][1]]
    if "--data" not in rest:
        rest = list(rest) + ["--data", "csv"]
    cfg = load_config(rest)
    cfg.verbose = False
    cfg.forensics = False

    data: Dict[str, Dict[str, List[Candle]]] = {}
    if known.positive_control:
        data = build_shift_data(cfg, n=max(6000, rules_default_bars(known)))
        for sym, d in data.items():
            print(f"  🧪 {sym}: {len(d['trigger'])} کندل مصنوعی "
                  f"(نیمهٔ دوم با نوسان ۲×)")
    for sym, path in specs:
        if known.positive_control:
            break
        trig = csv_candles(path)
        filt, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_filter)
        bias, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_bias)
        data[sym] = {"trigger": trig, "filter": filt, "bias": bias}
        print(f"  📦 {sym}: {len(trig)} کندل از {os.path.basename(path)}")

    rules = dict(DEFAULT_RULES)
    if known.chunk_bars:
        rules["chunk_bars"] = known.chunk_bars
    if known.mode:
        rules["promotion_mode"] = known.mode

    t0 = time.time()
    print(f"🧠 حلقهٔ تطبیق{' (پلاسیبو)' if known.placebo else ''} — "
          f"حالت {rules['promotion_mode']} · "
          f"{len(data)} نماد × {rules['chunk_bars']} کندل در هر گام")
    if known.with_placebo and not known.placebo:
        res = run_evolve_with_placebo(cfg, data, rules=rules)
    else:
        res = run_evolve(cfg, data, rules=rules, placebo=known.placebo)
    res["sources"] = {s: p for s, p in specs}
    out = render_report(res, known.out)
    if known.html:
        try:
            render_dashboard(res, known.html)
            print(f"🖥 داشبورد: {known.html}")
        except Exception as e:                              # noqa: BLE001
            print(f"⚠️ داشبورد ساخته نشد: {e}")
    if known.json:
        with open(known.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2, default=str)

    v = verdict(res)
    print("\n" + "=" * 68)
    print(f"  تطبیق: {_f(res['adaptive_expectancy'])}$ در {res['adaptive_n']} معامله "
          f"· ارتقا: {res['promotions']}")
    if v.get("ok"):
        print(f"  بهترین ثابت: {_f(v['best_static_expectancy'])}$ ({v['best_static']}) "
              f"· اختلاف: {_f(v['difference'])}$ → {v['winner']}")
    print(f"\n📄 گزارش: {out}\n⏱ {time.time()-t0:.1f}s")
    print("=" * 68)
    return 0


# ----------------------------------------------------------------------------
# کنترل مثبت: داده‌ای که در آن «تغییر رژیم» واقعاً وجود دارد
# ----------------------------------------------------------------------------
def synthetic_vol_shift(tf: str = "1h", n: int = 6000, seed: int = 5,
                        shift: float = 2.0) -> List[Candle]:
    """سری مصنوعی که نیمهٔ دومش نوسان دو برابر دارد.

    چرا؟ برای جدا کردن دو حالت که نتیجه‌شان یکسان به‌نظر می‌رسد:
      (الف) ماشین تطبیق خراب است  → حتی وقتی تغییر رژیم هست، چیزی یاد نمی‌گیرد
      (ب) داده سیگنال ندارد       → ماشین سالم است، ولی چیزی برای یاد گرفتن نیست
    اگر روی این داده ارتقا رخ دهد، یعنی ماشین سالم است و نتیجهٔ منفی روی دادهٔ
    واقعی معنایش «نبود سیگنال» است، نه «کدِ خراب».
    """
    from .data import synthetic_candles
    base = synthetic_candles(tf, n, seed=seed)
    half = n // 2
    out: List[Candle] = []
    price = base[0].open
    for i, c in enumerate(base):
        k = shift if i >= half else 1.0
        r = math.log(max(c.close, 1e-9) / max(c.open, 1e-9)) * k
        o = price
        cl = o * math.exp(r)
        hi = o + max(c.high - c.open, 0.0) * k
        lo = o - max(c.open - c.low, 0.0) * k
        out.append(Candle(c.open_time_ms, round(o, 2),
                          round(max(o, cl, hi), 2), round(min(o, cl, lo), 2),
                          round(cl, 2), c.volume))
        price = cl
    return out


def build_shift_data(cfg: MTFConfig, symbols: Sequence[str] = ("SYN-A", "SYN-B"),
                     n: int = 6000, shift: float = 2.0) -> Dict[str, Dict[str, List[Candle]]]:
    from .data import resample_up
    data = {}
    for i, sym in enumerate(symbols):
        trig = synthetic_vol_shift(cfg.tf_trigger, n, seed=101 + i, shift=shift)
        filt, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_filter)
        bias, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_bias)
        data[sym] = {"trigger": trig, "filter": filt, "bias": bias}
    return data


# ----------------------------------------------------------------------------
# داشبورد HTML خودکفا (همان CSS داشبورد اصلی)
# ----------------------------------------------------------------------------
def render_dashboard(result: dict, out_path: str,
                     title: str = "آزمایشگاه تطبیق زنده") -> str:
    """یک صفحهٔ مستقل برای دیدن تصمیم‌ها. عمداً ساده و بی‌وابستگی."""
    from .dashboard import CSS, esc, fnum, fpct, svg_lines, table

    r = result
    v = verdict(r)
    comp = r.get("placebo_comparison")
    h = [f'<header><h1>{esc(title)}<span class="tag">PAPER · پلاسیبو دارد</span></h1>',
         f'<div class="sub">نمادها: {esc(", ".join(r["symbols"]))} · '
         f'گام‌ها: {r["decisions"]} · حالت: '
         f'{esc(PROMOTION_MODES[r["rules"]["promotion_mode"]]["label"])} · '
         f'ساخته‌شده: {esc(r["generated_at"])}</div></header>']

    # KPI
    h.append('<div class="grid3">')
    h.append(f'<div><h2>تطبیق (میانگین وزنی گام‌ها)</h2>'
             f'<div class="note"><b style="font-size:1.6em">'
             f'{fnum(r.get("adaptive_expectancy"), 2, True)}$</b><br>'
             f'در {fnum(r.get("adaptive_n"), 0)} معامله · '
             f'ارتقا: {r["promotions"]} بار</div></div>')
    h.append(f'<div><h2>بهترین نسخهٔ ثابت</h2>'
             f'<div class="note"><b style="font-size:1.6em">'
             f'{fnum(v.get("best_static_expectancy"), 2, True)}$</b><br>'
             f'<span class="mono">{esc(str(v.get("best_static")))}</span></div></div>')
    h.append(f'<div><h2>حکم</h2>'
             f'<div class="note {"ok" if v.get("winner") == "adaptive" else "bad"}">'
             f'<b>{"تطبیق برنده" if v.get("winner") == "adaptive" else "ثابت برنده"}</b><br>'
             f'اختلاف: {fnum(v.get("difference"), 2, True)}$ '
             f'(آستانهٔ ارزش {fnum(v.get("threshold"), 2, True)}$)</div></div>')
    h.append('</div>')

    # نمودار: قهرمان هر گام در برابر چالش‌گر
    if r["events"]:
        series = [
            {"name": "قهرمان (expectancy)", "color": "#3ddc97",
             "points": [(i, e["champion"]["expectancy"])
                        for i, e in enumerate(r["events"], 1)]},
            {"name": "چالش‌گر", "color": "#ffcf5c",
             "points": [(i, e["challenger"]["expectancy"])
                        for i, e in enumerate(r["events"], 1)]},
            {"name": "نسخهٔ ثابت", "color": "#b98bff",
             "points": [(i, e["static"]["expectancy"])
                        for i, e in enumerate(r["events"], 1)]},
        ]
        h.append('<h2>expectancy در هر گام (روی بازهٔ forward دیده‌نشده)</h2>')
        h.append(svg_lines(series, title="محور افقی: شمارهٔ گام"))

    # جدول تصمیم‌ها
    h.append('<h2>تصمیم‌ها و دروازه</h2>')
    rows = []
    for e in r["events"]:
        g = e["gate"]["checks"]
        failed = [k for k, ok in g.items() if not ok]
        rows.append([str(e["step"]),
                     f'{e["candidates_eligible"]}/{e["candidates_tested"]}',
                     f'τ={e["proposal"]["tau"]:.2f} · {esc(e["proposal"]["knob"])}',
                     f'{e["champion"]["n"]} / {fnum(e["champion"]["expectancy"], 2, True)}',
                     f'{e["challenger"]["n"]} / {fnum(e["challenger"]["expectancy"], 2, True)}',
                     f'{e["static"]["n"]} / {fnum(e["static"]["expectancy"], 2, True)}',
                     '—' if not failed else '❌ ' + '، '.join(failed),
                     '✅ v' + str(e["version_after"]) if e["promoted"] else '⛔'])
    h.append(table(["گام", "کاندید", "پیشنهاد", "قهرمان", "چالش‌گر", "ثابت", "دروازه", "نتیجه"],
                   rows))

    # پلاسیبو
    if comp:
        h.append('<h2>آزمون پلاسیبو</h2>')
        h.append(f'<div class="note {"ok" if comp.get("informative") else "bad"}">'
                 f'{esc(comp.get("note", ""))}<br>'
                 f'واقعی: <b>{fnum(comp.get("real"), 2, True)}$</b> · '
                 f'پلاسیبو: <b>{fnum(comp.get("placebo"), 2, True)}$</b> · '
                 f'اختلاف: <b>{fnum(comp.get("difference"), 2, True)}$</b></div>')
    else:
        h.append('<div class="note warn">این اجرا پلاسیبو ندارد. بدون آن، ادعای '
                 '«یادگیری» قابل دفاع نیست — با <span class="mono">--with-placebo</span> '
                 'دوباره اجرا کنید.</div>')

    # خط پایه‌ها
    h.append('<h2>خط پایه‌ها (همان داده، همان هزینه)</h2>')
    rows = []
    for name, b in r.get("baselines", {}).items():
        rows.append([f'<span class="mono">{esc(name)}</span>',
                     fnum(b["n"], 0), fnum(b["expectancy"], 2, True),
                     fnum(b["profit_factor"], 3),
                     fpct(b.get("max_drawdown_pct"), 2, False)])
    for sym, m in (r.get("final_full") or {}).items():
        rows.append([f'θ نهایی روی {esc(sym)}', fnum(m["n"], 0),
                     fnum(m["expectancy"], 2, True), fnum(m["profit_factor"], 3),
                     fpct(m.get("max_drawdown_pct"), 2, False)])
    orc = r.get("oracle_ceiling")
    if orc:
        rows.append(['🚨 اوراکل (سقف خیالی، انتخاب با دانستن آینده)', fnum(orc["n"], 0),
                     fnum(orc["expectancy"], 2, True), '—', '—'])
    h.append(table(["نسخه", "n", "expectancy$", "PF", "افت٪"], rows, raw=True))

    h.append('<div class="note warn"><b>چرا این ابزار پول را جابه‌جا نمی‌کند:</b> '
             'در همین داده، تطبیق از بهترین نسخهٔ ثابت بدتر بود و حتی از پلاسیبو هم '
             'بدتر یا مساوی. تا وقتی تطبیق <i>در آیندهٔ دیده‌نشده</i> از هر دو بهتر '
             'نشود، تنها کار درست این است که فقط گزارش بدهد.</div>')
    h.append('<footer>Futures MTF Lab · evolve · PAPER · توصیهٔ معاملاتی نیست</footer>')

    html = (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}</style></head><body>'
            + "".join(h) + '</body></html>')
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
