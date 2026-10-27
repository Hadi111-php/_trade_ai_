# تحلیلِ ۱-سالสุดท้าย Bybit — before/after + نسبتِ پنهان حجم vs سوددهی

داده: `data/btcusdt_1h_lastyear.csv` — BTCUSDT 1h، ۸,۷۶۰ candle، 2024-12-06 → 2025-12-05
(BTC از ۹۶,۹۷۷ به ۸۹,۱۸۹). ریسک ثابت ۱۰ USDT/معامله، slippage 0.05%، کارمزد 4 bps.

---

## ۱. مقایسه قبل/بعد تغییرات (۱ سال)

هر fixِ جداگانه revert شد تا impact مشخص شود:

| حالت | معاملات | بگیر | PF | Expectancy | lesson |
|---|---|---|---|---|---|
| **بعد (fixed کامل)** | 170 | 36% | **0.97** | −0.19 | realistik |
| shortbug reverted | 518 | 45% | **1.68** | +3.80 | **fake profit** — bug اصلی |
| exitclose reverted | 3 | 0% | **0.0** | −11.02 | مدار شکن زودِ active |
| regimeany reverted | 163 | 37% | 0.96 | −0.22 | تأثیر کم |

### lesson
1. **bug تسلِ short** عامل اصلیِ سودهای fake war (PF 1.68). بدون journal، نامحسوس war.
2. **خروج در close** (نه stop) باعثِ ضررهای gap-through می‌شود → مدار شکن زودِ active
   (PF 0). خروج در قیمتِ stop/take ضروری است.
3. **تغییرِ روند هر کسی** تأثیر کم دارد — winners' premature exit، اما impactِ کم.

---

## ۲. نسبتِ پنهان: حجم بازار vs سوددهی

### أ. حجمِ ورود vs سود
| ratioِ حجمِ ورود | n | avg PnL |
|---|---|---|
| **<0.5×avg** | 15 | **+4.08** (best) |
| 0.5-0.75× | 18 | −0.34 |
| 0.75-1.0× | 14 | −4.39 (worst) |
| 1.0-1.5× | 34 | +0.70 |
| 1.5-2.0× | 23 | −3.75 |
| >2.0× | 66 | +0.55 |

### ۲. حجمِ خروج vs سود
| ratioِ حجمِ خروج | n | avg PnL |
|---|---|---|
| <0.5×avg | 6 | −7.23 |
| 0.5-1.0× | 36 | −6.50 |
| 1.0-1.5× | 31 | −2.24 |
| 1.5-2.0× | 19 | +0.03 |
| **>2.0×avg** | 78 | **+4.01** (best) |

### ۳. Trendِ حجم درونِ trade (exit_vol/entry_vol)
| ratio | n | avg PnL |
|---|---|---|
| <0.5 (حجمِ کاهش) | 28 | −6.50 |
| 0.5-0.8 | 23 | −6.05 |
| 0.8-1.2 (شکسته) | 37 | +0.39 |
| 1.2-2.0 | 34 | +0.23 |
| **>2.0 (حجمِ افزایش)** | 48 | **+5.55** (best) |

### lessonِ کلیدی
1. **ورود در حجمِ پایین (<0.5×avg) بهترین است** — avoidsِ stop-hunts و نویز.
2. **خروج در حجمِ بالا (>2×avg) بهترین است** — fillِ بهتر و confirmation.
3. **حجمِ در حال افزایش درونِ trade = +5.55** — یعنی روند معتبر است.
4. **حجمِ کاهش = روند dying = −6.50** — یعنی باید خروج کنید.
5. **حدِ وسطِ حجم (0.75-1.0×) بدترین است** — سیگنال ambiguous، بیشترِ میزنِ شکن.

---

## ۳. Time-of-day (UTC) vs سوددهی

| hour | avg PnL | | hour | avg PnL |
|---|---|---|---|---|
| **00:00** | **+9.55** | | 11:00 | −8.75 |
| **09:00** | **+7.59** | | 14:00 | −1.22 |
| **18:00** | **+8.96** | | 02:00 | −6.69 |
| **19:00** | **+5.87** | | 05:00 | −3.31 |
| 16:00 | +0.85 | | 20:00 | −5.27 |

بهترین ساعات: ۰۰، ۰۹، ۱۸، ۱۹ UTC. بدترین: ۱۱، ۰۲، ۲۰، ۰۵ UTC.

---

## ۴. Tesِ out-of-sample (۵۰-۵۰ splitِ ۱ سال)

| فترة | baseline | low-vol filter |
|---|---|---|
| H1 (نیم‌سال اول) | PF 0.97 | **PF 1.21** (profitable) |
| H2 (نیم‌سال دوم) | PF 0.50 | PF 0.77 (هنوز ضرر) |

**تیرگی:** low-vol filter در H1 مفید است، اما در H2 (periodِ range-bound 2025 آخر)
edge نمی‌گیرد. استراتژی trend-following در بازار range-bound شکست می‌خورد.

---

## ۵. برای تنظیمِ دقیق‌تر (tuning suggestions)

### أ. فیلتر حجمِ ورود
- از `--vol-entry-filter --vol-entry-lo 0.5 --vol-entry-hi 99` استفاده کنید
  (ورود فقط در حجمِ <0.5×avg).
- این PF را از 0.97 به 1.12 (full) / 1.21 (H1) می‌برد — اما H2 شکست می‌خورد.

### ۲. فیلتر حجمِ خروج
- take_profit فقط وقتی exit کن که حجمِ کافی (ratio ≥1.0) داشته باشید.
- این خروجِ زودِ در حجمِ پایین جلوگیری می‌کند.

### ۳. تغییرِ ساختاری (برای profitable شدن)
- **Multi-timeframe:** 4h trend + 1h entry.
- **Regime detectionِ قوی‌تر:** اضافهِ funding rate، open interest، order flow.
- **خروجِ adaptive:** trailingِ منطقی به luxِ حجمِ بازار (حجمِ کاهش = خروجِ زودی).
- **تخصیصِ riskِ dynamique:** اهرمِ متحرک به luxِ regime.

### ۴. محدودیت‌ها
- این نتیجه روی BTC 1h است (نسبت به资产管理ی خاص).
- 1 سال داده — sampleِ محدود.
- out-of-sample (H2) شکست می‌خورد — استراتژی نیاز به redesign دارد، نه فقط parameter tuning.

---

## rerun

```bash
# before/after comparison
python3 -m scalplab trader --data csv --csv data/btcusdt_1h_lastyear.csv --tf 60 \
    --symbol BTCUSDT --run-id ly-base --risk 1.0 --fixed-risk 10 --rr 2.0 --entry-mode both --equity 1000
python3 -m scalplab trader --data csv --csv data/btcusdt_1h_lastyear.csv --tf 60 \
    --symbol BTCUSDT --run-id ly-shortbug --risk 1.0 --fixed-risk 10 --rr 2.0 --entry-mode both --equity 1000 --legacy-short-trail-bug

# low-volume entry filter
python3 -m scalplab trader --data csv --csv data/btcusdt_1h_lastyear.csv --tf 60 \
    --symbol BTCUSDT --run-id ly-vlow --risk 1.0 --fixed-risk 10 --rr 2.0 --entry-mode both --equity 1000 \
    --vol-entry-filter --vol-entry-lo 0.5 --vol-entry-hi 99
```
