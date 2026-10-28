# Futures MTF Lab — سناریوی معاملاتی چندتایم‌فریمی (PAPER)

نسخه: `2026-10-28.1` · **فقط کتابخانهٔ استاندارد پایتون** (بدون numpy / pandas /
requests / pyyaml / pytest) · اجرا روی هر PC، گوشی (Termux) و VPS بدون `pip install`.

> **این اپ مستقل از `apps/futures-scalp-lab` (سناریوی قدیم) است.** هیچ فایلی از آن
> تغییر نکرده؛ اتصال فقط از طریق `mtflab/compare.py` و به‌صورت فقط‌خواندنی است تا
> داشبورد مقایسه ساخته شود.

> **اصل طلایی:** هیچ عددی «سود واقعی» نیست مگر روی دادهٔ واقعی و out-of-sample،
> پس از کسر کامل هزینه، و با اختلاف معنادار از خط پایه. LIVE عمداً پیاده نشده است.

---

## ۱) این اپ چه می‌کند؟

| قابلیت | توضیح |
|---|---|
| **هم‌ترازی سه‌لایه** | بایاس (4h) + فیلتر رژیم (1h) + تریگر ورود (15m) — با هم‌ترازی تست‌شده و بدون lookahead |
| **سه نسخهٔ هم‌راستایی** | A (AND سخت‌گیرانه) · B (امتیاز وزنی) · C (فقط فیلتر رژیم) |
| **فیلتر اقتصادی هزینه** | سیگنالی که حرکت مورد انتظارش < ۱.۵× هزینهٔ رفت‌وبرگشت باشد رد می‌شود |
| **مدیریت ریسک** | ریسک ۱٪ موجودی، SL 1.5×ATR، TP 3×ATR، تریلینگ بعد از +1R، کول‌داون، مدار شکن، حد ضرر روزانه |
| **فورنزیک کامل** | هر سیگنال/وتو/معامله در JSONL با اسنپ‌شات همهٔ لایه‌ها، MFE/MAE و تشخیص دلیل سود/ضرر |
| **اعتبارسنجی** | split 60/20/20 · walk-forward ۶ پنجره با انتخاب مجدد آستانه · مونت‌کارلو ۱۰۰۰ · حساسیت · خط‌های پایه · چک‌لیست overfit |
| **داشبورد مقایسه** | HTML خودکفا با ۵ تب، مقایسهٔ سناریوی قدیم و جدید روی دادهٔ یکسان |
| **دانلودر Bybit** | دادهٔ عمومی بدون API key، با صفحه‌بندی، کش CSV و retry |

## ۲) نصب و اجرا (سه دستور)

```bash
cd apps/futures-mtf-lab

# ۱) خودآزمایی — قبل از هر کاری
python3 -m mtflab selftest

# ۲) مقایسهٔ سناریوی قدیم و جدید روی همان دادهٔ واقعی موجود + ساخت داشبورد
python3 -m mtflab compare \
  --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv \
  --out results/dash_scenarios.html

# ۳) گزارش تشخیصی: چرا سود کم برداشت می‌شود + آزمون سود شناور
python3 -m mtflab diagnose \
  --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv \
  --tf-trigger 1h --tf-filter 4h --tf-bias 1d --align A --bias-ema 50 \
  --out results/diagnosis_report.md

# ۴) دیدن داشبورد در مرورگر
python3 -m mtflab serve --dir results --port 8080
#   → http://localhost:8080/dash_scenarios.html
```

## ۳) دانلود دادهٔ 15m و اجرای طراحی اصلی سناریو

سناریو برای **15m / 1h / 4h** طراحی شده، ولی دادهٔ 15m در ریپو نیست
(و از 1h هم ساخته نمی‌شود — `resample_up` اجازه نمی‌دهد). روی PC خودت:

```bash
# حدود ۲ سال دادهٔ سه تایم‌فریم (بدون API key)
python3 -m mtflab download --symbol BTCUSDT --days 730

# بک‌تست + اعتبارسنجی کامل روی 15m
python3 -m mtflab validate --data bybit --symbol BTCUSDT \
  --tf-trigger 15m --tf-filter 1h --tf-bias 4h --align A

# مقایسهٔ نسخه‌های A/B/C (هر کدام یک اجرای مستقل)
python3 -m mtflab run --data bybit --symbol BTCUSDT --align B
python3 -m mtflab run --data bybit --symbol BTCUSDT --align C
```

## ۴) دستورهای CLI

| دستور | کار |
|---|---|
| `run` (پیش‌فرض) | بک‌تست یک سناریو |
| `validate` | بک‌تست + اعتبارسنجی کامل |
| `compare` | دو سناریو روی دادهٔ یکسان + داشبورد تب‌دار |
| `diagnose` | کالبدشکافی خروج + ۱۵ سیاست سود شناور + ۱۲ فرضیهٔ ورود + گزارش فارسی |
| `download` | دانلود دادهٔ عمومی Bybit (15m/1h/4h) |
| `dashboard` | بازسازی داشبورد از JSON ذخیره‌شده |
| `serve` | سرو داشبوردها در مرورگر (stdlib) |
| `selftest` | تست‌ها + علی‌بودن + نشتی + فیلتر هزینه |

نمونهٔ کامل پارامترها: `python3 -m mtflab --help`

## ۵) دیدن داشبورد — ۵ تب

| تب | محتوا |
|---|---|
| 🔀 **مقایسه** | KPI دو سناریو، منحنی موجودی هم‌پوشان، جدول دو مدل هزینه، حکم نهایی + آزمون معناداری |
| 🧠 **سناریوی قدیم** | جزئیات TraderBrain: رژیم، دلیل خروج، ساعت، بهترین/بدترین معاملات |
| 🧩 **سناریوی جدید** | مقایسهٔ A/B/C، آمار «چرا معامله نکرد» (وتوی هر لایه)، سلامت هم‌ترازی |
| ✅ **اعتبارسنجی** | split، walk-forward، مونت‌کارلو، خط‌های پایه، حساسیت، چک‌لیست overfit |
| 🛡️ **سلامت و دام‌ها** | نتیجهٔ تست‌های ضد lookahead، گپ داده، فهرست دام‌ها، ردپای اجرا |

## ۶) نتایج فعلی (BTCUSDT 1h، ۱ سال، هزینهٔ یکسان)

| | معاملات | PF | Expectancy | بازده | MaxDD |
|---|---|---|---|---|---|
| جدید (A) | 107 | 0.871 | −0.79$ | −8.46% | −13.78% |
| قدیم (TraderBrain) | 163 | 0.943 | −0.33$ | −5.39% | — |
| تک‌تایم‌فریم | 385 | 0.744 | −1.29$ | −49.61% | −52.37% |
| کنترل تصادفی | 140 | 0.679 | −2.22$ | −31.12% | −35.53% |
| Buy & Hold | — | — | — | −7.64% | −34.77% |

**خوانش صادقانه:** لایه‌های MTF نسبت به تک‌تایم‌فریم و کنترل تصادفی **بهتر** هستند
(زیان کمتر)، ولی **هیچ‌کدام از دو سناریو PF بالای ۱ ندارند** و اختلاف قدیم/جدید از
نظر آماری معنادار نیست (CI95 اختلاف `[−3.51, +2.71]$`). جزئیات کامل:
`docs/SUMMARY.md`.

## ۷) ساختار پروژه

```
futures-mtf-lab/
├── mtflab/
│   ├── bybit_public.py   دریافت دادهٔ عمومی + صفحه‌بندی + کش
│   ├── alignment.py      هم‌ترازی چندتایم‌فریمی + حسابرسی نشتی
│   ├── fees.py           هزینه/اسلیپیج + فیلتر اقتصادی
│   ├── indicators.py     EMA/RSI/ATR/ADX/Donchian/BB/volume_z/ساختار
│   ├── signals.py        سه لایه + نسخه‌های A/B/C
│   ├── engine.py         موتور بک‌تست PAPER + فورنزیک
│   ├── validation.py     split / WF / MC / baselines / sensitivity / overfit
│   ├── report.py         گزارش JSON + Markdown
│   ├── dashboard.py      داشبورد HTML ۵ تبی
│   ├── compare.py        مقایسهٔ دو سناریو + bootstrap معناداری
│   ├── diagnose.py       تشخیص: کالبدشکافی خروج، سیاست‌های سود شناور، فرضیه‌های ورود
│   ├── serve.py          سرور استاندارد برای داشبورد
│   └── selftest.py       خودآزمایی
├── tests/                ۲۱ تست (بدون pytest هم اجرا می‌شود)
├── config/default_config.json
├── docs/                 AGENT_TASK · strategy_design · pseudocode ·
│                         validation_plan · pitfalls · SUMMARY · ردیابی اسکلت
└── results/              خروجی‌ها (فایل‌های حجیم در git نیستند)
```

## ۸) اسناد کلیدی

- [`docs/strategy_design.md`](docs/strategy_design.md) — جدول کامل قوانین + تحلیل A/B/C + شواهد تجربی
- [`docs/validation_plan.md`](docs/validation_plan.md) — پلن اعتبارسنجی و چک‌لیست overfit
- [`docs/pitfalls.md`](docs/pitfalls.md) — ۱۱ دام و تست هرکدام
- [`docs/SUMMARY.md`](docs/SUMMARY.md) — نتایج، فرضیات، موارد نیازمند بازبینی انسانی
- [`docs/ORIGINAL_SCAFFOLD_NOTES_FA.md`](docs/ORIGINAL_SCAFFOLD_NOTES_FA.md) — چه چیزی از فایل پیوست تغییر کرد و چرا

## ۹) قانون‌های این اپ

1. **LIVE وجود ندارد.** `PAPER` تنها حالت است.
2. هر تغییری در منطق، باید تست جدید در `tests/` بگیرد و `selftest` سبز بماند.
3. هیچ API key / secret در کد و کانفیگ نمی‌آید (داده عمومی است).
4. **سناریوی قدیم دست‌نخورده می‌ماند**؛ هر بهبود آن PR جدا می‌خواهد.
