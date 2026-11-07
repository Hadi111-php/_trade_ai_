# نقشهٔ کد — الگوها، تنظیمات، موتور و مکانیزم رصد

هدف این سند: «کدام فایل چه کاری می‌کند» + «چه چیزی را به یک داشبورد دیگر بدهم».
همهٔ مسیرها نسبت به `my_project/apps/futures-mtf-lab/` هستند.

## ۱) یک نگاه بالا به پایین

```
کندل (Bybit عمومی) ──► data.py ──► alignment.py ──► signals.py ──► engine.py
                                                                      │
                                                     stats.py ◄───────┤ (آمار)
                                                     rules.py ◄───────┤ (قاعدهٔ بست)
                                                                      │
                        live.py (رصد زندهٔ مجازی) ────────────────────┘
                                 │
                desk.py / labweb.py (داشبورد و آزمایشگاه)
                                 │
                     autotrade_api.py (قرارداد برای بیرون)
```

## ۲) الگوها (تیم‌ها)

| فایل | چه دارد |
|---|---|
| `mtflab/patterns.py` | `variants_for()` — **تنها** منبع فهرست الگوها: `base`, `trend`, `trend_tp`, `pullback`, `climax`، هر کدام با overrides خودش |
| `mtflab/config.py` | `PRESETS` (پریست‌های نام‌دار مثل `trend_4h`) + همهٔ فیلدهای `MTFConfig` |
| `mtflab/signals.py` | منطق ورود: `breakout` / `pullback`، فیلتر ADX/شیب، ساختار قله/دره |

> الگو = مجموعه‌ای از کلیدهای `MTFConfig`. هیچ منطق معامله در داشبورد نوشته نشده؛
> داشبورد فقط این کلیدها را عوض می‌کند.

## ۳) تنظیمات

| فایل | چه دارد |
|---|---|
| `mtflab/knobs.py` | `KNOBS` (۲۷ کلید مجاز با بازه/نوع/توضیح فارسی)، `sanitize_overrides()` |
| `mtflab/config.py` | مقادیر پیش‌فرض واقعی (`stop_atr_mult=1.5`, `trail_atr_mult=2.0`, `risk_per_trade_pct=1.0`, …) |

قاعده: کلید بیرون `KNOBS` نادیده گرفته می‌شود؛ مقدار بیرون بازه به مرز کلمپ
می‌شود. این کار جلوی «تایپوی یک‌حرفی که کل آزمایش را بی‌معنا می‌کند» را می‌گیرد.

## ۴) موتور

| فایل | نقش |
|---|---|
| `data.py` | `Candle`، `resample_up()`، `build_layers()`، کندل مصنوعی، خواندن CSV/JSON |
| `indicators.py` | EMA، RSI، ATR، ADX، باند، حجم z، ساختار قله/دره |
| `alignment.py` | هم‌راستایی سه لایه (`trigger/filter/bias`) بدون نگاه به آینده |
| `fees.py` | هزینهٔ رفت‌وبرگشت و اسلیپیج |
| `signals.py` | تصمیم ورود + دلیل هر لایه (برای انتساب) |
| `engine.py` | `run_backtest()`: پوزیشن، حد ضرر، تریلینگ، برداشت جزئی، فیوز، آمار، معاملات |
| `stats.py` | `metrics()`, `breakdown()`, `rule_breakdown()` — تعریف‌های آماری مشترک |
| `rules.py` | `RULE_META` (قاعده‌های بست + این‌که ضدضرر هستند یا نه) |

## ۵) مکانیزم رصد

| فایل | نقش |
|---|---|
| `live.py` | `LiveRunner`: حالت، ژورنال، هر سیگنال با انتساب کامل، `--status`، `--serve` |
| `desk.py` | `Lab`: کمبریج بین داده، اجرای آزمایش، خط پایه، تیم‌ها، تنظیمات مغز |
| `labweb.py` | صفحهٔ وب + API (`/api/overview`, `/api/schema`, `/api/run`, `/api/signals`, …) |
| `brainview.py` + `observer.py` | «چشم مغز» — فقط مشاهده، بدون اثر در تصمیم (بخش ۱۱ سند مرجع) |
| `audit.py` | بازبینی سلامت معاملات: هر ضرر ≈۱R؟ با قاعدهٔ ضدضرر بست؟ |
| `pumpdump.py` | **سیستم مستقل** پامپ و دامپ: تشخیص رویداد + اندازه‌گیری واکنش. هیچ‌چیز از `engine`/`signals` ایمپورت نمی‌کند |

## ۶) قرارداد برای یک داشبورد دیگر

**گزینهٔ الف — همان مخزن:** `mtflab.autotrade_api` را import کن:

```python
from mtflab import autotrade_api as api
api.schema()                      # الگوها + ۲۷ کلید + پیش‌فرض‌ها
api.run(dataset, variant="trend") # سنجه‌ها، OOS، by_rule، معاملات
api.signals_now(dataset)          # سیگنال کندل بستهٔ آخر
```

**گزینهٔ ب — بستهٔ مستقل (توصیه‌شده برای تحویل):**

```bash
python3 -m mtflab bundle                 # می‌سازد: exports/autotrade_core/
python3 -m mtflab bundle --check         # آیا بسته با کد فعلی یکی است؟
python3 exports/autotrade_core/demo.py   # نمونهٔ اجرا با کندل مصنوعی
```

پوشهٔ `exports/autotrade_core/` شامل ۱۴ فایل موتور + `manifest.json` (هش هر
فایل) + `README_FA.md` + `demo.py` است و **بدون این مخزن** هم کار می‌کند:

```python
import sys; sys.path.insert(0, "/path/to/parent")
from autotrade_core import autotrade_api as api
```

## ۶.۵) پامپ و دامپ (سیستم مستقل)

```bash
bash run-auto.sh --pump --download --days 365    # یا: --symbols BTCUSDT ETHUSDT --days 90
python3 -m mtflab pumpdump --data-dir data --out-dir results
```

- تعریف یخ‌زده و دروازهٔ شش‌شرطی: `docs/PUMPDUMP_PLAN_FA.md`
- مکانیزم: `mtflab/pumpdump.py` (بدون وابستگی به موتور معامله)
- **عمداً در بستهٔ `exports/autotrade_core/` نیست**: آن بسته موتور اتوترید است،
  این یکی مکانیزم جدا با ریسک و هزینهٔ متفاوت.

## ۷) شکل دادهٔ ورودی

```python
data = {
  "BTCUSDT": [[1700000000000, 35000.1, 35200.0, 34900.0, 35100.5, 1234.5], ...],
  # یا: [{"ts":..., "o":..., "h":..., "l":..., "c":..., "v":...}, ...]
}
```

کندل‌ها باید **بسته‌شده** و به ترتیب زمان باشند. تایم‌فریم تریگر پیش‌فرض `4h`
است و لایه‌های `1d` خودشان از همان کندل‌ها ساخته می‌شوند (`build_layers`).

## ۸) چه چیزی را **نده**

- `live.py`/`desk.py`/`labweb.py` را برای یک داشبورد ساده لازم نداری.
- منطق ورود/خروج را در داشبورد خودت بازنویسی نکن؛ همان `engine.py` را صدا بزن.
  دو پیاده‌سازی = دو نتیجهٔ متفاوت = انتساب بی‌معنا.
- `stats.py` و `rules.py` را کپیِ دستی نکن؛ در بسته هستند.

## ۹) تست‌هایی که این مرزها را قفل می‌کنند

| تست | چه چیزی را تضمین می‌کند |
|---|---|
| `tests/test_bundle.py::test_bundle_builds_and_runs_without_the_repo` | بسته واقعاً مستقل است |
| `tests/test_bundle.py::test_committed_bundle_is_in_sync_with_engine` | بسته از موتور عقب نمی‌ماند |
| `tests/test_bundle.py::test_api_matches_desk_metrics` | آمار API و داشبورد یکی است |
| `tests/test_audit.py` | «ضرر طبیعی» از «خطای مکانیکی» جدا می‌شود |
