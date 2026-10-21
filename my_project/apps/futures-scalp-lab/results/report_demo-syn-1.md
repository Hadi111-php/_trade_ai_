# گزارش Futures Scalp Lab

- run_id: `demo-syn-1` | نسخهٔ lab: `2026-08-26.1`
- **برچسب داده: دادهٔ مصنوعی — فقط اعتبارسنجی مکانیزم؛ NOT real market**
- symbol=BTCUSDT tf=1m horizon=8 fee=4.0bps cooldown=5 seeds=[42, 123, 777]
- کل سیگنال‌های ثبت‌شده: **4214** (هر سیگنال با اسنپ‌شات کامل اندیکاتورها در `signals_*.jsonl`)

## روش‌های اعتبارسنجی (pooled روی همهٔ seedها)

| روش | n | hit_gross | hit_net | CI95(hit_net) | خالص(bps) | PF | MAE | MFE |
|---|---|---|---|---|---|---|---|---|
| consensus_k3 ⭐ | 147 | 0.510 | 0.401 | [0.33,0.48] | -4.40 | 0.65 | -12.6 | 16.8 |
| bb_squeeze | 472 | 0.525 | 0.400 | [0.36,0.45] | -6.27 | 0.54 | -13.8 | 15.8 |
| ema_cross | 1190 | 0.476 | 0.344 | [0.32,0.37] | -9.10 | 0.39 | -14.7 | 13.5 |
| donchian_breakout | 508 | 0.467 | 0.341 | [0.30,0.38] | -9.18 | 0.4 | -14.6 | 13.9 |
| consensus_k2 | 693 | 0.478 | 0.349 | [0.31,0.39] | -9.19 | 0.4 | -14.9 | 13.9 |
| macd_flip | 481 | 0.484 | 0.347 | [0.31,0.39] | -9.23 | 0.37 | -14.6 | 13.5 |
| rsi_reversion | 389 | 0.468 | 0.332 | [0.29,0.38] | -10.03 | 0.38 | -15.9 | 13.2 |
| random_control | 316 | 0.532 | 0.373 | [0.32,0.43] | -6.62 | 0.49 | -12.8 | 14.5 |

## رتبه‌بندی: consensus_k3 > bb_squeeze > ema_cross > donchian_breakout > consensus_k2 > macd_flip > rsi_reversion

حاشیهٔ روش برتر نسبت به کنترل تصادفی: +2.22 bps به‌ازای هر سیگنال.

## کالیبراسیون: آیا confidence بالاتر یعنی hit بالاتر؟

| بازهٔ conf | n | hit_net |
|---|---|---|
| 0.5–0.6 | 1207 | 0.349 |
| 0.6–0.7 | 857 | 0.336 |
| 0.7–0.8 | 278 | 0.356 |
| 0.8–0.9 | 197 | 0.365 |
| 0.9–1.0 | 501 | 0.375 |

## تفکیک seed

- seed=42: bb_squeeze: n=161 hit_net=0.398, consensus_k2: n=237 hit_net=0.329, consensus_k3: n=57 hit_net=0.404, consensus_k4: n=5 hit_net=0.200, donchian_breakout: n=172 hit_net=0.320, ema_cross: n=393 hit_net=0.366, macd_flip: n=165 hit_net=0.309, random_control: n=105 hit_net=0.314, rsi_reversion: n=127 hit_net=0.252
- seed=123: bb_squeeze: n=157 hit_net=0.369, consensus_k2: n=232 hit_net=0.349, consensus_k3: n=46 hit_net=0.413, consensus_k4: n=9 hit_net=0.111, donchian_breakout: n=174 hit_net=0.356, ema_cross: n=403 hit_net=0.333, macd_flip: n=159 hit_net=0.340, random_control: n=102 hit_net=0.402, rsi_reversion: n=128 hit_net=0.352
- seed=777: bb_squeeze: n=154 hit_net=0.435, consensus_k2: n=224 hit_net=0.370, consensus_k3: n=44 hit_net=0.386, consensus_k4: n=4 hit_net=0.000, donchian_breakout: n=162 hit_net=0.346, ema_cross: n=394 hit_net=0.335, macd_flip: n=157 hit_net=0.395, random_control: n=109 hit_net=0.404, rsi_reversion: n=134 hit_net=0.388

---
یادآوری علمی: این اعداد فقط روی همین دادهٔ ورودی معتبرند. برای ادعای واقعی، همین pipeline باید روی دادهٔ واقعی (csv/binance) و ترجیحاً out-of-sample اجرا شود. هیچ عددی اینجا «سود واقعی» نیست.
