# پوشهٔ نتایج

خروجی‌های تولیدی اینجا می‌آیند. فقط داشبورد و همین فایل در git نگه داشته می‌شوند؛
بقیه (JSON/JSONL/MD) بازتولیدپذیرند و در `.gitignore` هستند.

| فایل | توضیح | در git؟ |
|---|---|---|
| `dash_scenarios.html` | داشبورد مقایسه (۷ تب: مقایسه · قدیم · جدید · ورود اصلاح‌شده · آزمایشگاه خروج · اعتبارسنجی · سلامت) | ✅ |
| `diagnosis_report.md` | گزارش تشخیصی: کالبدشکافی خروج، ۱۵ سیاست سود شناور، ۱۲ فرضیهٔ ورود، ماتریس ورود×خروج | ✅ |
| `robust_report.md` | آزمون بقا: چند نماد × چند پنجره + حکم قاعدهٔ از پیش تعیین‌شده | ✅ |
| `evolve_report.md` | تطبیق زنده (حالت سخت‌گیرانه) روی BTC+ETH + پلاسیبو | ✅ |
| `evolve_report_rolling.md` | تطبیق زنده (حالت چرخشی) — ارتقا پذیرفت، نتیجه بدتر شد | ✅ |
| `dash_evolve.html` | داشبورد تطبیق: خط زمانی تصمیم‌ها، دروازه، خط پایه‌ها | ✅ |
| `evolve_report_5y.md` | تطبیق روی **۵.۷ سال BTC + ۴.۷ سال ETH** (حالت سخت‌گیرانه) | ✅ |
| `evolve_report_5y_rolling.md` | همان، حالت چرخشی + **توزیع ۵ پلاسیبو** (نتیجه: از نویز جدا نیست) | ✅ |
| `robust_report_5y.md` | آزمون بقا روی دادهٔ بلندمدت: `entry_quality` رد شد (۱۶.۷٪ پنجره‌ها) | ✅ |
| `robust_report_trend4h.md` | آزمون بقا `trend_4h` (۴h واقعی): BTC PF ۱.۹۵ همهٔ ۶ پنجره مثبت، ETH ۳/۶ → **۹/۱۲ (۷۵٪)**؛ رد فقط به‌خاطر p=۰.۵ با ۲ نماد | ✅ |
| `dash_evolve_5y*.html` | داشبورد همان اجراهای بلندمدت | ✅ |
| `scenario_compare_<ts>.json` | payload کامل داشبورد (برای بازسازی: `mtflab dashboard --payload …`) | ❌ |
| `mtf_report_<run_id>.json/.md` | گزارش سناریوی جدید (شامل اعتبارسنجی) | ❌ |
| `mtf_signals_<run_id>.jsonl` | فورنزیک ورودها و وتوها (دلیل هر معامله/عدم‌معامله) | ❌ |
| `mtf_trades_<run_id>.jsonl` | فورنزیک معاملات بسته‌شده با مسیر قیمت و MFE/MAE | ❌ |
| `trader_report_*.json`, `trader_trades_*.jsonl` | خروجی سناریوی قدیم در همان اجراهای مقایسه | ❌ |

## بازتولید

```bash
cd ..
python3 -m mtflab compare --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv \
  --out results/dash_scenarios.html
python3 -m mtflab diagnose --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv \
  --tf-trigger 1h --tf-filter 4h --tf-bias 1d --align A --bias-ema 50 \
  --out results/diagnosis_report.md
python3 -m mtflab robust --source csv --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv \
  --tf-trigger 1h --tf-filter 4h --tf-bias 1d --align A --bias-ema 50 \
  --presets entry_quality --windows 4 --out results/robust_report.md
python3 -m mtflab serve --dir results --port 8080
```

| `comove_verdict.md` | 🎯 حکم هم‌حرکتی: H1 تأیید · H2 لب‌مرزی و ناپایدار (۴۹٪ برش‌ها) + تصمیم نهایی پروژه | ✅ |
| `comove_method.md` | روش تحلیل هم‌حرکتی + دو دام آماری که خوردیم | ✅ |
| `autoscan_20symbols_verdict.md` | 🎯 **حکم نهایی**: `trend_4h` روی ۲۰ نماد رد شد (۵ سکه ۱۱۸٪ سود را می‌سازند) | ✅ |
| `phone_verification.md` | تأیید اجرای واقعی روی گوشی: اثر انگشت و ۱۰/۱۰ عدد یکسان با سندباکس | ✅ |
| `reaudit_4h.md` | بازاجرای همهٔ تست‌های 4h/1d بعد از باگ تایم‌فریم — قدیم در برابر جدید | ✅ |
| `auto_scan_<tag>.md` | گزارش اسکن خودکار ۲۰نمادی (خروجی `run-auto.sh`) | ✅ |
| `auto_scan_<tag>.json` | بستهٔ دادهٔ همان اسکن (برای بازبینی/بازتولید) | ✅ |

> ⚠️ اعداد این پوشه **PAPER** هستند. هیچ‌کدام سود واقعی نیستند.

| فایل | چیست |
|---|---|
| `autoscan_15m_verdict.md` | **حکم نهایی سناریوی اصلی اسپک (۱۵m/۱h/۴h) — رد شد** + حساب هزینه |
| `phone_run_15m_20261031.json` | خام اجرای گوشی (۱۶ نماد، ۱۱٬۱۰۷ معامله) |
| `phone_run_15m_20261031.md` | گزارش همان اجرا |
