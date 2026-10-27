# نتایج واقعی — داده‌ی واقعی Bybit (BTCUSDT 1h)

این صفحه نتیجه‌ی **استفاده از داده‌ی واقعی Bybit** برای تست الگوریتم TraderBrain است.
هیچ داده‌ی fake/synthetic استفاده نشده.

## منبع داده

- فایل: `data/btcusdt_1h_bybit.csv`
- منبع: repo GitHub `mestoness/btc-eth-candles-history` (کپی‌شده از Bybit)
-士والت: BTCUSDT perpetual، 1 ساعته
-长: 49,956 candle، 2020-03-25 → 2025-12-05
- سطرهای اولیه: `timestamp,open,high,low,close,volume`

## نتایج (ریسک ثابت ۱۰ USDT/معامله، slippage 0.05%، کارمزد 4 bps)

### کامل (FULL)
| شاخص | مقدار |
|---|---|
| تعداد معاملات | 216 |
| بگیر‌ها (win) | 85 (39.4%) |
| ضربه‌ها (loss) | 131 |
| Profit Factor | 0.976 (break-even) |
| Expectancy | −0.14 USDT/معامله |
| متوسط سودِ برنده | +1.63% |
| متوسط ضررِ بازنده | −1.02% |
| PnL کل | −30.27 USDT (−3.0%) |

### تفکیک Out-of-Sample (train/test 70-30)
| فترة | Profit Factor | Expectancy |
|---|---|---|
| TRAIN (2020-2024) | 0.976 | −0.14 |
| TEST (2024-2025) | 0.712 | −1.79 |

**تیرگی:** edge در TEST بدتر شد — استراتژی در داده‌ی out-of-sample **شکست** (PF<1). این
نتایج honest است، نه cherry-pick.

## است神明 بدنیا (bよねこの bug)

در gabrِ اول، نتیجه PF=1.93 (خیلی خوب) بود. اما بررسیِ دقیقِ journal نشان داد:

**bug تسلِ short:** stopِ تریلینگِ short روی `low_water − stop_dist×trail` گذاشته می‌شد
(زیرِ پایین‌ترین قیمت) → خروج با fillِ غیرواقعی (buy-backِ زیرِ market) → سودهای fake.

**تصحیح:** stopِ تریلینگِ short باید روی `low_water + stop_dist×trail` (بالاى low_water) باشد.
بعد از fix، PF از 1.93 به 0.98 (break-even) رسید — این نتیجه‌ی **واقعی** است.

## Diagnosisِ full (journal)

### از نظر reasonِ خروج
| reason | n | win | pnl |
|---|---|---|---|
| take_profit | 63 | 63 | +1168.17 |
| trailing_stop | 50 | 22 | −75.01 |
| stop_loss | 85 | 0 | −995.54 |
| regime_change_uptrend | 16 | 0 | −107.78 |
| regime_change_downtrend | 2 | 0 | −20.12 |

### از نظر regimeِ ورود
| regime | n | win | pnl |
|---|---|---|---|
| uptrend (long) | 118 | 45% | +83.25 |
| downtrend (short) | 98 | 33% | −113.52 |

### distributionِ بازگشت (net_pct)
| گلب | تعداد |
|---|---|
| −3% تا −1.5% | 19 |
| −1.5% تا −0.5% | 89 |
| −0.5% تا 0 | 20 |
| 0 تا +0.5% | 20 |
| +0.5% تا +1.5% | 22 |
| +1.5% تا +3% | 32 |
| +3% تا +5% | 11 |

- mean = +0.02% (break-even)
- median = −0.53%
- min = −3.54%, max = +4.94%
- std = 1.57%

## تعمیم (lessons)

1. **"یک سیگنال سودده در ماه = سیستم ۱۰۰%"،توهم است.** روی داده‌ی واقعی، 39% از
   معاملات سودده و در مجموع break-even هستند.
2. **bug تسلِ shortِ fake profitability را پیدا کرد.** بدون journal، این bug نامحسوس
   باقی می‌ماند.
3. **out-of-sample تست ضروری است.** TRAIN PF 0.98، TEST PF 0.71 — edge در dataِ جدید
   نگیر می‌کند.
4. **rigه شکارچی:** ترکیبِ ضرر + سود، lien است. 131 ضرر + 85 سود در این کار present است.

## rerun

```bash
# کامل
python3 -m scalplab trader --data csv --csv data/btcusdt_1h_bybit.csv --tf 60 \
    --symbol BTCUSDT --run-id bybit-final2 --risk 1.0 --fixed-risk 10 \
    --rr 2.0 --entry-mode both --equity 1000

# train
python3 -m scalplab trader --data csv --csv data/btcusdt_1h_train.csv --tf 60 \
    --symbol BTCUSDT --run-id bybit-tr2 --risk 1.0 --fixed-risk 10 --rr 2.0 --entry-mode both --equity 1000

# test
python3 -m scalplab trader --data csv --csv data/btcusdt_1h_test.csv --tf 60 \
    --symbol BTCUSDT --run-id bybit-te2 --risk 1.0 --fixed-risk 10 --rr 2.0 --entry-mode both --equity 1000
```

journal کامل:
- `results/trader_trades_bybit-final2.jsonl` (تمام معاملات، با diagnosis)
- `results/trader_signals_bybit-final2.jsonl` (تمام سیگنال‌های ورود)
