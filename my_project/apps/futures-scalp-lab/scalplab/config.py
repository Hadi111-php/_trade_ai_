"""پیکربندی پارامتریک Futures Scalp Lab.

همهٔ پارامترها از CLI / متغیر محیطی / فایل JSON قابل تنظیم‌اند؛ هیچ عددی hardcode نیست.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class LabConfig:
    # داده
    data_mode: str = "synthetic"          # synthetic | csv | binance | bybit
    symbol: str = "BTCUSDT"
    timeframe: str = "1m"
    candles: int = 2000
    csv_path: str = ""
    binance_url: str = os.environ.get(
        "SCALPLAB_BINANCE_URL", "https://api.binance.com/api/v3/klines")
    bybit_url: str = os.environ.get(
        "SCALPLAB_BYBIT_URL", "https://api.bybit.com/v5/market/kline")
    bybit_category: str = "linear"

    # اجرا
    seeds: List[int] = field(default_factory=lambda: [42, 123, 777])
    horizon: int = 12                     # کندل‌های افق ارزیابی
    fee_bps: float = 4.0                  # کارمزد هر طرف (bps)
    cooldown: int = 5                     # حداقل فاصلهٔ بین دو سیگنال یک مدل
    agree_min: int = 2                    # حداقل توافق برای ensemble

    # خروجی
    out_dir: str = "results"
    run_id: str = ""

    # حالت خودکار (PAPER فقط)
    max_ticks: int = 300          # پیش‌فرض محدود؛ بی‌پایان فقط با --forever
    interval: float = 0.0         # ثانیه بین کندل‌ها (binance)
    live: bool = False            # عمداً پشتیبانی نمی‌شود؛ فقط خطا می‌دهد
    forever: bool = False         # برای اجراي بلندمدت (daemon دستی)
    light: bool = False           # حالت سبک: اینتروال بلندتر + بافر کوچکتر (PC قفل نشه)

    # موتور مدیریت ریسک (پیش‌فرض خاموش؛ فقط با --trade روی PAPER)
    trade: bool = False
    trade_size_quote: float = 100.0
    leverage: float = 3.0
    max_concurrent: int = 4
    cb_losses: int = 2
    stop_pct: float = 0.005
    trail_pct: float = 0.003
    adaptive: bool = True          # استاپ/trailing بر پایهٔ ATR (سازگار با تایم‌فریم)
    stop_atr_mult: float = 1.5
    trail_atr_mult: float = 1.0
    sweep_tfs: list = None
    sweep_horizons: list = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scalplab",
                                description="Futures Scalp Lab — سیگنال چندمدلی با ثبت کامل و اعتبارسنجی")
    p.add_argument("--data", dest="data_mode", choices=["synthetic", "csv", "binance", "bybit"],
                   default=None, help="منبع داده")
    p.add_argument("--symbol", default=None)
    p.add_argument("--tf", dest="timeframe", default=None)
    p.add_argument("--candles", type=int, default=None)
    p.add_argument("--csv", dest="csv_path", default=None)
    p.add_argument("--seeds", type=int, nargs="+", default=None)
    p.add_argument("--seed", type=int, default=None, help="معادل --seeds با یک مقدار")
    p.add_argument("--horizon", type=int, default=None)
    p.add_argument("--fee-bps", dest="fee_bps", type=float, default=None)
    p.add_argument("--cooldown", type=int, default=None)
    p.add_argument("--agree-min", dest="agree_min", type=int, default=None)
    p.add_argument("--out", dest="out_dir", default=None)
    p.add_argument("--run-id", dest="run_id", default=None)
    p.add_argument("--max-ticks", dest="max_ticks", type=int, default=None,
                   help="حالت auto: حداکثر تعداد کندل (پیش‌فرض محدود)")
    p.add_argument("--interval", type=float, default=None,
                   help="حالت auto: فاصلهٔ ثانیه‌ای بین کندل‌ها (binance)")
    p.add_argument("--live", action="store_true", default=None,
                   help="عمداً غیرفعال؛ LIVE پیاده‌سازی نشده و خطا می‌دهد")
    p.add_argument("--forever", action="store_true", default=None,
                   help="حالت auto: اجرای بلندمدت (بدون سقف ticks)")
    p.add_argument("--light", action="store_true", default=None,
                   help="حالت سبک: اینتروال ≥۳۰ثانیه + بافر کوچک (PC سنگین نشه)")
    p.add_argument("--trade", action="store_true", default=None,
                   help="فعال‌سازی موتور ریسک (PAPER) در حالت auto")
    p.add_argument("--size", dest="trade_size_quote", type=float, default=None,
                   help="حجم هر معامله (quote)")
    p.add_argument("--leverage", type=float, default=None, help="ضریب/لوریج")
    p.add_argument("--max-concurrent", dest="max_concurrent", type=int, default=None,
                   help="حداکثر معاملهٔ همزمان")
    p.add_argument("--cb-losses", dest="cb_losses", type=int, default=None,
                   help="تعداد ضرر برای قطع کامل (circuit breaker)")
    p.add_argument("--stop-pct", dest="stop_pct", type=float, default=None)
    p.add_argument("--trail-pct", dest="trail_pct", type=float, default=None)
    p.add_argument("--no-adaptive", dest="no_adaptive", action="store_true",
                   default=None, help="استاپ ثابت (به‌جای ATR)")
    p.add_argument("--stop-atr-mult", dest="stop_atr_mult", type=float, default=None)
    p.add_argument("--trail-atr-mult", dest="trail_atr_mult", type=float, default=None)
    p.add_argument("--tfs", default=None, help="سویپ: دقیقه‌ها، مثل 1,5,15")
    p.add_argument("--horizons", default=None, help="سویپ: افق‌ها، مثل 4,8,16")
    p.add_argument("--config", default=None, help="فایل JSON پیکربندی")
    return p


def load_config(argv=None) -> LabConfig:
    cfg = LabConfig()
    args, _ = build_parser().parse_known_args(argv)

    if args.config:
        with open(args.config, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    for key in ("data_mode", "symbol", "timeframe", "candles", "csv_path",
                "seeds", "horizon", "fee_bps", "cooldown", "agree_min",
                "out_dir", "run_id", "max_ticks", "interval", "live", "forever", "light",
                "trade", "trade_size_quote", "leverage", "max_concurrent",
                "cb_losses", "stop_pct", "trail_pct",
                "stop_atr_mult", "trail_atr_mult"):
        val = getattr(args, key)
        if val is not None:
            setattr(cfg, key, val)

    if getattr(args, "seed", None) is not None:
        cfg.seeds = [args.seed]
    if getattr(args, "no_adaptive", False):
        cfg.adaptive = False
    if getattr(args, "tfs", None):
        cfg.sweep_tfs = [int(x) for x in args.tfs.split(",") if x.strip()]
    if getattr(args, "horizons", None):
        cfg.sweep_horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    if cfg.forever:
        cfg.max_ticks = 10**9

    if not cfg.run_id:
        import time
        cfg.run_id = time.strftime("%Y%m%d-%H%M%S")
    return cfg
