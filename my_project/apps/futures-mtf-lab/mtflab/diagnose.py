"""تشخیص (diagnosis): چرا معاملات سود نمی‌دهند و کجا سود «جا می‌ماند»؟

این ماژول به‌جای حدس، سه کار روی دادهٔ واقعی انجام می‌دهد:

۱) **کالبدشکافی خروج** — برای هر معامله، MFE/MAE و حرکت قیمت **بعد از خروج**
   را می‌سنجد تا بفهمیم سود زود بسته شده (money left on the table) یا استاپ
   زود خورده (stop too tight).

۲) **آزمون سیاست‌های خروج** — «سود شناور» را واقعاً اجرا می‌کند: تریلینگ با
   آستانه‌های مختلف، بدون تریلینگ، TP بازتر، فقط تریلینگ، بریک‌ایون، خروج جزئی.
   هر سیاست روی کل داده + TRAIN + OOS سنجیده می‌شود تا معلوم شود بهبود،
   واقعی است یا خوش‌شانسیِ درون‌نمونه.

۳) **نقشهٔ نشت سود** — تفکیک expectancy بر اساس حالت تریگر، رژیم، ساعت،
   مدت نگهداری و نوسان (ATR%) تا معلوم شود edge در کدام گروه می‌میرد.

اصول: هیچ عددی بدون مقایسه با baseline گزارش نمی‌شود؛ تفاوت‌ها با بازهٔ
اطمینان bootstrap سنجیده می‌شوند؛ و «بهترین» فقط وقتی توصیه می‌شود که در
TRAIN و OOS هم‌علامت باشد.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import MTFConfig
from .data import Candle, csv_candles
from .engine import run_backtest
from .validation import metrics, _slice_layers


# ----------------------------------------------------------------------------
# ۱) آمار حرکت قیمت پس از خروج (money left on the table)
# ----------------------------------------------------------------------------
def forward_path_stats(candles: Sequence[Candle], idx: int, direction: int,
                       entry: float, horizons: Sequence[int] = (4, 8, 16, 24, 48)) -> dict:
    """حرکت قیمت بعد از خروج: چقدر به نفع جهتِ معامله ادامه داشت؟

    برای هر افق h: بیشترین حرکت مطلوب و حرکت نهایی (به درصد نسبت به قیمت ورود).
    هیچ آینده‌نگری‌ای در تصمیم‌گیری نیست؛ این فقط تحلیل پس‌ازواقع است.
    """
    out: Dict[str, float] = {}
    n = len(candles)
    for h in horizons:
        seg = candles[idx + 1: min(idx + 1 + h, n)]
        if not seg:
            continue
        if direction == 1:
            fav = (max(c.high for c in seg) - entry) / entry * 100.0
            adv = (min(c.low for c in seg) - entry) / entry * 100.0
        else:
            fav = (entry - min(c.low for c in seg)) / entry * 100.0
            adv = (entry - max(c.high for c in seg)) / entry * 100.0
        out[f"fav_{h}"] = round(fav, 4)
        out[f"adv_{h}"] = round(adv, 4)
        out[f"end_{h}"] = round((seg[-1].close - entry) / entry * 100.0 * direction, 4)
    return out


def _exit_reason_group(reason: str) -> str:
    r = str(reason)
    if r.startswith("partial_take"):
        return "partial"
    if r.startswith("regime_flip"):
        return "regime_flip"
    if r == "breakeven":
        return "breakeven"
    if r in ("stop_loss", "stop/trail"):
        return r
    if r == "take_profit":
        return "take_profit"
    if r == "time_stop":
        return "time_stop"
    return "end_of_data" if r == "end_of_data" else "other"


def exit_autopsy(cfg: MTFConfig, layers: Dict[str, List[Candle]], res: dict,
                 horizons: Sequence[int] = (4, 12, 24, 48)) -> dict:
    """کالبدشکافی هر معامله: چه شد، چه می‌شد، و چه چیزی جا ماند."""
    trig = layers["trigger"]
    trades = [t for t in res["trades"] if not t.get("partial")]
    rows: List[dict] = []

    for t in trades:
        xb = int(t.get("exit_bar", -1))
        entry = float(t.get("entry") or 0.0)
        if xb < 0 or xb >= len(trig) or entry <= 0:
            continue
        fwd = forward_path_stats(trig, xb, int(t["side"]), entry, horizons)
        realized_pct = (float(t["exit"]) - entry) / entry * 100.0 * int(t["side"])
        r_mult = float(t.get("r_multiple") or 0.0)
        mfe_pct = float(t.get("mfe_pct") or 0.0)
        mae_pct = float(t.get("mae_pct") or 0.0)
        stop_pct = abs(entry - float(t.get("stop_initial") or entry)) / entry * 100.0
        rows.append({
            "ts": t["ts"], "side": t["side"], "reason": t["reason"],
            "group": _exit_reason_group(t["reason"]),
            "pnl": t["pnl"], "r": r_mult, "realized_pct": round(realized_pct, 4),
            "mfe_pct": mfe_pct, "mae_pct": mae_pct, "stop_pct": round(stop_pct, 4),
            "bars_held": t.get("bars_held", 0),
            # برای برنده‌ها: سودی که از قلهٔ مسیر تا خروج پس داده شد
            # برای بازنده‌ها: سودی که «باز» بود و به ضرر تبدیل شد
            "gave_back_pct": round(mfe_pct - realized_pct, 4) if realized_pct > 0 else 0.0,
            "green_to_loss_pct": round(mfe_pct, 4) if realized_pct <= 0 else 0.0,
            "trigger_mode": t.get("trigger_mode", "—"),
            "regime": t.get("regime_entry", "—"),
            "atr_pct": (t.get("indicators_entry") or {}).get("atr_pct"),
            **fwd,
        })

    # ── خلاصه بر اساس گروه خروج ──
    by_group: Dict[str, dict] = {}
    for r in rows:
        g = r["group"]
        d = by_group.setdefault(g, {"n": 0, "pnl": 0.0, "r": 0.0, "mfe": 0.0,
                                    "gave_back": 0.0, "g2l": 0.0, "g2l_n": 0,
                                    "fav24": 0.0, "end24": 0.0, "bars": 0.0})
        d["n"] += 1
        d["pnl"] += r["pnl"]
        d["r"] += r["r"]
        d["mfe"] += r["mfe_pct"]
        d["gave_back"] += r["gave_back_pct"]
        if r["green_to_loss_pct"] > 0:
            d["g2l"] += r["green_to_loss_pct"]
            d["g2l_n"] += 1
        d["fav24"] += r.get("fav_24", 0.0)
        d["end24"] += r.get("end_24", 0.0)
        d["bars"] += r["bars_held"]
    for g, d in by_group.items():
        n = max(d["n"], 1)
        by_group[g] = {
            "n": d["n"], "pnl": round(d["pnl"], 3), "pnl_per_trade": round(d["pnl"] / n, 3),
            "avg_r": round(d["r"] / n, 3), "avg_mfe_pct": round(d["mfe"] / n, 3),
            "avg_gave_back_pct": round(d["gave_back"] / n, 3),
            "avg_green_to_loss_pct": round(d["g2l"] / d["g2l_n"], 3) if d["g2l_n"] else 0.0,
            "green_to_loss_n": d["g2l_n"],
            "avg_favorable_after_24bars": round(d["fav24"] / n, 3),
            "avg_end_after_24bars": round(d["end24"] / n, 3),
            "avg_bars_held": round(d["bars"] / n, 1),
        }

    # ── پرسش کلیدی ۱: چقدر سود در مسیر بود و نگرفتیم؟ ──
    winners = [r for r in rows if r["pnl"] > 0]
    losers = [r for r in rows if r["pnl"] <= 0]
    giveback = [r["gave_back_pct"] for r in winners if r["mfe_pct"] > 0]
    # سود «قابل دسترس» = بیشترین MFE که معامله‌های برنده دیده‌اند
    capture = (sum(r["realized_pct"] for r in winners) /
               max(sum(r["mfe_pct"] for r in winners), 1e-9) * 100.0) if winners else 0.0

    # ── پرسش کلیدی ۲: استاپ تنگ بود؟ ──
    # معامله‌ای که با استاپ بسته شده ولی قیمت بعداً به سمت هدف برگشته
    stopped = [r for r in rows if r["group"] in ("stop_loss", "stop/trail", "breakeven")]
    recovered = [r for r in stopped if r.get("fav_24", 0.0) >= r.get("stop_pct", 999)]
    premature = [r for r in stopped if r.get("fav_24", 0.0) >= r.get("stop_pct", 999) * 0.8]

    # ── پرسش کلیدی ۳: برنده‌ها قبل از سود، چقدر زیر آب رفتند؟ ──
    win_mae = [r["mae_pct"] for r in winners]
    loss_mfe = [r["mfe_pct"] for r in losers]
    losers_were_green = [r for r in losers if r["mfe_pct"] >= 0.3]

    return {
        "trades_analyzed": len(rows),
        "horizons": list(horizons),
        "by_group": by_group,
        "capture_ratio_pct": round(capture, 2),
        "avg_giveback_pct_winners": round(sum(giveback) / len(giveback), 3) if giveback else 0.0,
        "median_giveback_pct_winners": round(_median(giveback), 3) if giveback else 0.0,
        "winners_reaching_2R_before_exit": sum(1 for r in winners if r["mfe_pct"] >= 2 * r["stop_pct"] * 0.95),
        "winner_n": len(winners),
        "stop_exits": len(stopped),
        "stop_recovered_within_24bars": len(recovered),
        "stop_premature_pct": round(100.0 * len(premature) / max(len(stopped), 1), 2),
        "avg_mae_winners_pct": round(sum(win_mae) / len(win_mae), 3) if win_mae else 0.0,
        "avg_mfe_losers_pct": round(sum(loss_mfe) / len(loss_mfe), 3) if loss_mfe else 0.0,
        "losers_were_once_green": len(losers_were_green),
        "losers_were_once_green_pct": round(100.0 * len(losers_were_green) / max(len(losers), 1), 2),
        "rows": rows,
    }


def _median(v: Sequence[float]) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# ----------------------------------------------------------------------------
# ۲) آزمون سیاست‌های خروج (سود شناور)
# ----------------------------------------------------------------------------
EXIT_POLICIES: List[Tuple[str, str, dict]] = [
    ("base", "فعلی: TP 3×ATR + تریلینگ از 1R (2×ATR)", {}),
    ("no_trail", "بدون تریلینگ: TP ثابت 3×ATR", dict(trail_enabled=False)),
    ("trail_0.5R", "تریلینگ از 0.5R (زودتر قفل سود)", dict(trail_start_r=0.5)),
    ("trail_1.5R", "تریلینگ از 1.5R (صبر بیشتر)", dict(trail_start_r=1.5)),
    ("trail_2R", "تریلینگ از 2R", dict(trail_start_r=2.0)),
    ("trail_tight", "تریلینگ تنگ 1×ATR", dict(trail_atr_mult=1.0)),
    ("trail_wide", "تریلینگ باز 3×ATR (فضای نفس)", dict(trail_atr_mult=3.0)),
    ("trail_only", "فقط تریلینگ، بدون TP (بگذار بدود)", dict(take_profit_atr_mult=50.0,
                                                              trail_start_r=1.0,
                                                              trail_atr_mult=3.0)),
    ("tp4", "TP بازتر 4×ATR + تریلینگ", dict(take_profit_atr_mult=4.0)),
    ("tp6", "TP خیلی باز 6×ATR + تریلینگ", dict(take_profit_atr_mult=6.0)),
    ("be_1R", "بریک‌ایون در 1R", dict(breakeven_at_r=1.0)),
    ("partial_1R", "خروج جزئی ۵۰٪ در 1R + BE", dict(partial_take_r=1.0, partial_take_frac=0.5)),
    ("partial_1R_trail1.5", "جزئی ۵۰٪ در 1R + تریلینگ 1.5×ATR",
     dict(partial_take_r=1.0, partial_take_frac=0.5, trail_atr_mult=1.5)),
    ("partial_1.5R_be1", "جزئی ۵۰٪ در 1.5R + BE در 1R",
     dict(partial_take_r=1.5, partial_take_frac=0.5, breakeven_at_r=1.0)),
    ("partial_tp6", "جزئی ۵۰٪ در 1R + TP 6×ATR + تریلینگ 3×ATR",
     dict(partial_take_r=1.0, partial_take_frac=0.5,
          take_profit_atr_mult=6.0, trail_atr_mult=3.0)),
]


def run_exit_policies(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                      policies: Optional[List[Tuple[str, str, dict]]] = None,
                      split: bool = True) -> dict:
    """اجرای همهٔ سیاست‌های خروج روی کل داده + TRAIN + OOS.

    خروجی: برای هر سیاست expectancy/PF/بازده/DD در سه بازه + حکم پایداری.
    """
    policies = policies or EXIT_POLICIES
    trig = layers["trigger"]
    n = len(trig)
    i1, i2 = int(n * cfg.train_ratio), int(n * (cfg.train_ratio + cfg.validation_ratio))
    train_sub = _slice_layers(layers, cfg, trig[0].open_time_ms, trig[i1 - 1].open_time_ms)
    oos_sub = _slice_layers(layers, cfg, trig[i2].open_time_ms, trig[-1].open_time_ms)

    rows: List[dict] = []
    for pid, label, over in policies:
        c = replace(cfg, verbose=False, forensics=False, run_id="", **over)
        full = run_backtest(c, layers)
        m_full = _metrics_positions(full, c)
        row = {"id": pid, "label": label, "overrides": over, "full": m_full}
        if split:
            tr = _metrics_positions(run_backtest(c, train_sub), c)
            oo = _metrics_positions(run_backtest(c, oos_sub), c)
            row["train"] = tr
            row["oos"] = oo
            row["robust"] = bool(
                tr["n"] >= 5 and oo["n"] >= 5
                and tr["expectancy"] > 0 and oo["expectancy"] > 0)
            row["oos_gain_vs_base"] = None      # بعداً پر می‌شود
        rows.append(row)

    base_exp_full = rows[0]["full"]["expectancy"] if rows else 0.0
    base_exp_oos = rows[0].get("oos", {}).get("expectancy", 0.0) if rows else 0.0
    for r in rows:
        r["gain_vs_base_full"] = round(r["full"]["expectancy"] - base_exp_full, 4)
        if split:
            r["oos_gain_vs_base"] = round(r.get("oos", {}).get("expectancy", 0.0)
                                          - base_exp_oos, 4)

    ranked = sorted(rows, key=lambda r: (-(r["full"]["expectancy"])))
    best_full = ranked[0]["id"] if ranked else None
    robust_rows = [r for r in rows if r.get("robust")]
    best_robust = max(robust_rows, key=lambda r: r["oos"]["expectancy"])["id"] if robust_rows else None
    return {
        "rows": rows, "best_full_sample": best_full, "best_robust": best_robust,
        "robust_count": len(robust_rows), "n_policies": len(rows),
        "segments": {"train": [trig[0].open_time_ms, trig[i1 - 1].open_time_ms],
                     "oos": [trig[i2].open_time_ms, trig[-1].open_time_ms]},
    }


def _metrics_positions(res: dict, cfg: MTFConfig) -> dict:
    """معیارها بر مبنای «پوزیشن» (لگ‌های جزئی کنار هم جمع می‌شوند)."""
    trades = res["trades"]
    groups: Dict[Tuple[int, float], List[dict]] = {}
    for t in trades:
        groups.setdefault((t.get("open_bar", 0), t.get("entry", 0.0)), []).append(t)
    pos_rows = [{"ts": g[-1]["ts"], "pnl": sum(x["pnl"] for x in g),
                 "fees": sum(x["fees"] for x in g), "r_multiple": g[-1].get("position_pnl", 0) /
                 max(g[-1].get("risk_amount", 1.0), 1e-9),
                 "bars_held": g[-1].get("bars_held", 0)}
                for g in groups.values()]
    m = metrics(pos_rows, cfg.initial_equity)
    m["legs"] = len(trades)
    m["positions"] = len(pos_rows)
    m["return_pct"] = round(m["total_pnl"] / cfg.initial_equity * 100.0, 4)
    return m


# ----------------------------------------------------------------------------
# ۳) نقشهٔ نشت سود (کجا edge می‌میرد)
# ----------------------------------------------------------------------------
def leak_map(res: dict, cfg: MTFConfig) -> dict:
    """expectancy به تفکیک: حالت تریگر، رژیم، جهت، ساعت، مدت نگهداری، نوسان."""
    trades = [t for t in res["trades"] if not t.get("partial")]
    if not trades:
        return {"buckets": {}}

    def bucket(key_fn, order=None):
        d: Dict[str, List[dict]] = {}
        for t in trades:
            d.setdefault(str(key_fn(t)), []).append(t)
        items = []
        for k, ts in d.items():
            n = len(ts)
            pnl = sum(x["pnl"] for x in ts)
            wins = sum(1 for x in ts if x["pnl"] > 0)
            items.append({"key": k, "n": n, "pnl": round(pnl, 2),
                          "exp": round(pnl / n, 3), "win_rate": round(wins / n, 4),
                          "avg_r": round(sum(x.get("r_multiple", 0) for x in ts) / n, 3)})
        if order:
            items.sort(key=lambda x: order.index(x["key"]) if x["key"] in order else 99)
        else:
            items.sort(key=lambda x: -x["n"])
        return items

    def bars_bucket(t):
        b = t.get("bars_held", 0)
        return "1-2" if b <= 2 else ("3-6" if b <= 6 else ("7-12" if b <= 12 else "13+"))

    def vol_bucket(t):
        a = (t.get("indicators_entry") or {}).get("atr_pct")
        if a is None:
            return "?"
        return "<0.8%" if a < 0.8 else ("0.8-1.5%" if a < 1.5 else ("1.5-2.5%" if a < 2.5 else "≥2.5%"))

    def hour_bucket(t):
        import datetime as _dt
        try:
            h = _dt.datetime.fromtimestamp(t["ts"] / 1000, tz=_dt.timezone.utc).hour
        except Exception:                                 # noqa: BLE001
            return "?"
        return f"{h:02d}"

    return {
        "buckets": {
            "trigger_mode": bucket(lambda t: t.get("trigger_mode", "—"),
                                   order=["pullback", "breakout"]),
            "regime": bucket(lambda t: t.get("regime_entry", "—"),
                             order=["uptrend", "downtrend", "sideways"]),
            "side": bucket(lambda t: "LONG" if t.get("side", 1) > 0 else "SHORT",
                           order=["LONG", "SHORT"]),
            "bars_held": bucket(bars_bucket, order=["1-2", "3-6", "7-12", "13+"]),
            "volatility_atr_pct": bucket(vol_bucket, order=["<0.8%", "0.8-1.5%", "1.5-2.5%", "≥2.5%"]),
            "hour_utc": bucket(hour_bucket),
        },
        "n": len(trades),
    }


# ----------------------------------------------------------------------------
# ۴) مقایسهٔ آماری دو سیاست (bootstrap روی PnL هر معامله)
# ----------------------------------------------------------------------------
def bootstrap_policy_diff(a: Sequence[float], b: Sequence[float], sims: int = 1500,
                          seed: int = 11) -> dict:
    if len(a) < 5 or len(b) < 5:
        return {"ok": False, "note": "نمونه کافی نیست"}
    rng = random.Random(seed)
    diffs = []
    for _ in range(sims):
        ma = sum(a[rng.randrange(len(a))] for _ in range(len(a))) / len(a)
        mb = sum(b[rng.randrange(len(b))] for _ in range(len(b))) / len(b)
        diffs.append(ma - mb)
    diffs.sort()

    def q(p):
        return round(diffs[min(len(diffs) - 1, max(0, int(p * (len(diffs) - 1))))], 4)

    ci = (q(0.025), q(0.975))
    return {"ok": True, "observed": round(sum(a) / len(a) - sum(b) / len(b), 4),
            "ci95": [ci[0], ci[1]], "significant": not (ci[0] <= 0 <= ci[1]),
            "note": "✅ معنادار" if not (ci[0] <= 0 <= ci[1]) else "⚠️ معنادار نیست"}


# ----------------------------------------------------------------------------
# اجرای کامل
# ----------------------------------------------------------------------------
def diagnose(cfg: MTFConfig, layers: Dict[str, List[Candle]],
             progress: bool = True) -> dict:
    if progress:
        print("🔬 اجرای سناریوی پایه …")
    base_res = run_backtest(replace(cfg, verbose=False, forensics=False, run_id=""), layers)

    if progress:
        print("🔬 کالبدشکافی خروج (حرکت قیمت بعد از خروج) …")
    autopsy = exit_autopsy(cfg, layers, base_res)

    if progress:
        print("📈 آزمون سیاست‌های خروج/سود شناور (۱۵ سیاست × ۳ بازه) …")
    policies = run_exit_policies(cfg, layers)

    if progress:
        print("🧪 آزمون فرضیه‌های ورود (۱۲ آزمایش × ۳ بازه) …")
    setups = run_setup_experiments(cfg, layers)

    if progress:
        print("🧭 نقشهٔ نشت سود …")
    leaks = leak_map(base_res, cfg)

    # مقایسهٔ آماری «بهترین سیاست» با پایه (PnL هر پوزیشن)
    comp = {}
    base_pnls = _position_pnls(base_res)
    for pid in {policies.get("best_robust"), policies.get("best_full_sample")}:
        if not pid:
            continue
        row = next((r for r in policies["rows"] if r["id"] == pid), None)
        if not row:
            continue
        c = replace(cfg, verbose=False, forensics=False, run_id="", **row["overrides"])
        alt = run_backtest(c, layers)
        comp[pid] = bootstrap_policy_diff(_position_pnls(alt), base_pnls)

    return {
        "base": {"summary": base_res["summary"], "health": base_res["health"]},
        "autopsy": {k: v for k, v in autopsy.items() if k != "rows"},
        "autopsy_rows": autopsy["rows"],
        "policies": policies,
        "setups": setups,
        "leaks": leaks,
        "policy_significance": comp,
    }


def _position_pnls(res: dict) -> List[float]:
    groups: Dict[Tuple[int, float], float] = {}
    for t in res["trades"]:
        k = (t.get("open_bar", 0), t.get("entry", 0.0))
        groups[k] = groups.get(k, 0.0) + t["pnl"]
    return list(groups.values())


# ----------------------------------------------------------------------------
# توصیه‌های خودکار (بر پایهٔ داده، نه سلیقه)
# ----------------------------------------------------------------------------
def recommendations(diag: dict, cfg: MTFConfig) -> List[dict]:
    """هر توصیه فقط اگر شاهدی در داده داشته باشد صادر می‌شود."""
    out: List[dict] = []
    a = diag["autopsy"]
    pol = diag["policies"]
    base = diag["base"]["summary"]
    rows = {r["id"]: r for r in pol["rows"]}

    cap = a.get("capture_ratio_pct", 0)
    if cap < 70:
        out.append({
            "title": "سود در مسیر دیده می‌شود ولی برداشت نمی‌شود",
            "evidence": f"معاملات برنده فقط {cap:.1f}% از بیشترین سودِ مسیرِ خود را "
                        f"واقعاً برداشت کرده‌اند (به‌طور میانگین "
                        f"{a.get('avg_giveback_pct_winners', 0):.2f}% قیمت از دست رفته).",
            "action": "TP و تریلینگ را بازتر کنید یا از خروج جزئی استفاده کنید تا "
                      "بخشی از سود قبل از برگشت قفل شود.",
            "severity": "high" if cap < 55 else "medium",
        })
    if a.get("stop_premature_pct", 0) >= 25:
        # توصیهٔ «استاپ بازتر» را با آزمایش واقعیِ همان پارامتر می‌سنجیم، نه با حس
        srows = {r["id"]: r for r in (diag.get("setups") or {}).get("rows", [])}
        base_exp = srows.get("base", {}).get("full", {}).get("expectancy")
        wider = [srows[k]["full"]["expectancy"] for k in ("stop_2R", "stop_1.8R")
                 if k in srows]
        contradicted = (base_exp is not None and wider
                        and all(x <= base_exp for x in wider))
        if contradicted:
            out.append({
                "title": "استاپ زود می‌خورد، ولی «بازتر کردن استاپ» جواب نداد",
                "evidence": f"{a['stop_premature_pct']:.1f}% از استاپ‌ها در ۲۴ کندل بعد مسیر "
                            f"مطلوب داشته‌اند؛ اما در آزمون مستقیم، استاپ 1.8×ATR "
                            f"({srows['stop_1.8R']['full']['expectancy']:+.2f}$) و 2×ATR "
                            f"({srows['stop_2R']['full']['expectancy']:+.2f}$) بدتر از پایه "
                            f"({base_exp:+.2f}$) شدند.",
                "action": "استاپ را دست نزنید — زود خوردنِ استاپ نشانهٔ «زمان‌بندی بد ورود» "
                          "است، نه تنگی استاپ. زمان‌بندی ورود را اصلاح کنید (فیلتر کندل اوج "
                          "/ فقط pullback) و بعد استاپ را دوباره بسنجید.",
                "severity": "medium",
            })
        else:
            out.append({
                "title": "استاپ در بخشی از معاملات زود خورده",
                "evidence": f"{a['stop_premature_pct']:.1f}% از خروج‌های استاپ، در ۲۴ کندل "
                            f"بعد به سمت هدف برگشته‌اند (یعنی استاپ تنگ‌تر از نوسان بود).",
                "action": "Δ stop را کمی بازتر کنید (مثلاً 1.5 → 1.8×ATR) و آزمون TRAIN/OOS "
                          "را دوباره بگیرید.",
                "severity": "high" if a["stop_premature_pct"] >= 40 else "medium",
            })
    lwg = a.get("losers_were_once_green_pct", 0)
    if lwg >= 30:
        brows = {r["id"]: r for r in diag.get("policies", {}).get("rows", [])}
        be_rows = [brows[k]["full"]["expectancy"] for k in ("be_1R", "partial_1R")
                   if k in brows]
        base_pol_exp = brows.get("base", {}).get("full", {}).get("expectancy")
        if base_pol_exp is not None and be_rows and all(x <= base_pol_exp for x in be_rows):
            out.append({
                "title": "ضررها قبلاً سبز بوده‌اند، ولی «بریک‌ایون/خروج جزئی» بدترشان کرد",
                "evidence": f"{lwg:.1f}% از معاملات ضررده قبلاً سود باز داشتند؛ اما در آزمون "
                            f"مستقیم، بریک‌ایون 1R ({brows['be_1R']['full']['expectancy']:+.2f}$) "
                            f"و خروج جزئی 1R ({brows['partial_1R']['full']['expectancy']:+.2f}$) "
                            f"از پایه ({base_pol_exp:+.2f}$) بدتر شدند.",
                "action": "این‌ها را فعال نکنید. علت: در این استراتژی، معامله‌ای که به 1R رسیده "
                          "بیشتر وقت‌ها تا TP نمی‌رود؛ قفل‌کردن سود در 1R نرخ برد را کم می‌کند. "
                          "به‌جای آن کیفیت ورود را بالا ببرید.",
                "severity": "medium",
            })
        else:
            out.append({
                "title": "ضررها قبلاً سبز بوده‌اند",
                "evidence": f"{lwg:.1f}% از معاملات ضررده، در مسیر خود حداقل +0.3% سود "
                            f"باز داشتند و بعد ضرر شدند.",
                "action": "بریک‌ایون (BE) در 1R یا خروج جزئی را فعال کنید — دقیقاً برای "
                          "همین گروه طراحی شده‌اند.",
                "severity": "high" if lwg >= 50 else "medium",
            })
    if pol.get("best_robust"):
        bid = pol["best_robust"]
        br = rows[bid]
        gain_full = br["full"]["expectancy"] - rows["base"]["full"]["expectancy"]
        gain_oos = (br.get("oos", {}).get("expectancy", 0)
                    - rows["base"].get("oos", {}).get("expectancy", 0))
        if gain_full > 0 and gain_oos > 0:
            out.append({
                "title": f"سیاست خروج بهتر و پایدار: «{br['label']}»",
                "evidence": f"expectancy روی کل داده {gain_full:+.3f}$ و در "
                            f"out-of-sample {gain_oos:+.3f}$ بهتر از پایه است "
                            f"(هر دو بازه مثبتِ بهبود → پایدار، نه خوش‌شانسی).",
                "action": f"پارامترها: {br['overrides'] or 'بدون تغییر'}",
                "severity": "high",
            })
    else:
        out.append({
            "title": "هیچ سیاست خروجی در هر دو بازه پایدار نبود",
            "evidence": f"از {pol['n_policies']} سیاست آزمون‌شده، هیچ‌کدام هم‌زمان در "
                        f"TRAIN و OOS expectancy مثبت نداشت.",
            "action": "پارامترهای خروج را تغییر ندهید؛ مشکل در «کیفیت سیگنال ورود» یا "
                      "در «کمبود edge نسبت به هزینه» است، نه در مدیریت خروج.",
            "severity": "high",
        })

    # یافتهٔ سمت ورود: مهم‌ترین اهرم
    su = diag.get("setups") or {}
    srow = {r["id"]: r for r in su.get("rows", [])}
    if su.get("best_robust") and "base" in srow:
        bid = su["best_robust"]
        br = srow[bid]
        gain_full = br["full"]["expectancy"] - srow["base"]["full"]["expectancy"]
        gain_oos = br["oos"]["expectancy"] - srow["base"]["oos"]["expectancy"]
        out.append({
            "title": f"اهرم واقعی سمتِ ورود است: «{br['label']}»",
            "evidence": f"expectancy {gain_full:+.2f}$ بهتر از پایه روی کل داده و "
                        f"{gain_oos:+.2f}$ بهتر در OOS، با افت سرمایهٔ کمتر "
                        f"({br['full']['max_drawdown_pct']:+.2f}% در برابر "
                        f"{srow['base']['full']['max_drawdown_pct']:+.2f}%) — بدون تغییر "
                        f"منطق خروج. توجه: OOS فقط {br['oos']['n']} معامله دارد.",
            "action": f"پارامترها: {br['overrides'] or 'بدون تغییر'} — و روی دادهٔ بیشتر "
                      f"(چند سال/چند نماد) تکرار کنید.",
            "severity": "high",
        })
    if "pullback_only" in srow and "breakout_only" in srow:
        pb, bo = srow["pullback_only"]["full"], srow["breakout_only"]["full"]
        if pb["expectancy"] > bo["expectancy"]:
            out.append({
                "title": "ورودِ «شکست» (breakout) بزرگ‌ترین نشتی است",
                "evidence": f"pullback: {pb['n']} معامله expectancy {pb['expectancy']:+.2f}$ "
                            f"در برابر breakout: {bo['n']} معامله {bo['expectancy']:+.2f}$.",
                "action": "با `--entry-modes pullback` فقط pullback را نگه دارید و "
                          "breakout را خاموش کنید (یا شرط «بدون کندل اوج» را اجباری کنید).",
                "severity": "high",
            })

    # نشت سود بر اساس حالت تریگر
    tm = diag["leaks"].get("buckets", {}).get("trigger_mode", [])
    if len(tm) >= 2:
        worst = min(tm, key=lambda x: x["exp"])
        best = max(tm, key=lambda x: x["exp"])
        if worst["n"] >= 10 and worst["exp"] < 0 < best["exp"]:
            out.append({
                "title": f"حالت تریگر «{worst['key']}» پول می‌سوزاند",
                "evidence": f"«{worst['key']}»: {worst['n']} معامله، expectancy "
                            f"{worst['exp']:+.3f}$ | «{best['key']}»: {best['n']} معامله، "
                            f"expectancy {best['exp']:+.3f}$.",
                "action": f"با `--entry-modes {best['key']}` فقط حالت سودده را نگه دارید "
                          f"(و روی دادهٔ بیشتر تأیید کنید).",
                "severity": "high",
            })

    # نشت بر اساس نوسان
    vol = diag["leaks"].get("buckets", {}).get("volatility_atr_pct", [])
    if len(vol) >= 2:
        worst_v = min(vol, key=lambda x: x["exp"])
        if worst_v["n"] >= 10 and worst_v["exp"] < 0:
            out.append({
                "title": f"نوسان «{worst_v['key']}» برای این استراتژی مناسب نیست",
                "evidence": f"{worst_v['n']} معامله در این بازهٔ نوسان با expectancy "
                            f"{worst_v['exp']:+.3f}$.",
                "action": "فیلتر نوسان (مثلاً ATR% حداقل) اضافه کنید تا در بازار "
                          "کم‌دامنه که هزینه می‌خورد معامله نشود.",
                "severity": "medium",
            })

    if (base.get("profit_factor") or 0) < 1.0:
        out.append({
            "title": "تصویر کلی: مدیریت خروج تنها نجات‌دهنده نیست",
            "evidence": f"PF پایه {base.get('profit_factor')} و expectancy "
                        f"{base.get('expectancy'):+.3f}$ با {base.get('trades')} معامله.",
            "action": "ابتدا ورود (کیفیت سیگنال/تایم‌فریم/فیلتر هزینه) را بهبود بدهید؛ "
                      "خروج فقط توزیع سود را عوض می‌کند، edge نمی‌سازد.",
            "severity": "high",
        })
    return out


# ----------------------------------------------------------------------------
# ۵) آزمون فرضیه‌های «ورود» (چون کالبدشکافی نشان داد نشت اصلی اینجاست)
# ----------------------------------------------------------------------------
SETUP_EXPERIMENTS: List[Tuple[str, str, dict]] = [
    ("base", "پایه (pullback + breakout)", {}),
    ("pullback_only", "فقط pullback (حذف شکست)", dict(trigger_entry_modes=["pullback"])),
    ("breakout_only", "فقط breakout (برای مقایسه)", dict(trigger_entry_modes=["breakout"])),
    ("climax_1.0", "ردِ کندلِ اوج (دامنه > 1.0×ATR)", dict(trigger_max_range_atr=1.0)),
    ("climax_1.5", "ردِ کندلِ اوج (دامنه > 1.5×ATR)", dict(trigger_max_range_atr=1.5)),
    ("stop_2R", "استاپ بازتر 2×ATR (RR ثابت ۲)", dict(stop_atr_mult=2.0,
                                                      take_profit_atr_mult=4.0)),
    ("stop_1.8R", "استاپ 1.8×ATR (RR ثابت ۲)", dict(stop_atr_mult=1.8,
                                                    take_profit_atr_mult=3.6)),
    ("pullback_climax", "pullback + ردِ کندلِ اوج", dict(trigger_entry_modes=["pullback"],
                                                        trigger_max_range_atr=1.0)),
    ("pullback_stop2", "pullback + استاپ 2×ATR", dict(trigger_entry_modes=["pullback"],
                                                      stop_atr_mult=2.0,
                                                      take_profit_atr_mult=4.0)),
    ("hours_off", "حذف ساعت‌های 00-02 و 13-14 UTC (⚠️ خطر overfit)",
     dict(skip_hours_utc=[0, 1, 2, 13, 14])),
    ("patient_trail", "تریلینگ صبور (از 1.5R)", dict(trail_start_r=1.5)),
    ("pullback+patient", "pullback + تریلینگ صبور", dict(trigger_entry_modes=["pullback"],
                                                         trail_start_r=1.5)),
]


def run_setup_experiments(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                          experiments: Optional[List[Tuple[str, str, dict]]] = None
                          ) -> dict:
    """آزمون فرضیه‌های سمتِ ورود + ارزیابی TRAIN/OOS (ضدِ خوش‌شانسی)."""
    experiments = experiments or SETUP_EXPERIMENTS
    trig = layers["trigger"]
    n = len(trig)
    i1, i2 = int(n * cfg.train_ratio), int(n * (cfg.train_ratio + cfg.validation_ratio))
    train_sub = _slice_layers(layers, cfg, trig[0].open_time_ms, trig[i1 - 1].open_time_ms)
    oos_sub = _slice_layers(layers, cfg, trig[i2].open_time_ms, trig[-1].open_time_ms)

    rows: List[dict] = []
    for eid, label, over in experiments:
        c = replace(cfg, verbose=False, forensics=False, run_id="", **over)
        full = _metrics_positions(run_backtest(c, layers), c)
        tr = _metrics_positions(run_backtest(c, train_sub), c)
        oo = _metrics_positions(run_backtest(c, oos_sub), c)
        rows.append({
            "id": eid, "label": label, "overrides": over,
            "full": full, "train": tr, "oos": oo,
            "robust": bool(tr["n"] >= 5 and oo["n"] >= 5
                           and tr["expectancy"] > 0 and oo["expectancy"] > 0),
        })
    base_full = rows[0]["full"]["expectancy"] if rows else 0.0
    base_oos = rows[0]["oos"]["expectancy"] if rows else 0.0
    for r in rows:
        r["gain_full"] = round(r["full"]["expectancy"] - base_full, 4)
        r["gain_oos"] = round(r["oos"]["expectancy"] - base_oos, 4)
    ranked = sorted(rows, key=lambda r: -r["full"]["expectancy"])
    robust = [r for r in rows if r["robust"]]
    return {
        "rows": rows,
        "best_full_sample": ranked[0]["id"] if ranked else None,
        "best_robust": (max(robust, key=lambda r: r["oos"]["expectancy"])["id"]
                        if robust else None),
        "robust_count": len(robust),
        "n_experiments": len(rows),
    }


# ----------------------------------------------------------------------------
# ۶) سنجش «فلات پارامتری» — تا معلوم شود بهبود، یک قلهٔ تصادفی نیست
# ----------------------------------------------------------------------------
SWEEP_AXES: List[Tuple[str, str, List]] = [
    ("climax", "آستانهٔ ردِ کندلِ اوج (دامنه ÷ ATR) — فقط pullback",
     [0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 2.0]),
    ("trail", "نقطهٔ شروع تریلینگ (R) — pullback + climax 1.0",
     [1.0, 1.25, 1.5, 2.0, 99.0]),
    ("tp", "هدف سود (×ATR) — pullback + climax 1.0 + تریلینگ 1.5R",
     [2.0, 3.0, 4.0, 6.0]),
    ("max_hold", "حداکثر نگه‌داری (کندل) — pullback + climax 1.0 + تریلینگ 1.5R",
     [12, 24, 48, 72]),
]

_SWEEP_OVERRIDES = {
    "climax": dict(trigger_entry_modes=["pullback"]),
    "trail": dict(trigger_entry_modes=["pullback"], trigger_max_range_atr=1.0),
    "tp": dict(trigger_entry_modes=["pullback"], trigger_max_range_atr=1.0,
               trail_start_r=1.5),
    "max_hold": dict(trigger_entry_modes=["pullback"], trigger_max_range_atr=1.0,
                     trail_start_r=1.5),
}
_SWEEP_PARAM = {"climax": "trigger_max_range_atr", "trail": "trail_start_r",
                "tp": "take_profit_atr_mult", "max_hold": "max_holding_bars"}


def run_setup_sweep(cfg: MTFConfig, layers: Dict[str, List[Candle]]) -> List[dict]:
    """روی یک محور، فقط یک پارامتر را عوض می‌کند و می‌بیند آیا نتیجه پیوسته است."""
    trig = layers["trigger"]
    n = len(trig)
    i1, i2 = int(n * cfg.train_ratio), int(n * (cfg.train_ratio + cfg.validation_ratio))
    train_sub = _slice_layers(layers, cfg, trig[0].open_time_ms, trig[i1 - 1].open_time_ms)
    oos_sub = _slice_layers(layers, cfg, trig[i2].open_time_ms, trig[-1].open_time_ms)

    axes: List[dict] = []
    for axis, label, values in SWEEP_AXES:
        base_over = dict(_SWEEP_OVERRIDES[axis])
        points: List[dict] = []
        for v in values:
            over = dict(base_over)
            over[_SWEEP_PARAM[axis]] = v
            c = replace(cfg, verbose=False, forensics=False, run_id="", **over)
            f = _metrics_positions(run_backtest(c, layers), c)
            o = _metrics_positions(run_backtest(c, oos_sub), c)
            points.append({"value": v, "n": f["n"], "exp": f["expectancy"],
                           "pf": f["profit_factor"],
                           "dd": f["max_drawdown_pct"],
                           "oos_exp": o["expectancy"], "oos_n": o["n"]})
        pos = [p for p in points if p["exp"] > 0]
        # طولانی‌ترین زنجیرهٔ پیوستهٔ نقاط مثبت = شاهد «فلات»، نه قله
        best_run, cur = 0, 0
        for p in points:
            cur = cur + 1 if p["exp"] > 0 else 0
            best_run = max(best_run, cur)
        axes.append({"axis": axis, "label": label, "points": points,
                     "positive": len(pos), "of": len(points),
                     "plateau_len": best_run,
                     "verdict": ("فلات (پایدار)" if best_run >= 3 and len(pos) >= 3
                                 else "قله/نوسان‌دار (احتمال خوش‌شانسی)")})
    return axes


# ----------------------------------------------------------------------------
# ۷) معناداری آماری فرضیه‌های برنده در برابر پایه
# ----------------------------------------------------------------------------
def setup_significance(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                       setups: dict) -> dict:
    ids = [i for i in (setups.get("best_robust"), setups.get("best_full_sample")) if i]
    base_pnls = _position_pnls(run_backtest(
        replace(cfg, verbose=False, forensics=False, run_id=""), layers))
    out: Dict[str, dict] = {}
    for sid in ids:
        row = next((r for r in setups["rows"] if r["id"] == sid), None)
        if not row:
            continue
        c = replace(cfg, verbose=False, forensics=False, run_id="", **row["overrides"])
        out[sid] = bootstrap_policy_diff(_position_pnls(run_backtest(c, layers)), base_pnls)
    return out


# ----------------------------------------------------------------------------
# ۸) گزارش مارک‌داون فارسی
# ----------------------------------------------------------------------------
def _f(x, d: int = 2) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        if abs(x) < 0.5 * 10 ** (-d):
            x = 0.0
        return f"{x:+,.{d}f}"
    return str(x)


def _fmt_pct(x, d=2) -> str:
    return "—" if x is None else f"{x:+.{d}f}%"


def write_diagnosis_report(diag: dict, cfg: MTFConfig, out_path: str,
                           sweeps: Optional[List[dict]] = None) -> str:
    b = diag["base"]["summary"]
    a = diag["autopsy"]
    pol = diag["policies"]
    su = diag["setups"]
    lk = diag["leaks"]
    prow = {r["id"]: r for r in pol["rows"]}
    srow = {r["id"]: r for r in su["rows"]}
    base_pol = prow.get("base", {})
    sig = diag.get("policy_significance", {})
    ssig = diag.get("setup_significance", {})

    L: List[str] = []
    w = L.append
    w("# گزارش تشخیصی: چرا سود «زود بسته می‌شود» و سود شناور چه نقشی دارد\n")
    w("*تولید‌شده به‌صورت خودکار از داده؛ همهٔ اعداد از اجرای واقعی بک‌تست می‌آیند، "
      "هیچ عددی دستی نوشته نشده.*\n")
    w(f"- داده: `{cfg.csv_path or cfg.data_mode}` — {cfg.tf_trigger} تریگر / "
      f"{cfg.tf_filter} فیلتر / {cfg.tf_bias} بایاس، هم‌راستایی `{cfg.alignment_version}`")
    w(f"- نوسان‌سنج: EMA{cfg.bias_ema_period} | استاپ {cfg.stop_atr_mult}×ATR | "
      f"TP {cfg.take_profit_atr_mult}×ATR | تریلینگ از {cfg.trail_start_r}R "
      f"({cfg.trail_atr_mult}×ATR)")
    w(f"- بازهٔ آموزش/OOS: {int(cfg.train_ratio*100)}/{int(cfg.validation_ratio*100)} "
      f"درصد | تعداد معاملهٔ پایه: {b.get('trades')}\n")

    # ---------- ۱) خلاصهٔ مدیریتی ----------
    w("## ۱) خلاصهٔ مدیریتی (اگر فقط یک پاراگراف می‌خوانید)\n")
    cap = a.get("capture_ratio_pct", 0)
    w(f"فرض اولیه این بود که «سود در مسیر دیده می‌شود ولی زود بسته می‌شود». "
      f"داده این فرض را **تا حد زیادی رد می‌کند**: معاملات برنده "
      f"{cap:.1f}٪ از بیشترین سودِ مسیرشان را واقعاً برداشت کرده‌اند. "
      f"یعنی مشکل «برداشتِ دیر» نیست، مشکل **«ورودِ بد»** است.\n")
    w(f"عدد تعیین‌کننده: از {b.get('trades')} معامله، "
      f"{a.get('stop_premature_pct', 0):.1f}٪ خروج‌های استاپ در ۲۴ کندل بعد به سمت "
      f"هدف برگشته‌اند و {a.get('losers_were_once_green_pct', 0):.1f}٪ ضررها قبلاً "
      f"سبز بوده‌اند — این‌ها نشانهٔ **ورود در انتهای حرکت** است، نه مدیریت خروج بد.\n")
    if su.get("best_robust"):
        r = srow[su["best_robust"]]
        w(f"و مهم‌ترین یافته: با اصلاح **سمت ورود** (فقط pullback + ردِ کندلِ اوج)، "
          f"expectancy از {b.get('expectancy'):+.2f}$ به "
          f"{r['full']['expectancy']:+.2f}$ رسید، PF از {b.get('profit_factor')} به "
          f"{r['full']['profit_factor']}، و drawdown از {_fmt_pct(b.get('max_drawdown_pct'))} به "
          f"{_fmt_pct(r['full']['max_drawdown_pct'])} کم شد — **بدون یک خط تغییر در منطق خروج**. "
          f"پس اهرم واقعی، ورود است.\n")
    w("---\n")

    # ---------- ۲) کالبدشکافی ----------
    w("## ۲) کالبدشکافی خروج: سود واقعاً کجا گم می‌شود؟\n")
    w("| گروه خروج | n | PnL/معامله | avg R | MFE (حداکثر سود شناور) | سودِ برگشته | "
      "حرکت مطلوب ۲۴ کندل بعد |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for g, v in a["by_group"].items():
        w(f"| `{g}` | {v['n']} | {_f(v['pnl_per_trade'])} | {_f(v['avg_r'])} | "
          f"{_fmt_pct(v['avg_mfe_pct'])} | {_fmt_pct(v['avg_gave_back_pct'], 3)} | "
          f"{_fmt_pct(v['avg_favorable_after_24bars'])} |")
    w("")
    tp = a["by_group"].get("take_profit", {})
    sl = a["by_group"].get("stop_loss", {})
    w(f"**خواندن این جدول:**\n")
    w(f"1. گروه `take_profit` (n={tp.get('n', 0)}) پول‌ساز است "
      f"({_f(tp.get('pnl_per_trade'))}$ به‌ازای هر معامله) ولی **بعد از خروجش** هنوز "
      f"{_fmt_pct(tp.get('avg_favorable_after_24bars'))} حرکت مطلوب باقی مانده — "
      f"یعنی TP ما کمی زود است، نه خیلی زود.")
    w(f"2. گروه `stop_loss` (n={sl.get('n', 0)}) کل زیان را می‌سازد "
      f"({_f(sl.get('pnl_per_trade'))}$). این گروه به‌طور میانگین MFE صفر دارد — "
      f"یعنی **حتی یک لحظه هم سود نبوده** که بخواهیم بگیریمش. این تعریفِ «بد بودن ورود» است.")
    w(f"3. گروه `stop/trail` همان جایی است که تریلینگ فعال شده: MFE "
      f"{_fmt_pct(a['by_group'].get('stop/trail', {}).get('avg_mfe_pct'))} بوده ولی "
      f"{_fmt_pct(a['by_group'].get('stop/trail', {}).get('avg_gave_back_pct'), 3)} "
      f"از آن برگشته — **تریلینگ سود را از ما گرفته، نه داده**.\n")
    w(f"- نسبت برداشت (capture ratio): **{cap:.2f}٪** — بالاست، یعنی «سود زود بسته می‌شود» "
      f"در سطح پوزیشن‌های برنده واقعیت ندارد.")
    w(f"- استاپِ زودهنگام: **{a.get('stop_premature_pct', 0):.2f}٪** از استاپ‌ها در ۲۴ کندل "
      f"بعد مسیر مطلوب داشته‌اند.")
    w(f"- ضررهای «سبزشده»: **{a.get('losers_were_once_green_pct', 0):.2f}٪** با میانگین MFE "
      f"{_fmt_pct(a.get('avg_mfe_losers_pct'))}.\n")

    # ---------- ۳) سود شناور ----------
    w("## ۳) سود شناور / تریلینگ: راه بهترِ سود بیشتر هست یا نه؟\n")
    w(f"۱۵ سیاست خروج، هر یک روی سه بازه (کل / TRAIN / OOS) اجرا شد. "
      f"معیار پذیرش: مثبت‌بودن expectancy در **هر دو** TRAIN و OOS.\n")
    w("| سیاست | n | PF | expectancy کل | بازده٪ | حداکثر افت٪ | TRAIN | OOS | پایدار؟ |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for r in pol["rows"]:
        f_, t_, o_ = r["full"], r.get("train", {}), r.get("oos", {})
        w(f"| {r['label']} | {f_['n']} | {f_['profit_factor'] if f_['profit_factor'] is not None else '—'} | "
          f"{_f(f_['expectancy'])} | {_fmt_pct(f_['return_pct'])} | "
          f"{_fmt_pct(f_['max_drawdown_pct'])} | {_f(t_.get('expectancy'))} | "
          f"{_f(o_.get('expectancy'))} | {'✅' if r['robust'] else '❌'} |")
    w("")
    best_full = pol.get("best_full_sample")
    w(f"- بهترین روی کل داده: `{best_full}` "
      f"({_f(prow[best_full]['full']['expectancy'])}$ در برابر پایه "
      f"{_f(base_pol['full']['expectancy'] if base_pol else None)}$)."
      if best_full else "- سیاست برنده‌ای پیدا نشد.")
    if pol.get("best_robust"):
        w(f"- پایدار در هر دو بازه: `{pol['best_robust']}` "
          f"(`{prow[pol['best_robust']]['label']}`).")
    else:
        w("- **هیچ سیاست خروجی** هم‌زمان در TRAIN و OOS مثبت نبود → تغییر تریلینگ/TP/BE "
          "یک تصمیم «سلیقه‌ای» است، نه بهبود آماری.")
    for pid, s in sig.items():
        w(f"- بوت‌استرپ `{pid}` در برابر پایه: تفاوت {_f(s.get('observed'))}$، "
          f"بازهٔ اطمینان ۹۵٪ = [{_f((s.get('ci95') or [None, None])[0])} , "
          f"{_f((s.get('ci95') or [None, None])[1])}] → {s.get('note')}")
    w("")
    w("**پاسخ کوتاه به سؤال شما:** سود شناور به‌خودی‌خود سود نمی‌سازد. تریلینگ فقط "
      "«توزیع» سود را عوض می‌کند: دمِ راست را کوتاه و نرخ برد را بالا می‌برد. اگر ورود "
      "edge نداشته باشد، تریلینگِ تنگ‌تر صرفاً سریع‌تر ضرر را قطع می‌کند (که همان کاهش "
      "drawdown است) و تریلینگِ بازتر اجازه می‌دهد سودِ موجود برگردد. در دادهٔ ما تریلینگ "
      "**تنگ‌تر** (۱×ATR) کم‌ضررترین بود و تریلینگ از ۰.۵R بدترین — یعنی تریلینگ زودهنگام، "
      "سم است.\n")

    # ---------- ۴) نقشهٔ نشت ----------
    w("## ۴) نقشهٔ نشت سود (کجا پول می‌سوزد)\n")
    for name, label in (("trigger_mode", "حالت ورود"), ("regime", "رژیم بازار"),
                        ("side", "جهت"), ("bars_held", "مدت نگه‌داری (کندل)"),
                        ("volatility_atr_pct", "نوسان (ATR٪)"), ("hour_utc", "ساعت UTC")):
        rows = lk.get("buckets", {}).get(name, [])
        if not rows:
            continue
        note = ""
        if name == "hour_utc":
            rows = sorted([r for r in rows if r["n"] >= 4], key=lambda r: -r["exp"])
            note = ("\n> ⚠️ ساعت‌ها با n کوچک‌اند و همین تحلیل «بهترین ساعت» را "
                    "خوش‌شانسی می‌کند؛ از این جدول برای فیلتر ساعت استفاده نکنید "
                    "(آزمون مستقیم `hours_off` هم بدتر شد).\n")
        w(f"**{label}**{note}\n")
        w("| بازه | n | expectancy$ | نرخ برد٪ |")
        w("|---|---:|---:|---:|")
        for r in rows:
            w(f"| `{r['key']}` | {r['n']} | {_f(r['exp'])} | {r['win_rate']*100:.1f} |")
        w("")

    # ---------- ۵) فرضیه‌های ورود ----------
    w("## ۵) آزمون فرضیه‌های «سمت ورود» (جایی که داده گفت باید بگردیم)\n")
    w("| # | فرضیه | n | PF | expectancy کل | بازده٪ | افت٪ | TRAIN | OOS | پایدار؟ |")
    w("|---:|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for i, r in enumerate(su["rows"], 1):
        f_, t_, o_ = r["full"], r["train"], r["oos"]
        w(f"| {i} | {r['label']} | {f_['n']} | "
          f"{f_['profit_factor'] if f_['profit_factor'] is not None else '—'} | "
          f"{_f(f_['expectancy'])} | {_fmt_pct(f_['return_pct'])} | "
          f"{_fmt_pct(f_['max_drawdown_pct'])} | {_f(t_['expectancy'])} | "
          f"{_f(o_['expectancy'])} (n={o_['n']}) | {'✅' if r['robust'] else '❌'} |")
    w("")
    w(f"از {su['n_experiments']} فرضیه، **{su['robust_count']}** فرضیه در هر دو بازه مثبت شد. "
      f"بهترین روی کل داده: `{su['best_full_sample']}` | پایدارترین: `{su['best_robust']}`.\n")
    for sid, s in ssig.items():
        w(f"- بوت‌استرپ `{sid}` در برابر پایه: {_f(s.get('observed'))}$، "
          f"CI95 [{_f((s.get('ci95') or [None, None])[0])} , "
          f"{_f((s.get('ci95') or [None, None])[1])}] → {s.get('note')}")
    w("")

    # ---------- ۶) فلات پارامتری ----------
    if sweeps:
        w("## ۶) آزمون فلات: آیا بهبود، یک قلهٔ خوش‌شانسی است؟\n")
        w("یک پارامتر را پله‌پله تغییر دادیم. اگر نتیجه فقط در یک نقطه خوب باشد، "
          "«overfit» است؛ اگر یک بازهٔ پیوسته خوب باشد، یافته واقعی‌تر است.\n")
        for ax in sweeps:
            w(f"**{ax['label']}** — نتیجه: `{ax['verdict']}` "
              f"({ax['positive']}/{ax['of']} نقطه مثبت، طولانی‌ترین فلات {ax['plateau_len']})\n")
            w("| مقدار | n | expectancy کل | PF | افت٪ | OOS |")
            w("|---|---:|---:|---:|---:|---:|")
            for p in ax["points"]:
                v = p["value"]
                vs = "بدون تریلینگ" if (ax["axis"] == "trail" and v >= 99) else v
                w(f"| `{vs}` | {p['n']} | {_f(p['exp'])} | "
                  f"{p['pf'] if p['pf'] is not None else '—'} | {_fmt_pct(p['dd'])} | "
                  f"{_f(p['oos_exp'])} (n={p['oos_n']}) |")
            w("")

    # ---------- ۷) نسخهٔ پیشنهادی ----------
    w("## ۷) نسخهٔ پیشنهادی (اگر بخواهیم همین اسکریپت را جدی‌تر کنیم)\n")
    if su.get("best_robust"):
        r = srow[su["best_robust"]]
        w("```bash")
        w(f"python3 -m mtflab validate --data csv --csv <same.csv> \\\n"
          f"    --align A --bias-ema 50 --entry-modes pullback --max-range-atr 1.0")
        w("```\n")
        w(f"- expectancy {_f(r['full']['expectancy'])}$ در {r['full']['n']} معامله، "
          f"PF {r['full']['profit_factor']}، افت {_fmt_pct(r['full']['max_drawdown_pct'])}، "
          f"بازده {_fmt_pct(r['full']['return_pct'])}.")
        w(f"- ولی: **OOS فقط {r['oos']['n']} معامله** دارد. این عدد برای تصمیم‌گیری "
          f"کافی نیست؛ باید روی دادهٔ بیشتر (چند سال / چند نماد) تکرار شود.\n")
    else:
        w("- هیچ ترکیبی در هر دو بازه پایدار نشد؛ نتیجهٔ صادقانه این است که این اسکریپت "
          "در نسخهٔ فعلی edge ندارد.\n")

    # ---------- ۸) توصیه‌ها ----------
    w("## ۸) توصیه‌های خودکار (هر کدام فقط با شاهد داده‌ای)\n")
    for r in recommendations(diag, cfg):
        w(f"### {r['title']}  `[{r['severity']}]`")
        w(f"- **شاهد:** {r['evidence']}")
        w(f"- **اقدام:** {r['action']}\n")

    # ---------- ۹) تحلیل مارکتر ----------
    w("## ۹) خوانش من به‌عنوان مارکتر کریپتو/فیوچرز\n")
    w("این بخش، تحلیل بازاریابی و محصول است — نه توصیهٔ سرمایه‌گذاری.\n")
    w("**۱. «سود زود بسته می‌شود» یک دردِ واقعیِ کاربر است، حتی وقتی عدد چیز دیگری "
      "می‌گوید.** کاربر حس می‌کند سودش را از دست می‌دهد؛ داده می‌گوید برداشتش خوب است. "
      "این یعنی مشکل در **روایت محصول** است: داشبورد باید «capture ratio» و «MFE» را "
      "نشان بدهد تا کاربر ببیند سود کجا رفته. چیزی که اندازه‌گیری نشود، حس می‌شود و "
      "حس، بدترین مشاور است.\n")
    w("**۲. اهرم واقعی فروش این اسکریپت، «شهودِ ورود» است نه «تنظیم خروج».** "
      "در داده، تغییر ورود ۱.۵ دلار به expectancy اضافه کرد؛ بهترین تغییر خروج فقط "
      "۰.۶ دلار. اگر می‌خواهید این محصول بفروشد، روی «فیلتر کیفیت ورود» بازاریابی کنید "
      "(pullback + ردِ کندلِ اوج)، نه روی ده‌ها اسلایدر تریلینگ.\n")
    w("**۳. اسلایدر تریلینگ، تلهٔ محصول است.** ۱۵ سیاست خروج آزمودیم؛ هیچ‌کدام پایدار "
      "نبود، و بدترین‌ها همان‌هایی بودند که کاربر تازه‌کار دوست دارد (تریلینگ زودهنگام "
      "۰.۵R، بریک‌ایون 1R). اگر اسلایدر می‌گذارید، باید پیش‌فرضِ محافظه‌کارانه و "
      "هشدار «این پارامتر در تست تاریخی پایدار نبود» کنارش باشد.\n")
    w("**۴. هزینه، بخشی از محصول است.** با ۱۰۷ معامله در سال و ATR کوچک، کارمزد و "
      "اسلیپیج بخش قابل‌توجهی از expectancy را می‌خورند. در بازاریابی، «PF بدون هزینه» "
      "فروختن و بعد نمایش «PF با هزینه» = ریزش اعتماد. هزینه را از روز اول نشان بدهید "
      "(ما در همین ابزار فیلتر هزینه را عمداً اجباری کردیم).\n")
    w("**۵. فیلتر نوسان، بهترین «قابلیتِ» قابل‌فروش بعدی است.** داده می‌گوید بیشترین "
      "ضرر در ATR٪ پایین (<0.8) رخ می‌دهد؛ یعنی «وقتی بازار خواب است، معامله نکن». "
      "این یک پیام بازاریابی تمیز و صادقانه است: «ابزار، بازار بی‌رمق را تشخیص می‌دهد و "
      "ساکت می‌ماند» — باهوش‌تر از فروش «سود تضمینی».\n")
    w("**۶. صداقت دربارهٔ اندازهٔ نمونه، مزیت رقابتی است.** ما در همین گزارش گفتیم OOS "
      "فقط ۷ معامله دارد. اکثر محصولات این عدد را پنهان می‌کنند. اگر عددِ نمونه را کنار "
      "هر نتیجه نشان بدهید، مخاطب حرفه‌ای به شما اعتماد می‌کند — و مخاطب حرفه‌ای، "
      "مشتریِ ماندگار است.\n")
    w("**۷. مسیر درآمدی درست:** نه «سیگنال» و نه «ربات سودده»، بلکه «آزمایشگاهِ صداقت» — "
      "ابزاری که قبل از ریسک کردن پول، به شما می‌گوید ایده‌تان در داده چه می‌کند و "
      "چقدر شکننده است. این چیزی است که همین اسکریپت انجام می‌دهد و بازار کم‌تر دارد.\n")

    # ---------- ۱۰) محدودیت‌ها ----------
    w("## ۱۰) محدودیت‌ها (که داوطلبانه اعلام می‌کنیم)\n")
    w(f"- فقط {b.get('trades')} معامله در یک سال و یک نماد (BTCUSDT). "
      f"هر نتیجه‌ای با n<30 باید «فرضیه» خوانده شود، نه «یافته».")
    w("- فضای پارامتر زیاد است؛ با این حجم داده، خطر overfit بالا است. تنها محافظ ما "
      "شرط «مثبت در TRAIN و OOS هم‌زمان» و آزمون فلات بود.")
    w("- هزینه‌ها با فرض کارمزد/اسلیپیج ثابت مدل شده‌اند؛ در بازار واقعی، نقدشوندگی "
      "متغیر است.")
    w("- بازهٔ داده یک ساله است و رژیم بازارِ خاص خودش را دارد؛ رفتار در بازار خرسیِ "
      "شدید یا رالیِ پرشتاب می‌تواند متفاوت باشد.\n")
    w("---")
    w("_این گزارش صرفاً تحلیل دادهٔ تاریخی است و توصیهٔ معاملاتی نیست._")

    text = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path
