"""پیکربندی پارامتریک Futures MTF Lab.

همهٔ پارامترها از CLI / فایل JSON / مقادیر پیش‌فرض می‌آیند؛ هیچ عددی hardcode
نیست (شرط ۴ در docs/AGENT_TASK.md). به‌جای YAML از JSON استفاده می‌شود تا
وابستگی به `pyyaml` لازم نباشد (فقط کتابخانهٔ استاندارد).
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field, fields
import copy
from typing import Dict, List, Optional

CONFIG_FILENAME = "config/default_config.json"

# ----------------------------------------------------------------------------
# پریست‌ها — «ترکیب‌های نام‌دار» پارامترها
# ----------------------------------------------------------------------------
# چرا پریست و نه تغییر پیش‌فرض؟ چون پیش‌فرض باید «بی‌طرف» بماند تا مقایسه با
# سناریوی قدیم روی دادهٔ یکسان، مقایسهٔ منصفانه باشد. هر پریست یعنی «یک فرضیه
# که روی داده آزموده شد»؛ در `--preset entry_quality` صریحاً می‌گوییم پارامترها
# از همین داده انتخاب شده‌اند و ریسک overfit دارند (نتایج TRAIN/OOS در گزارش
# diagnose دیده می‌شود).
PRESETS: Dict[str, dict] = {
    "base": {},
    # از گزارش تشخیص: pullback-only + ردِ کندلِ اوج (دامنه > 1×ATR)
    # شاهد: expectancy −0.79$ → +0.80$ و DD −13.8% → −4.6% (بدون تغییر خروج)
    # قید: OOS فقط ۷ معامله → «فرضیهٔ قوی»، نه یافتهٔ قطعی.
    "entry_quality": {
        "trigger_entry_modes": ["pullback"],
        "trigger_max_range_atr": 1.0,
    },
}


@dataclass
class MTFConfig:
    # ── داده ──────────────────────────────────────────────────────────────
    symbol: str = "BTCUSDT"
    data_mode: str = "csv"              # csv | bybit | synthetic
    csv_path: str = ""                  # CSV تایم‌فریم تریگر (یا منبع resample)
    csv_filter_path: str = ""           # اختیاری: CSV جداگانه برای لایهٔ فیلتر
    csv_bias_path: str = ""             # اختیاری: CSV جداگانه برای لایهٔ بایاس
    tf_trigger: str = "15m"             # تریگر ورود
    tf_filter: str = "1h"               # فیلتر رژیم/جهت
    tf_bias: str = "4h"                 # بایاس اختیاری
    candles: int = 0                    # 0 = همهٔ کندل‌ها
    days: int = 365                     # برای حالت bybit
    data_dir: str = "data"              # کش دانلود
    refresh_cache: bool = False
    bybit_base_url: str = os.environ.get("MTFLAB_BYBIT_URL", "https://api.bybit.com")
    bybit_category: str = "linear"

    # ── لایهٔ بایاس (tf_bias) ─────────────────────────────────────────────
    bias_enabled: bool = True
    bias_ema_period: int = 200
    bias_slope_bars: int = 3
    bias_slope_min_pct: float = 0.05    # حداقل شیب EMA برای تأیید جهت
    bias_donchian_window: int = 20

    # ── لایهٔ فیلتر (tf_filter) ───────────────────────────────────────────
    filter_adx_period: int = 14
    filter_adx_min: float = 22.0        # زیر این → sideways (بدون معامله در نسخه A/C)
    filter_ema_period: int = 50
    filter_ema_fast_period: int = 21
    filter_slope_bars: int = 3
    filter_slope_min_pct: float = 0.02
    filter_confirm_bars: int = 2        # تغییر رژیم باید N بار تأیید شود

    # ── لایهٔ تریگر (tf_trigger) ──────────────────────────────────────────
    trigger_ema_period: int = 21
    trigger_pullback_atr: float = 0.7   # فاصلهٔ مجاز تا EMA (×ATR)
    trigger_rsi_period: int = 14
    trigger_rsi_long_max: float = 60.0  # pullback لانگ: RSI باید زیر این باشد
    trigger_rsi_short_min: float = 40.0
    trigger_donchian_window: int = 20
    trigger_donchian_pos_long: float = 0.75
    trigger_donchian_pos_short: float = 0.25
    trigger_vol_window: int = 50
    trigger_vol_z_min: float = 1.2      # تأیید حجم برای شکست
    trigger_atr_period: int = 14
    trigger_entry_modes: List[str] = field(default_factory=lambda: ["pullback", "breakout"])
    # ضدِ «دویدن دنبال قیمت»: اگر دامنهٔ کندلِ ورود > این × ATR باشد، وارد نشو (0 = خاموش)
    trigger_max_range_atr: float = 0.0
    # فیلتر ساعت (UTC) — عمداً پیش‌فرض خاموش؛ فقط برای آزمایش و با هشدار overfit
    skip_hours_utc: List[int] = field(default_factory=list)

    # ── نسخهٔ هم‌راستایی (A/B/C طبق docs/strategy_design.md) ──────────────
    alignment_version: str = "A"        # A: AND سخت‌گیرانه | B: امتیاز وزنی | C: فقط فیلتر رژیم
    score_w_bias: float = 0.4
    score_w_filter: float = 0.4
    score_w_trigger: float = 0.2
    score_min: float = 0.55

    # ── هزینه (fees.py) ───────────────────────────────────────────────────
    fee_bps: float = 5.5                # کارمزد taker هر طرف (bps)
    slippage_pct: float = 0.02          # اسلیپیج هر طرف (درصد)
    min_edge_multiplier: float = 1.5    # سود موردانتظار >= این × هزینهٔ رفت‌وبرگشت
    edge_atr_mult: float = 2.0          # حرکت موردانتظار = این × ATR%

    # ── حساب / ریسک (PAPER) ───────────────────────────────────────────────
    initial_equity: float = 1000.0
    risk_per_trade_pct: float = 1.0     # درصدِ موجودی در هر معامله
    fixed_risk: float = 0.0             # اگر >0: ریسک ثابتِ USDT (بدون compounding)
    max_leverage: float = 5.0
    stop_atr_mult: float = 1.5
    take_profit_atr_mult: float = 3.0   # RR = take/stop = 2.0
    trail_enabled: bool = True
    trail_start_r: float = 1.0          # تریلینگ فقط بعد از +1R سود
    trail_atr_mult: float = 2.0
    breakeven_at_r: float = 0.0         # >0: بعد از رسیدن به این R، استاپ به نقطهٔ ورود
    partial_take_r: float = 0.0         # >0: خروج جزئی در این R
    partial_take_frac: float = 0.5      # چه کسری از پوزیشن جزئی بسته شود
    max_concurrent: int = 1
    cooldown_bars_after_loss: int = 4
    cb_losses: int = 3                  # ضرر متوالی → مدار شکن
    cb_cooldown_bars: int = 12
    daily_loss_limit_pct: float = 5.0
    regime_change_exit: bool = True
    max_holding_bars: int = 0           # 0 = بدون time-stop
    entry_on_next_open: bool = False    # True: ورود در open کندل بعد (محافظه‌کارانه‌تر)
    min_confidence: float = 0.0

    # ── خروجی ─────────────────────────────────────────────────────────────
    out_dir: str = "results"
    run_id: str = ""
    verbose: bool = True
    forensics: bool = True              # ثبت کامل سیگنال/معامله در JSONL
    preset: str = "base"                # base | entry_quality (نگاه کنید به PRESETS)
    seed: int = 42

    # ── اعتبارسنجی ────────────────────────────────────────────────────────
    validate: bool = False              # اجرای split/walk-forward/monte-carlo/baselines
    train_ratio: float = 0.6
    validation_ratio: float = 0.2
    out_of_sample_ratio: float = 0.2
    walk_forward_windows: int = 6
    walk_forward_reselect: bool = True  # انتخاب آستانه روی train هر پنجره → اجرا روی test
    monte_carlo_simulations: int = 1000
    sensitivity_grid: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rr(self) -> float:
        return round(self.take_profit_atr_mult / max(self.stop_atr_mult, 1e-9), 4)

    def label(self) -> str:
        tag = "" if self.preset == "base" else f" · پریست {self.preset}"
        if self.data_mode == "bybit":
            return "دادهٔ واقعی Bybit (عمومی، بدون کلید) — PAPER؛ هنوز سود واقعی نیست"
        if self.data_mode == "csv":
            return "بازپخش دادهٔ CSV واقعی — PAPER؛ هنوز سود واقعی نیست"
        return "دادهٔ مصنوعی — فقط اعتبارسنجی مکانیزم؛ NOT real market"


# ----------------------------------------------------------------------------
# فایل کانفیگ
# ----------------------------------------------------------------------------
def default_config_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, CONFIG_FILENAME)


def load_json_config(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # ساختار تو در تو (data/fees/risk/…) → کلیدهای تخت dataclass
    flat: dict = {}
    sections = {"data", "fees", "risk", "layers", "bias", "filter", "trigger",
                "alignment", "validation", "output", "scores"}
    for k, v in raw.items():
        if isinstance(v, dict) and k in sections:
            for k2, v2 in v.items():
                flat[k2] = v2
        else:
            flat[k] = v
    return flat


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mtflab",
                                description="Futures MTF Lab — سناریوی چندتایم‌فریمی (PAPER)")
    p.add_argument("--config", default=None, help="فایل JSON کانفیگ")
    p.add_argument("--preset", choices=sorted(PRESETS), default=None,
                   help="ترکیب نام‌دار پارامترها (base = پیش‌فرض بی‌طرف)")

    g = p.add_argument_group("داده")
    g.add_argument("--data", dest="data_mode", choices=["csv", "bybit", "synthetic"], default=None)
    g.add_argument("--symbol", default=None)
    g.add_argument("--csv", dest="csv_path", default=None)
    g.add_argument("--csv-filter", dest="csv_filter_path", default=None)
    g.add_argument("--csv-bias", dest="csv_bias_path", default=None)
    g.add_argument("--tf-trigger", default=None)
    g.add_argument("--tf-filter", default=None)
    g.add_argument("--tf-bias", default=None)
    g.add_argument("--candles", type=int, default=None)
    g.add_argument("--days", type=int, default=None)
    g.add_argument("--data-dir", dest="data_dir", default=None)
    g.add_argument("--refresh-cache", dest="refresh_cache", action="store_true", default=None)

    g = p.add_argument_group("لایه‌ها")
    g.add_argument("--alignment", dest="alignment_version", choices=["A", "B", "C"], default=None)
    g.add_argument("--adx-min", dest="filter_adx_min", type=float, default=None)
    g.add_argument("--bias-ema", dest="bias_ema_period", type=int, default=None)
    g.add_argument("--filter-ema", dest="filter_ema_period", type=int, default=None)
    g.add_argument("--trigger-ema", dest="trigger_ema_period", type=int, default=None)
    g.add_argument("--vol-z-min", dest="trigger_vol_z_min", type=float, default=None)
    g.add_argument("--score-min", dest="score_min", type=float, default=None)
    g.add_argument("--no-bias", dest="bias_enabled", action="store_false", default=None)
    g.add_argument("--entry-modes", dest="trigger_entry_modes", nargs="+", default=None)
    g.add_argument("--max-range-atr", dest="trigger_max_range_atr", type=float, default=None,
                   help="ردِ ورود اگر دامنهٔ کندلِ تریگر > این × ATR باشد (ضدِ climax/chasing، 0=خاموش)")
    g.add_argument("--skip-hours", dest="skip_hours_utc", type=int, nargs="+", default=None,
                   help="ساعت‌های UTC که در آن‌ها ورود نکن (مثلاً 0 1 2 13 14)")

    g = p.add_argument_group("هزینه")
    g.add_argument("--fee-bps", dest="fee_bps", type=float, default=None)
    g.add_argument("--slippage-pct", dest="slippage_pct", type=float, default=None)
    g.add_argument("--min-edge", dest="min_edge_multiplier", type=float, default=None)
    g.add_argument("--edge-atr", dest="edge_atr_mult", type=float, default=None)

    g = p.add_argument_group("ریسک")
    g.add_argument("--equity", dest="initial_equity", type=float, default=None)
    g.add_argument("--risk-pct", dest="risk_per_trade_pct", type=float, default=None)
    g.add_argument("--fixed-risk", dest="fixed_risk", type=float, default=None)
    g.add_argument("--leverage", dest="max_leverage", type=float, default=None)
    g.add_argument("--stop-atr", dest="stop_atr_mult", type=float, default=None)
    g.add_argument("--tp-atr", dest="take_profit_atr_mult", type=float, default=None)
    g.add_argument("--trail-atr", dest="trail_atr_mult", type=float, default=None)
    g.add_argument("--no-trail", dest="trail_enabled", action="store_false", default=None)
    g.add_argument("--breakeven-r", dest="breakeven_at_r", type=float, default=None,
                   help="استاپ را بعد از این R به نقطهٔ ورود ببر (0=خاموش)")
    g.add_argument("--partial-r", dest="partial_take_r", type=float, default=None,
                   help="خروج جزئی در این R (0=خاموش)")
    g.add_argument("--partial-frac", dest="partial_take_frac", type=float, default=None,
                   help="کسر خروج جزئی (پیش‌فرض 0.5)")
    g.add_argument("--max-concurrent", dest="max_concurrent", type=int, default=None)
    g.add_argument("--cooldown", dest="cooldown_bars_after_loss", type=int, default=None)
    g.add_argument("--cb-losses", dest="cb_losses", type=int, default=None)
    g.add_argument("--daily-loss", dest="daily_loss_limit_pct", type=float, default=None)
    g.add_argument("--next-open", dest="entry_on_next_open", action="store_true", default=None)

    g = p.add_argument_group("خروجی / اعتبارسنجی")
    g.add_argument("--out", dest="out_dir", default=None)
    g.add_argument("--run-id", dest="run_id", default=None)
    g.add_argument("--validate", action="store_true", default=None)
    g.add_argument("--mc", dest="monte_carlo_simulations", type=int, default=None)
    g.add_argument("--wf", dest="walk_forward_windows", type=int, default=None)
    g.add_argument("--quiet", dest="verbose", action="store_false", default=None)
    g.add_argument("--seed", type=int, default=None)
    return p


def load_config(argv: Optional[List[str]] = None) -> MTFConfig:
    """اولویت: CLI > فایل JSON > پیش‌فرض dataclass."""
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv or [])
    if unknown:
        raise SystemExit(f"آرگومان ناشناخته: {unknown}\n(راهنما: python3 -m mtflab --help)")

    cfg = MTFConfig()
    path = args.config or (default_config_path() if os.path.exists(default_config_path()) else "")
    file_vals = load_json_config(path) if path else {}
    valid = {f.name for f in fields(MTFConfig)}
    for k, v in file_vals.items():
        if k in valid:
            setattr(cfg, k, v)
        elif not str(k).startswith("_") and cfg.verbose:
            print(f"⚠️  کلید ناشناخته در کانفیگ نادیده گرفته شد: {k}")

    # پریست، بین فایل و CLI اعمال می‌شود: CLI همیشه حرف آخر را می‌زند.
    preset_name = args.preset or cfg.preset or "base"
    if preset_name not in PRESETS:
        raise SystemExit(f"پریست ناشناخته: {preset_name} (مجاز: {sorted(PRESETS)})")
    for k, v in PRESETS[preset_name].items():
        setattr(cfg, k, copy.deepcopy(v))
    cfg.preset = preset_name

    for k, v in vars(args).items():
        if k == "config" or v is None:
            continue
        if k in valid:
            setattr(cfg, k, v)

    _validate_config(cfg)
    return cfg


def _validate_config(cfg: MTFConfig) -> None:
    """جلوگیری از کانفیگ بی‌معنا قبل از اجرا (خطای صریح به‌جای نتیجهٔ غلط)."""
    from .data import tf_to_minutes
    t = tf_to_minutes(cfg.tf_trigger)
    f = tf_to_minutes(cfg.tf_filter)
    b = tf_to_minutes(cfg.tf_bias) if cfg.bias_enabled else 0
    if f < t:
        raise ValueError(f"تایم‌فریم فیلتر ({cfg.tf_filter}) باید >= تریگر ({cfg.tf_trigger}) باشد.")
    if cfg.bias_enabled and b < f:
        raise ValueError(f"تایم‌فریم بایاس ({cfg.tf_bias}) باید >= فیلتر ({cfg.tf_filter}) باشد.")
    if cfg.alignment_version not in ("A", "B", "C"):
        raise ValueError("alignment_version باید A یا B یا C باشد.")
    r = cfg.train_ratio + cfg.validation_ratio + cfg.out_of_sample_ratio
    if abs(r - 1.0) > 1e-6:
        raise ValueError(f"نسبت‌های split باید جمعاً ۱ شوند (الان {r}).")
    if cfg.stop_atr_mult <= 0 or cfg.take_profit_atr_mult <= 0:
        raise ValueError("ضریب‌های ATR برای stop/take باید مثبت باشند.")
    if cfg.max_concurrent < 1:
        raise ValueError("max_concurrent باید >= 1 باشد.")
    if cfg.data_mode == "csv" and not cfg.csv_path:
        raise ValueError("در حالت csv باید --csv مشخص شود.")
