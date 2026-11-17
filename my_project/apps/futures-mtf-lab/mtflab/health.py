"""سلامت سیستم — «کار می‌کند، ولی هنوز سیگنالی نیست» را با عدد ثابت کن.

**چرا این ماژول:** کاربر گفت وقتی سیگنالی نیست باید بتواند مطمئن شود سیستم
*درست کار می‌کند* و فقط شرط‌ها برقرار نیستند. «هیچ خبری نیست» پاسخ بدی است،
چون از «خراب است» قابل تفکیک نیست. این‌جا چهار سؤال با عدد جواب داده می‌شود:

  ۱) **ساعت کندل**: آخرین کندل بسته کِی بود و کندل بعدی کِی بسته می‌شود؟
  ۲) **تازگی داده**: دادهٔ محلی چند کندل عقب است؟ (کهنه ⇒ اصلاً تصمیم نمی‌گیریم)
  ۳) **گرم‌کردن (warmup)**: هر لایه چند کندل لازم دارد و چند تا دارد؟ (نبودِ
     تاریخ کافی، شبیه «سیگنال ندادن» به نظر می‌رسد ولی چیز دیگری است)
  ۴) **دروازه‌ها**: کدام شرط‌ها پاس شدند و کدام یکی جلوی سیگنال را گرفت؟

هیچ عددی این‌جا از خودمان ساخته نمی‌شود: دروازه‌ها از همان `watch.evaluate_symbol`
می‌آیند که خودش `bias_state`/`filter_state`/`trigger_state`/`decide` موتور را
صدا می‌زند. اگر این دو از هم جدا می‌شدند، داشبورد چیزی می‌گفت و موتور چیز دیگری
معامله می‌کرد.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Sequence

from .config import MTFConfig
from .data import Candle, tf_to_ms

VERSION = 1
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _utc(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    return time.strftime(TIME_FORMAT, time.gmtime(int(ms) / 1000.0))


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ساعت کندل
# ══════════════════════════════════════════════════════════════════════════
def candle_clock(tf: str, now_ms: Optional[int] = None) -> dict:
    """آخرین کندل بسته / کندل در حال شکل‌گیری / زمان بسته شدن بعدی.

    تعریف‌ها (مهم، چون یک‌بار اشتباه گرفتنشان باعث «سیگنال دیر» می‌شود):
      • `last_closed_open_ms`: زمان **باز شدن** آخرین کندلِ بسته.
      • `last_closed_close_ms`: همان کندل، لحظهٔ **بسته شدن** (= باز شدن کندل جاری).
      • `next_close_ms`: لحظه‌ای که کندل جاری بسته می‌شود و ارزیابی تازه ممکن است.
    """
    step = tf_to_ms(tf)
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    forming_open = now - (now % step)
    last_open = forming_open - step
    next_close = forming_open + step
    return {
        "tf": tf,
        "step_minutes": step // 60000,
        "now_ms": now,
        "now_utc": _utc(now),
        "forming_open_ms": forming_open,
        "last_closed_open_ms": last_open,
        "last_closed_close_ms": forming_open,
        "last_closed_utc": _utc(last_open),
        "next_close_ms": next_close,
        "next_close_utc": _utc(next_close),
        "seconds_to_next": max(0, int((next_close - now) // 1000)),
        "note": ("تصمیم فقط روی کندل بسته گرفته می‌شود؛ کندل جاری هر چه هم "
                 "جذاب باشد، تا بسته نشدنش سیگنال نمی‌دهد."),
    }


# ══════════════════════════════════════════════════════════════════════════
#  ۲) گرم‌کردن (warmup) هر لایه
# ══════════════════════════════════════════════════════════════════════════
def warmup_status(candles: Sequence[Candle], cfg: MTFConfig) -> dict:
    """هر لایه چند کندل لازم دارد و چند تا دارد؟ (بدون حدس زدن)"""
    from .data import build_layers

    need_trigger = max(int(cfg.trigger_ema_period), int(cfg.trigger_atr_period) + 1,
                       int(cfg.trigger_rsi_period) + 1,
                       int(cfg.trigger_donchian_window),
                       int(cfg.trigger_vol_window), 30)
    need_filter = max(int(cfg.filter_ema_period), int(cfg.filter_ema_fast_period),
                      2 * int(cfg.filter_adx_period), 30)
    need_bias = max(int(cfg.bias_ema_period), int(cfg.bias_donchian_window),
                    int(cfg.bias_slope_bars) + 2)

    layers = build_layers(candles, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                          bias_enabled=cfg.bias_enabled)
    rows = [{"layer": "trigger", "tf": cfg.tf_trigger, "need": need_trigger,
             "have": len(layers["trigger"])},
            {"layer": "filter", "tf": cfg.tf_filter, "need": need_filter,
             "have": len(layers["filter"])}]
    if cfg.bias_enabled:
        rows.append({"layer": "bias", "tf": cfg.tf_bias, "need": need_bias,
                     "have": len(layers["bias"])})
    else:
        rows.append({"layer": "bias", "tf": cfg.tf_bias, "need": 0, "have": 0,
                     "off": True})
    for r in rows:
        r["ready"] = bool(r.get("off")) or r["have"] >= r["need"]
        r["shortfall"] = max(0, int(r["need"]) - int(r["have"]))
    return {"rows": rows, "ok": all(r["ready"] for r in rows),
            "missing": [r for r in rows if not r["ready"]]}


# ══════════════════════════════════════════════════════════════════════════
#  ۳) وضعیت یک نماد: تازگی داده + دروازه‌ها
# ══════════════════════════════════════════════════════════════════════════
def symbol_status(symbol: str, candles: Sequence[Candle], cfg: MTFConfig,
                  clock: dict, last_bar_ms: Optional[int] = None) -> dict:
    from . import watch

    step = tf_to_ms(cfg.tf_trigger)
    out: dict = {"symbol": symbol, "bars": len(candles or []),
                 "last_candle_ms": (int(candles[-1].open_time_ms) if candles else None),
                 "last_candle_utc": (_utc(candles[-1].open_time_ms) if candles else None),
                 "fresh": False, "behind_bars": None, "warmup_ok": None,
                 "state": "—", "readiness": None, "blocking": "داده نیست",
                 "direction": 0, "mode": "", "price": None, "gates": [],
                 "pending_bars": 0}
    if not candles:
        return out

    expected = int(clock["last_closed_open_ms"])
    out["behind_bars"] = int(max(0, (expected - out["last_candle_ms"]) // step))
    out["fresh"] = out["behind_bars"] == 0

    wu = warmup_status(candles, cfg)
    out["warmup_ok"] = bool(wu["ok"])
    out["warmup_missing"] = [r["layer"] for r in wu["missing"]]

    if last_bar_ms:
        out["pending_bars"] = sum(1 for c in candles
                                  if int(c.open_time_ms) > int(last_bar_ms))

    try:
        w = watch.evaluate_symbol(symbol, candles, cfg)
        out.update({"state": w.get("state"), "readiness": w.get("readiness"),
                    "blocking": w.get("blocking") or "",
                    "direction": w.get("direction") or 0,
                    "mode": w.get("mode") or "",
                    "price": w.get("price"),
                    "gates": [{"id": c.get("id"), "label": c.get("fa"),
                               "ok": bool(c.get("ok")), "detail": c.get("detail"),
                               "weight": c.get("weight")}
                              for c in (w.get("checks") or [])]})
    except Exception as e:                                     # noqa: BLE001
        out["blocking"] = f"ارزیابی دروازه‌ها خطا داد: {type(e).__name__}"
    return out


# ══════════════════════════════════════════════════════════════════════════
#  ۴) حکم کلی
# ══════════════════════════════════════════════════════════════════════════
def verdict(rows: Sequence[dict], warmup: dict, clock: dict) -> dict:
    """چرا سیگنالی نیست؟ — با اولویت: داده → تازگی → warmup → شرط‌ها."""
    if not rows:
        return {"code": "no_data", "label": "دادهٔ محلی نیست",
                "detail": "از تب «مدیریت کلان» داده را دانلود کن."}
    if not any(r["bars"] for r in rows):
        return {"code": "no_data", "label": "دادهٔ محلی نیست",
                "detail": "فایل کش خالی است — اول دانلود/به‌روزرسانی."}
    if not any(r["fresh"] for r in rows):
        worst = max((r.get("behind_bars") or 0) for r in rows)
        return {"code": "stale", "label": "داده کهنه است",
                "detail": (f"آخرین کندل {worst} کندل عقب‌تر از «{clock['last_closed_utc']}» "
                           "است؛ تا تازه نشود تصمیمی گرفته نمی‌شود.")}
    if not warmup.get("ok"):
        miss = warmup.get("missing") or []
        bits = "، ".join(f"{m['layer']} ({m['have']}/{m['need']} کندل {m['tf']})"
                         for m in miss)
        return {"code": "warmup", "label": "تاریخ کافی نیست (warmup ناقص)",
                "detail": f"{bits} — سیستم درست است، ولی هنوز دادهٔ کافی برای این لایه‌ها ندارد."}
    if any(r.get("state") == "سیگنال" for r in rows):
        syms = [r["symbol"] for r in rows if r.get("state") == "سیگنال"]
        return {"code": "signal", "label": "سیگنال آماده است",
                "detail": "شرط‌ها روی {0} برقرار است.".format("، ".join(syms))}
    near = [r for r in rows if r.get("state") == "نزدیک"]
    if near:
        return {"code": "idle_near", "label": "سالم است؛ نزدیک سیگنال",
                "detail": (f"{len(near)} نماد نزدیک است (آمادگی "
                           f"{max((r.get('readiness') or 0) for r in near) * 100:.0f}٪). "
                           f"ارزیابی بعدی: {clock['next_close_utc']}")}
    return {"code": "idle", "label": "سالم است؛ منتظر کندل بعدی",
            "detail": (f"همهٔ لایه‌ها آماده‌اند و دروازه‌ها کار می‌کنند، ولی شرط ورود "
                       f"برقرار نیست. ارزیابی بعدی: {clock['next_close_utc']}")}


# ══════════════════════════════════════════════════════════════════════════
#  ۵) وضعیت کامل
# ══════════════════════════════════════════════════════════════════════════
def _read_state(state_path: Optional[str], state: Optional[dict]) -> dict:
    if state:
        return state
    if not state_path or not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _journal_summary(journal_path: Optional[str], journal: Optional[Sequence[dict]]) -> dict:
    rows = list(journal or [])
    if not rows and journal_path and os.path.exists(journal_path):
        with open(journal_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    opens = [r for r in rows if r.get("type") == "open"]
    closes = [r for r in rows if r.get("type") == "close"]
    last_ts = None
    for r in rows:
        t = r.get("ts") or (r.get("exit_candle") or {}).get("ts")
        if t and (last_ts is None or int(t) > last_ts):
            last_ts = int(t)
    return {"records": len(rows), "opens": len(opens), "closes": len(closes),
            "last_record_ms": last_ts, "last_record_utc": _utc(last_ts)}


def system_health(universe: Dict[str, Sequence[Candle]], cfg: MTFConfig,
                  state: Optional[dict] = None,
                  state_path: Optional[str] = None,
                  journal_path: Optional[str] = None,
                  journal: Optional[Sequence[dict]] = None,
                  now_ms: Optional[int] = None) -> dict:
    clock = candle_clock(cfg.tf_trigger, now_ms)
    st = _read_state(state_path, state)
    sym_state = (st.get("symbols") or {}) if isinstance(st, dict) else {}

    rows: List[dict] = []
    warm: dict = {"ok": False, "rows": [], "missing": []}
    for sym, cs in sorted((universe or {}).items()):
        last_ms = (sym_state.get(sym) or {}).get("last_bar_ms")
        rows.append(symbol_status(sym, cs, cfg, clock, last_ms))
    if rows and universe:
        # گرم‌کردن را از کم‌تاریخ‌ترین نماد گزارش می‌کنیم (بدترین حالت)
        worst = min((universe[s] for s in universe if universe[s]), key=len, default=None)
        if worst:
            warm = warmup_status(worst, cfg)

    v = verdict(rows, warm, clock)
    hb = {
        "last_processed": {s: (sym_state.get(s) or {}).get("last_bar_ms")
                           for s in (sym_state or {})},
        "variant": (st.get("variant") if isinstance(st, dict) else None),
        "equity": (st.get("equity") if isinstance(st, dict) else None),
        "updated_utc": (st.get("updated_utc") if isinstance(st, dict) else None),
    }
    return {
        "version": VERSION,
        "created_utc": _utc(clock["now_ms"]),
        "clock": clock,
        "tf": {"trigger": cfg.tf_trigger, "filter": cfg.tf_filter, "bias": cfg.tf_bias},
        "warmup": warm,
        "rows": rows,
        "journal": _journal_summary(journal_path, journal),
        "heartbeat": hb,
        "verdict": v,
        "note": ("«سیگنالی نیست» با «خراب است» یکی نیست: این‌جا می‌بینی داده تازه "
                 "است، لایه‌ها آماده‌اند و فقط شرط ورود برقرار نیست."),
    }


def render_text(h: dict) -> str:
    c = h["clock"]
    v = h["verdict"]
    L = ["# سلامت سیستم", ""]
    L.append(f"**{v['label']}** — {v['detail']}")
    L.append("")
    L.append(f"کندل {c['tf']} · آخرین کندل بسته: {c['last_closed_utc']} · "
             f"بسته شدن بعدی: {c['next_close_utc']} "
             f"(تا {c['seconds_to_next'] // 60} دقیقهٔ دیگر)")
    L.append("")
    if h["rows"]:
        L.append("| نماد | کندل | آخرین کندل | عقب‌بودن | وضعیت | آمادگی | مانع |")
        L.append("|---|---|---|---|---|---|---|")
        for r in h["rows"]:
            L.append(f"| {r['symbol']} | {r['bars']} | {r.get('last_candle_utc') or '—'} | "
                     f"{r.get('behind_bars')} | {r.get('state')} | "
                     f"{(round((r.get('readiness') or 0) * 100))}٪ | "
                     f"{r.get('blocking') or '—'} |")
        L.append("")
    if h["warmup"].get("rows"):
        L.append("## گرم‌کردن لایه‌ها")
        for w in h["warmup"]["rows"]:
            mark = "✅" if w["ready"] else "❌"
            L.append(f"- {mark} {w['layer']} ({w['tf']}): {w['have']} از {w['need']} کندل"
                     + (" — خاموش" if w.get("off") else ""))
        L.append("")
    j = h["journal"]
    L.append(f"ژورنال: {j['opens']} ورود · {j['closes']} خروج · آخرین رکورد: "
             f"{j['last_record_utc'] or '—'}")
    L.append("")
    L.append(f"_{h['note']}_")
    return "\n".join(L)


def health_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from dataclasses import replace

    from .config import load_config
    from .desk import load_universe

    p = argparse.ArgumentParser(prog="mtflab health",
                                description="سلامت سیستم: چرا سیگنالی نیست؟")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--symbols", default="")
    p.add_argument("--state", default="results/live/state.json")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--json", action="store_true")
    p.add_argument("--lang", choices=["fa", "en"], default="fa",
                   help="پذیرفته می‌شود تا run-auto --lang رد نشود؛ خروجی فارسی می‌ماند")
    a = p.parse_args(argv)

    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=a.tf, tf_filter=a.tf_filter, tf_bias=a.tf_bias,
                  verbose=False, forensics=False, run_id="", symbol="")
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or None
    uni = load_universe(a.data_dir, a.tf, syms)
    if not uni:
        print(f"❌ داده‌ای در {a.data_dir}/json برای {a.tf} نیست — "
              "bash run-auto.sh --ops --download")
        return 2
    h = system_health(uni, cfg, state_path=a.state, journal_path=a.journal)
    if a.json:
        print(json.dumps(h, ensure_ascii=False, indent=2))
    else:
        print(render_text(h))
    return 0
