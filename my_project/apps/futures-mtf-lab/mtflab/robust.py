"""آزمون «بقا» — آیا یافته روی چند نماد و چند پنجرهٔ زمانی هم زنده می‌ماند؟

چرا این ماژول لازم است: هر بهبودی که روی یک فایل CSV پیدا شود، به‌طور پیش‌فرض
مشکوک است (overfit). تنها راه معقولِ دفاع، تکرار همان آزمون روی:
  ۱) چند نماد متفاوت (نه فقط BTCUSDT)
  ۲) چند پنجرهٔ زمانی جدا (نه فقط یک بازهٔ خوش‌اتفاق)
و سپس قضاوت با قاعده‌ای که «قبل از دیدن نتیجه» تعیین شده است.

قاعدهٔ بقا (همان چیزی که در گزارش چاپ می‌شود، بدون تغییر بعد از دیدن اعداد):
  - حداقل ۶۰٪ نمادها PF > 1
  - حداقل ۵۵٪ پنجره‌ها expectancy مثبت
  - میانهٔ PF نمادها ≥ 1.05
  - آزمون علامت در برابر پریست پایه: p < 0.10
اگر هر چهار شرط برقرار نشود، حکم «بقا نیافت» است — حتی اگر عدد کلی زیبا باشد.

منابع داده:
  --source csv        یک فایل (تک‌نماد) — تست سریع همان دادهٔ موجود
  --source bybit      دانلود چند نماد از API عمومی Bybit (بدون کلید)
  --source synthetic  تولید چند «نماد» مصنوعی — فقط برای آزمون خودِ قابلیت
"""
from __future__ import annotations

import json
import math
import os
import time
import zlib
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import PRESETS, MTFConfig
from .data import Candle, csv_candles, resample_up, synthetic_candles
from .diagnose import _metrics_positions, _slice_layers
from .engine import run_backtest

SURVIVAL_RULES = {
    "min_profitable_symbols_pct": 60.0,
    "min_positive_windows_pct": 55.0,
    "min_median_pf": 1.05,
    "max_sign_test_p": 0.10,
}


# ----------------------------------------------------------------------------
# ساخت لایه‌ها برای هر نماد
# ----------------------------------------------------------------------------
def _stamp_seed(symbol: str) -> int:
    """بذرِ پایدار و بازتولیدپذیر (hash() پایتون بین اجراها تصادفی است)."""
    return 1000 + (zlib.crc32(symbol.encode("utf-8")) % 9000)


def layers_for_symbol(cfg: MTFConfig, symbol: str, source: str,
                      data_dir: str = "data",
                      path: str = "") -> Tuple[Dict[str, List[Candle]], dict]:
    """سه لایهٔ زمانی یک نماد را بدون هیچ نشتی از آینده آماده می‌کند."""
    meta = {"symbol": symbol, "source": source}

    if source == "synthetic":
        trig = synthetic_candles(cfg.tf_trigger, cfg.candles or 2400,
                                 seed=_stamp_seed(symbol))
        filt, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_filter)
        bias, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_bias)
        meta["resample"] = [cfg.tf_filter, cfg.tf_bias]
        return {"trigger": trig, "filter": filt, "bias": bias}, meta

    if source == "csv":
        csv_path = path or cfg.csv_path
        if not csv_path or not os.path.exists(csv_path):
            raise RuntimeError(f"CSV پیدا نشد: {csv_path}")
        trig = csv_candles(csv_path)
        filt, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_filter)
        bias, _ = resample_up(trig, cfg.tf_trigger, cfg.tf_bias)
        meta["path"] = csv_path
        return {"trigger": trig, "filter": filt, "bias": bias}, meta

    if source == "bybit":
        from .bybit_public import fetch_klines_range
        os.makedirs(data_dir, exist_ok=True)
        out = {}
        for tf in (cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias):
            out[tf] = fetch_klines_range(symbol, tf, cfg.days,
                                         cache_dir=data_dir,
                                         base_url=cfg.bybit_base_url,
                                         category=cfg.bybit_category)
        meta["days"] = cfg.days
        return {"trigger": out[cfg.tf_trigger], "filter": out[cfg.tf_filter],
                "bias": out[cfg.tf_bias]}, meta

    raise ValueError(f"منبع ناشناخته: {source}")


def split_windows(layers: Dict[str, List[Candle]], cfg: MTFConfig,
                  n_windows: int = 4) -> List[Dict[str, List[Candle]]]:
    """بازهٔ تریگر را به پنجره‌های پیوسته و بدون هم‌پوشانی تقسیم می‌کند."""
    trig = layers["trigger"]
    n = len(trig)
    if n_windows < 1 or n < n_windows * 50:
        return [layers]
    out = []
    step = n // n_windows
    for k in range(n_windows):
        i0 = k * step
        i1 = (k + 1) * step - 1 if k < n_windows - 1 else n - 1
        out.append(_slice_layers(layers, cfg, trig[i0].open_time_ms,
                                 trig[i1].open_time_ms))
    return out


# ----------------------------------------------------------------------------
# آزمون علامت (بدون scipy)
# ----------------------------------------------------------------------------
def sign_test_p(wins: int, n: int) -> float:
    """p-value دوطرفهٔ آزمون علامت با فرض p=0.5 (دقیق، دوجمله‌ای).

    دوطرفهٔ درست = ۲ × مینِ دو دُم، نه فقط دُمِ بالا؛ وگرنه وقتی بردها کمتر از
    نصف است p اشتباهاً ۱ برمی‌گردد و هر پریستِ ضعیف هم «بی‌تفاوت» دیده می‌شود.
    """
    if n <= 0:
        return 1.0
    wins = max(0, min(n, wins))
    upper = sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)
    lower = sum(math.comb(n, k) for k in range(0, wins + 1)) / (2 ** n)
    return round(min(1.0, 2 * min(upper, lower)), 4)


# ----------------------------------------------------------------------------
# اجرای کل آزمون
# ----------------------------------------------------------------------------
def _run_preset(cfg: MTFConfig, layers: Dict[str, List[Candle]], preset: str) -> dict:
    c = replace(cfg, verbose=False, forensics=False, run_id="", preset=preset,
                **{k: v for k, v in PRESETS.get(preset, {}).items()})
    res = run_backtest(c, layers)
    m = _metrics_positions(res, c)
    m["veto_stats"] = res["summary"].get("veto_stats", {})
    return m


def run_robust(cfg: MTFConfig, symbols: Sequence[str], presets: Sequence[str],
               source: str = "csv", n_windows: int = 4,
               data_dir: str = "data", progress: bool = True,
               paths: Optional[Dict[str, str]] = None) -> dict:
    base = "base"
    presets = list(dict.fromkeys([base] + list(presets)))

    per_preset: Dict[str, dict] = {
        p: {"symbols": {}, "full_exp": [], "full_pf": [], "full_n": [], "win_flags": []}
        for p in presets
    }
    errors: List[str] = []

    for sym in symbols:
        if progress:
            print(f"  🔎 نماد {sym} …")
        try:
            layers, _meta = layers_for_symbol(cfg, sym, source, data_dir,
                                              path=(paths or {}).get(sym, ""))
        except Exception as e:                                   # noqa: BLE001
            errors.append(f"{sym}: {e}")
            continue
        if not layers["trigger"]:
            errors.append(f"{sym}: دادهٔ خالی")
            continue

        wins = split_windows(layers, cfg, n_windows)
        for p in presets:
            full = _run_preset(cfg, layers, p)
            wrows = []
            for wi, wl in enumerate(wins):
                wm = _run_preset(cfg, wl, p)
                wrows.append({"window": wi + 1, "n": wm["n"],
                              "exp": wm["expectancy"], "pf": wm["profit_factor"]})
                per_preset[p]["win_flags"].append(bool(wm["n"] >= 3 and wm["expectancy"] > 0))
            per_preset[p]["symbols"][sym] = {"full": full, "windows": wrows}
            per_preset[p]["full_exp"].append(full["expectancy"])
            per_preset[p]["full_n"].append(full["n"])
            if full["profit_factor"] is not None:
                per_preset[p]["full_pf"].append(full["profit_factor"])

    # ── تجمیع ────────────────────────────────────────────────────────────────
    summary: Dict[str, dict] = {}
    for p, d in per_preset.items():
        pfs = sorted(d["full_pf"])
        exps = sorted(d["full_exp"])
        n_sym = len(pfs)
        prof_sym = sum(1 for x in pfs if x > 1.0)
        win_pos = sum(1 for f in d["win_flags"] if f)
        n_win = len(d["win_flags"])
        med_pf = pfs[len(pfs) // 2] if pfs else 0.0
        summary[p] = {
            "symbols_n": n_sym,
            "profitable_symbols": prof_sym,
            "profitable_symbols_pct": round(100.0 * prof_sym / n_sym, 2) if n_sym else 0.0,
            "median_pf": round(med_pf, 4),
            "median_expectancy": round(exps[len(exps) // 2], 4) if exps else 0.0,
            "windows_n": n_win,
            "positive_windows": win_pos,
            "positive_windows_pct": round(100.0 * win_pos / n_win, 2) if n_win else 0.0,
            "median_trades": (sorted(d["full_n"])[len(d["full_n"]) // 2]
                              if d["full_n"] else 0),
            "total_trades": sum(d["full_n"]),
        }

    # ── آزمون علامت هر پریست در برابر پایه (جفت‌شده روی نمادها) ─────────────
    for p in presets:
        if p == base:
            summary[p]["sign_vs_base"] = None
            continue
        wins_n = n = 0
        for sym in per_preset[p]["symbols"]:
            b = per_preset[base]["symbols"].get(sym)
            q = per_preset[p]["symbols"][sym]
            if not b:
                continue
            n += 1
            if q["full"]["expectancy"] > b["full"]["expectancy"]:
                wins_n += 1
        summary[p]["sign_vs_base"] = {
            "wins": wins_n, "of": n,
            "p_value": sign_test_p(wins_n, n),
            "note": ("بهتر از پایه در اکثر نمادها" if n and wins_n * 2 > n
                     else "بهتر از پایه در نیمه یا کمتر نمادها"),
        }

    for p in presets:
        s = summary[p]
        checks = {
            "has_trades": s["total_trades"] >= 20,
            "profitable_symbols": s["profitable_symbols_pct"] >= SURVIVAL_RULES["min_profitable_symbols_pct"],
            "positive_windows": s["positive_windows_pct"] >= SURVIVAL_RULES["min_positive_windows_pct"],
            "median_pf": s["median_pf"] >= SURVIVAL_RULES["min_median_pf"],
            "significance": (p == base) or
                            ((s["sign_vs_base"] or {}).get("p_value", 1.0) <= SURVIVAL_RULES["max_sign_test_p"]),
        }
        s["checks"] = checks
        s["survived"] = bool(all(checks.values()))

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "source": source,
        "symbols": list(symbols),
        "n_windows": n_windows,
        "presets": presets,
        "rules": SURVIVAL_RULES,
        "summary": summary,
        "per_preset": {p: {"symbols": d["symbols"]} for p, d in per_preset.items()},
        "errors": errors,
    }


# ----------------------------------------------------------------------------
# گزارش
# ----------------------------------------------------------------------------
def _f(x, d: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+,.{d}f}" if isinstance(x, float) else str(x)


def render_robust_report(r: dict, out_path: str) -> str:
    L: List[str] = []
    w = L.append
    w("# آزمون بقا: آیا یافته روی چند نماد و چند پنجره زنده می‌ماند؟\n")
    w(f"- منبع داده: `{r['source']}` · نمادها: {', '.join(r['symbols'])} · "
      f"پنجره‌ها: {r['n_windows']} · ساخته‌شده: {r['generated_at']}")
    ru = r["rules"]
    w(f"- قاعدهٔ بقا (از پیش تعیین‌شده): PF>1 در ≥{ru['min_profitable_symbols_pct']}٪ نمادها، "
      f"expectancy مثبت در ≥{ru['min_positive_windows_pct']}٪ پنجره‌ها، "
      f"میانهٔ PF ≥ {ru['min_median_pf']}، p آزمون علامت ≤ {ru['max_sign_test_p']}.\n")

    w("## خلاصه\n")
    w("| پریست | نمادها | معاملات | PF>1 | میانهٔ PF | میانهٔ expectancy | پنجره‌های مثبت | حکم |")
    w("|---|---:|---:|---:|---:|---:|---:|:--:|")
    for p in r["presets"]:
        s = r["summary"][p]
        verdict = "✅ بقا یافت" if s["survived"] else "❌ بقا نیافت"
        w(f"| `{p}` | {s['symbols_n']} | {s['total_trades']} | {s['profitable_symbols']} "
          f"({s['profitable_symbols_pct']}٪) | {s['median_pf']} | "
          f"{_f(s['median_expectancy'])}$ | {s['positive_windows']}/{s['windows_n']} "
          f"({s['positive_windows_pct']}٪) | {verdict} |")
    w("")

    for p in r["presets"]:
        s = r["summary"][p]
        if p != "base" and s.get("sign_vs_base"):
            sg = s["sign_vs_base"]
            w(f"- **{p}** در برابر پایه: در {sg['wins']} از {sg['of']} نماد بهتر بود "
              f"(p = {sg['p_value']}) → {sg['note']}")
    w("")

    w("## جزئیات به‌ازای نماد\n")
    for p in r["presets"]:
        w(f"### پریست `{p}`\n")
        w("| نماد | n | PF | expectancy | بازده٪ | افت٪ | پنجره‌ها (expectancy) |")
        w("|---|---:|---:|---:|---:|---:|---|")
        for sym, d in r["per_preset"][p]["symbols"].items():
            f = d["full"]
            wins = " · ".join(f"W{x['window']}:{_f(x['exp'])}" for x in d["windows"])
            w(f"| {sym} | {f['n']} | "
              f"{f['profit_factor'] if f['profit_factor'] is not None else '—'} | "
              f"{_f(f['expectancy'])}$ | {_f(f.get('return_pct'))}% | "
              f"{_f(f.get('max_drawdown_pct'))}% | {wins} |")
        w("")

    if r["errors"]:
        w("## خطاها\n")
        for e in r["errors"]:
            w(f"- {e}")
        w("")

    w("## چطور همین را روی دادهٔ واقعی اجرا کنم؟\n")
    w("```bash")
    w("python3 -m mtflab robust --source bybit --symbols BTCUSDT ETHUSDT SOLUSDT \\")
    w("    --days 730 --tf-trigger 15m --tf-filter 1h --tf-bias 4h \\")
    w("    --presets entry_quality --windows 4")
    w("```\n")
    w("> اگر Bybit از شبکهٔ شما در دسترس است. در محیط بسته، `--source synthetic` "
      "همان مسیر کد را بدون اینترنت می‌آزماید (فقط برای اعتبارسنجی مکانیزم، "
      "نه نتیجهٔ بازار).")
    text = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def robust_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .config import load_config

    p = argparse.ArgumentParser(prog="mtflab robust",
                                description="آزمون بقا روی چند نماد و چند پنجره")
    p.add_argument("--source", choices=["csv", "bybit", "synthetic"], default="csv")
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    p.add_argument("--csv", action="append", default=[],
                   help="CSV هر نماد: --csv BTCUSDT=path.csv (قابل تکرار)")
    p.add_argument("--presets", nargs="+", default=["entry_quality"])
    p.add_argument("--windows", type=int, default=4)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out", default="results/robust_report.md")
    p.add_argument("--json", default="")
    known, rest = p.parse_known_args(argv if argv is not None else None)

    # منبع دادهٔ همین دستور، حالتِ دادهٔ موتور را تعیین می‌کند
    if "--data" not in rest:
        rest = list(rest) + ["--data", known.source]
    paths: Dict[str, str] = {}
    for item in known.csv:
        if "=" in item:
            sym, path = item.split("=", 1)
            paths[sym.strip().upper()] = path.strip()
    if paths and known.symbols == ["BTCUSDT"]:
        known.symbols = list(paths)
    if known.source == "csv" and not paths and "--csv" not in rest:
        print("❌ در حالت csv باید --csv بدهید (یا --csv SYMBOL=path).")
        return 2
    if "--csv" not in rest:
        rest = list(rest) + ["--csv", (paths or {}).get(known.symbols[0], "")]
    cfg = load_config(rest)
    cfg.verbose = False
    cfg.forensics = False

    t0 = time.time()
    print(f"🧪 آزمون بقا · منبع={known.source} · نمادها={len(known.symbols)} · "
          f"پریست‌ها={known.presets} · پنجره‌ها={known.windows}")
    res = run_robust(cfg, known.symbols, known.presets, source=known.source,
                     n_windows=known.windows, data_dir=known.data_dir, paths=paths)
    res["sources"] = paths
    out = render_robust_report(res, known.out)
    if known.json:
        with open(known.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 66)
    for pr in res["presets"]:
        s = res["summary"][pr]
        print(f"  {pr:<16} symbols={s['symbols_n']} trades={s['total_trades']:>4}  "
              f"PF>1={s['profitable_symbols_pct']:>5.1f}%  "
              f"medianPF={s['median_pf']:<5}  windows+={s['positive_windows_pct']:>5.1f}%  "
              f"→ {'✅ بقا' if s['survived'] else '❌ بقا نیافت'}")
    if all(res["summary"][pr]["total_trades"] == 0 for pr in res["presets"]):
        print("  ⚠️ هیچ معامله‌ای شکل نگرفت — احتمالاً داده/دورهٔ گرم‌کردن کافی نیست "
              "(مثلاً --candles بیشتر یا --bias-ema کوچک‌تر).")
    if res["errors"]:
        print("  ⚠️ خطاها:", "; ".join(res["errors"][:3]))
    print(f"\n📄 گزارش: {out}\n⏱ {time.time()-t0:.1f}s")
    print("=" * 66)
    return 0
