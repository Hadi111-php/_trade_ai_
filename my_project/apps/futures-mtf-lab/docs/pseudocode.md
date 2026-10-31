# شبه‌کد حلقهٔ اصلی بک‌تست

نسخهٔ اجرایی: `mtflab/engine.py::run_backtest` · نگاشت خط‌به‌خط در انتهای سند.

---

## ۱) آماده‌سازی (یک‌بار)

```
FUNCTION run_backtest(cfg, layers):
    # layers = {trigger: [...], filter: [...], bias: [...]}   (همه صعودی و یکتا)

    # ۱. هم‌ترازی سه لایه — تنها راه مجازِ دیدن تایم‌فریم بالاتر
    bars ← align_multi_timeframe(
              layers.trigger, minutes(cfg.tf_trigger),
              layers.filter,  minutes(cfg.tf_filter),
              layers.bias,    minutes(cfg.tf_bias))       # → [AlignedBar]

    # ۲. آرایه‌های اندیکاتور هر لایه (کاملاً علی)
    ctx_trigger ← TFContext(layers.trigger, "trigger")
    ctx_filter  ← TFContext(layers.filter,  "filter")
    ctx_bias    ← TFContext(layers.bias,    "bias")

    # ۳. حسابرسی نشتی (assert در selftest، گزارش در output)
    audit ← leakage_audit(bars, minutes(tf_filter), minutes(tf_bias))
    ASSERT audit.clean

    state ← {equity: cfg.initial_equity, positions: [], trades: [],
             cooldown_until: -1, cb_until: -1, streak: 0, day: none}
```

## ۲) حلقهٔ اصلی — برای هر کندل تریگر

```
FOR i, bar IN enumerate(bars):
    candle ← bar.low_tf_candle

    # ── (الف) شمارش تأیید رژیم (فقط دادهٔ گذشته) ────────────────────────
    filt_now ← filter_state(ctx_filter, bar.higher_idx, cfg)
    update_regime_streak(state, filt_now.direction)

    # ── (ب) مدیریت پوزیشن‌های باز (پیش از هر ورود جدید) ─────────────────
    FOR pos IN copy(state.positions):
        stop_at_open ← pos.stop_current          # فقط از کندل‌های قبل معلوم است
        IF pos.long AND candle.low  ≤ stop_at_open:  exit = min(candle.open, stop_at_open); why="stop"
        ELIF pos.long AND candle.high ≥ pos.take:    exit = max(candle.open, pos.take);   why="take"
        ELIF pos.short AND candle.high ≥ stop_at_open: exit = max(candle.open, stop_at_open); why="stop"
        ELIF pos.short AND candle.low ≤ pos.take:      exit = min(candle.open, pos.take);    why="take"
        ELIF regime_flip_confirmed(state.streak ≥ cfg.filter_confirm_bars,
                                   filt_now.direction = −pos.dir): exit = candle.close; why="regime_flip"
        ELIF cfg.max_holding_bars > 0 AND i − pos.open_bar ≥ cfg.max_holding_bars:
                                                       exit = candle.close; why="time_stop"

        IF exit IS NOT NULL:
            close_position(pos, exit, why)        # کارمزد+اسلیپیج دو طرف، آپدیت equity
            IF loss: state.cooldown_until ← i + cfg.cooldown_bars_after_loss
            IF consecutive_losses ≥ cfg.cb_losses: state.cb_until ← i + cfg.cb_cooldown_bars
        ELSE:
            # تریلینگ در پایان کندل (نه داخل آن) — علی
            IF payout_in_R ≥ cfg.trail_start_r: pos.trail_active ← TRUE
            IF pos.trail_active:
                pos.stop_current ← max(pos.stop_current, pos.high_water − cfg.trail_atr_mult×ATR[i])

    # ── (ج) تصمیم ورود برای همان کندل ───────────────────────────────────
    trig ← trigger_state(ctx_trigger, i)                 # pullback | breakout | none
    bia  ← bias_state(ctx_bias, bar.bias_idx)            # +1 | 0 | −1
    info ← decide(bia, filt_now, trig, cfg, fee_config)  # نسخهٔ A/B/C + فیلتر هزینه

    IF info.action = ENTER:
        IF state.cb_until > i        : veto("circuit_breaker")
        ELIF i ≤ state.cooldown_until: veto("cooldown")
        ELIF state.daily_limit_hit   : veto("daily_loss")
        ELIF len(positions) ≥ cfg.max_concurrent: veto("slots")
        ELSE:
            entry_price ← candle.close                       # یا open کندل بعد با --next-open
            entry ← slippage(entry_price, +dir)
            stop_dist ← max(cfg.stop_atr_mult × ATR[i], 0.0008 × price)
            stop  ← entry − dir × stop_dist
            take  ← entry + dir × stop_dist × (take_atr / stop_atr)     # RR
            risk  ← fixed_risk>0 ? fixed_risk : equity × risk_pct/100
            qty   ← risk / stop_dist
            qty   ← min(qty, equity × max_leverage / entry)             # سقف اهرم
            open_position(entry, stop, take, qty, snapshot=...)
    ELSE:
        veto(info.veto_layer)                                # bias | filter | trigger | cost

    equity_curve.append({ts: candle.ts, equity: state.equity})
```

## ۳) پایان

```
# پوزیشن بازِ باقی‌مانده با برچسب صریح بسته می‌شود (تا در آمار «سود معلق» نماند)
FOR pos IN state.positions: close_position(pos, last.close, "end_of_data")

RETURN { summary, trades, equity_curve, health }
```

---

## ۴) قواعدی که در شبه‌کد عمداً «سخت» نوشته شده‌اند

| قاعده | چرا |
|---|---|
| `stop_at_open` از کندل قبل | اگر stop را با high/low همان کندل به‌روز کنیم و همان کندل چک کنیم، عملاً از آیندهٔ درون‌کندلی استفاده کرده‌ایم |
| stop قبل از take | وقتی هر دو در یک کندل لمس می‌شوند، ترتیب واقعی نامعلوم است؛ محافظه‌کارانه‌ترین فرض = ضرر |
| `veto` حتی در حالت HOLD | برای اینکه داشبورد بتواند بگوید «چرا معامله نکرد» (نه فقط «چه شد») |
| ورود در close کندل تریگر | تصمیم از اطلاعات همان کندل بسته‌شده گرفته می‌شود؛ ورود در open کندل بعد با `--next-open` محافظه‌کارانه‌تر است |

## ۵) نگاشت به کد

| شبه‌کد | کد |
|---|---|
| `align_multi_timeframe` | `mtflab/alignment.py` |
| `TFContext` / `bias_state` / `filter_state` / `trigger_state` | `mtflab/signals.py` |
| `decide` (A/B/C + فیلتر هزینه) | `mtflab/signals.py::decide` |
| حلقه و مدیریت پوزیشن | `mtflab/engine.py::run_backtest` / `MTFEngine` |
| `close_position` | `MTFEngine._close` |
| `leakage_audit` | `mtflab/alignment.py::leakage_audit` |
