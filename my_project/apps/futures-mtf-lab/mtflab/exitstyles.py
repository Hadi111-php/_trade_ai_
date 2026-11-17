"""مقایسهٔ «حد ضرر/سود ثابت درصدی» با «شناور (ATR + تریل)» روی همان ورودی‌ها.

**سؤال کاربر:** روی دادهٔ یک‌ساله، کدام بهتر است — درصدهای ثابت یا شناور؟

**چرا ماژول جدا:** نمی‌شود با دو اجرای بک‌تست معمولی جواب داد، چون آن‌جا هر تغییر
پارامتر **ورودی‌ها** را هم عوض می‌کند (کول‌داون، اشغال اسلات، تعداد معامله). این‌جا
برای انصاف، ورودی‌ها **قفل** هستند:

  ۱) دروازهٔ ورود موتور روی هر کندل (`MTFEngine.build_decision`) یک‌بار حساب می‌شود.
  ۲) همان فهرست ورود به **همهٔ سیاست‌های خروج** داده می‌شود.
  ۳) هر بار فقط یک پوزیشن باز است؛ کول‌داون و سقف اسلات حذف شده‌اند تا تفاوت
     فقط از «مدیریت خروج» بیاید، نه از تعداد معامله.

**چرا R و نه درصد خام:** حد ضرر ۱٪ و ۳٪ دو ریسک متفاوت‌اند. اگر با ریسک ثابت
(۱٪ سرمایه در هر معامله) اندازهٔ پوزیشن را با فاصلهٔ حد ضرر تنظیم کنیم، مقایسه
منصفانه می‌شود: هر معامله یک واحد ریسک. برای همین ستون اصلی `expectancy_r` است
و درصد خام هم کنارش می‌آید.

**قاعدهٔ داوری (از قبل):** یک سیاست «بهتر» است فقط اگر
`n ≥ 30` و `expectancy_r` بالاتر و **بیرون‌نمونه (۳۰٪ آخر) هم همان جهت** را
تأیید کند. وگرنه می‌نویسیم «تفکیک‌نشده».
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .alignment import align_multi_timeframe
from .config import load_config
from .data import Candle, build_layers, tf_to_minutes
from .engine import MTFEngine
from .indicators import atr as atr_series
from .signals import TFContext

VERSION = 1
LADDER = ["15m", "1h", "4h", "1d"]
MIN_TRADES_FOR_VERDICT = 30
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ══════════════════════════════════════════════════════════════════════════
#  ۱) سیاست‌های خروج
# ══════════════════════════════════════════════════════════════════════════
POLICIES: List[dict] = [
    {"id": "fixed_1_2", "label": "ثابت ۱٪ / ۲٪", "kind": "fixed",
     "sl_pct": 1.0, "tp_pct": 2.0},
    {"id": "fixed_1.5_3", "label": "ثابت ۱.۵٪ / ۳٪", "kind": "fixed",
     "sl_pct": 1.5, "tp_pct": 3.0},
    {"id": "fixed_2_4", "label": "ثابت ۲٪ / ۴٪", "kind": "fixed",
     "sl_pct": 2.0, "tp_pct": 4.0},
    {"id": "fixed_3_6", "label": "ثابت ۳٪ / ۶٪", "kind": "fixed",
     "sl_pct": 3.0, "tp_pct": 6.0},
    {"id": "atr_1.5_3_trail", "label": "شناور ATR ۱.۵ / ۳ + تریل ۲",
     "kind": "atr", "sl_atr": 1.5, "tp_atr": 3.0,
     "trail_atr": 2.0, "trail_start_r": 1.0},
    {"id": "atr_2_4_trail", "label": "شناور ATR ۲ / ۴ + تریل ۲.۵",
     "kind": "atr", "sl_atr": 2.0, "tp_atr": 4.0,
     "trail_atr": 2.5, "trail_start_r": 1.0},
    {"id": "atr_1.5_trail_only", "label": "شناور ATR ۱.۵ بدون حد سود + تریل ۳",
     "kind": "atr", "sl_atr": 1.5, "tp_atr": None,
     "trail_atr": 3.0, "trail_start_r": 1.0},
]


def policy_by_id(pid: str) -> dict:
    for p in POLICIES:
        if p["id"] == pid:
            return p
    raise KeyError(f"سیاست ناشناس: {pid}")


# ══════════════════════════════════════════════════════════════════════════
#  ۲) ورودی‌ها (قفل‌شده و مشترک بین همهٔ سیاست‌ها)
# ══════════════════════════════════════════════════════════════════════════
def entry_signals(candles: Sequence[Candle], cfg,
                  exec_candles: Optional[Sequence[Candle]] = None) -> Tuple[list, list]:
    """همهٔ نقاط ورود موتور روی این کندل‌ها (بدون توجه به خروج).

    :return: (bars، ورودی‌ها) — هر ورودی: `{i, ts, side, entry, atr, confidence, mode}`
    """
    layers = build_layers(candles, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                          bias_enabled=cfg.bias_enabled, exec_candles=exec_candles)
    bars = align_multi_timeframe(
        layers["trigger"], tf_to_minutes(cfg.tf_trigger),
        layers["filter"], tf_to_minutes(cfg.tf_filter),
        layers["bias"] if cfg.bias_enabled else None,
        tf_to_minutes(cfg.tf_bias) if cfg.bias_enabled else None)
    ctxs = {
        "trigger": TFContext(layers["trigger"], cfg, "trigger"),
        "filter": TFContext(layers["filter"], cfg, "filter"),
        "bias": (TFContext(layers["bias"], cfg, "bias") if cfg.bias_enabled
                 else TFContext(layers["filter"], cfg, "filter")),
    }
    eng = MTFEngine(cfg, None, None)
    atr_by_ts = {int(c.open_time_ms): (v or 0.0)
                 for c, v in zip(layers["trigger"],
                                 atr_series(layers["trigger"], cfg.trigger_atr_period))}
    out: List[dict] = []
    for i, b in enumerate(bars):
        info = eng.build_decision(b, ctxs)
        d = info["decision"]
        if d.action != "ENTER" or not d.direction:
            continue
        c = b.low_tf_candle
        out.append({"i": i, "ts": int(c.open_time_ms),
                    "side": 1 if d.direction > 0 else -1,
                    "entry": float(c.close),
                    "atr": float(atr_by_ts.get(int(c.open_time_ms)) or 0.0),
                    "confidence": float(getattr(d, "confidence", 0.0) or 0.0),
                    "mode": info["trig"].mode})
    return bars, out


# ══════════════════════════════════════════════════════════════════════════
#  ۳) شبیه‌سازی یک سیاست خروج روی ورودی‌های قفل‌شده
# ══════════════════════════════════════════════════════════════════════════
def _levels(policy: dict, entry: float, atr: float) -> Tuple[float, Optional[float], dict]:
    """فاصلهٔ حد ضرر/سود (به قیمت) + تنظیمات تریل مخصوص همان سیاست."""
    if policy["kind"] == "fixed":
        sd = entry * float(policy["sl_pct"]) / 100.0
        td = entry * float(policy["tp_pct"]) / 100.0
        return sd, td, {"trail_dist": 0.0, "trail_start_r": 0.0}
    atr = atr if atr > 0 else entry * 0.005
    sd = atr * float(policy["sl_atr"])
    tp_atr = policy.get("tp_atr")
    td = (atr * float(tp_atr)) if tp_atr else None
    return sd, td, {"trail_dist": atr * float(policy.get("trail_atr") or 0.0),
                    "trail_start_r": float(policy.get("trail_start_r") or 0.0)}


def simulate(bars: Sequence, entries: Sequence[dict], policy: dict, cfg,
             one_at_a_time: bool = True) -> List[dict]:
    """کندل‌به‌کندل جلو برو و با این سیاست ببند.

    :param one_at_a_time: `True` = مثل سیستم واقعی، هر بار یک پوزیشن (انجام هر
        ورودی جدید تا پوزیشن قبلی بسته نشود ممکن نیست). `False` = همهٔ ورودی‌ها
        مستقل شبیه‌سازی می‌شوند تا تعداد معامله در همهٔ سیاست‌ها **یکی** باشد و
        فقط رفتار خروج مقایسه شود.
    """
    fee_pct = 2.0 * (float(cfg.fee_bps) / 10000.0) * 100.0
    slip_pct = 2.0 * float(cfg.slippage_pct)
    cost_pct = fee_pct + slip_pct
    max_bars = int(cfg.max_holding_bars or 0)

    trades: List[dict] = []
    busy_until = -1
    for e in entries:
        i0 = int(e["i"])
        if one_at_a_time and i0 <= busy_until:
            continue                       # یک پوزیشن در هر لحظه
        sign = int(e["side"])
        entry = float(e["entry"])
        if entry <= 0:
            continue
        sd, td, tr = _levels(policy, entry, float(e.get("atr") or 0.0))
        if sd <= 0:
            continue
        stop = entry - sign * sd
        take = (entry + sign * td) if td else None
        hw, lw = entry, entry
        trail_on = tr["trail_dist"] > 0 and tr["trail_start_r"] > 0
        trail_active = False
        mfe = mae = 0.0
        exit_px = None
        reason = ""
        bars_held = 0
        exit_ts = None
        for j in range(i0 + 1, len(bars)):
            c = bars[j].low_tf_candle
            hi, lo, op, cl = float(c.high), float(c.low), float(c.open), float(c.close)
            bars_held = j - i0

            # ۰) گپ در باز شدن کندل: اگر قیمت آن‌طرف حد ضرر باز شد، همان‌جا پر می‌شود
            if (sign > 0 and op <= stop) or (sign < 0 and op >= stop):
                exit_px, reason, exit_ts = op, "stop_gap", int(c.open_time_ms)
                break

            fav = (hi - entry) if sign > 0 else (entry - lo)
            adv = (entry - lo) if sign > 0 else (hi - entry)
            mfe = max(mfe, fav)
            mae = max(mae, adv)

            hit_stop = (lo <= stop) if sign > 0 else (hi >= stop)
            hit_take = False
            if take is not None:
                hit_take = (hi >= take) if sign > 0 else (lo <= take)

            if hit_stop:                        # احتیاط: اول حد ضرر
                exit_px, reason, exit_ts = stop, "stop", int(c.open_time_ms)
                break
            if hit_take:
                exit_px, reason, exit_ts = take, "take", int(c.open_time_ms)
                break
            if max_bars and bars_held >= max_bars:
                exit_px, reason, exit_ts = cl, "time_stop", int(c.open_time_ms)
                break

            # تریل در پایان کندل (مثل موتور: فعال‌سازی بر اساس R بستهٔ کندل)
            if trail_on:
                r_now = sign * (cl - entry) / sd
                if r_now >= tr["trail_start_r"]:
                    trail_active = True
                if trail_active:
                    if sign > 0:
                        hw = max(hw, hi)
                        stop = max(stop, hw - tr["trail_dist"])
                    else:
                        lw = min(lw, lo)
                        stop = min(stop, lw + tr["trail_dist"])

        if exit_px is None:                     # تا آخر داده باز ماند ⇒ از آمار بیرون
            trades.append({"symbol": e.get("symbol"), "status": "open_at_end",
                           "entry_ts": int(e["ts"]), "side": "LONG" if sign > 0 else "SHORT",
                           "entry": entry, "bars_held": bars_held,
                           "mfe_pct": round(mfe / entry * 100.0, 3),
                           "mae_pct": round(mae / entry * 100.0, 3)})
            if one_at_a_time:
                busy_until = len(bars) - 1
            continue

        if one_at_a_time:
            busy_until = i0 + max(bars_held, 1)
        gross = sign * (exit_px - entry) / entry * 100.0
        net = gross - cost_pct
        r = net / (sd / entry * 100.0)          # ریسک‌نرمال‌شده
        trades.append({
            "symbol": e.get("symbol"), "status": "closed",
            "entry_ts": int(e["ts"]), "exit_ts": exit_ts,
            "side": "LONG" if sign > 0 else "SHORT",
            "entry": round(entry, 8), "exit": round(exit_px, 8),
            "stop_dist_pct": round(sd / entry * 100.0, 4),
            "reason": reason, "bars_held": bars_held,
            "gross_pct": round(gross, 4), "net_pct": round(net, 4),
            "r_multiple": round(r, 3), "is_win": bool(net > 0),
            "mfe_pct": round(mfe / entry * 100.0, 3),
            "mae_pct": round(mae / entry * 100.0, 3),
        })
    return trades


# ══════════════════════════════════════════════════════════════════════════
#  ۴) سنجه‌ها
# ══════════════════════════════════════════════════════════════════════════
def metrics(trades: Sequence[dict], risk_pct: float = 1.0,
            compound: bool = True) -> dict:
    closed = [t for t in trades if t.get("status") == "closed"]
    n = len(closed)
    if not n:
        # همهٔ کلیدها باید باشند: گزارش‌دهی به کلیدِ غایب نباید بشکند
        return {"n": 0, "wins": 0, "win_rate": None, "expectancy_r": None,
                "r_sum": 0.0, "profit_factor": None, "equity_multiple": None,
                "max_dd_pct": None, "avg_bars": None, "avg_net_pct": None,
                "avg_stop_pct": None,
                "open_at_end": sum(1 for t in trades if t.get("status") == "open_at_end")}
    rs = [float(t["r_multiple"]) for t in closed]
    wins = [r for r in rs if r > 0]
    gl = abs(sum(r for r in rs if r <= 0))
    eq = 1.0
    peak = 1.0
    dd = 0.0
    for r in rs:
        if compound:
            eq *= (1.0 + (risk_pct / 100.0) * r)
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak * 100.0)
    return {
        "n": n,
        "wins": len(wins),
        "win_rate": round(len(wins) / n * 100.0, 1),
        "expectancy_r": round(sum(rs) / n, 3),
        "r_sum": round(sum(rs), 2),
        "profit_factor": (round(sum(wins) / gl, 2) if gl > 0 else None),
        "equity_multiple": (round(eq, 3) if compound else None),
        "max_dd_pct": (round(dd, 2) if compound else None),
        "avg_bars": round(sum(int(t["bars_held"]) for t in closed) / n, 1),
        "avg_net_pct": round(sum(float(t["net_pct"]) for t in closed) / n, 3),
        "avg_stop_pct": round(sum(float(t["stop_dist_pct"]) for t in closed) / n, 3),
        "open_at_end": sum(1 for t in trades if t.get("status") == "open_at_end"),
    }


def _verdict(base: dict, other: dict) -> dict:
    """قاعدهٔ ازپیش‌نوشته: n کافی + تفاوت مثبت + تأیید بیرون‌نمونه + تأیید حالت مستقل."""
    a, b = base.get("all") or {}, other.get("all") or {}
    if a.get("n", 0) < MIN_TRADES_FOR_VERDICT or b.get("n", 0) < MIN_TRADES_FOR_VERDICT:
        return {"code": "need_more", "label": "داده کافی نیست"}
    d = (b.get("expectancy_r") or 0) - (a.get("expectancy_r") or 0)
    oa, ob = base.get("oos") or {}, other.get("oos") or {}
    od = None
    if oa.get("expectancy_r") is not None and ob.get("expectancy_r") is not None:
        od = ob["expectancy_r"] - oa["expectancy_r"]
    ia, ib = base.get("ind_all") or {}, other.get("ind_all") or {}
    idiff = None
    if ia.get("expectancy_r") is not None and ib.get("expectancy_r") is not None:
        idiff = ib["expectancy_r"] - ia["expectancy_r"]
    agree_up = d > 0 and (od is None or od > 0) and (idiff is None or idiff > 0)
    agree_dn = d < 0 and (od is None or od < 0) and (idiff is None or idiff < 0)
    if agree_up:
        lab = "بهتر" if (b.get("expectancy_r") or 0) > 0 else "کم‌ضررتر از پایه (هنوز منفی)"
        return {"code": "better", "label": lab, "delta_r": round(d, 3)}
    if agree_dn:
        lab = "بدتر" if (b.get("expectancy_r") or 0) < 0 else "کم‌سودتر از پایه"
        return {"code": "worse", "label": lab, "delta_r": round(d, 3)}
    return {"code": "mixed", "label": "تفکیک‌نشده", "delta_r": round(d, 3)}


# ══════════════════════════════════════════════════════════════════════════
#  ۵) اجرای مقایسه روی یک یا چند نماد
# ══════════════════════════════════════════════════════════════════════════
def matched_policy(atr_pct: float) -> dict:
    """سیاست «ثابت با همان عرض ATR» — منصفانه‌ترین مقایسهٔ ثابت در برابر شناور.

    چرا لازم است: اگر حد ضرر ثابت ۲٪ باشد و حد ضرر شناور ۰.۷٪، مقایسه در واقع
    «حد ضرر باز در برابر تنگ» است، نه «ثابت در برابر شناور». این سیاست عرض را
    از میانگین ATR همان داده می‌گیرد تا فقط جنسِ قاعده عوض شود.
    """
    # عرض را با همان ضریب موتور (۱.۵×ATR) هم‌عرض می‌کنیم، نه خودِ ATR
    sl = max(round(float(atr_pct) * 1.5, 2), 0.1)
    return {"id": "fixed_matched_2r", "kind": "fixed", "synthetic": True,
            "label": f"ثابت هم‌عرض ATR×۱.۵ ({sl}٪) / ۲R", "sl_pct": sl,
            "tp_pct": round(sl * 2, 2)}


def mean_atr_pct(entries_all: Dict[str, list]) -> Optional[float]:
    vals = []
    for ents in entries_all.values():
        for e in ents:
            atr, px = float(e.get("atr") or 0.0), float(e.get("entry") or 0.0)
            if atr > 0 and px > 0:
                vals.append(atr / px * 100.0)
    if not vals:
        return None
    return sum(vals) / len(vals)


def compare(universe: Dict[str, Sequence[Candle]], cfg,
            policies: Optional[Sequence[dict]] = None,
            exec_universe: Optional[Dict[str, Sequence[Candle]]] = None,
            risk_pct: float = 1.0, oos_frac: float = 0.30,
            verbose: bool = False) -> dict:
    policies = list(policies or POLICIES)
    entries_all: Dict[str, list] = {}
    bars_all: Dict[str, list] = {}
    for sym, cs in universe.items():
        try:
            bars, ents = entry_signals(cs, cfg, (exec_universe or {}).get(sym))
        except Exception as e:                                     # noqa: BLE001
            entries_all[sym], bars_all[sym] = [], []
            print(f"   ⚠️ {sym}: ورودی‌ها محاسبه نشد ({type(e).__name__})")
            continue
        for e in ents:
            e["symbol"] = sym
        entries_all[sym], bars_all[sym] = ents, bars
        if verbose:
            print(f"   · {sym}: {len(cs)} کندل · {len(ents)} ورودی")

    # سیاست هم‌عرض ATR (اگر عرض ATR قابل محاسبه باشد) به فهرست اضافه می‌شود
    mar = mean_atr_pct(entries_all)
    if mar is not None and not any(p.get("synthetic") for p in policies):
        policies = [matched_policy(mar)] + list(policies)

    rows: List[dict] = []
    trades_real: Dict[str, List[dict]] = {}
    trades_ind: Dict[str, List[dict]] = {}
    for pol in policies:
        real: List[dict] = []
        ind: List[dict] = []
        for sym, ents in entries_all.items():
            real.extend(simulate(bars_all[sym], ents, pol, cfg, one_at_a_time=True))
            ind.extend(simulate(bars_all[sym], ents, pol, cfg, one_at_a_time=False))
        trades_real[pol["id"]] = real
        trades_ind[pol["id"]] = ind
        rows.append({"policy": pol,
                     "all": metrics(real, risk_pct, compound=True),
                     "ind_all": metrics(ind, risk_pct, compound=False)})

    # بیرون‌نمونه: ۳۰٪ آخر بر اساس زمان ورود (نه ترتیب)
    all_ts = sorted({int(t["entry_ts"]) for tr in trades_real.values()
                     for t in tr if t.get("status") == "closed"})
    cut = None
    if all_ts:
        t0, t1 = all_ts[0], all_ts[-1]
        cut = t0 + (t1 - t0) * (1.0 - oos_frac)
    for r in rows:
        pid = r["policy"]["id"]
        tr = [t for t in trades_real[pid] if t.get("status") == "closed"]
        oos = [t for t in tr if cut is not None and int(t["entry_ts"]) >= cut]
        r["oos"] = metrics(oos, risk_pct)
        ti = [t for t in trades_ind[pid] if t.get("status") == "closed"]
        oosi = [t for t in ti if cut is not None and int(t["entry_ts"]) >= cut]
        r["ind_oos"] = metrics(oosi, risk_pct, compound=False)
        r["all"]["trades_per_symbol"] = round(r["all"]["n"] / max(len(universe), 1), 1)

    # خط پایه = سیاست شناور سیستم
    base_id = "atr_1.5_3_trail"
    base = next((r for r in rows if r["policy"]["id"] == base_id), rows[0] if rows else None)
    if base:
        for r in rows:
            if r is base:
                r["verdict"] = {"code": "base", "label": "خط پایه (شناور)"}
            else:
                r["verdict"] = _verdict(base, r)
        rows.sort(key=lambda x: -(x["all"].get("expectancy_r") or -99))

    n_entries = sum(len(v) for v in entries_all.values())
    return {
        "version": VERSION,
        "created_utc": time.strftime(TIME_FORMAT, time.gmtime()),
        "symbols": sorted(universe),
        "bars": {s: len(c) for s, c in universe.items()},
        "range": _range(universe),
        "tf": {"trigger": cfg.tf_trigger, "filter": cfg.tf_filter, "bias": cfg.tf_bias},
        "variant_cfg": {"stop_atr_mult": cfg.stop_atr_mult,
                        "take_profit_atr_mult": cfg.take_profit_atr_mult,
                        "trail_atr_mult": cfg.trail_atr_mult,
                        "trail_start_r": cfg.trail_start_r,
                        "fee_bps": cfg.fee_bps,
                        "slippage_pct": cfg.slippage_pct},
        "entries": n_entries,
        "mean_atr_pct": (round(mar, 3) if mar is not None else None),
        "risk_pct": risk_pct,
        "oos_cut_ts": cut,
        "rows": rows,
        "note": ("ورودی‌ها برای همهٔ سیاست‌ها یکسان‌اند؛ هر بار یک پوزیشن، بدون "
                 "کول‌داون/سقف اسلات، تا تفاوت فقط از خروج بیاید."),
    }


def _range(universe: Dict[str, Sequence[Candle]]) -> dict:
    ts = [int(c.open_time_ms) for cs in universe.values() for c in cs[:1]]
    te = [int(c.open_time_ms) for cs in universe.values() for c in cs[-1:]]
    if not ts:
        return {}
    fmt = lambda ms: time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))  # noqa: E731
    return {"start": fmt(min(ts)), "end": fmt(max(te)),
            "days": round((max(te) - min(ts)) / 86400000.0, 1)}


# ══════════════════════════════════════════════════════════════════════════
#  ۶) گزارش متنی
# ══════════════════════════════════════════════════════════════════════════
def render_text(res: dict) -> str:
    rng = res.get("range") or {}
    L = ["# حد ضرر/سود ثابت در برابر شناور (همان ورودی‌ها)", ""]
    L.append(f"داده: {', '.join(res['symbols'])} · {rng.get('start')} → {rng.get('end')}"
             f" ({rng.get('days')} روز) · تایم‌فریم {res['tf']['trigger']}"
             f"/{res['tf']['filter']}/{res['tf']['bias']}")
    L.append(f"نقاط ورود (مشترک بین همه): {res['entries']} · کارمزد "
             f"{res['variant_cfg']['fee_bps']}bps + اسلیپیج "
             f"{res['variant_cfg']['slippage_pct']}٪ هر طرف")
    L.append("")
    L.append("## ۱) واقع‌گرا — هر بار یک پوزیشن (مثل سیستم)")
    L.append("")
    L.append("| سیاست | n | برد | حد ضرر ٪ | expectancy R | جمع R | PF | سرمایه | حداکثر افت | کندل | حکم |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res["rows"]:
        a = r["all"]
        v = r.get("verdict") or {}
        L.append(f"| {r['policy']['label']} | {a['n']} | "
                 f"{a['win_rate'] if a['win_rate'] is not None else '—'}٪ | "
                 f"{a.get('avg_stop_pct') if a.get('avg_stop_pct') is not None else '—'} | "
                 f"{a['expectancy_r'] if a['expectancy_r'] is not None else '—'} | "
                 f"{a.get('r_sum', 0)} | {a.get('profit_factor') if a.get('profit_factor') is not None else '—'} | "
                 f"{a['equity_multiple'] if a['equity_multiple'] is not None else '—'}× | "
                 f"{a['max_dd_pct'] if a['max_dd_pct'] is not None else '—'}٪ | "
                 f"{a['avg_bars'] if a['avg_bars'] is not None else '—'} | "
                 f"{v.get('label', '—')} |")
    L.append("")
    L.append("## ۲) همهٔ ورودی‌ها مستقل (n یکسان برای همه — مقایسهٔ خالص خروج)")
    L.append("")
    L.append("| سیاست | n | برد | حد ضرر ٪ | expectancy R | جمع R | PF |")
    L.append("|---|---|---|---|---|---|---|")
    for r in res["rows"]:
        a = r["ind_all"]
        L.append(f"| {r['policy']['label']} | {a['n']} | "
                 f"{a['win_rate'] if a['win_rate'] is not None else '—'}٪ | "
                 f"{a.get('avg_stop_pct') if a.get('avg_stop_pct') is not None else '—'} | "
                 f"{a['expectancy_r'] if a['expectancy_r'] is not None else '—'} | "
                 f"{a['r_sum']} | {a['profit_factor'] if a['profit_factor'] is not None else '—'} |")
    L.append("")
    L.append("## بیرون‌نمونه (۳۰٪ آخرِ زمان)")
    L.append("")
    L.append("| سیاست | n | برد | expectancy R | جمع R |")
    L.append("|---|---|---|---|---|")
    for r in res["rows"]:
        o = r["oos"]
        L.append(f"| {r['policy']['label']} | {o['n']} | "
                 f"{o['win_rate'] if o['win_rate'] is not None else '—'}٪ | "
                 f"{o['expectancy_r'] if o['expectancy_r'] is not None else '—'} | "
                 f"{o['r_sum']} |")
    L.append("")
    L.append(f"_{res['note']}_")
    L.append("_«حد ضرر ٪» یعنی فاصلهٔ واقعی حد ضرر از قیمت. اگر «ثابت ۱٪» از "
             "«ATR×۱.۵» عدد بزرگ‌تری دارد، آن سیاست عملاً حد ضررِ بازتری گذاشته و "
             "نرخ بردش بالاتر رفتن دلیل برتری نیست._")
    L.append("_حکم فقط با n ≥ ۳۰، تأیید بیرون‌نمونه و تأیید حالت مستقل صادر می‌شود؛ "
             "مقایسهٔ ۷ سیاست روی یک بازه خودش خطر «شانس» دارد._")
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════
#  ۷) CLI
# ══════════════════════════════════════════════════════════════════════════
def _load_cache(data_dir: str, tf: str,
                symbols: Optional[Sequence[str]] = None) -> Dict[str, List[Candle]]:
    from .autoscan import candles_from_json
    jdir = os.path.join(data_dir, "json")
    if not os.path.isdir(jdir):
        return {}
    want = {s.upper() for s in symbols} if symbols else None
    out: Dict[str, List[Candle]] = {}
    for name in sorted(os.listdir(jdir)):
        if not name.endswith(f"_{tf}.json"):
            continue
        sym = name[: -len(f"_{tf}.json")].upper()
        if want and sym not in want:
            continue
        try:
            with open(os.path.join(jdir, name), encoding="utf-8") as f:
                cs = candles_from_json(json.load(f))
        except (OSError, ValueError):
            continue
        if len(cs) >= 300:
            out[sym] = cs
    return out


def _detect_tf(data_dir: str) -> Optional[str]:
    jdir = os.path.join(data_dir, "json")
    if not os.path.isdir(jdir):
        return None
    counts: Dict[str, int] = {}
    for name in os.listdir(jdir):
        if not name.endswith(".json") or "_" not in name:
            continue
        tf = name.rsplit("_", 1)[-1][:-5]
        counts[tf] = counts.get(tf, 0) + 1
    if not counts:
        return None
    # پرتکرارترین تایم‌فریم؛ در تساوی، ریزترین (چون تریگر است و بقیه از آن ساخته می‌شوند)
    def _rank(t: str):
        idx = LADDER.index(t) if t in LADDER else len(LADDER)
        return (counts[t], -idx)
    return max(counts, key=_rank)


def _next_tf(tf: str) -> Optional[str]:
    if tf in LADDER:
        k = LADDER.index(tf)
        return LADDER[min(k + 1, len(LADDER) - 1)]
    return None


def exitstyles_command(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="mtflab exitstyles",
        description="مقایسهٔ حد ضرر/سود ثابت درصدی با شناور (ATR + تریل) روی همان ورودی‌ها")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="auto", help="تایم‌فریم تریگر (auto = از فایل‌ها)")
    p.add_argument("--tf-filter", default="", help="پیش‌فرض: یک پله بالاتر")
    p.add_argument("--tf-bias", default="", help="پیش‌فرض: دو پله بالاتر")
    p.add_argument("--symbols", default="")
    p.add_argument("--variant", default="base")
    p.add_argument("--policies", default="", help="فهرست idها با کاما (پیش‌فرض: همه)")
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--oos-frac", type=float, default=0.30)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tf = args.tf if args.tf != "auto" else (_detect_tf(args.data_dir) or "1h")
    tf_filter = args.tf_filter or (_next_tf(tf) or tf)
    tf_bias = args.tf_bias or (_next_tf(tf_filter) or tf_filter)
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None
    uni = _load_cache(args.data_dir, tf, syms)
    if not uni:
        print(f"❌ داده‌ای در {os.path.join(args.data_dir, 'json')} برای "
              f"تایم‌فریم {tf} پیدا نشد.")
        print("   اول داده دانلود کن: bash run-auto.sh --download --days 365")
        return 2

    from .patterns import variants_for
    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=tf, tf_filter=tf_filter, tf_bias=tf_bias,
                  verbose=False, forensics=False, run_id="", symbol="")
    for vid, _label, ov in variants_for(tf, tf_filter, tf_bias):
        if vid == args.variant:
            cfg = replace(cfg, **{k: v for k, v in (ov or {}).items()
                                  if k in cfg.__dataclass_fields__})
            break

    pols = POLICIES
    if args.policies:
        ids = [x.strip() for x in args.policies.split(",") if x.strip()]
        pols = [policy_by_id(i) for i in ids]

    if args.max_symbols and len(uni) > args.max_symbols:
        uni = dict(sorted(uni.items())[: args.max_symbols])
    print(f"   تایم‌فریم {tf} · {len(uni)} نماد · در حال محاسبهٔ ورودی‌ها …")
    res = compare(uni, cfg, pols, risk_pct=args.risk_pct,
                  oos_frac=args.oos_frac, verbose=True)
    res["variant"] = args.variant
    print(render_text(res))

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    jpath = os.path.join(args.out_dir, f"exit_styles_{tf}_{stamp}.json")
    mpath = os.path.join(args.out_dir, f"exit_styles_{tf}_{stamp}.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(render_text(res) + "\n")
    print(f"\n✅ {mpath}\n✅ {jpath}")
    return 0
