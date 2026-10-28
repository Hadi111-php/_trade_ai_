# پوشهٔ نتایج

خروجی‌های تولیدی اینجا می‌آیند. فقط داشبورد و همین فایل در git نگه داشته می‌شوند؛
بقیه (JSON/JSONL/MD) بازتولیدپذیرند و در `.gitignore` هستند.

| فایل | توضیح | در git؟ |
|---|---|---|
| `dash_scenarios.html` | داشبورد مقایسهٔ دو سناریو (۵ تب) — خودکفا، بدون وابستگی | ✅ |
| `diagnosis_report.md` | گزارش تشخیصی: کالبدشکافی خروج، ۱۵ سیاست سود شناور، ۱۲ فرضیهٔ ورود | ✅ |
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
python3 -m mtflab serve --dir results --port 8080
```

> ⚠️ اعداد این پوشه **PAPER** هستند. هیچ‌کدام سود واقعی نیستند.
