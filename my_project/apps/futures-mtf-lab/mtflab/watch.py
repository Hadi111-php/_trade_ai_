"""شکار زنده — «این نماد الان کجای مسیر سیگنال است و چقدر وزن دارد؟»

## اصل طراحی (مهم)

وزن آمادگی **از همان شرط‌هایی** ساخته می‌شود که موتور واقعاً اجرا می‌کند
(`bias_state` / `filter_state` / `trigger_state` / `decide`). هیچ امتیاز موازی و
ساختگی وجود ندارد؛ اگر امتیاز جداگانه‌ای می‌ساختیم، داشبورد چیزی نشان می‌داد و
موتور چیز دیگری معامله می‌کرد — و آن بدترین نوع دروغ در یک سیستم معاملاتی است.

هر شرط سه چیز دارد: **وزن**، **مقدار فعلی**، **آستانه**. داشبورد همان‌ها را
نشان می‌دهد تا بتوانی ببینی «چرا ۸۵٪ است و نه ۱۰۰٪».

## سه حالت

| حالت | معنی |
|---|---|
| `سیگنال` | موتور الان معامله می‌کند (همهٔ دروازه‌ها پاس) |
| `نزدیک` | وزن ≥ ۷۵٪ **یا** فقط یک شرط مانده |
| `دور` | بقیه |

## هشدار

`alert()` بوق ترمینال + اعلان Termux می‌دهد، با **ضدتکرار**: یک نماد در یک سطح،
حداکثر هر `ALERT_COOLDOWN_MIN` دقیقه یک‌بار اعلام می‌شود. بدون این، هر پیمایش
دوباره بوق می‌زد و در نیم ساعت آدم را دیوانه می‌کرد.

## صداقت زمانی

پیمایش **داخل کندل** (هر ۵ دقیقه) وضعیت تقریبی می‌دهد و در گزارش صریح برچسب
`intra_candle: true` می‌خورد. **تصمیم** همیشه روی کندل بسته گرفته می‌شود؛ این
ماژول تصمیم نمی‌گیرد، فقط نگاه می‌کند.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Sequence

from .config import MTFConfig
from .data import Candle, build_layers, tf_to_minutes
from .alignment import align_multi_timeframe
from .fees import FeeConfig
from .signals import (TFContext, bias_state, decide, filter_state,
                      trigger_state)
from .patterns import variants_for
from .knobs import sanitize_overrides

VERSION = "1.0"

#: وزن هر شرط (جمع = ۱۰۰). وزن‌ها بر اساس «چقدر نزدیک‌بودنش به سیگنال را
#: تعیین می‌کند» انتخاب شده‌اند؛ عدد جادویی نیست، اما **از پیش ثابت** است تا
#: بعداً با دیدن نتیجه عوضش نکنیم.
WEIGHTS: Dict[str, float] = {
    "data": 5.0,        # لایه‌ها دادهٔ بسته دارند
    "bias": 20.0,       # جهت کلان
    "filter": 20.0,     # جهت/رژیم لایهٔ میانی
    "trigger": 25.0,    # خودِ تریگر (نزدیک‌ترین چیز به سیگنال)
    "cost": 12.0,       # نسبت حرکت مورد انتظار به هزینه
    "confidence": 10.0, # امتیاز نهایی
    "climax": 8.0,      # فیلتر «کندل اوج» (نَدویم دنبال قیمت)
}

CHECKS_FA = {
    "data": "دادهٔ لایه‌ها",
    "bias": "هم‌جهتی بایاس (کلان)",
    "filter": "هم‌جهتی فیلتر (میانی)",
    "trigger": "تریگر (نقطهٔ ورود)",
    "cost": "حرکت به‌اندازهٔ هزینه",
    "confidence": "امتیاز اعتماد",
    "climax": "کندل اوج نبودن",
}

NEAR_WEIGHT = 0.75          # آستانهٔ «نزدیک» بر اساس وزن
ALERT_COOLDOWN_MIN = 30     # ضدتکرار اعلان (دقیقه)


# ══════════════════════════════════════════════════════════════════════════
#  ارزیابی یک نماد
# ══════════════════════════════════════════════════════════════════════════
def evaluate_symbol(symbol: str, candles: Sequence[Candle], cfg: MTFConfig,
                    fee: Optional[FeeConfig] = None,
                    intra_candle: bool = False) -> dict:
    """وضعیت یک نماد در آخرین کندل (یا آخرین کندلِ در حال شکل‌گیری).

    خروجی: `readiness` (۰..۱)، `checks` (فهرست با مقدار/آستانه/وزن)،
    `state` (سیگنال/نزدیک/دور)، `missing`، و دلیل مسدودکننده.
    """
    out = {"symbol": symbol, "version": VERSION, "intra_candle": bool(intra_candle),
           "ts": None, "price": None, "readiness": 0.0, "state": "دور",
           "checks": [], "missing": [], "blocking": "", "mode": "",
           "direction": 0, "atr_pct": None}
    t_min = tf_to_minutes(cfg.tf_trigger)
    f_min = tf_to_minutes(cfg.tf_filter)
    b_min = tf_to_minutes(cfg.tf_bias) if cfg.bias_enabled else f_min

    if not candles or len(candles) < 3:
        out["checks"] = _blank_checks("داده کافی نیست")
        out["blocking"] = "داده کافی نیست"
        return out

    try:
        layers = build_layers(candles, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                             bias_enabled=cfg.bias_enabled)
        bars = align_multi_timeframe(
            layers["trigger"], t_min, layers["filter"], f_min,
            layers["bias"] if cfg.bias_enabled else None,
            b_min if cfg.bias_enabled else None)
    except Exception as e:                                     # noqa: BLE001
        out["blocking"] = f"ساخت لایه‌ها: {type(e).__name__}"
        out["checks"] = _blank_checks(out["blocking"])
        return out

    if not bars:
        out["blocking"] = "کندل هم‌ترازشده‌ای نیست"
        out["checks"] = _blank_checks(out["blocking"])
        return out

    ctxs = {
        "trigger": TFContext(layers["trigger"], cfg, "trigger"),
        "filter": TFContext(layers["filter"], cfg, "filter"),
        "bias": (TFContext(layers["bias"], cfg, "bias") if cfg.bias_enabled
                 else TFContext(layers["filter"], cfg, "filter")),
    }
    bar = bars[-1]
    out["ts"] = bar.low_tf_candle.open_time_ms
    out["price"] = round(bar.low_tf_candle.close, 6)

    # هر لایه **اندیس خودش** را دارد: بایاس روزانه ۳۶۵ کندل دارد نه ۲۱۹۰ کندل.
    # (باگ واقعی که همین‌جا گرفته شد: دادن اندیس تریگر به لایهٔ روزانه ⇒ همیشه
    # «رژیم unknown» و وزن ۱۸٪ برای همه.)
    ti = len(ctxs["trigger"].candles) - 1
    fi = len(ctxs["filter"].candles) - 1
    bi = len(ctxs["bias"].candles) - 1

    bias = bias_state(ctxs["bias"], bi, cfg)
    filt = filter_state(ctxs["filter"], fi, cfg)
    trig = trigger_state(ctxs["trigger"], ti, cfg)
    dec = decide(bias, filt, trig, cfg, fee or FeeConfig.from_bps(
        cfg.fee_bps, cfg.slippage_pct))

    # ── شرط‌ها ─────────────────────────────────────────────────────────
    checks: List[dict] = []

    def add(key: str, ok: bool, detail: str, value=None, threshold=None,
            hard: bool = True) -> None:
        checks.append({
            "id": key, "fa": CHECKS_FA.get(key, key), "weight": WEIGHTS.get(key, 0.0),
            "ok": bool(ok), "hard": bool(hard), "detail": detail,
            "value": value, "threshold": threshold,
        })

    # ۱) داده
    have_data = (bias.regime != "unknown") and (filt.regime != "unknown")
    add("data", have_data,
        "هر دو لایهٔ بالا داده دارند" if have_data else "لایهٔ بالا داده ندارد")

    # ۲) بایاس — جهت کلان با جهت تریگر/فیلتر
    ref = trig.direction or filt.direction or 0
    bias_ok = (not cfg.bias_enabled) or (bias.direction != 0
                                         and (ref == 0 or bias.direction == ref))
    add("bias", bias_ok,
        f"رژیم {bias.regime} · جهت {bias.direction:+d}" + (
            "" if cfg.bias_enabled else " (بایاس خاموش)"),
        value=bias.direction, threshold="هم‌جهت")

    # ۳) فیلتر
    filt_ok = filt.direction != 0 and (ref == 0 or filt.direction == ref)
    add("filter", filt_ok,
        f"رژیم {filt.regime} · جهت {filt.direction:+d} · ADX≈"
        f"{_num(ctxs['filter'].adx, fi)}",
        value=filt.direction, threshold="هم‌جهت")

    # ۴) تریگر
    trig_ok = trig.direction != 0
    add("trigger", trig_ok,
        f"{trig.mode or '—'} · {trig.reason[:70]}",
        value=trig.direction, threshold="nonzero")

    # ۵) هزینه — اگر موتور به مرحلهٔ هزینه نرسیده باشد (چون تریگر خنثی است)،
    # خودمان از «حرکت مورد انتظارِ تریگر» حساب می‌کنیم تا این شرط «نامعلوم»
    # نماند. تشخیص، نه تصمیم: تصمیم فقط از decide() می‌آید.
    cc = dict(dec.cost_check or {})
    if not cc:
        try:
            from .fees import (edge_ratio, passes_cost_filter,
                               round_trip_cost_pct)
            _f = fee or FeeConfig.from_bps(cfg.fee_bps, cfg.slippage_pct)
            _exp = float(trig.expected_move_pct or 0.0)
            cc = {"expected_move_pct": round(_exp, 5),
                  "round_trip_cost_pct": round(round_trip_cost_pct(_f), 5),
                  "min_edge_multiplier": cfg.min_edge_multiplier,
                  "edge_ratio": round(edge_ratio(_exp, _f), 3),
                  "passed": passes_cost_filter(_exp, _f, cfg.min_edge_multiplier),
                  "provisional": True}
        except Exception:                                      # noqa: BLE001
            cc = {}
    cost_ok = bool(cc.get("passed", False))
    add("cost", cost_ok,
        f"حرکت {cc.get('expected_move_pct')}٪ ÷ هزینه {cc.get('round_trip_cost_pct')}٪ "
        f"= {cc.get('edge_ratio')}× (حد {cc.get('min_edge_multiplier')}×)",
        value=cc.get("edge_ratio"), threshold=cc.get("min_edge_multiplier"))

    # ۶) اعتماد
    conf_ok = bool(dec.action != "WAIT") or dec.confidence >= cfg.min_confidence
    add("confidence", conf_ok,
        f"اعتماد {dec.confidence:.2f} (حد {cfg.min_confidence})",
        value=round(float(dec.confidence), 4), threshold=cfg.min_confidence)

    # ۷) کندل اوج
    rng_atr = None
    try:
        c = layers["trigger"][ti]
        a = ctxs["trigger"].atr[ti] or 0.0
        if a > 0:
            rng_atr = (c.high - c.low) / a
    except (IndexError, AttributeError, TypeError):
        pass
    climax_ok = (cfg.trigger_max_range_atr <= 0 or rng_atr is None
                 or rng_atr <= cfg.trigger_max_range_atr)
    add("climax", climax_ok,
        f"دامنه {_fmt(rng_atr)}×ATR (حد {cfg.trigger_max_range_atr})",
        value=(None if rng_atr is None else round(float(rng_atr), 4)),
        threshold=cfg.trigger_max_range_atr)

    total = sum(c["weight"] for c in checks) or 1.0
    got = sum(c["weight"] for c in checks if c["ok"])
    readiness = got / total
    hard_missing = [c["id"] for c in checks if c["hard"] and not c["ok"]]

    if dec.action != "WAIT":
        state = "سیگنال"
    elif readiness >= NEAR_WEIGHT or len(hard_missing) == 1:
        state = "نزدیک"
    else:
        state = "دور"

    out.update({
        "readiness": round(readiness, 4),
        "checks": checks,
        "missing": hard_missing,
        "state": state,
        "blocking": ("" if state == "سیگنال" else dec.reason),
        "mode": trig.mode or "",
        "direction": int(trig.direction or dec.direction or 0),
        "atr_pct": _num(ctxs["trigger"].atr_pct, ti),
        "decision": dec.action,
        "confidence": round(float(dec.confidence), 4),
        "adx": _num(ctxs["filter"].adx, fi),
        "bars": {"trigger": len(ctxs["trigger"].candles),
                 "filter": len(ctxs["filter"].candles),
                 "bias": len(ctxs["bias"].candles)},
    })
    return out


def _num(seq, i):
    try:
        v = seq[i]
        return None if v is None else round(float(v), 4)
    except (IndexError, TypeError, ValueError):
        return None


def _fmt(x) -> str:
    return "—" if x is None else f"{x:.2f}"


def _blank_checks(reason: str) -> List[dict]:
    return [{"id": k, "fa": v, "weight": WEIGHTS[k], "ok": False, "hard": True,
             "detail": reason, "value": None, "threshold": None}
            for k, v in CHECKS_FA.items()]


# ══════════════════════════════════════════════════════════════════════════
#  اعلان
# ══════════════════════════════════════════════════════════════════════════
def _termux_notify(title: str, body: str) -> bool:
    """اعلان Termux — اگر `termux-api` نصب نباشد، بی‌صدا رد می‌شود."""
    try:
        subprocess.run(["termux-notification", "--title", title, "--content", body,
                        "--priority", "high"],
                       check=False, timeout=8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


def alert(row: dict, use_beep: bool = True, use_notify: bool = True) -> dict:
    """بوق + اعلان برای یک ردیف «نزدیک»/«سیگنال». ضدتکرار دستِ فراخواننده است."""
    sym = row.get("symbol", "?")
    state = row.get("state", "")
    pct = int(round(float(row.get("readiness") or 0) * 100))
    missing = row.get("missing") or []
    if state == "سیگنال":
        title = f"🎯 سیگنال: {sym}"
        body = f"{sym} آمادهٔ ورود است ({pct}٪) · {row.get('mode') or ''}".strip()
    else:
        title = f"⏳ نزدیک سیگنال: {sym}"
        body = (f"{sym} · {pct}٪" +
                (f" · یک شرط مانده: {_fa_missing(missing)}" if len(missing) == 1
                 else f" · مانده: {_fa_missing(missing)}"))
    sent = {"beep": False, "notify": False}
    if use_beep:
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
            sent["beep"] = True
        except Exception:                                      # noqa: BLE001
            pass
    if use_notify:
        sent["notify"] = _termux_notify(title, body)
    return {"title": title, "body": body, **sent}


def _fa_missing(ids: Sequence[str]) -> str:
    return "، ".join(CHECKS_FA.get(i, i) for i in ids) or "—"


# ══════════════════════════════════════════════════════════════════════════
#  پیمایش
# ══════════════════════════════════════════════════════════════════════════
def scan(universe: Dict[str, Sequence[Candle]], cfg: MTFConfig,
         fee: Optional[FeeConfig] = None, intra_candle: bool = False) -> dict:
    """همهٔ نمادها را می‌سنجد و یک گزارش مرتب‌شده برمی‌گرداند."""
    rows = [evaluate_symbol(s, cs, cfg, fee, intra_candle)
            for s, cs in (universe or {}).items() if cs]
    order = {"سیگنال": 0, "نزدیک": 1, "دور": 2}
    rows.sort(key=lambda r: (order.get(r["state"], 3), -float(r["readiness"] or 0)))
    return {
        "version": VERSION,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "intra_candle": bool(intra_candle),
        "tf": f"{cfg.tf_trigger}/{cfg.tf_filter}/{cfg.tf_bias}",
        "n": len(rows),
        "signals": sum(1 for r in rows if r["state"] == "سیگنال"),
        "near": sum(1 for r in rows if r["state"] == "نزدیک"),
        "rows": rows,
    }


def render(rep: dict, lang: str = "fa") -> str:
    L = ["# شکار زنده — آمادگی سیگنال\n"]
    L.append(f"*{rep['created_utc']}* · تایم‌فریم `{rep['tf']}` · "
             f"{rep['n']} نماد · سیگنال {rep['signals']} · نزدیک {rep['near']}"
             + ("  \n⚠️ داخل کندل (تقریبی)" if rep.get("intra_candle") else ""))
    L.append("")
    L.append("| نماد | قیمت | آمادگی | حالت | مانده |")
    L.append("|---|---:|---:|---|---|")
    for r in rep["rows"]:
        L.append(f"| {r['symbol']} | {r.get('price')} | "
                 f"{int(round(r['readiness'] * 100))}٪ | {r['state']} | "
                 f"{_fa_missing(r['missing'])} |")
    return "\n".join(L)


def watch_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab watch",
        description="شکار زنده: کدام نماد به سیگنال نزدیک است (فقط نگاه)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--variant", default="trend")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--every", type=int, default=300, help="ثانیه بین پیمایش‌ها")
    p.add_argument("--once", action="store_true", help="فقط یک‌بار")
    p.add_argument("--refresh", action="store_true", help="دانلود تازه")
    p.add_argument("--no-beep", action="store_true")
    p.add_argument("--no-notify", action="store_true")
    p.add_argument("--cooldown-min", type=int, default=ALERT_COOLDOWN_MIN)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)

    from .live import _default_symbols
    from .autoscan import fetch_or_load, pick_base_url

    syms = a.symbols or _default_symbols()
    cfg = MTFConfig(tf_trigger=a.tf, tf_filter=a.tf_filter, tf_bias=a.tf_bias)
    for vid, label, ov in variants_for(a.tf, a.tf_filter, a.tf_bias):
        if vid == a.variant:
            clean, _ignored = sanitize_overrides(ov or {})
            for k, v in clean.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            break
    fee = FeeConfig.from_bps(cfg.fee_bps, cfg.slippage_pct)

    out_json = os.path.join(a.out_dir, "watch.json")
    os.makedirs(a.out_dir, exist_ok=True)
    state_path = os.path.join(a.out_dir, ".watch_alerts.json")
    last_alert: Dict[str, float] = {}
    if os.path.exists(state_path):
        try:
            last_alert = json.load(open(state_path, encoding="utf-8"))
        except (OSError, ValueError):
            last_alert = {}

    base = None
    while True:
        universe: Dict[str, List[Candle]] = {}
        if a.refresh or base is None:
            try:
                base = pick_base_url(progress=not a.quiet)
            except Exception:                                  # noqa: BLE001
                base = "https://api.bybit.com"
        for sym in syms:
            try:
                cs, _ = fetch_or_load(sym, a.tf, a.days, a.data_dir, base_url=base,
                                      refresh=a.refresh, progress=False)
                if cs:
                    universe[sym] = cs
            except Exception as e:                             # noqa: BLE001
                if not a.quiet:
                    print(f"  ⚠️ {sym}: {type(e).__name__}")
        if not universe:
            print("❌ هیچ داده‌ای نبود (اول `run-auto.sh --live` یا `--dash` را بزن)")
            return 2

        rep = scan(universe, cfg, fee, intra_candle=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, default=str)

        if not a.quiet:
            print(render(rep))
        now = time.time()
        for r in rep["rows"]:
            if r["state"] not in ("سیگنال", "نزدیک"):
                continue
            key = f"{r['symbol']}:{r['state']}"
            if now - float(last_alert.get(key) or 0) < a.cooldown_min * 60:
                continue
            res = alert(r, use_beep=not a.no_beep, use_notify=not a.no_notify)
            last_alert[key] = now
            print(f"  🔔 {res['title']} — {res['body']}")
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(last_alert, f)
        except OSError:
            pass

        if a.once:
            return 0
        time.sleep(max(20, int(a.every)))
        a.refresh = True          # پیمایش‌های بعدی دادهٔ تازه می‌گیرند
