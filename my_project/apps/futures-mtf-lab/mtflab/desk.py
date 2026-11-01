"""کارگاه اتوترید مجازی — داشبورد وب + آزمایشگاه تنظیمات (PAPER، بدون سفارش).

**چرا این ماژول:** فاز قبل فقط «رصد» بود: الگوریتم قفل، ژورنال، گزارش. ولی رصدِ
بی‌تغییر عملاً هم‌ارز بک‌تست روی داده‌ای است که هنوز نیامده — و رسیدن به نمونهٔ
معنادار سال‌ها طول می‌کشد. این ماژول همان اتوترید را با یک **میز کار** بالا
می‌آورد که سه کار می‌کند:

  ۱) **زنده**: سرمایهٔ مجازی، سیگنال‌های باز، آخرین بستن‌ها و «چرا وارد نشد».
  ۲) **پرونده**: هر سیگنال با تمام جزئیاتش (الگوریتم، الگو، اندیکاتورها، قاعدهٔ بست).
  ۳) **آزمایشگاه**: کاربر می‌تواند تنظیمات را عوض کند و همان‌جا نتیجه را ببیند —
     ولی هر آزمایش با «انگشت‌نگاری»، «شمارهٔ آزمایش روی همین داده» و «بازهٔ
     اطمینان بوت‌استرپ» ذخیره می‌شود تا خوش‌بینیِ ناشی از چندبار آزمودن
     (multiple testing) پنهان نماند.

**صادقانه:** آزادی تغییر پارامتر بدون ثبت تعداد آزمون‌ها، همان دامی است که کل
پروژه را به آن رساند. برای همین هر اجرا سه چیز را کنار نتیجه چاپ می‌کند:
`trial_index` (چندمین آزمایش روی همین داده)، `Δ` با بازهٔ اطمینان ۹۰٪ نسبت به
خط پایه، و نتیجهٔ **بخش بیرون‌نمونه** (۳۰٪ آخرِ بازهٔ زمانی).

اجرا: `python3 -m mtflab live --serve` (یا `bash run-auto.sh --dash`)
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .autoscan import build_layers, candles_from_json, variants_for
from .config import MTFConfig, load_config
from .data import Candle, synthetic_candles
from .engine import run_backtest
from .live import (VETO_FA, cfg_digest, open_positions_from_journal,
                   read_journal, rule_meta, summarize)

LAB_DIR = os.path.join("results", "live_lab")
VERSION = "1.0"

# ══════════════════════════════════════════════════════════════════════════
#  ۱) تنظیماتی که کاربر می‌تواند دست بزند
# ══════════════════════════════════════════════════════════════════════════
# فقط همین کلیدها مجازند. هر کلید بیرون این فهرست نادیده گرفته می‌شود
# (هم امنیتی، هم برای این‌که یک تایپوی ساده کل آزمایش را بی‌معنا نکند).
KNOBS: List[dict] = [
    # ── ریسک و اندازه ────────────────────────────────────────────────────
    dict(k="risk_per_trade_pct", fa="ریسک هر معامله (٪ موجودی)", g="ریسک",
         t="float", lo=0.1, hi=5.0, st=0.1, unit="%",
         note="بزرگ‌تر = سود و ضرر هر دو بزرگ‌تر؛ روی تعداد معامله اثری ندارد."),
    dict(k="max_concurrent", fa="حداکثر پوزیشن هم‌زمان", g="ریسک",
         t="int", lo=1, hi=5, st=1, unit="",
         note="۱ = تک‌پوزیشن. بالا بردنش سیگنال‌های بیشتری را می‌گیرد ولی ریسک را جمع می‌کند."),
    dict(k="daily_loss_limit_pct", fa="سقف ضرر روزانه", g="ریسک",
         t="float", lo=0.0, hi=50.0, st=0.5, unit="%",
         note="۰ = خاموش."),
    dict(k="cb_losses", fa="فیوز: چند ضرر پیاپی", g="ریسک",
         t="int", lo=1, hi=10, st=1, unit="ضرر", note=""),
    dict(k="cb_cooldown_bars", fa="فیوز: چند کندل توقف", g="ریسک",
         t="int", lo=0, hi=100, st=1, unit="کندل", note=""),
    dict(k="cooldown_bars_after_loss", fa="استراحت بعد از هر ضرر", g="ریسک",
         t="int", lo=0, hi=50, st=1, unit="کندل", note=""),
    # ── خروج ─────────────────────────────────────────────────────────────
    dict(k="stop_atr_mult", fa="حد ضرر (×ATR)", g="خروج",
         t="float", lo=0.3, hi=5.0, st=0.1, unit="ATR",
         note="کوچک‌تر = ضرر کمتر ولی استاپ‌خوردن بیشتر (نویز)."),
    dict(k="trail_enabled", fa="تریلینگ استاپ روشن", g="خروج", t="bool", note=""),
    dict(k="trail_atr_mult", fa="فاصلهٔ تریلینگ (×ATR)", g="خروج",
         t="float", lo=0.5, hi=10.0, st=0.5, unit="ATR",
         note="تنگ‌تر = سود زودتر قفل می‌شود و روندهای بزرگ قطع می‌شوند."),
    dict(k="trail_start_r", fa="تریلینگ از چند R", g="خروج",
         t="float", lo=0.0, hi=5.0, st=0.5, unit="R", note=""),
    dict(k="take_profit_atr_mult", fa="حد سود (×ATR)", g="خروج",
         t="float", lo=1.0, hi=60.0, st=1.0, unit="ATR",
         note="۵۰ = عملاً خاموش. با این ساختار «قرعه‌کشی»، حد سود سخت برنده‌ها را می‌کشد."),
    dict(k="breakeven_at_r", fa="انتقال استاپ به سربه‌سر در R", g="خروج",
         t="float", lo=0.0, hi=5.0, st=0.5, unit="R", note="۰ = خاموش."),
    dict(k="partial_take_r", fa="برداشت جزئی در R", g="خروج",
         t="float", lo=0.0, hi=5.0, st=0.5, unit="R", note="۰ = خاموش."),
    dict(k="partial_take_frac", fa="کسر برداشت جزئی", g="خروج",
         t="float", lo=0.1, hi=0.9, st=0.1, unit="", note=""),
    dict(k="max_holding_bars", fa="سقف زمان نگه‌داری", g="خروج",
         t="int", lo=0, hi=200, st=10, unit="کندل", note="۰ = بدون سقف."),
    dict(k="giveback_arm_r", fa="قاعدهٔ افت سود: مسلح‌شدن در R", g="خروج",
         t="float", lo=0.0, hi=10.0, st=0.5, unit="R",
         note="۰ = خاموش. (در آزمون قبلی ۱۰× تنگ‌تر از تریلینگ بود و سود را نابود کرد.)"),
    dict(k="giveback_frac", fa="قاعدهٔ افت سود: کسر اوج", g="خروج",
         t="float", lo=0.0, hi=0.95, st=0.05, unit="", note=""),
    dict(k="regime_change_exit", fa="خروج با چرخش رژیم", g="خروج", t="bool", note=""),
    # ── فیلترها و ورود ───────────────────────────────────────────────────
    dict(k="filter_adx_min", fa="حداقل ADX فیلتر", g="ورود",
         t="float", lo=0.0, hi=50.0, st=1.0, unit="",
         note="۰ = خاموش. بالاتر = فقط روندهای قوی."),
    dict(k="filter_slope_min_pct", fa="حداقل شیب EMA (٪)", g="ورود",
         t="float", lo=0.0, hi=3.0, st=0.05, unit="%", note=""),
    dict(k="min_edge_multiplier", fa="حداقل لبه نسبت به هزینه", g="ورود",
         t="float", lo=0.0, hi=5.0, st=0.25, unit="×",
         note="کمتر از ۱ یعنی سیگنالی که هزینه‌اش را هم درنمی‌آورد رد نمی‌شود."),
    dict(k="min_confidence", fa="حداقل اطمینان تصمیم", g="ورود",
         t="float", lo=0.0, hi=1.0, st=0.05, unit="", note=""),
    dict(k="trigger_max_range_atr", fa="سقف دامنهٔ کندل تریگر (×ATR)", g="ورود",
         t="float", lo=0.0, hi=6.0, st=0.1, unit="ATR",
         note="۰ = خاموش. ۰.۵ = جلوی ورود در کندل‌های انفجاری را می‌گیرد."),
    dict(k="entry_on_next_open", fa="ورود در open کندل بعد", g="ورود", t="bool",
         note="محافظه‌کارانه‌تر (بدون فرض اجرا در close همان کندل)."),
    # ── ساختار ───────────────────────────────────────────────────────────
    dict(k="alignment_version", fa="نسخهٔ هم‌راستایی", g="ساختار", t="choice",
         choices=["A", "B", "C"],
         note="A سخت‌گیر، B امتیازی، C فقط فیلتر رژیم (بیشترین سیگنال)."),
    dict(k="bias_enabled", fa="لایهٔ بایاس روشن", g="ساختار", t="bool", note=""),
    dict(k="trigger_entry_modes", fa="الگوی ورود", g="ساختار", t="modes",
         note="breakout = شکست؛ pullback = بازگشت به میانگین."),
]

KNOB_INDEX = {k["k"]: k for k in KNOBS}


def _coerce(knob: dict, raw) -> Optional[object]:
    """مقدار ورودی کاربر را به نوع درست تبدیل و در بازهٔ مجاز نگه می‌دارد."""
    t = knob["t"]
    try:
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "on", "yes", "بله")
        if t == "int":
            v = int(round(float(raw)))
        elif t == "float":
            v = float(raw)
        elif t == "choice":
            v = str(raw).strip().upper()
            return v if v in knob["choices"] else None
        elif t == "modes":
            if isinstance(raw, str):
                raw = [x for x in raw.replace("،", ",").split(",") if x.strip()]
            out = [str(x).strip() for x in raw if str(x).strip() in ("breakout", "pullback")]
            return sorted(set(out)) or None
        else:
            return None
    except (TypeError, ValueError):
        return None
    if t in ("int", "float"):
        return max(knob["lo"], min(knob["hi"], v))
    return v


def sanitize_overrides(raw: dict) -> Tuple[dict, List[str]]:
    """فقط کلیدهای مجاز؛ بقیه با هشدار برگردانده می‌شوند (نادیده گرفته می‌شوند)."""
    clean, ignored = {}, []
    for k, v in (raw or {}).items():
        knob = KNOB_INDEX.get(k)
        if not knob:
            ignored.append(k)
            continue
        val = _coerce(knob, v)
        if val is not None:
            clean[k] = val
    return clean, ignored


# ══════════════════════════════════════════════════════════════════════════
#  ۲) داده و سنجه‌ها
# ══════════════════════════════════════════════════════════════════════════
def data_fingerprint(universe: Dict[str, Sequence[Candle]]) -> str:
    """انگشت‌نگاری بستهٔ داده: نماد + تعداد + اولین/آخرین کندل."""
    h = hashlib.sha1()
    for sym in sorted(universe):
        cs = universe[sym]
        if not cs:
            continue
        h.update(f"{sym}:{len(cs)}:{cs[0].open_time_ms}:{cs[-1].open_time_ms}".encode())
    return h.hexdigest()[:10]


def load_universe(data_dir: str, tf: str, symbols: Optional[Sequence[str]] = None,
                  demo: bool = False, demo_bars: int = 1500) -> Dict[str, List[Candle]]:
    """کندل‌های کش‌شده (بدون شبکه). `demo=True` فقط برای دیدن ساختار داشبورد."""
    if demo:
        syms = list(symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"])
        return {s: synthetic_candles(tf, demo_bars, seed=31 + i)
                for i, s in enumerate(syms)}
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
        if len(cs) >= 60:
            out[sym] = cs
    return out


def _positions_from_trades(trades: Sequence[dict], candles: Sequence[Candle]) -> List[dict]:
    """لگ‌های بک‌تست را به «پوزیشن» جمع می‌کند (برداشت جزئی یک معامله است، نه دو)."""
    groups: Dict[tuple, List[dict]] = {}
    for t in trades:
        key = (t.get("open_bar"), round(float(t.get("entry") or 0), 8))
        groups.setdefault(key, []).append(t)
    out = []
    for (open_bar, _), legs in groups.items():
        last = legs[-1]
        risk = float(last.get("risk_amount") or 0.0)
        pnl = sum(float(x.get("pnl") or 0.0) for x in legs)
        r = (pnl / risk) if risk > 0 else float(last.get("r_multiple") or 0.0)
        entry_ts = None
        try:
            if 0 <= int(open_bar) < len(candles):
                entry_ts = candles[int(open_bar)].open_time_ms
        except (TypeError, ValueError):
            entry_ts = None
        out.append({
            "symbol": last.get("symbol") or "",
            "entry_ts": entry_ts,
            "exit_ts": last.get("ts"),
            "mode": last.get("trigger_mode") or "?",
            "rule": last.get("reason") or "?",
            "pnl": round(pnl, 4),
            "r": round(r, 4),
            "bars": int(last.get("bars_held") or 0),
            "is_win": pnl > 0,
        })
    out.sort(key=lambda x: (x.get("exit_ts") or 0))
    return out


def metrics(rows: Sequence[dict], initial_equity: float = 1000.0) -> dict:
    """سنجه‌های اصلی از فهرست پوزیشن‌ها."""
    n = len(rows)
    if not n:
        return {"n": 0, "win_rate": None, "expectancy_r": None, "pnl": 0.0,
                "profit_factor": None, "max_dd_pct": None, "avg_win": None,
                "avg_loss": None, "median_bars": None, "r_sum": 0.0}
    rs = [float(x["r"]) for x in rows]
    pnls = [float(x["pnl"]) for x in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    eq = initial_equity
    peak, maxdd = eq, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, (eq - peak) / peak * 100.0)
    bars = sorted(int(x["bars"]) for x in rows)
    return {
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "expectancy_r": round(sum(rs) / n, 4),
        "r_sum": round(sum(rs), 3),
        "pnl": round(sum(pnls), 2),
        "profit_factor": round(gross_w / gross_l, 3) if gross_l > 0 else None,
        "max_dd_pct": round(maxdd, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "median_bars": bars[len(bars) // 2] if bars else None,
        "equity": round(eq, 2),
    }


def breakdown(rows: Sequence[dict], key: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for x in rows:
        k = str(x.get(key) or "?")
        d = out.setdefault(k, {"n": 0, "r_sum": 0.0, "pnl": 0.0, "wins": 0})
        d["n"] += 1
        d["r_sum"] += float(x["r"])
        d["pnl"] += float(x["pnl"])
        d["wins"] += 1 if x["is_win"] else 0
    for d in out.values():
        d["expectancy_r"] = round(d["r_sum"] / d["n"], 4) if d["n"] else None
        d["win_rate"] = round(d["wins"] / d["n"], 4) if d["n"] else None
        d["pnl"] = round(d["pnl"], 2)
    return out


def rule_breakdown(rows: Sequence[dict]) -> Dict[str, dict]:
    out = breakdown(rows, "rule")
    for k in list(out):
        meta = rule_meta(k)
        out[k]["fa"] = meta["fa"]
        out[k]["is_risk_control"] = meta["is_risk_control"]
    return out


# ══════════════════════════════════════════════════════════════════════════
#  ۳) آزمایشگاه: اجرا، ثبت، مقایسه با خط پایه
# ══════════════════════════════════════════════════════════════════════════
class Lab:
    """مغز داشبورد: داده، اجرای آزمایش، ثبت آزمایش‌ها، و پروندهٔ سیگنال‌ها."""

    def __init__(self, data_dir: str = "data", tf: str = "4h", tf_filter: str = "1d",
                 tf_bias: str = "1d", variant: str = "trend",
                 state_path: str = "results/live/state.json",
                 journal_path: str = "results/live/journal.jsonl",
                 lab_dir: str = LAB_DIR, demo: bool = False,
                 demo_bars: int = 1500, symbols: Optional[Sequence[str]] = None,
                 report_dir: str = "results"):
        self.data_dir = data_dir
        self.tf, self.tf_filter, self.tf_bias = tf, tf_filter, tf_bias
        self.variant = variant
        self.state_path = state_path
        self.journal_path = journal_path
        self.lab_dir = lab_dir
        self.report_dir = report_dir
        self.brain_model_path = os.path.join(report_dir, "brain_model.json")
        self._views_cache: tuple = (0.0, None)
        self.demo = demo
        self.demo_bars = demo_bars
        self.symbols_filter = list(symbols) if symbols else None
        self._universe: Optional[Dict[str, List[Candle]]] = None
        self._baselines: Dict[str, dict] = {}
        self._lock = threading.Lock()
        os.makedirs(self.lab_dir, exist_ok=True)

    # -- داده -------------------------------------------------------------
    def universe(self, reload: bool = False) -> Dict[str, List[Candle]]:
        if self._universe is None or reload:
            self._universe = load_universe(self.data_dir, self.tf, self.symbols_filter,
                                           demo=self.demo, demo_bars=self.demo_bars)
        return self._universe

    @property
    def data_fp(self) -> str:
        return data_fingerprint(self.universe())

    def variant_def(self) -> Tuple[str, str, dict]:
        by_id = {v[0]: v for v in variants_for(self.tf, self.tf_filter, self.tf_bias)}
        if self.variant not in by_id:
            self.variant = "trend" if "trend" in by_id else next(iter(by_id))
        return by_id[self.variant]

    def base_cfg(self, overrides: Optional[dict] = None) -> MTFConfig:
        cfg = load_config(["--data", "synthetic", "--quiet"])
        cfg = replace(cfg, tf_trigger=self.tf, tf_filter=self.tf_filter,
                      tf_bias=self.tf_bias, verbose=False, forensics=False,
                      run_id="", symbol="")
        cfg = replace(cfg, **self.variant_def()[2])
        if overrides:
            cfg = replace(cfg, **overrides)
        return cfg

    # -- اجرای یک آزمایش ---------------------------------------------------
    def evaluate(self, overrides: Optional[dict] = None,
                 symbols: Optional[Sequence[str]] = None,
                 oos_frac: float = 0.30) -> dict:
        uni = self.universe()
        if not uni:
            raise RuntimeError("هیچ داده‌ای در کش نیست — اول `bash run-auto.sh --live` "
                               "یا دانلود داده را اجرا کن")
        syms = [s for s in (symbols or list(uni)) if s in uni]
        if not syms:
            raise RuntimeError("نماد انتخاب‌شده داده ندارد")
        cfg = self.base_cfg(overrides)
        rows: List[dict] = []
        errors: List[str] = []
        for sym in syms:
            cs = uni[sym]
            try:
                layers = build_layers(cs, self.tf, self.tf_filter, self.tf_bias,
                                      bias_enabled=cfg.bias_enabled)
                res = run_backtest(replace(cfg, symbol=sym), layers)
                rows.extend(_positions_from_trades(res["trades"], layers["trigger"]))
            except Exception as e:                                  # noqa: BLE001
                errors.append(f"{sym}: {str(e)[:60]}")
        # پوزیشن‌هایی که آخرِ داده باز مانده‌اند، «بسته‌شده» نیستند: سودشان
        # تحقق نیافته و اگر بمانند، هر پارامتری که در انتها لانگ باشد پاداش
        # می‌گیرد. پس از سنجه‌ها بیرون می‌مانند و فقط شمرده می‌شوند.
        open_at_end = sum(1 for x in rows if x["rule"] == "end_of_data")
        rows = [x for x in rows if x["rule"] != "end_of_data"]

        # بخش‌بندی زمانی: ۳۰٪ آخرِ بازه = بیرون‌نمونه
        stamps = [c.open_time_ms for cs in (uni[s] for s in syms) for c in cs]
        t0, t1 = (min(stamps), max(stamps)) if stamps else (0, 0)
        cut = t0 + (t1 - t0) * (1.0 - oos_frac)
        ins = [x for x in rows if (x.get("entry_ts") or 0) < cut]
        oos = [x for x in rows if (x.get("entry_ts") or 0) >= cut]
        m = metrics(rows, cfg.initial_equity)
        m["open_at_end"] = open_at_end
        return {
            "digest": cfg_digest(overrides or {}),
            "overrides": dict(overrides or {}),
            "variant": self.variant,
            "symbols": syms,
            "n_bars": sum(len(uni[s]) for s in syms),
            "span": [t0, t1],
            "cut_ts": int(cut),
            "metrics": m,
            "in_sample": metrics(ins, cfg.initial_equity),
            "out_of_sample": metrics(oos, cfg.initial_equity),
            "by_rule": rule_breakdown(rows),
            "by_pattern": breakdown(rows, "mode"),
            "by_symbol": breakdown(rows, "symbol"),
            "trades": rows,
            "errors": errors,
        }

    def baseline(self, reload: bool = False) -> dict:
        """خط پایه = همان الگوریتم زنده، **بدون** هیچ تغییر تنظیمی."""
        fp = self.data_fp
        if not reload and fp in self._baselines:
            return self._baselines[fp]
        path = os.path.join(self.lab_dir, f"baseline_{fp}.json")
        if not reload and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self._baselines[fp] = data
                return data
            except (OSError, ValueError):
                pass
        ev = self.evaluate({})
        slim = {k: v for k, v in ev.items() if k != "trades"}
        slim["r_list"] = [x["r"] for x in ev["trades"]]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=1)
        self._baselines[fp] = slim
        return slim

    # -- ثبت آزمایش --------------------------------------------------------
    def _index_path(self) -> str:
        return os.path.join(self.lab_dir, "runs.json")

    def runs(self) -> List[dict]:
        path = self._index_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def run_experiment(self, overrides: Optional[dict] = None,
                       label: str = "", gate: Optional[dict] = None,
                       symbols: Optional[Sequence[str]] = None) -> dict:
        with self._lock:
            clean, ignored = sanitize_overrides(overrides or {})
            fp = self.data_fp
            prev = [r for r in self.runs() if r.get("data_fp") == fp]
            trial_index = len(prev) + 1
            ev = self.evaluate(clean, symbols=symbols)
            base = self.baseline() if clean else None

            delta = None
            if base and clean:
                from .evolve import bootstrap_ci
                delta = bootstrap_ci([x["r"] for x in ev["trades"]],
                                     list(base.get("r_list") or []),
                                     level=0.90, sims=800)

            gate = dict(gate or {})
            verdict = self._verdict(ev, gate)
            rid = f"{time.strftime('%Y%m%d_%H%M%S')}_{ev['digest']}"
            rec = {
                "run_id": rid,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "label": (label or "").strip()[:200],
                "digest": ev["digest"],
                "data_fp": fp,
                "trial_index": trial_index,
                "trial_warning": _trial_warning(trial_index),
                "variant": ev["variant"],
                "overrides": ev["overrides"],
                "ignored_keys": ignored,
                "symbols": ev["symbols"],
                "n_bars": ev["n_bars"],
                "span": ev["span"],
                "cut_ts": ev["cut_ts"],
                "metrics": ev["metrics"],
                "in_sample": ev["in_sample"],
                "out_of_sample": ev["out_of_sample"],
                "by_rule": ev["by_rule"],
                "by_pattern": ev["by_pattern"],
                "by_symbol": ev["by_symbol"],
                "delta_vs_baseline": delta,
                "gate": gate,
                "verdict": verdict,
                "errors": ev["errors"],
                "trades": ev["trades"],
            }
            path = os.path.join(self.lab_dir, "runs", f"{rid}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1, default=str)
            idx = self.runs()
            idx.append({k: rec[k] for k in ("run_id", "created", "label", "digest",
                                            "data_fp", "trial_index", "variant",
                                            "overrides", "metrics", "out_of_sample",
                                            "verdict", "delta_vs_baseline")})
            with open(self._index_path(), "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False, indent=1, default=str)
            return rec

    @staticmethod
    def _verdict(ev: dict, gate: dict) -> dict:
        """دروازه‌ای که کاربر **قبل از** دیدن نتیجه نوشته — نه بعدش."""
        checks = []
        m = ev["metrics"]
        oos = ev["out_of_sample"]
        if "min_expectancy_r" in gate and gate["min_expectancy_r"] is not None:
            need = float(gate["min_expectancy_r"])
            got = m.get("expectancy_r")
            checks.append({"fa": f"expectancy ≥ {need:+.2f}R",
                           "got": got, "ok": got is not None and got >= need})
        if "min_trades" in gate and gate["min_trades"] is not None:
            need = int(gate["min_trades"])
            checks.append({"fa": f"حداقل {need} معامله", "got": m["n"],
                           "ok": m["n"] >= need})
        if gate.get("require_oos_positive"):
            got = oos.get("expectancy_r")
            checks.append({"fa": "بخش بیرون‌نمونه مثبت باشد", "got": got,
                           "ok": got is not None and got > 0})
        if gate.get("require_ci_excludes_zero") and ev.get("delta_vs_baseline"):
            d = ev["delta_vs_baseline"]
            checks.append({"fa": "Δ نسبت به خط پایه معنادار باشد",
                           "got": d.get("ci"), "ok": bool(d.get("significant"))})
        passed = bool(checks) and all(c["ok"] for c in checks)
        return {"checks": checks, "passed": passed,
                "note": ("✅ همهٔ شرط‌های ازپیش‌نوشته پاس شد" if passed else
                         "❌ دروازه پاس نشد" if checks else "— دروازه‌ای تعیین نشد")}

    def run_detail(self, run_id: str) -> Optional[dict]:
        path = os.path.join(self.lab_dir, "runs", f"{os.path.basename(run_id)}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # -- نمای زنده و پروندهٔ سیگنال‌ها --------------------------------------
    def overview(self) -> dict:
        from .live import load_state
        st = load_state(self.state_path)
        jr = read_journal(self.journal_path)
        rep = summarize(jr)
        rep["open_positions"] = open_positions_from_journal(jr, st)
        rep["vetoes"] = ((st.get("engine") or {}).get("veto_stats") or {})
        uni = self.universe()
        return {
            "version": VERSION,
            "demo": self.demo,
            "now": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data_fp": self.data_fp if uni else None,
            "symbols_cached": sorted(uni),
            "bars": {s: len(cs) for s, cs in uni.items()},
            "last_bar_ts": {s: cs[-1].open_time_ms for s, cs in uni.items() if cs},
            "variant": self.variant,
            "state": st,
            "report": rep,
            "veto_labels": VETO_FA,
            "runs": len(self.runs()),
            "tf": f"{self.tf}/{self.tf_filter}/{self.tf_bias}",
        }

    def signals(self, symbol: str = "", rule: str = "", only_risk: bool = False,
                status: str = "", limit: int = 300) -> List[dict]:
        jr = read_journal(self.journal_path)
        opens = {r.get("id"): r for r in jr if r.get("type") == "open"}
        closes = {r.get("open_id"): r for r in jr if r.get("type") == "close"}
        out = []
        for sid, o in opens.items():
            c = closes.get(sid) or {}
            ep = o.get("entry_pattern") or {}
            cb = c.get("closed_by") or {}
            res = c.get("result") or {}
            card = {
                "id": sid,
                "symbol": o.get("symbol"),
                "ts": o.get("ts"),
                "backfilled": bool(o.get("backfilled")),
                "algorithm": (o.get("algorithm") or {}).get("id"),
                "digest": (o.get("algorithm") or {}).get("cfg_digest"),
                "mode": ep.get("mode"),
                "regime": ep.get("regime_filter"),
                "trigger_reason": ep.get("trigger_reason"),
                "decision_reason": ep.get("decision_reason"),
                "confidence": ep.get("confidence"),
                "entry": (o.get("order") or {}).get("entry"),
                "stop": (o.get("order") or {}).get("stop"),
                "status": "closed" if c else "open",
                "rule": cb.get("rule"),
                "is_risk_control": cb.get("is_risk_control"),
                "rule_fa": cb.get("fa"),
                "exit": res.get("exit"),
                "pnl": res.get("pnl"),
                "r": res.get("r_multiple"),
                "bars": res.get("bars_held"),
                "raw_open": o,
                "raw_close": c or None,
            }
            if symbol and str(card["symbol"] or "").upper() != symbol.upper():
                continue
            if rule and str(card["rule"] or "") != rule:
                continue
            if only_risk and not card["is_risk_control"]:
                continue
            if status and card["status"] != status:
                continue
            out.append(card)
        out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
        return out[:max(1, min(int(limit or 300), 2000))]

    def brain_report(self) -> dict:
        """آخرین گزارش «مغز دوم» (اگر ساخته شده باشد)."""
        path = os.path.join(self.report_dir, "brain_report.json")
        if not os.path.exists(path):
            return {"available": False,
                    "hint": "bash run-auto.sh --brain"}
        try:
            with open(path, encoding="utf-8") as f:
                rep = json.load(f)
            rep["available"] = True
            return rep
        except (OSError, ValueError):
            return {"available": False, "hint": "گزارش خوانده نشد"}

    def brain_views(self, max_age: int = 60) -> dict:
        """دیدگاه مغز روی آخرین کندل بستهٔ هر نماد — برای «قبل از سیگنال».

        فقط نمایش است؛ هیچ تصمیمی از این‌جا خوانده نمی‌شود. نتیجه ۶۰ ثانیه
        کش می‌شود تا رفرش‌های پشت‌سرهم گوشی را داغ نکند.
        """
        ts, cached = self._views_cache
        if cached is not None and time.time() - ts < max_age:
            return cached
        from .brainview import model_digest
        from .observer import BrainObserver
        obs = BrainObserver(self.brain_model_path, self.base_cfg({}))
        if not obs.available:
            out = {"available": False, "hint": "bash run-auto.sh --brain-view --train",
                   "model_path": self.brain_model_path}
        else:
            views = obs.views_now(self.universe())
            m = obs.model or {}
            out = {"available": True,
                   "model": {"version": m.get("version"),
                             "trained_through_ts": m.get("trained_through_ts"),
                             "trained_utc": m.get("trained_utc"),
                             "digest": model_digest(m),
                             "oof": m.get("oof"), "w": m.get("w"),
                             "features": m.get("features")},
                   "views": views,
                   "note": "فقط مشاهده — تصمیم ورود/خروج هیچ‌جا از این‌جا خوانده نمی‌شود."}
        self._views_cache = (time.time(), out)
        return out

    def schema(self) -> dict:
        cfg = self.base_cfg({})
        base_vals = {k["k"]: getattr(cfg, k["k"], None) for k in KNOBS}
        vid, label, overrides = self.variant_def()
        return {
            "knobs": KNOBS,
            "baseline_values": base_vals,
            "variant": {"id": vid, "label": label, "overrides": overrides},
            "variants": [{"id": v[0], "label": v[1]} for v in
                         variants_for(self.tf, self.tf_filter, self.tf_bias)],
            "symbols": sorted(self.universe()),
            "data_fp": self.data_fp,
            "gate_defaults": {"min_expectancy_r": 0.0, "min_trades": 100,
                              "require_oos_positive": True,
                              "require_ci_excludes_zero": False},
        }


def _trial_warning(k: int) -> str:
    """چندمین آزمایش روی همین داده — و هزینهٔ آماری‌اش."""
    if k <= 1:
        return "اولین آزمایش روی این داده."
    p = 1 - 0.95 ** k
    return (f"این {k}امین آزمایش روی همین داده است. اگر هر آزمایش را ۵٪ خطا فرض "
            f"کنیم، احتمال این‌که دست‌کم یکی «شانسی» خوب به نظر برسد ≈ {p * 100:.0f}٪. "
            f"پس بهبود کوچک را باور نکن؛ به بازهٔ اطمینان و بخش بیرون‌نمونه نگاه کن.")


# ══════════════════════════════════════════════════════════════════════════
#  ۴) قدم زنده (همان مسیر `mtflab live`، از داخل داشبورد)
# ══════════════════════════════════════════════════════════════════════════
def run_step(lab: "Lab", min_gap: int = 20) -> dict:
    """یک قدمِ اتوترید مجازی: کندل تازه → سیگنال تازه → گزارش. (شبکه)

    `min_gap` جلوی فشار دادن دکمه پشت‌سرهم را می‌گیرد (خودِ کش هم بیشترِ
    درخواست‌ها را حذف می‌کند، ولی این‌جا صریح‌تر است).
    """
    if lab.demo:
        return {"ok": False, "note": "حالت نمایشی: داده مصنوعی است، قدم زنده ندارد"}
    now = time.time()
    if now - getattr(lab, "_last_step", 0.0) < min_gap:
        return {"ok": False, "note": f"کمتر از {min_gap} ثانیه از قدم قبلی گذشته"}
    lab._last_step = now
    from .live import live_command
    argv = ["--variant", lab.variant, "--tf", lab.tf,
            "--tf-filter", lab.tf_filter, "--tf-bias", lab.tf_bias,
            "--data-dir", lab.data_dir, "--state", lab.state_path,
            "--journal", lab.journal_path, "--lang", "fa"]
    if lab.symbols_filter:
        argv += ["--symbols"] + list(lab.symbols_filter)
    rc = live_command(argv)
    lab.universe(reload=True)
    return {"ok": rc == 0, "rc": rc}


def start_auto(lab: "Lab", every: int, logger=print) -> threading.Thread:
    """حلقهٔ پس‌زمینه: هر `every` ثانیه یک قدم زنده."""
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                r = run_step(lab, min_gap=0)
                logger(f"⏱ step: {r}")
            except Exception as e:                                  # noqa: BLE001
                logger(f"⚠️ step failed: {e}")
            stop.wait(max(60, int(every)))

    t = threading.Thread(target=loop, daemon=True, name="lab-auto")
    t.start()
    return t
