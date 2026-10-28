"""CLI یکپارچهٔ Futures MTF Lab.

دستورها:
  run        (پیش‌فرض) بک‌تست یک سناریو روی یک نسخهٔ هم‌راستایی
  validate   بک‌تست + اعتبارسنجی کامل (split / walk-forward / monte-carlo / baselines)
  download   دانلود دادهٔ عمومی Bybit برای سه تایم‌فریم (بدون API key)
  compare    اجرای هر دو سناریو روی دادهٔ یکسان + ساخت داشبورد تب‌دار
  diagnose   کالبدشکافی چرا سود کم برداشت می‌شود + آزمون سود شناور + گزارش فارسی
  dashboard  ساخت مجدد داشبورد از payload ذخیره‌شده
  serve      سرو کردن داشبوردها در مرورگر (بدون Flask)
  selftest   خودآزمایی (تست‌ها + علی‌بودن + نشتی + فیلتر هزینه)

نمونه‌ها:
  python3 -m mtflab selftest
  python3 -m mtflab download --symbol BTCUSDT --days 365
  python3 -m mtflab run --data bybit --symbol BTCUSDT --tf-trigger 15m --tf-filter 1h --tf-bias 4h
  python3 -m mtflab validate --data bybit --symbol BTCUSDT --tf-trigger 15m
  python3 -m mtflab compare --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv
  python3 -m mtflab diagnose --data csv --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv --align A --bias-ema 50
  python3 -m mtflab serve --dir ../futures-scalp-lab/results --port 8080
"""
from __future__ import annotations

import json
import os
import sys
import time

from . import __version__


USAGE = __doc__


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd = argv[0] if argv and not argv[0].startswith("-") else "run"
    rest = argv[1:] if argv and not argv[0].startswith("-") else argv

    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("version", "--version", "-V"):
        print(f"futures-mtf-lab {__version__}")
        return 0

    if cmd == "selftest":
        from .selftest import run_selftest
        return run_selftest()

    if cmd == "diagnose":
        import argparse
        p = argparse.ArgumentParser(prog="mtflab diagnose", add_help=False)
        p.add_argument("--out", default="results/diagnosis_report.md")
        known, rest2 = p.parse_known_args(rest)
        rest = rest2
        from .config import load_config
        from .data import load_layers
        from .diagnose import (diagnose, run_setup_sweep, setup_significance,
                               write_diagnosis_report)
        cfg = load_config(rest)
        layers, _meta = load_layers(cfg)
        t0 = time.time()
        diag = diagnose(cfg, layers)
        sweeps = run_setup_sweep(cfg, layers)
        diag["setup_significance"] = setup_significance(cfg, layers, diag["setups"])
        out = write_diagnosis_report(diag, cfg, known.out, sweeps=sweeps)
        b, su = diag["base"]["summary"], diag["setups"]
        print(f"\n⏱ {time.time()-t0:.1f}s")
        print(f"📄 گزارش تشخیصی: {out}")
        print(f"   پایه: {b['trades']} معامله | PF {b['profit_factor']} | "
              f"expectancy {b['expectancy']:+.3f}$")
        print(f"   بهترین فرضیهٔ پایدار: {su['best_robust']} "
              f"(از {su['n_experiments']} فرضیه، {su['robust_count']} پایدار)")
        return 0

    if cmd == "compare":
        from .compare import compare_command
        return compare_command(rest)

    if cmd == "serve":
        import argparse
        p = argparse.ArgumentParser(prog="mtflab serve")
        p.add_argument("--dir", default="results")
        p.add_argument("--host", default="0.0.0.0")
        p.add_argument("--port", type=int, default=8080)
        a = p.parse_args(rest)
        from .serve import serve
        serve(a.dir, a.host, a.port)
        return 0

    if cmd == "download":
        import argparse
        from .bybit_public import fetch_klines_range
        p = argparse.ArgumentParser(prog="mtflab download",
                                    description="دانلود دادهٔ عمومی Bybit (بدون API key)")
        p.add_argument("--symbol", default="BTCUSDT")
        p.add_argument("--days", type=int, default=365)
        p.add_argument("--tfs", nargs="+", default=["15m", "1h", "4h"])
        p.add_argument("--dir", default="data")
        a = p.parse_args(rest)
        print(f"⬇ دانلود {a.symbol} — {a.days} روز — {', '.join(a.tfs)}")
        ok = 0
        for tf in a.tfs:
            try:
                cs = fetch_klines_range(a.symbol, tf, a.days, cache_dir=a.dir)
                print(f"   ✅ {tf}: {len(cs)} کندل")
                ok += 1
            except Exception as e:                       # noqa: BLE001
                print(f"   ❌ {tf}: {e}")
        return 0 if ok else 1

    if cmd == "dashboard":
        import argparse
        from .dashboard import write_dashboard
        p = argparse.ArgumentParser(prog="mtflab dashboard")
        p.add_argument("--payload", required=True, help="فایل scenario_compare_*.json")
        p.add_argument("--out", default="results/dash_scenarios.html")
        a = p.parse_args(rest)
        with open(a.payload, encoding="utf-8") as f:
            payload = json.load(f)
        write_dashboard(payload, a.out, title="داشبورد مقایسهٔ سناریوها")
        print(f"✅ داشبورد بازسازی شد: {a.out}")
        return 0

    # run / validate
    from .config import load_config
    from .engine import run_from_config
    cfg = load_config(rest)
    if cmd == "validate":
        cfg.validate = True
    elif cmd != "run":
        print(f"❌ دستور ناشناخته: {cmd}\n\n{USAGE}")
        return 2
    t0 = time.time()
    res = run_from_config(cfg)
    s = res["summary"]
    print(f"\n⏱ زمان اجرا: {time.time()-t0:.2f}s")
    print(f"📄 گزارش‌ها: {res.get('files', {})}")
    if cfg.validate and res.get("validation"):
        o = res["validation"]["overfit"]
        print(f"🧪 چک‌لیست overfit: {o['passed']}/{o['total']} → {o['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
