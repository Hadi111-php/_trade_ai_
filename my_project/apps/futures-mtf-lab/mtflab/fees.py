"""محاسبهٔ کارمزد، اسلیپیج و «فیلتر هزینه» (Cost/Edge Filter).

تمام مقادیر از کانفیگ خوانده می‌شوند؛ هیچ عددی hardcode نیست.

چرا این ماژول مهم است؟ در دادهٔ پرنوسانِ کم‌دامنه، کارمزد + اسلیپیج بیشترِ edge
را می‌بلعد (دقیقاً همان درسی که در `RESULTS_1YEAR_ANALYSIS.md` سناریوی قدیم
ثبت شده). پس سیگنال **قبل از ورود** باید از نظر اقتصادی توجیه داشته باشد:

    حرکت مورد انتظار >= min_edge_multiplier × هزینهٔ رفت‌وبرگشت
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeConfig:
    """هزینهٔ هر طرف معامله.

    `taker_fee_pct`: کارمزد taker به‌صورت کسر (0.00055 = 0.055% = 5.5bps)
    `slippage_pct` : اسلیپیج به‌صورت کسر (0.0002 = 0.02% = 2bps)
    """
    taker_fee_pct: float = 0.00055
    slippage_pct: float = 0.0002

    @classmethod
    def from_bps(cls, fee_bps: float, slippage_pct: float) -> "FeeConfig":
        """ساخت از قراردادهای بقیهٔ مخزن (کارمزد با bps، اسلیپیج با درصد)."""
        return cls(taker_fee_pct=float(fee_bps) / 10_000.0,
                   slippage_pct=float(slippage_pct) / 100.0)

    @property
    def one_side_pct(self) -> float:
        return (self.taker_fee_pct + self.slippage_pct) * 100.0


def one_side_cost_pct(fee_config: FeeConfig) -> float:
    """هزینهٔ یک طرف به درصد."""
    return fee_config.one_side_pct


def round_trip_cost_pct(fee_config: FeeConfig) -> float:
    """هزینهٔ کل یک معاملهٔ رفت‌وبرگشت (ورود + خروج) به درصدِ نوشنال.

    فرض: هم ورود و هم خروج با taker fee انجام می‌شود (محافظه‌کارانه‌ترین حالت).
    """
    return (fee_config.taker_fee_pct + fee_config.slippage_pct) * 2.0 * 100.0


def round_trip_cost_frac(fee_config: FeeConfig) -> float:
    """همان round_trip ولی به‌صورت کسر (برای محاسبات داخلی)."""
    return (fee_config.taker_fee_pct + fee_config.slippage_pct) * 2.0


def passes_cost_filter(expected_move_pct: float, fee_config: FeeConfig,
                       min_edge_multiplier: float = 1.5) -> bool:
    """سیگنال فقط وقتی معتبر است که سود موردانتظار >= ضریب × هزینه باشد.

    :param expected_move_pct: حرکت موردانتظار قیمت به درصد (مثلاً از ATR)
    :param fee_config: تنظیمات کارمزد/اسلیپیج
    :param min_edge_multiplier: حداقل نسبت سود به هزینه (پیش‌فرض 1.5)
    """
    cost = round_trip_cost_pct(fee_config)
    return expected_move_pct >= (cost * float(min_edge_multiplier))


def edge_ratio(expected_move_pct: float, fee_config: FeeConfig) -> float:
    """نسبت حرکت موردانتظار به هزینهٔ رفت‌وبرگشت (برای ثبت در فورنزیک)."""
    cost = round_trip_cost_pct(fee_config)
    return round(expected_move_pct / cost, 4) if cost > 0 else 0.0


def min_required_move_pct(fee_config: FeeConfig, min_edge_multiplier: float = 1.5) -> float:
    """حداقل حرکت لازم (درصد) تا یک سیگنال اصلاً بررسی شود — برای مستندسازی."""
    return round(round_trip_cost_pct(fee_config) * float(min_edge_multiplier), 6)


def fee_on_notional(notional: float, fee_bps: float) -> float:
    """کارمزد یک طرف روی نوشنال (USDT)."""
    return abs(float(notional)) * (float(fee_bps) / 10_000.0)


def slip_price(price: float, slippage_pct: float, direction: int) -> float:
    """قیمت پرشدنِ بدتر از بازار به‌خاطر اسلیپیج.

    direction=+1 (خرید) → قیمت بالاتر؛ direction=-1 (فروش) → قیمت پایین‌تر.
    """
    s = float(slippage_pct) / 100.0
    return price * (1 + s) if direction > 0 else price * (1 - s)
