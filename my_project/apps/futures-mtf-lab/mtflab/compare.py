"""مقایسهٔ سناریوی قدیم (TraderBrain) و جدید (MTF) روی **داده و هزینهٔ یکسان**.

این ماژول تنها نقطهٔ تماس دو اپ است و کاملاً **یک‌طرفه و فقط‌خواندنی** است:
- سناریوی قدیم را با `sys.path` ضمیمه و import می‌کند.
- هیچ فایلی از `apps/futures-scalp-lab` را تغییر نمی‌دهد (فقط خروجی‌های
  JSONL خودش را در پوشهٔ results همان اپ می‌نویسد، مثل همیشه).
- دو مدل هزینه اجرا می‌شود:
    * `normalized`  → کارمزد/اسلیپیج/ریسک/تعداد معاملهٔ همزمان یکسان
    * `native`      → هر سناریو با تنظیمات پیش‌فرض خودش
  ستون «normalized» تنها مبنای معتبر مقایسهٔ «منطق استراتژی» است.

علاوه بر KPI، یک **آزمون بوت‌استرپ روی اختلاف expectancy** انجام می‌شود تا
مشخص شود تفاوت دو سناریو از نظر آماری معنادار است یا نه (با n کوچک، تقریباً
همیشه معنادار نیست — و گفتنِ همین، صادقانه‌ترین بخش گزارش است).
"""
from __future__ import annotations

import io
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from . import __version__
from .config import MTFConfig, load_config
from .engine import run_from_config
from .validation import full_validation

OLD_APP_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "futures-scalp-lab"))


# ----------------------------------------------------------------------------
# دسترسی به سناریوی قدیم (فقط‌خواندنی)
# ----------------------------------------------------------------------------
def _import_old():
    if not os.path.isdir(OLD_APP_DIR):
        raise RuntimeError(f"اپ سناریوی قدیم پیدا نشد: {OLD_APP_DIR}")
    if OLD_APP_DIR not in sys.path:
        sys.path.insert(0, OLD_APP_DIR)
    import scalplab  # noqa: F401
    from scalplab import trader_brain
    from scalplab.data import csv_candles as old_csv_candles
    return trader_brain, old_csv_candles


def old_available() -> bool:
    try:
        _import_old()
        return True
    except Exception:                                   # noqa: BLE001
        return False


# ----------------------------------------------------------------------------
# اجرای سناریوی قدیم
# ----------------------------------------------------------------------------
def run_old(csv_path: str, symbol: str, cost_model: str, out_dir: str,
            run_id: str) -> dict:
    """اجرای TraderBrain روی همان CSV (بدون تغییر در کد قدیم)."""
    trader_brain, _ = _import_old()
    TraderConfig = trader_brain.TraderConfig

    if cost_model == "normalized":
        cfg = TraderConfig(
            symbol=symbol, data_mode="csv", timeframe="60", csv_path=csv_path,
            out_dir=out_dir, run_id=run_id,
            initial_equity=1000.0, fixed_risk=0.0, risk_per_trade_pct=1.0,
            fee_bps=5.5, slippage_pct=0.02,               # ← هم‌تراز با MTF
            max_leverage=5.0, take_profit_rr=2.0, stop_atr_mult=1.5,
            trail_atr_mult=2.0, trail_start_profit_pct=0.008,
            max_concurrent=1,                             # ← هم‌تراز با MTF
            daily_loss_limit_pct=5.0, cb_losses=3, cooldown_bars=4,
            entry_mode="both", range_breakout=True, range_breakout_vol_min=2.0,
            regime_change_exit=True,
        )
    else:                                                 # native (پیش‌فرض خودش)
        cfg = TraderConfig(
            symbol=symbol, data_mode="csv", timeframe="60", csv_path=csv_path,
            out_dir=out_dir, run_id=run_id,
            initial_equity=1000.0, fixed_risk=10.0, risk_per_trade_pct=1.0,
            fee_bps=4.0, slippage_pct=0.05,
            max_leverage=5.0, take_profit_rr=2.0, stop_atr_mult=1.5,
            trail_atr_mult=2.0, trail_start_profit_pct=0.008,
            max_concurrent=3, daily_loss_limit_pct=10.0, cb_losses=2, cooldown_bars=5,
            entry_mode="both", range_breakout=True, range_breakout_vol_min=2.0,
            regime_change_exit=True,
        )

    buf = io.StringIO()
    t0 = time.time()
    old_stdout = sys.stdout
    try:
        sys.stdout = buf
        code = trader_brain.run_trader(cfg)          # کل لاگ چاپی مهار می‌شود
    finally:
        sys.stdout = old_stdout
    elapsed = time.time() - t0

    tpath = os.path.join(out_dir, f"trader_trades_{run_id}.jsonl")
    trades_raw: List[dict] = []
    if os.path.exists(tpath):
        with open(tpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "close":
                    trades_raw.append(d)

    rpath = os.path.join(out_dir, f"trader_report_{run_id}.json")
    summary_raw = {}
    if os.path.exists(rpath):
        with open(rpath, encoding="utf-8") as f:
            summary_raw = json.load(f).get("summary", {})

    trades = [_norm_old_trade(t) for t in trades_raw]
    summary = {
        "trades": summary_raw.get("trades", len(trades)),
        "wins": summary_raw.get("wins", sum(1 for t in trades if t["pnl"] > 0)),
        "losses": summary_raw.get("losses", sum(1 for t in trades if t["pnl"] <= 0)),
        "win_rate": summary_raw.get("win_rate", _wr(trades)),
        "profit_factor": summary_raw.get("profit_factor", _pf(trades)),
        "expectancy": summary_raw.get("expectancy", _mean([t["pnl"] for t in trades])),
        "total_pnl": summary_raw.get("total_pnl", round(sum(t["pnl"] for t in trades), 3)),
        "equity": summary_raw.get("equity", round(1000.0 + sum(t["pnl"] for t in trades), 3)),
        "return_pct": summary_raw.get("return_pct"),
        "max_drawdown_pct": _mdd(trades, 1000.0),
        "total_fees": round(sum(t.get("fees", 0.0) for t in trades), 3),
        "avg_bars_held": round(_mean([t.get("bars_held", 0) for t in trades]), 2),
        "veto_stats": {},
    }
    if summary["return_pct"] is None:
        summary["return_pct"] = round(summary["total_pnl"] / 1000.0 * 100, 4)

    return {
        "summary": summary,
        "trades": trades,
        "equity_curve": _curve_from_trades(trades, 1000.0),
        "label": "بازپخش CSV واقعی — PAPER (TraderBrain، تک‌تایم‌فریم)",
        "elapsed_s": round(elapsed, 2),
        "config_used": {k: v for k, v in cfg.to_dict().items()
                        if k in ("fee_bps", "slippage_pct", "fixed_risk", "risk_per_trade_pct",
                                 "max_concurrent", "take_profit_rr", "stop_atr_mult",
                                 "cb_losses", "cooldown_bars", "daily_loss_limit_pct",
                                 "entry_mode")},
        "exit_code": code,
        "log_tail": buf.getvalue().strip().splitlines()[-3:],
    }


def _norm_old_trade(t: dict) -> dict:
    notional = float(t.get("notional") or 0.0)
    gross = (t.get("gross_pct") or 0.0) / 100.0 * notional
    pnl = float(t.get("pnl") or 0.0)
    return {
        "ts": int(t.get("ts") or 0),
        "side": int(t.get("side") or 0),
        "entry": t.get("entry"), "exit": t.get("exit"),
        "pnl": round(pnl, 4),
        "gross_pnl": round(gross, 4),
        "fees": round(gross - pnl, 4),
        "is_win": bool(t.get("is_win")),
        "reason": str(t.get("reason") or "—"),
        "regime": str(t.get("regime_entry") or "—"),
        "trigger_mode": str(t.get("reason_entry") or "—")[:48],
        "bars_held": int(t.get("bars_held") or 0),
        "notional": notional,
        "r_multiple": round(pnl / t["risk_amount"], 4) if t.get("risk_amount") else 0.0,
        "mfe_pct": t.get("mfe_pct"), "mae_pct": t.get("mae_pct"),
        "diagnosis": str(t.get("diagnosis") or "")[:160],
    }


# ----------------------------------------------------------------------------
# اجرای سناریوی جدید
# ----------------------------------------------------------------------------
def run_new(csv_path: str, symbol: str, cost_model: str, out_dir: str,
            run_id: str, tf: Tuple[str, str, str] = ("1h", "4h", "1d"),
            version: str = "A", validate: bool = False,
            extra: Optional[List[str]] = None) -> dict:
    argv = ["--data", "csv", "--csv", csv_path, "--symbol", symbol,
            "--tf-trigger", tf[0], "--tf-filter", tf[1], "--tf-bias", tf[2],
            "--alignment", version, "--out", out_dir, "--run-id", run_id,
            "--quiet"]
    if cost_model == "normalized":
        argv += ["--fee-bps", "5.5", "--slippage-pct", "0.02",
                 "--risk-pct", "1.0", "--fixed-risk", "0", "--max-concurrent", "1",
                 "--cb-losses", "3", "--cooldown", "4", "--daily-loss", "5.0"]
    else:
        argv += ["--fee-bps", "5.5", "--slippage-pct", "0.02"]   # پیش‌فرض خودِ MTF
    # warmup: اگر بایاس روی 1d باشد و دادهٔ کمی داشته باشیم، EMA200 در ۱ سال
    # داده جا نمی‌شود و نیمی از بازه «بدون لایهٔ بایاس» می‌ماند. برای حالت
    # «دادهٔ یکسان» دورهٔ EMA را متناسب می‌کنیم (شفاف و قابل تغییر با CLI).
    if tf[2] in ("1d", "1D") and "--bias-ema" not in argv:
        argv += ["--bias-ema", "50"]
    if extra:
        argv += list(extra)

    cfg = load_config(argv)
    cfg.forensics = False
    cfg.validate = bool(validate)
    t0 = time.time()
    res = run_from_config(cfg)
    elapsed = time.time() - t0

    trades = []
    for t in res["trades"]:
        d = dict(t)
        d.setdefault("regime", d.get("regime_filter_entry", d.get("regime_entry", "—")))
        d.setdefault("trigger_mode", d.get("trigger_mode", "—"))
        d["diagnosis"] = str(d.get("diagnosis", ""))[:160]
        d.pop("path_candles", None)
        trades.append(d)

    summary = dict(res["summary"])
    summary["total_fees"] = round(sum(t.get("fees", 0.0) for t in trades), 4)
    return {
        "summary": summary,
        "trades": trades,
        "equity_curve": _curve_from_trades(trades, cfg.initial_equity),
        "health": res["health"],
        "meta": res["meta"],
        "label": cfg.label(),
        "elapsed_s": round(elapsed, 2),
        "config_used": {k: v for k, v in cfg.to_dict().items()
                        if k in ("fee_bps", "slippage_pct", "fixed_risk", "risk_per_trade_pct",
                                 "max_concurrent", "stop_atr_mult", "take_profit_atr_mult",
                                 "cb_losses", "cooldown_bars_after_loss", "daily_loss_limit_pct",
                                 "tf_trigger", "tf_filter", "tf_bias", "alignment_version")},
        "validation": res.get("validation"),
        "_cfg": cfg,
        "_res": res,
    }


# ----------------------------------------------------------------------------
# آمار کمکی
# ----------------------------------------------------------------------------
def _mean(v: Sequence[float]) -> float:
    return round(sum(v) / len(v), 4) if v else 0.0


def _wr(trades: Sequence[dict]) -> float:
    return round(sum(1 for t in trades if t["pnl"] > 0) / len(trades), 4) if trades else 0.0


def _pf(trades: Sequence[dict]) -> Optional[float]:
    gw = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    if gl == 0:
        return None if gw > 0 else 0.0
    return round(gw / gl, 4)


def _mdd(trades: Sequence[dict], initial: float) -> float:
    eq, peak, mdd = initial, initial, 0.0
    for t in sorted(trades, key=lambda x: x.get("ts", 0)):
        eq += t.get("pnl", 0.0)
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, (eq - peak) / peak * 100.0)
    return round(mdd, 4)


def _curve_from_trades(trades: Sequence[dict], initial: float) -> List[dict]:
    out, eq = [], initial
    for t in sorted(trades, key=lambda x: x.get("ts", 0)):
        eq += t.get("pnl", 0.0)
        out.append({"ts": t.get("ts", 0), "equity": round(eq, 4)})
    return out


def bootstrap_diff(a: Sequence[float], b: Sequence[float], sims: int = 2000,
                   seed: int = 2026) -> dict:
    """آزمون بوت‌استرپ روی اختلاف میانگین (expectancy) دو گروه معامله.

    فرض صفر: هر دو نمونه از یک توزیع‌اند. اگر بازهٔ اطمینان ۹۵٪ اختلاف، صفر را
    دربر بگیرد → «تفاوت معنادار نیست» و حق نداریم بگوییم یکی بهتر است.
    """
    if len(a) < 5 or len(b) < 5:
        return {"ok": False, "note": "نمونهٔ کافی برای آزمون معناداری نیست (<5 معامله)"}
    rng = random.Random(seed)
    diffs = []
    for _ in range(sims):
        ma = sum(a[rng.randrange(len(a))] for _ in range(len(a))) / len(a)
        mb = sum(b[rng.randrange(len(b))] for _ in range(len(b))) / len(b)
        diffs.append(ma - mb)
    diffs.sort()

    def q(p):
        return round(diffs[min(len(diffs) - 1, max(0, int(p * (len(diffs) - 1))))], 4)

    observed = round(sum(a) / len(a) - sum(b) / len(b), 4)
    p_b_better = round(sum(1 for d in diffs if d < 0) / len(diffs), 4)
    ci = (q(0.025), q(0.975))
    significant = not (ci[0] <= 0 <= ci[1])
    return {
        "ok": True, "sims": sims,
        "observed_diff": observed,
        "ci95": [ci[0], ci[1]],
        "p_a_better": round(1 - p_b_better, 4),
        "p_b_better": p_b_better,
        "significant": bool(significant),
        "note": ("✅ تفاوت از نظر آماری معنادار است (CI شامل صفر نیست)" if significant else
                 "⚠️ تفاوت معنادار نیست — با این تعداد معامله نمی‌توان گفت کدام بهتر است"),
    }


# ----------------------------------------------------------------------------
# ساخت payload داشبورد
# ----------------------------------------------------------------------------
def _verdict(old_norm: dict, new_norm: dict, diff: dict, old_native: dict,
             new_native: dict) -> dict:
    so, sn = old_norm["summary"], new_norm["summary"]

    def val(d, k):
        v = d.get(k)
        return v if isinstance(v, (int, float)) else 0.0

    crit = [
        ("Expectancy ($/معامله)", val(so, "expectancy"), val(sn, "expectancy"), True),
        ("Profit Factor", val(so, "profit_factor"), val(sn, "profit_factor"), True),
        ("بازده (%)", val(so, "return_pct"), val(sn, "return_pct"), True),
        ("Max Drawdown (%)", abs(val(so, "max_drawdown_pct")),
         abs(val(sn, "max_drawdown_pct")), False),
    ]
    rows, new_wins, old_wins = [], 0, 0
    for name, a, b, high_good in crit:
        if high_good:
            new_better = b > a
        else:
            new_better = b < a
        if abs(a - b) < 1e-9:
            winner = "مساوی"
        elif new_better:
            winner, new_wins = "🟢 جدید", new_wins + 1
        else:
            winner, old_wins = "🟣 قدیم", old_wins + 1
        rows.append([name, f"{a:+,.2f}", f"{b:+,.2f}", winner])

    if new_wins > old_wins:
        winner = "new"
    elif old_wins > new_wins:
        winner = "old"
    else:
        winner = "tie"

    both_unprofitable = (val(so, "profit_factor") or 0) < 1.0 and (val(sn, "profit_factor") or 0) < 1.0
    parts = []
    parts.append(f"در مقایسهٔ عادلانه (هزینه/ریسک یکسان)، <b>سناریوی "
                 f"{'جدید' if winner == 'new' else 'قدیم' if winner == 'old' else 'ها'}</b> "
                 f"در {max(new_wins, old_wins) if winner != 'tie' else 0} از {len(crit)} "
                 f"معیار برنده شد.")
    parts.append(f"expectancy: قدیم {so.get('expectancy'):+.3f}$ در برابر جدید "
                 f"{sn.get('expectancy'):+.3f}$ (اختلاف {diff.get('observed_diff', 0):+.3f}$).")
    if diff.get("ok"):
        parts.append(f"آزمون بوت‌استرپ: {diff['note']} "
                     f"(CI95 اختلاف: [{diff['ci95'][0]:+.3f}, {diff['ci95'][1]:+.3f}]).")
    if both_unprofitable:
        parts.append("<br><b>نتیجهٔ مهم:</b> هر دو سناریو در این بازه PF زیر ۱ دارند — "
                     "یعنی هیچ‌کدام روی این دادهٔ واقعی edge اثبات‌شده ندارند. "
                     "پس «کدام بهتر است» فعلاً یعنی «کدام کمتر ضرر می‌دهد»، نه «کدام سودآور است».")
    if new_wins > old_wins and both_unprofitable:
        parts.append(" ارزش واقعی لایه‌های MTF اینجا در <b>کاهش تعداد معامله و کنترل ضرر</b> است، "
                     "نه ساخت سود؛ برای اثبات سود باید روی دادهٔ 15m/4h دانلودشده و بازهٔ "
                     "بزرگ‌تر (چند سال) اجرا شود.")
    parts.append(f"<br>ستون «پیش‌فرض خودش»: قدیم {old_native['summary'].get('expectancy', 0):+.3f}$ "
                 f"({old_native['summary'].get('trades', 0)} معامله) · "
                 f"جدید {new_native['summary'].get('expectancy', 0):+.3f}$ "
                 f"({new_native['summary'].get('trades', 0)} معامله).")
    return {"winner": winner, "text": " ".join(parts), "detail_rows": rows,
            "new_wins": new_wins, "old_wins": old_wins}


PITFALLS = [
    ("lookahead در resample",
     "bucket ناقص حذف می‌شود و هم‌ترازی فقط کندلِ بسته‌شده را می‌دهد (test_resample_drops_partial_edge_buckets)"),
    ("ساختن 15m از 1h (fabrication)",
     "resample فقط به بالا مجاز است؛ در غیر این صورت ValueError صریح (test_resample_cannot_fabricate_lower_timeframe)"),
    ("کندل ناقص تایم‌فریم بالاتر",
     "drop_forming_candle + شرط close_time ≤ trigger_open (test_forming_candle_is_dropped_by_bybit_module)"),
    ("Donchian شامل کندل جاری",
     "کانال از window کندلِ قبلی ساخته می‌شود تا شکست قابل تشخیص باشد (test_donchian_excludes_current_candle…)"),
    ("نادیده گرفتن هزینه",
     "فیلتر edge ≥ 1.5× هزینهٔ رفت‌وبرگشت پیش از ورود (test_cost_filter_rejects_low_edge_signals)"),
    ("خروج خوش‌بینانه (stop و take در یک کندل)",
     "stop اول فرض می‌شود — محافظه‌کارانه‌ترین حالت (test_stop_takes_priority…)"),
    ("نشتی آینده در تصمیم موتور",
     "تست علی‌بودن با برش دادهٔ آینده و مقایسهٔ معاملات (test_engine_is_causal_prefix_invariance)"),
    ("survivorship bias",
     "موتور تک‌نمادی است و این محدودیت در meta ثبت می‌شود؛ هیچ انتخابِ «بهترین نماد گذشته» وجود ندارد"),
    ("گپ داده",
     "گپ‌ها فقط گزارش می‌شوند و هیچ forward-fill کورکورانه‌ای انجام نمی‌شود (test_gap_detection…)"),
]


def _run_unit_tests() -> List[dict]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = os.path.join(root, "tests", "run_tests.py")
    tests = []
    try:
        p = subprocess.run([sys.executable, runner], cwd=root, capture_output=True,
                           text=True, timeout=300)
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("✅ ") or line.startswith("❌ "):
                tests.append({"pass": line.startswith("✅"),
                              "name": line[2:].split(":")[0].strip(),
                              "detail": line[2:]})
        ok = p.returncode == 0
        done = [t for t in tests if t["pass"]]
        tests.append({"pass": ok, "name": "مجموع تست‌های واحد (run_tests.py)",
                      "detail": f"{len(done)}/{len(tests)} پاس"})
    except Exception as e:                              # noqa: BLE001
        tests.append({"pass": False, "name": "اجرای تست‌ها", "detail": f"خطا: {e}"})
    return tests


def build_payload(csv_path: str, symbol: str, out_dir: str, stamp: str,
                  tf: Tuple[str, str, str] = ("1h", "4h", "1d"),
                  with_validation: bool = True, progress: bool = True) -> dict:
    """اجرای هر دو سناریو در دو مدل هزینه و ساخت payload داشبورد."""
    from .data import csv_candles

    candles = csv_candles(csv_path)
    if not candles:
        raise RuntimeError("CSV خالی است.")

    def log(msg):
        if progress:
            print(msg)

    log("🧠 اجرای سناریوی قدیم (TraderBrain) — مدل هزینهٔ یکسان …")
    old_norm = run_old(csv_path, symbol, "normalized", out_dir, f"cmp-old-norm-{stamp}")
    log("🧠 اجرای سناریوی قدیم — پیش‌فرض خودش …")
    old_native = run_old(csv_path, symbol, "native", out_dir, f"cmp-old-native-{stamp}")
    log("🧩 اجرای سناریوی جدید (MTF) — مدل هزینهٔ یکسان …")
    new_norm = run_new(csv_path, symbol, "normalized", out_dir, f"cmp-new-norm-{stamp}",
                       tf=tf, validate=with_validation)
    log("🧩 اجرای سناریوی جدید — پیش‌فرض خودش …")
    new_native = run_new(csv_path, symbol, "native", out_dir, f"cmp-new-native-{stamp}", tf=tf)

    log("✨ اجرای نسخهٔ اصلاح‌شدهٔ ورود (پریست entry_quality) — مدل هزینهٔ یکسان …")
    new_eq = run_new(csv_path, symbol, "normalized", out_dir, f"cmp-new-eq-{stamp}",
                     tf=tf, extra=["--preset", "entry_quality"])

    log("🔀 مقایسهٔ نسخه‌های A/B/C سناریوی جدید …")
    versions = {}
    best_v, best_exp = None, -1e18
    for v in ("A", "B", "C"):
        r = run_new(csv_path, symbol, "normalized", out_dir, f"cmp-new-{v}-{stamp}", tf=tf, version=v)
        versions[v] = {"summary": r["summary"], "label": r["label"]}
        e = r["summary"].get("expectancy") or -1e18
        if e > best_exp:
            best_v, best_exp = v, e

    diff = bootstrap_diff([t["pnl"] for t in new_norm["trades"]],
                          [t["pnl"] for t in old_norm["trades"]])
    diff_eq = bootstrap_diff([t["pnl"] for t in new_eq["trades"]],
                             [t["pnl"] for t in new_norm["trades"]])
    diff_eq_old = bootstrap_diff([t["pnl"] for t in new_eq["trades"]],
                                 [t["pnl"] for t in old_norm["trades"]])

    # ماتریس «ورود × خروج» برای تب آزمایشگاه خروج (کوتاه، فقط برای داشبورد)
    log("🧬 ماتریس ورود × خروج برای داشبورد …")
    try:
        from .diagnose import run_policy_matrix
        from .data import load_layers
        cfg_diag = new_eq.get("_cfg")
        layers_diag, _meta = load_layers(cfg_diag)
        matrix = run_policy_matrix(cfg_diag, layers_diag,
                                   policy_ids=["base", "no_trail", "trail_0.5R",
                                               "trail_tight", "tp6", "be_1R"])
    except Exception as e:                                  # noqa: BLE001
        matrix = {"error": str(e)}
        log(f"   ⚠️ ماتریس خروج ساخته نشد: {e}")

    # تست‌های واحد برای تب سلامت (سریع: ~۰.۳ ثانیه)
    log("🧪 اجرای تست‌های واحد برای تب سلامت …")
    tests = _run_unit_tests()

    res_new = new_norm.get("_res") or {}
    health_new = new_norm.get("health") or {}

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "app_version": __version__,
        "subtitle": f"{symbol} · دادهٔ {os.path.basename(csv_path)} · "
                    f"تریگر {tf[0]} / فیلتر {tf[1]} / بایاس {tf[2]}",
        "initial_equity": 1000.0,
        "data": {
            "path": csv_path, "candles": len(candles),
            "start_ts": candles[0].open_time_ms, "end_ts": candles[-1].open_time_ms,
        },
        "cost_models": {
            "normalized": {"label": "یکسان‌سازی‌شده", "fee_bps": 5.5,
                           "slippage_pct": 0.02, "risk_per_trade_pct": 1.0,
                           "max_concurrent": 1},
            "native": {"label": "پیش‌فرض هر سناریو",
                       "old": old_native.get("config_used"),
                       "new": new_native.get("config_used")},
        },
        "scenarios": {
            "old": {
                "id": "old",
                "name": "🧠 سناریوی قدیم — TraderBrain (تک‌تایم‌فریم)",
                "short_name": "قدیم (TraderBrain)",
                "subtitle": f"1h · رژیم+تریگر روی همان کندل · {old_norm['summary'].get('trades', 0)} معامله",
                "description": "استراتژی قاعده‌محور تک‌تایم‌فریمی با تشخیص رژیم (ADX/EMA/Donchian/BB/حجم)، "
                               "ورود pullback یا breakout، تریلینگ بعد از سود، مدار شکن و فورنزیک کامل. "
                               "منبع: <span class='mono'>apps/futures-scalp-lab</span>",
                "runs": {"normalized": old_norm, "native": old_native},
            },
            "new_eq": {
                "id": "new_eq",
                "name": "✨ سناریوی جدید — ورودِ اصلاح‌شده (پریست entry_quality)",
                "short_name": "جدید (ورود اصلاح‌شده)",
                "subtitle": f"{tf[0]}/{tf[1]}/{tf[2]} · فقط pullback + ردِ کندلِ اوج · "
                            f"{new_eq['summary'].get('trades', 0)} معامله",
                "description": "همان سناریوی MTF، فقط با دو تغییر در سمت ورود: "
                               "(۱) حذف ورودِ شکست (breakout) و (۲) وتوی کندلِ اوج "
                               "(دامنه > ۱×ATR). این پارامترها از تحلیل همین داده "
                               "انتخاب شده‌اند → <b>ریسک overfit</b> دارند و باید در "
                               "TRAIN/OOS و دادهٔ بیشتر تأیید شوند.",
                "runs": {"normalized": new_eq},
                "caution": True,
            },
            "new": {
                "id": "new",
                "name": "🧩 سناریوی جدید — MTF (چندتایم‌فریمی)",
                "short_name": "جدید (MTF)",
                "subtitle": f"{tf[0]}/{tf[1]}/{tf[2]} · هم‌ترازی ضد lookahead · "
                            f"{new_norm['summary'].get('trades', 0)} معامله",
                "description": "سه لایهٔ هم‌راستاشده (بایاس/فیلتر/تریگر) با هم‌ترازی تست‌شده، "
                               "فیلتر اقتصادی هزینه، و سه نسخهٔ هم‌راستایی A/B/C. "
                               "منبع: <span class='mono'>apps/futures-mtf-lab</span>",
                "runs": {"normalized": new_norm, "native": new_native},
                "versions": versions,
            },
        },
        "validation": res_new.get("validation"),
        "best_version": best_v,
        "entry_quality": {
            "bootstrap_vs_new": diff_eq,
            "bootstrap_vs_old": diff_eq_old,
            "delta_expectancy": round(new_eq["summary"].get("expectancy", 0)
                                      - new_norm["summary"].get("expectancy", 0), 4),
            "preset": "entry_quality",
            "preset_overrides": {"trigger_entry_modes": ["pullback"],
                                 "trigger_max_range_atr": 1.0},
        },
        "exit_matrix": matrix,
        "health_new": health_new,
        "health": {
            "tests": tests,
            "leakage": (health_new.get("leakage_audit") or {}),
            "gaps": ((new_norm.get("meta") or {}).get("gaps") or {}),
            "pitfalls": PITFALLS,
            "runs": [
                (f"mtf_report_cmp-new-norm-{stamp}.json",
                 "گزارش کامل JSON سناریوی جدید (شامل اعتبارسنجی)"),
                (f"mtf_report_cmp-new-norm-{stamp}.md", "گزارش خوانا Markdown"),
                (f"trader_report_cmp-old-norm-{stamp}.json",
                 "گزارش سناریوی قدیم (در پوشهٔ futures-scalp-lab/results)"),
                (f"scenario_compare_{stamp}.json", "payload کامل همین داشبورد (reproducible)"),
            ],
        },
    }
    payload["verdict"] = _verdict(old_norm, new_norm, diff, old_native, new_native)
    payload["verdict_eq"] = _verdict(old_norm, new_eq, diff_eq_old, old_native, new_eq)
    payload["bootstrap"] = diff

    # پاک‌سازی اشیای سنگین (موتور/زمینه/کندل‌ها) — فقط دادهٔ لازم برای داشبورد
    for scn in payload["scenarios"].values():
        for run in scn["runs"].values():
            run.pop("_res", None)
            run.pop("_cfg", None)
    return payload


def compare_command(argv: Optional[List[str]] = None) -> int:
    """CLI: python3 -m mtflab compare --csv … --out dash_scenarios.html"""
    import argparse
    p = argparse.ArgumentParser(prog="mtflab compare",
                                description="مقایسهٔ سناریوی قدیم و جدید + داشبورد تب‌دار")
    p.add_argument("--csv", default="../futures-scalp-lab/data/btcusdt_1h_lastyear.csv")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--tf-trigger", default="1h")
    p.add_argument("--tf-filter", default="4h")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--out", default="results/dash_scenarios.html")
    p.add_argument("--out-dir", default="results",
                   help="پوشهٔ نتایج هر دو سناریو (پیش‌فرض: results همین اپ)")
    p.add_argument("--no-validation", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    if not os.path.isabs(args.csv):
        cand = [args.csv,
                os.path.join(OLD_APP_DIR, args.csv),
                os.path.join(os.path.dirname(OLD_APP_DIR), args.csv)]
        for c in cand:
            if os.path.exists(c):
                args.csv = c
                break
    if not os.path.exists(args.csv):
        print(f"❌ CSV پیدا نشد: {args.csv}")
        return 2

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    payload = build_payload(args.csv, args.symbol, out_dir, stamp,
                            tf=(args.tf_trigger, args.tf_filter, args.tf_bias),
                            with_validation=not args.no_validation,
                            progress=not args.quiet)

    from .dashboard import write_dashboard
    out_html = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_html) or ".", exist_ok=True)
    write_dashboard(payload, out_html,
                    title=f"داشبورد مقایسهٔ سناریوها — {args.symbol}")

    json_path = os.path.join(out_dir, f"scenario_compare_{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    so = payload["scenarios"]["old"]["runs"]["normalized"]["summary"]
    sn = payload["scenarios"]["new"]["runs"]["normalized"]["summary"]
    sq = payload["scenarios"]["new_eq"]["runs"]["normalized"]["summary"]
    print("\n" + "=" * 72)
    print("📊 مقایسهٔ عادلانه (هزینه/ریسک یکسان)")
    print(f"  قدیم : n={so['trades']:>4}  PF={so.get('profit_factor')}  "
          f"exp={so['expectancy']:+.3f}$  ret={so.get('return_pct'):+.2f}%")
    print(f"  جدید : n={sn['trades']:>4}  PF={sn.get('profit_factor')}  "
          f"exp={sn['expectancy']:+.3f}$  ret={sn.get('return_pct'):+.2f}%")
    print(f"  اصلاح : n={sq['trades']:>4}  PF={sq.get('profit_factor')}  "
          f"exp={sq['expectancy']:+.3f}$  ret={sq.get('return_pct'):+.2f}%  "
          f"(پریست entry_quality)")
    print(f"  برنده: {payload['verdict']['winner']}  ({payload['verdict']['new_wins']} "
          f"در برابر {payload['verdict']['old_wins']} معیار)")
    dq = payload.get("entry_quality", {}).get("bootstrap_vs_new", {})
    if dq.get("ok"):
        print(f"  اصلاح ورود در برابر جدید: {dq['observed_diff']:+.3f}$ "
              f"CI95 [{dq['ci95'][0]:+.3f}, {dq['ci95'][1]:+.3f}] → {dq['note']}")
    b = payload.get("bootstrap", {})
    if b.get("ok"):
        print(f"  معناداری آماری: {b['note']}")
        print(f"     CI95 اختلاف expectancy = "
              f"[{b['ci95'][0]:+.3f}, {b['ci95'][1]:+.3f}] $")
    print(f"\n✅ داشبورد: {out_html}")
    print(f"✅ JSON    : {json_path}")
    print("=" * 72)
    return 0
