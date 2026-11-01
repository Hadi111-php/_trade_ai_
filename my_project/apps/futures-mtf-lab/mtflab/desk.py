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
from .knobs import (KNOB_INDEX, KNOBS, _coerce,   # noqa: F401,E402
                   sanitize_overrides)


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


from .stats import (breakdown, metrics,                # noqa: F401,E402
                   positions_from_trades as _positions_from_trades,
                   rule_breakdown)


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

    def variant_defs(self) -> List[Tuple[str, str, dict]]:
        """همهٔ تیم‌ها/الگوها روی همین تایم‌فریم (برای انتخاب در داشبورد)."""
        return list(variants_for(self.tf, self.tf_filter, self.tf_bias))

    def variant_def(self, variant: Optional[str] = None) -> Tuple[str, str, dict]:
        by_id = {v[0]: v for v in self.variant_defs()}
        vid = variant or self.variant
        if vid not in by_id:
            vid = self.variant if self.variant in by_id else next(iter(by_id))
        return by_id[vid]

    def base_cfg(self, overrides: Optional[dict] = None,
                 variant: Optional[str] = None) -> MTFConfig:
        cfg = load_config(["--data", "synthetic", "--quiet"])
        cfg = replace(cfg, tf_trigger=self.tf, tf_filter=self.tf_filter,
                      tf_bias=self.tf_bias, verbose=False, forensics=False,
                      run_id="", symbol="")
        cfg = replace(cfg, **self.variant_def(variant)[2])
        if overrides:
            cfg = replace(cfg, **overrides)
        return cfg

    # -- اجرای یک آزمایش ---------------------------------------------------
    def evaluate(self, overrides: Optional[dict] = None,
                 symbols: Optional[Sequence[str]] = None,
                 oos_frac: float = 0.30,
                 variant: Optional[str] = None) -> dict:
        uni = self.universe()
        if not uni:
            raise RuntimeError("هیچ داده‌ای در کش نیست — اول `bash run-auto.sh --live` "
                               "یا دانلود داده را اجرا کن")
        syms = [s for s in (symbols or list(uni)) if s in uni]
        if not syms:
            raise RuntimeError("نماد انتخاب‌شده داده ندارد")
        vid, vlabel, _vov = self.variant_def(variant)
        cfg = self.base_cfg(overrides, variant)
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
            "variant": vid,
            "variant_label": vlabel,
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

    def baseline(self, reload: bool = False, variant: Optional[str] = None) -> dict:
        """خط پایه = همان **تیم** با تنظیمات دست‌نخورده.

        خط پایه به‌ازای هر تیم جداست: مقایسهٔ «تیم pullback با تنظیم تازه» در
        برابر «خط پایهٔ trend» بی‌معنا بود — دو چیز مختلف را می‌سنجید.
        """
        fp = self.data_fp
        vid = self.variant_def(variant)[0]
        key = f"{fp}__{vid}"
        if not reload and key in self._baselines:
            return self._baselines[key]
        path = os.path.join(self.lab_dir, f"baseline_{fp}__{vid}.json")
        if not reload and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self._baselines[key] = data
                return data
            except (OSError, ValueError):
                pass
        ev = self.evaluate({}, variant=vid)
        slim = {k: v for k, v in ev.items() if k != "trades"}
        slim["r_list"] = [x["r"] for x in ev["trades"]]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=1)
        self._baselines[key] = slim
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
                       symbols: Optional[Sequence[str]] = None,
                       variant: Optional[str] = None) -> dict:
        with self._lock:
            clean, ignored = sanitize_overrides(overrides or {})
            vid = self.variant_def(variant)[0]
            fp = self.data_fp
            prev = [r for r in self.runs() if r.get("data_fp") == fp]
            trial_index = len(prev) + 1
            ev = self.evaluate(clean, symbols=symbols, variant=vid)
            base = self.baseline(variant=vid) if clean else None

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
                "variant_label": ev["variant_label"],
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
                                            "variant_label",
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

    # -- تیم‌ها: همان موتور + یک دستهٔ تنظیماتِ نام‌دار ----------------------
    def teams_path(self) -> str:
        return os.path.join(self.lab_dir, "teams.json")

    def teams(self) -> List[dict]:
        """تیم‌های ذخیره‌شده (فقط تنظیمات؛ هیچ منطق تازه‌ای اضافه نمی‌کنند)."""
        path = self.teams_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def save_team(self, name: str, overrides: Optional[dict] = None,
                  variant: Optional[str] = None, note: str = "") -> dict:
        """ذخیرهٔ تنظیمات فعلی به‌عنوان یک «تیم» نام‌دار.

        چرا لازم است: بدون آن، هر بار باید ده knob را دستی برگردانی. اما تیم
        **اعتبار آماری ندارد** — فقط یک اسم برای یک دستهٔ تنظیمات است؛ هر اجرا
        باز هم شمارهٔ آزمایش و Δ با خط پایهٔ همان تیم را ثبت می‌کند.
        """
        nm = (name or "").strip()[:60]
        if not nm:
            raise ValueError("اسم تیم خالی است")
        vid, vlabel, _ = self.variant_def(variant)
        clean, ignored = sanitize_overrides(overrides or {})
        rec = {
            "id": f"team_{time.strftime('%Y%m%d_%H%M%S')}_{cfg_digest(clean)[:6]}",
            "name": nm,
            "note": (note or "").strip()[:200],
            "variant": vid,
            "variant_label": vlabel,
            "overrides": clean,
            "ignored_keys": ignored,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data_fp": self.data_fp if self.universe() else None,
        }
        items = self.teams()
        items.append(rec)
        with open(self.teams_path(), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        return rec

    def delete_team(self, team_id: str) -> bool:
        items = self.teams()
        keep = [t for t in items if t.get("id") != team_id]
        if len(keep) == len(items):
            return False
        with open(self.teams_path(), "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False, indent=1)
        return True

    # -- تنظیمات نمایشی مغز ------------------------------------------------
    def brain_settings_path(self) -> str:
        return os.path.join(self.report_dir, "brain_settings.json")

    def brain_settings(self) -> dict:
        """آستانه‌های برچسبِ دیدگاه. **فقط نمایش**؛ هیچ معامله‌ای از آن خوانده نمی‌شود."""
        out = {"long_th": 0.55, "short_th": 0.45}
        path = self.brain_settings_path()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                out.update({k: float(raw[k]) for k in ("long_th", "short_th")
                            if raw.get(k) is not None})
            except (OSError, ValueError, TypeError):
                pass
        out["long_th"] = min(0.95, max(0.505, out["long_th"]))
        out["short_th"] = min(0.495, max(0.05, out["short_th"]))
        return out

    def save_brain_settings(self, long_th, short_th) -> dict:
        try:
            lo = min(0.95, max(0.505, float(long_th)))
            sh = min(0.495, max(0.05, float(short_th)))
        except (TypeError, ValueError):
            raise ValueError("آستانه باید عدد باشد")
        path = self.brain_settings_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"long_th": lo, "short_th": sh}, f, ensure_ascii=False, indent=1)
        self._views_cache = (0.0, None)
        return self.brain_settings()

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
            st = self.brain_settings()
            from .brainview import lean_label
            for v in views.values():
                if not isinstance(v, dict) or v.get("p_up") is None:
                    continue
                v["lean_model"] = v.get("lean")
                v["lean"] = lean_label(float(v["p_up"]), st["long_th"], st["short_th"])
            m = obs.model or {}
            out = {"available": True,
                   "settings": st,
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
        variants = []
        for v_id, v_label, v_ov in self.variant_defs():
            vcfg = self.base_cfg({}, v_id)
            variants.append({
                "id": v_id,
                "label": v_label,
                "overrides": v_ov,
                "values": {k["k"]: getattr(vcfg, k["k"], None) for k in KNOBS},
            })
        return {
            "knobs": KNOBS,
            "baseline_values": base_vals,
            "variant": {"id": vid, "label": label, "overrides": overrides},
            "variants": variants,
            "teams": self.teams(),
            "brain_settings": self.brain_settings(),
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
def run_step(lab: "Lab", min_gap: int = 20, quiet: bool = False) -> dict:
    """یک قدمِ اتوترید مجازی: کندل تازه → سیگنال تازه → گزارش. (شبکه)

    `min_gap` جلوی فشار دادن دکمه پشت‌سرهم را می‌گیرد (خودِ کش هم بیشترِ
    درخواست‌ها را حذف می‌کند، ولی این‌جا صریح‌تر است).
    `quiet` جدول را در ترمینال چاپ نمی‌کند — داشبورد همان داده را نشان می‌دهد و
    ریختن یک صفحه markdown روی پیام‌های سرور فقط کاربر را گم می‌کند.
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
    if quiet:
        argv.append("--quiet")
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
