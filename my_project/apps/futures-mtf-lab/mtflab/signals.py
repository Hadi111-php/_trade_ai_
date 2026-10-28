"""لایهٔ سیگنال چندتایم‌فریمی: بایاس / فیلتر / تریگر + نسخه‌های هم‌راستایی A/B/C.

جدول قوانین کامل در `docs/strategy_design.md` است؛ خلاصه:

| لایه | تایم‌فریم | نقش | قاعده |
|---|---|---|---|
| بایاس | tf_bias (پیش‌فرض 4h) | جهت مجازِ کلان | close vs EMA200 + شیب EMA + ساختار HH/HL |
| فیلتر | tf_filter (پیش‌فرض 1h) | رژیم/جهت | ADX≥22 + شیب EMA50 + close vs EMA50 |
| تریگر | tf_trigger (پیش‌فرض 15m) | نقطهٔ ورود | pullback به EMA21 با RSI، یا شکست Donchian20 با volume_z |

نسخه‌های هم‌راستایی:
- **A** = AND سخت‌گیرانه: بایاس ∧ فیلتر ∧ تریگر هم‌جهت
- **B** = امتیاز وزنی: w_b·بایاس + w_f·فیلتر + w_t·تریگر ≥ آستانه
- **C** = فقط فیلتر رژیم: لایهٔ بایاس نادیده گرفته می‌شود

همهٔ توابع این ماژول **خالص** هستند: ورودی = آرایه‌های از قبل محاسبه‌شدهٔ علی
+ ایندکس؛ خروجی = یک وضعیت. هیچ حالت داخلی/تصادفی وجود ندارد.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .data import Candle
from .fees import FeeConfig, edge_ratio, passes_cost_filter, round_trip_cost_pct
from . import indicators as ind

TREND_UP = "uptrend"
TREND_DOWN = "downtrend"
SIDEWAYS = "sideways"


# ----------------------------------------------------------------------------
# زمینهٔ هر تایم‌فریم (آرایه‌های اندیکاتور، همه علی)
# ----------------------------------------------------------------------------
class TFContext:
    """آرایه‌های اندیکاتور یک تایم‌فریم + دسترسی به وضعیتِ خانهٔ i."""

    def __init__(self, candles: Sequence[Candle], cfg, layer: str):
        self.candles = list(candles)
        self.layer = layer
        closes = [c.close for c in self.candles]
        p = cfg
        # انتخاب پارامترها بر اساس نقش لایه
        if layer == "bias":
            ema_period = p.bias_ema_period
            slope_bars = p.bias_slope_bars
            slope_min = p.bias_slope_min_pct
            don_w = p.bias_donchian_window
            adx_period, adx_min = p.filter_adx_period, p.filter_adx_min
        elif layer == "filter":
            ema_period = p.filter_ema_period
            slope_bars = p.filter_slope_bars
            slope_min = p.filter_slope_min_pct
            don_w = p.trigger_donchian_window
            adx_period, adx_min = p.filter_adx_period, p.filter_adx_min
        else:                                   # trigger
            ema_period = p.trigger_ema_period
            slope_bars = 3
            slope_min = 0.0
            don_w = p.trigger_donchian_window
            adx_period, adx_min = p.filter_adx_period, p.filter_adx_min

        self.ema_main = ind.ema(closes, ema_period)
        self.ema_main_slope = ind.slope_pct(self.ema_main, slope_bars)
        self.ema_fast = ind.ema(closes, p.filter_ema_fast_period) if layer == "filter" \
            else ind.ema(closes, p.trigger_ema_period)
        self.rsi = ind.rsi(closes, p.trigger_rsi_period)
        self.atr = ind.atr(self.candles, p.trigger_atr_period if layer == "trigger" else 14)
        self.atr_pct = ind.atr_pct(self.candles, p.trigger_atr_period if layer == "trigger" else 14)
        self.adx = ind.adx(self.candles, adx_period)
        self.don = ind.donchian(self.candles, don_w)
        self.bb = ind.bollinger(closes, 20)
        self.volz = ind.volume_z(self.candles, p.trigger_vol_window)
        self.volr = ind.volume_ratio(self.candles, p.trigger_vol_window)
        self.structure = ind.market_structure(self.candles, don_w)
        self.ema_period = ema_period
        self.slope_min = slope_min
        self.adx_min = adx_min
        self.don_w = don_w
        self.n = len(self.candles)

    def ready(self, i: int) -> bool:
        """آیا خانهٔ i دادهٔ کافی دارد (warmup تمام شده)؟"""
        if i < 0 or i >= self.n:
            return False
        return (self.ema_main[i] is not None and self.adx[i] is not None
                and self.atr[i] is not None and self.rsi[i] is not None
                and self.don[i]["upper"] is not None)

    def snapshot(self, i: int) -> dict:
        if i < 0 or i >= self.n:
            return {}
        c = self.candles[i]
        return {
            "ts": c.open_time_ms, "close": c.close,
            "ema_main": _r(self.ema_main[i]), "ema_main_slope_pct": _r(self.ema_main_slope[i]),
            "ema_fast": _r(self.ema_fast[i]), "rsi": _r(self.rsi[i]),
            "atr": _r(self.atr[i], 4), "atr_pct": _r(self.atr_pct[i], 4),
            "adx": _r(self.adx[i]), "don_pos": _r(self.don[i]["pos"]),
            "don_upper": _r(self.don[i]["upper"]), "don_lower": _r(self.don[i]["lower"]),
            "bb_pos": _r(self.bb[i]["pos"]), "bb_width": _r(self.bb[i]["width"], 5),
            "vol_z": _r(self.volz[i]), "vol_ratio": _r(self.volr[i]),
            "structure_dir": self.structure[i]["direction"],
            "structure_score": _r(self.structure[i]["score"]),
        }


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


# ----------------------------------------------------------------------------
# وضعیت لایه‌ها
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class LayerState:
    direction: int          # +1 / -1 / 0
    strength: float         # 0..1
    regime: str             # uptrend / downtrend / sideways / unknown
    reason: str
    detail: dict = field(default_factory=dict)


UNKNOWN = LayerState(0, 0.0, "unknown", "دادهٔ لایه موجود نیست (warmup/گپ)")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def bias_state(ctx: Optional[TFContext], i: int, cfg) -> LayerState:
    """لایهٔ بایاس (کلان): جهتِ مجازِ معامله را تعیین می‌کند.

    قاعده: close نسبت به EMA(bias_ema_period) + شیب همان EMA + ساختار HH/HL.
    ارزش افزودهٔ این لایه (پاسخ به سوال AGENT_TASK): جلوی «شکارِ سیگنال‌های
    خلافِ جهت کلان» را می‌گیرد؛ یعنی فیلتر 1h ممکن است در یک اصلاحِ موقتِ
    داخلِ روندِ بزرگ، جهتِ مخالف بدهد و بایاس 4h آن را وتو کند.
    """
    if not cfg.bias_enabled or ctx is None or i < 0 or i >= ctx.n or not ctx.ready(i):
        return UNKNOWN
    c = ctx.candles[i]
    ema_v = ctx.ema_main[i]
    slope = ctx.ema_main_slope[i] or 0.0
    st = ctx.structure[i]
    above = c.close > ema_v
    dir_ema = 1 if (above and slope >= ctx.slope_min) else (-1 if ((not above) and slope <= -ctx.slope_min) else 0)
    dir_struct = st["direction"]

    if dir_ema == 0:
        direction, regime = 0, SIDEWAYS
        reason = f"EMA{ctx.ema_period} بدون جهت (شیب {slope:+.3f}%)"
    elif dir_struct != 0 and dir_struct != dir_ema:
        direction, regime = 0, SIDEWAYS
        reason = f"تضاد EMA ({'+' if dir_ema>0 else '-'}) با ساختار ({'+' if dir_struct>0 else '-'})"
    else:
        direction = dir_ema
        regime = TREND_UP if direction > 0 else TREND_DOWN
        reason = f"EMA{ctx.ema_period} + شیب {slope:+.3f}% + ساختار تأیید"

    strength = _clamp(0.5 * min(abs(slope) / max(ctx.slope_min * 4, 1e-9), 1.0)
                      + 0.3 * (1.0 if dir_struct == direction and direction != 0 else 0.0)
                      + 0.2 * min((ctx.adx[i] or 0.0) / 40.0, 1.0))
    return LayerState(direction, round(strength, 4), regime, reason,
                      {"ema": _r(ema_v), "slope_pct": _r(slope, 4), "structure": st["direction"],
                       "adx": _r(ctx.adx[i])})


def filter_state(ctx: Optional[TFContext], i: int, cfg,
                 confirm_bars: Optional[int] = None) -> LayerState:
    """لایهٔ فیلتر (رژیم/جهت): ADX + شیب EMA + موقعیت close.

    `confirm_bars`: اگر >1 باشد، جهتِ خام باید N کندلِ متوالی همان بماند تا
    تأیید شود (جلوگیری از whipsaw در مرزِ رژیم). این شمارش فقط از خانه‌های
    `<= i` استفاده می‌کند → علی است.
    """
    if ctx is None or i < 0 or i >= ctx.n or not ctx.ready(i):
        return UNKNOWN
    c = ctx.candles[i]
    adx_v = ctx.adx[i] or 0.0
    slope = ctx.ema_main_slope[i] or 0.0
    ema_v = ctx.ema_main[i]
    above = c.close > ema_v

    if adx_v >= ctx.adx_min and slope >= ctx.slope_min and above:
        raw, regime = 1, TREND_UP
    elif adx_v >= ctx.adx_min and slope <= -ctx.slope_min and not above:
        raw, regime = -1, TREND_DOWN
    else:
        raw, regime = 0, SIDEWAYS

    n_conf = int(confirm_bars if confirm_bars is not None else cfg.filter_confirm_bars)
    if raw != 0 and n_conf > 1:
        streak = 0
        j = i
        while j >= 0 and streak < n_conf:
            st_j = _raw_filter_dir(ctx, j)
            if st_j != raw:
                break
            streak += 1
            j -= 1
        if streak < n_conf:
            return LayerState(0, 0.0, SIDEWAYS,
                              f"رژیم {regime} اما تأیید {streak}/{n_conf} کندل (whipsaw)",
                              {"adx": _r(adx_v), "slope_pct": _r(slope, 4), "streak": streak})

    strength = _clamp(0.6 * min(adx_v / max(ctx.adx_min * 2, 1e-9), 1.0)
                      + 0.4 * min(abs(slope) / max(ctx.slope_min * 4, 1e-9), 1.0)) if raw else \
        _clamp(0.3 * min(adx_v / max(ctx.adx_min, 1e-9), 1.0))
    reason = (f"ADX={adx_v:.1f} (حد {ctx.adx_min:.0f})، شیب EMA{ctx.ema_period}={slope:+.3f}%، "
              f"close {'>' if above else '<'} EMA")
    return LayerState(raw, round(strength, 4), regime, reason,
                      {"adx": _r(adx_v), "slope_pct": _r(slope, 4), "ema": _r(ema_v),
                       "streak": n_conf})


def _raw_filter_dir(ctx: TFContext, i: int) -> int:
    if not ctx.ready(i):
        return 0
    adx_v = ctx.adx[i] or 0.0
    slope = ctx.ema_main_slope[i] or 0.0
    above = ctx.candles[i].close > ctx.ema_main[i]
    if adx_v >= ctx.adx_min and slope >= ctx.slope_min and above:
        return 1
    if adx_v >= ctx.adx_min and slope <= -ctx.slope_min and not above:
        return -1
    return 0


@dataclass(frozen=True)
class TriggerSignal:
    direction: int          # +1 / -1 / 0
    strength: float         # 0..1
    mode: str               # pullback | breakout | none
    reason: str
    expected_move_pct: float = 0.0
    detail: dict = field(default_factory=dict)


NO_TRIGGER = TriggerSignal(0, 0.0, "none", "تریگری برقرار نیست")


def trigger_state(ctx: TFContext, i: int, cfg) -> TriggerSignal:
    """لایهٔ تریگر: نقطهٔ دقیق ورود روی تایم‌فریم پایین.

    دو راه ورود (قابل انتخاب با `--entry-modes`):
    1. **pullback**: قیمت به EMA(21) نزدیک است (≤ 0.7×ATR) و RSI هنوز اشباع
       نشده → ورود در جهتِ لایه‌های بالاتر با قیمتِ بهتر.
    2. **breakout**: شکست کانال Donchian(20) با تأیید حجم (volume_z ≥ حد).
    """
    if not ctx.ready(i):
        return NO_TRIGGER
    c = ctx.candles[i]
    atr_v = ctx.atr[i] or 0.0
    if atr_v <= 0:
        return NO_TRIGGER
    rsi_v = ctx.rsi[i]
    ema_v = ctx.ema_fast[i]
    don = ctx.don[i]
    volz = ctx.volz[i] or 0.0
    modes = cfg.trigger_entry_modes or ["pullback", "breakout"]

    # --- pullback (دو طرفه؛ جهت در لایهٔ هم‌راستایی تعیین می‌شود) ---
    if "pullback" in modes and ema_v is not None:
        dist = abs(c.close - ema_v)
        if dist <= cfg.trigger_pullback_atr * atr_v:
            if rsi_v is not None and rsi_v <= cfg.trigger_rsi_long_max:
                strength = _clamp(1.0 - dist / max(cfg.trigger_pullback_atr * atr_v, 1e-9))
                return TriggerSignal(1, round(0.4 + 0.6 * strength, 4), "pullback",
                                     f"pullback به EMA{cfg.trigger_ema_period} "
                                     f"(فاصله {dist/atr_v:.2f}×ATR، RSI={rsi_v:.1f})",
                                     _r(atr_v / c.close * 100.0 * cfg.edge_atr_mult, 4),
                                     {"dist_atr": _r(dist / atr_v, 3), "rsi": _r(rsi_v)})
            if rsi_v is not None and rsi_v >= cfg.trigger_rsi_short_min:
                strength = _clamp(1.0 - dist / max(cfg.trigger_pullback_atr * atr_v, 1e-9))
                return TriggerSignal(-1, round(0.4 + 0.6 * strength, 4), "pullback",
                                     f"pullback به EMA{cfg.trigger_ema_period} "
                                     f"(فاصله {dist/atr_v:.2f}×ATR، RSI={rsi_v:.1f})",
                                     _r(atr_v / c.close * 100.0 * cfg.edge_atr_mult, 4),
                                     {"dist_atr": _r(dist / atr_v, 3), "rsi": _r(rsi_v)})

    # --- breakout ---
    if "breakout" in modes and don["upper"] is not None:
        pos = don["pos"] or 0.5
        if pos >= cfg.trigger_donchian_pos_long and volz >= cfg.trigger_vol_z_min:
            return TriggerSignal(1, round(_clamp(0.45 + 0.15 * volz), 4), "breakout",
                                 f"شکست سقف Donchian{cfg.trigger_donchian_window} "
                                 f"(pos={pos:.2f}، vol_z={volz:.2f})",
                                 _r(atr_v / c.close * 100.0 * cfg.edge_atr_mult, 4),
                                 {"don_pos": _r(pos, 3), "vol_z": _r(volz)})
        if pos <= cfg.trigger_donchian_pos_short and volz >= cfg.trigger_vol_z_min:
            return TriggerSignal(-1, round(_clamp(0.45 + 0.15 * volz), 4), "breakout",
                                 f"شکست کف Donchian{cfg.trigger_donchian_window} "
                                 f"(pos={pos:.2f}، vol_z={volz:.2f})",
                                 _r(atr_v / c.close * 100.0 * cfg.edge_atr_mult, 4),
                                 {"don_pos": _r(pos, 3), "vol_z": _r(volz)})

    return TriggerSignal(0, 0.0, "none", "نه pullback و نه breakout برقرار نیست",
                         _r(atr_v / c.close * 100.0 * cfg.edge_atr_mult, 4))


# ----------------------------------------------------------------------------
# هم‌راستایی A / B / C
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Decision:
    action: str             # ENTER | WAIT | HOLD
    direction: int
    confidence: float
    score: float
    reason: str
    version: str
    layers: dict = field(default_factory=dict)
    cost_check: dict = field(default_factory=dict)
    veto_layer: str = ""        # bias | filter | trigger | cost | confidence | data


def decide(bias: LayerState, filt: LayerState, trig: TriggerSignal,
           cfg, fee_config: FeeConfig) -> Decision:
    """تصمیم نهایی بر اساس نسخهٔ هم‌راستایی + فیلتر هزینه.

    ترتیب بررسی‌ها عمداً این‌گونه است:
    1) لایه‌های بالا (ارزان‌ترین وتو) → 2) تریگر → 3) فیلتر اقتصادی هزینه.
    این ترتیب باعث می‌شود دلیلِ رد شدن هر سیگنال دقیق و قابل حساب باشد
    (برای ستون «چرا معامله نکرد» در داشبورد).
    """
    layers = {
        "bias": {"dir": bias.direction, "strength": bias.strength, "regime": bias.regime,
                 "reason": bias.reason},
        "filter": {"dir": filt.direction, "strength": filt.strength, "regime": filt.regime,
                   "reason": filt.reason},
        "trigger": {"dir": trig.direction, "strength": trig.strength, "mode": trig.mode,
                    "reason": trig.reason},
    }

    if bias.regime == "unknown" and cfg.bias_enabled:
        return Decision("WAIT", 0, 0.0, 0.0, "لایهٔ بایاس هنوز دادهٔ بسته ندارد",
                        cfg.alignment_version, layers, veto_layer="data")
    if filt.regime == "unknown":
        return Decision("WAIT", 0, 0.0, 0.0, "لایهٔ فیلتر هنوز دادهٔ بسته ندارد",
                        cfg.alignment_version, layers, veto_layer="data")
    if trig.direction == 0:
        return Decision("WAIT", 0, 0.0, 0.0, trig.reason, cfg.alignment_version, layers,
                        veto_layer="trigger")

    version = cfg.alignment_version
    direction, score, reason = 0, 0.0, ""

    _veto = ""
    if version == "A":
        # AND سخت‌گیرانه: همهٔ لایه‌های فعال هم‌جهت
        need = [filt.direction, trig.direction] + ([bias.direction] if cfg.bias_enabled else [])
        if all(d == trig.direction for d in need) and trig.direction != 0:
            direction = trig.direction
            score = round(sum(s.strength for s in
                              ([bias] if cfg.bias_enabled else []) + [filt,
                               LayerState(trig.direction, trig.strength, "", "")]) /
                          (3 if cfg.bias_enabled else 2), 4)
            reason = "A: بایاس ∧ فیلتر ∧ تریگر هم‌جهت"
        else:
            dirs = {("bias" if cfg.bias_enabled else "-"): bias.direction,
                    "filter": filt.direction, "trigger": trig.direction}
            reason = f"A: هم‌راستایی برقرار نیست {dirs}"
            _vl = ("bias" if (cfg.bias_enabled and bias.direction != trig.direction)
                   else "filter" if filt.direction != trig.direction else "trigger")
            _veto = _vl

    elif version == "B":
        # امتیازدهی وزنی — اجازهٔ معامله وقتی یک لایه خنثی است ولی بقیه قوی‌اند
        s = ((cfg.score_w_bias * bias.direction * bias.strength if cfg.bias_enabled else 0.0)
             + cfg.score_w_filter * filt.direction * filt.strength
             + cfg.score_w_trigger * trig.direction * trig.strength)
        wsum = (cfg.score_w_bias if cfg.bias_enabled else 0.0) + cfg.score_w_filter + cfg.score_w_trigger
        score = round(s / wsum, 4) if wsum else 0.0
        direction = 1 if score > 0 else (-1 if score < 0 else 0)
        if abs(score) >= cfg.score_min and direction == trig.direction:
            reason = f"B: امتیاز وزنی {score:+.3f} ≥ {cfg.score_min}"
        elif abs(score) < cfg.score_min:
            direction = 0
            _veto = "bias" if (cfg.bias_enabled and bias.direction == 0) else "filter"
            reason = f"B: امتیاز {score:+.3f} زیر آستانهٔ {cfg.score_min}"
        else:
            direction = 0
            _veto = "bias" if (cfg.bias_enabled and bias.direction != trig.direction) else "filter"
            reason = f"B: جهت امتیاز ({'+' if score>0 else '-'}) با تریگر مخالف است"

    else:                                   # C
        if cfg.bias_enabled:
            layers["bias"]["ignored"] = True   # در نسخه C بایاس عمداً نادیده گرفته می‌شود
        if filt.direction == trig.direction and filt.direction != 0:
            direction = trig.direction
            score = round((filt.strength + trig.strength) / 2.0, 4)
            reason = "C: فیلتر رژیم ∧ تریگر هم‌جهت (بایاس نادیده)"
        else:
            _veto = "filter"
            reason = f"C: فیلتر ({filt.direction}) با تریگر ({trig.direction}) هم‌جهت نیست"

    if direction == 0:
        return Decision("WAIT", 0, 0.0, score, reason, version, layers, veto_layer=_veto)

    # ── فیلتر اقتصادی هزینه (fees.py) ─────────────────────────────────────
    expected = trig.expected_move_pct
    ok = passes_cost_filter(expected, fee_config, cfg.min_edge_multiplier)
    cost_check = {
        "expected_move_pct": expected,
        "round_trip_cost_pct": round(round_trip_cost_pct(fee_config), 5),
        "min_edge_multiplier": cfg.min_edge_multiplier,
        "edge_ratio": edge_ratio(expected, fee_config),
        "passed": ok,
    }
    if not ok:
        return Decision("WAIT", 0, 0.0, score,
                        f"ردِ اقتصادی: حرکت مورد انتظار {expected:.4f}% < "
                        f"{cfg.min_edge_multiplier}× هزینه ({round_trip_cost_pct(fee_config):.4f}%)",
                        version, layers, cost_check, veto_layer="cost")

    confidence = round(_clamp(score), 4)
    if confidence < cfg.min_confidence:
        return Decision("WAIT", 0, confidence, score,
                        f"اعتماد {confidence:.2f} زیر حد {cfg.min_confidence}", version, layers,
                        cost_check, veto_layer="confidence")

    return Decision("ENTER", direction, confidence, score,
                    f"{reason} | تریگر: {trig.mode}", version, layers, cost_check)
