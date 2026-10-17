# Futures Scalp Lab — آزمایشگاه سیگنال اسکالپ فیوچرز

نسخه: `2026-08-26.1` · فقط کتابخانهٔ استاندارد پایتون (بدون numpy/pandas) ·
اجرا روی هر PC و همین سندباکس.

> **اصل طلایی:** هیچ عددی «سود واقعی» نیست مگر روی دادهٔ واقعی و out-of-sample
> اجرا شده باشد. خروجی‌های synthetic فقط اعتبارسنجیِ **مکانیزم**‌اند و در گزارش‌ها
> صریحاً برچسب می‌خورند.

---

## ۱) چه می‌سازد؟

- **صدور سیگنال چندمدلی:** پنج خانوادهٔ مدل عمداً متنوع + یک خط پایهٔ تصادفی:
  `ema_cross` (روند)، `rsi_reversion` (بازگشت به میانگین)، `donchian_breakout`
  (مومنتوم)، `bb_squeeze` (نوسان)، `macd_flip` (روند) + `random_control` (کنترل).
- **ثبت کامل هر سیگنال** (`signals_*.jsonl`): run_id، seed، منبع داده، symbol/tf،
  کندل و ts، مدل + خانواده + نسخه، جهت، confidence، دلیل، قیمت ورود، کارمزد، افق،
  و **اسنپ‌شات کامل اندیکاتورها** (ema fast/slow، rsi، atr%، bb_pos/width،
  donchian، macd_hist، vol_z) + همهٔ پارامترها.
- **پیامد هر سیگنال** (`outcomes_*.jsonl`): بازده ناخالص/خالص (پس از کارمزد)،
  hit، MAE/MFE روی مسیر افق.
- **اعتبارسنجی و رتبه‌بندی روش‌ها** (`report_*.json/md`): معیارهای هر مدل، روش‌های
  «توافق k از M» (`consensus_k2..k5`)، کالیبراسیون confidence↔hit، و CI95.

## ۲) اجرا

```bash
cd apps/futures-scalp-lab

# خودآزمایی (علی‌بودن + سلامت کنترل)
python3 -m scalplab selftest

# اجرای مصنوعی چند seed (اعتبارسنجی مکانیزم)
python3 -m scalplab --data synthetic --seeds 42 123 777 --candles 2500 \
    --horizon 8 --fee-bps 4 --run-id demo-syn-1

# بازپخش دادهٔ واقعی (CSV با ستون‌های ts,open,high,low,close,volume)
python3 -m scalplab --data csv --csv data/btc_1m.csv --horizon 8 --run-id btc-replay-1

# زنده (فقط روی PC با اینترنت)
python3 -m scalplab --data binance --symbol BTCUSDT --tf 1m --candles 1000
```

همهٔ پارامترها از CLI/`--config config.json`: `--data --symbol --tf --candles
--seeds --horizon --fee-bps --cooldown --agree-min --out --run-id`.

## ۳) تضمین علمی (walk-forward)

- اسنپ‌شات t فقط از دادهٔ `<= t` ساخته می‌شود؛ خودآزمایی «causality» این را با
  مقایسهٔ prefix تأیید می‌کند (PASS).
- پیامد فقط از کندل‌های `> t` محاسبه می‌شود.
- `random_control` همیشه اجرا می‌شود؛ هر روشی که از کنترل بهتر نباشد، بی‌ارزش است.
- کارمزد هر دو طرف (`fee-bps`) در بازده خالص لحاظ می‌شود — درس مهم: روی دادهٔ
  پرنوسانِ کم‌دامنه، کارمزد بیشترِ edge را می‌بلعد.

## ۴) خواندن خروجی نمونهٔ synthetic (demo-syn-1)

روی دادهٔ مصنوعیِ رنج/پرنوسان، **هیچ روشی پس از کارمزد سود مثبت ندارد** — دقیقاً
انتظار علمی. اما «توافق» واقعاً hit-rate را بالا می‌برد:
`consensus_k3` با hit_net≈0.40 و خالص ‎-4.4bps بهتر از تک‌مدل‌ها (≈0.34) و بهتر
از کنترل در خالص است. یعنی: **توافق بین خانواده‌های متنوع، معتبرترین روش
فیلتر سیگنال است** — ولی برای سود واقعی، دادهٔ واقعی و بهینه‌سازی کارمزد لازم است.

## ۵) اتصال به داشبورد

صفحهٔ `/scalp-lab` در `apps/dsa-command-dashboard` آخرین `report_*.json` را از
`../futures-scalp-lab/results` می‌خواند (API: `/api/scalp/status`) و جدول
رتبه‌بندی + کالیبراسیون را با برچسب منبع داده نشان می‌دهد.

## ۶) حالت خودکار (AUTO) — فقط PAPER

```bash
# پیش‌فرض محدود (۳۰۰ کندل) و بی‌خطر:
python3 -m scalplab auto --data synthetic --seed 7 --run-id auto-1

# روی PC با دادهٔ زنده (هر ۵ ثانیه یک کندل بسته):
python3 -m scalplab auto --data binance --symbol BTCUSDT --tf 1m --interval 5

# --live عمداً خطا می‌دهد؛ LIVE پیاده‌سازی نشده است.
```

ایمنی:
- AUTO فقط سیگنال **ثبت و ارزیابی کاغذی** می‌کند؛ هیچ سفارشی نمی‌گذارد.
- پیش‌فرض `--max-ticks` محدود است؛ kill با Ctrl-C؛ هیچ daemon پنهانی نیست.
- `--forever` برای اجرای بلندمدت دستی (همان چیزی که bat ها استفاده می‌کنند).
- تا وقتی روی دادهٔ واقعی و out-of-sample برتری آماریِ پایدار (در برابر
  random_control و پس از کارمزد) ثابت نشده، LIVE توصیه/پیاده‌سازی نمی‌شود.

### راه‌اندازی روی ویندوز (بدون تایپ دستور)
| فایل | کار |
|---|---|
| `start-auto.bat` | دابل‌کلیک → AUTO با دادهٔ زندهٔ Binance (فقط خواندنی/PAPER)، `--forever` |
| `start-auto-offline.bat` | تست آفلاین با دادهٔ مصنوعی (۵۰۰ کندل) |
| `enable-autostart.bat` | افزودن میان‌بر به Startup ویندوز → با لاگین خودکار بالا می‌آید |
| `disable-autostart.bat` | حذف autostart |

برای تغییر نماد/تایم‌فریم، خط `--symbol`/`--tf` داخل `start-auto.bat` را ویرایش کن.
autostart فقط همان AUTOِ PAPER را بالا می‌آورد؛ LIVE هرگز فعال نمی‌شود.

## ۶٫۵) موتور مدیریت ریسک (PAPER TRADE) — پیاده‌سازی شرط‌های تو

فعال‌سازی فقط با `--trade` (پیش‌فرض خاموش). هر رویداد (open/close/reject/halt)
با تمام جزئیات در `trades_*.jsonl` ثبت می‌شود.

| شرط تو | پیاده‌سازی | پرچم |
|---|---|---|
| فعال‌سازی فقط با ارادهٔ من | پیش‌فرض خاموش | `--trade` |
| حجم و ضریب قابل تنظیم | size / leverage | `--size` `--leverage` |
| همزمان ۴ معامله | سقف پوزیشن | `--max-concurrent 4` |
| ۲ ضرر → بستن کل + توقف | circuit breaker | `--cb-losses 2` |
| سود/ضرر شناور (trailing) | stop اولیه + trailing | `--stop-pct` `--trail-pct` |

ویندوز: `start-trade.bat` (دادهٔ زنده، PAPER، موتور ریسک روشن).

**اتصال واقعی به صرافی (LIVE) عمداً در این ریپو نیست.** لایهٔ `live_adapter`
جداست و فقط روی PC تو با کلیدهای API داخل یک فایل لوکال (هرگز در git/چت) ساخته
می‌شود، آن‌هم بعد از عبور از دروازهٔ اعتبارسنجی. تا آن موقع همه‌چیز PAPER است.

## ۶٫۶) اجرای خودکار در WSL / لینوکس (به‌جای bat)

`.bat` فقط مال ویندوزه؛ توی WSL از `wsl-auto.sh` استفاده کن که **خودش دانلود/
آپدیت و اجرا می‌کند**:

```bash
# بار اول (کلون + اجرا؛ اگر private بود یک‌بار اعتبار GitHub می‌خواهد):
bash wsl-auto.sh

# دفعات بعد (آپدیت خودکار + اجرا):
bash wsl-auto.sh

# بدون دانلود، از نسخهٔ موجود (مثلاً پوشهٔ ویندوز):
bash wsl-auto.sh /mnt/c/.../Main_Arena_conn
```

اگر ریپو private است و کلون سخت بود، ساده‌ترین راه اجرای مستقیم از پوشهٔ
ويندوز در WSL است:
```bash
cd /mnt/c/<مسیر>/Main_Arena_conn/apps/futures-scalp-lab
python3 -m scalplab auto --data binance --symbol BTCUSDT --tf 1m --interval 5 \
    --forever --trade --size 100 --leverage 3 --max-concurrent 4 --cb-losses 2
```

## ۶٫۷) استاپ سازگار با تایم‌فریم + سویپ چند تایم‌فریم

- **استاپ/trailing پیش‌فرض ATR‑ای است** (`adaptive=True`): stop = ATR% × `stop_atr_mult`،
  trail = ATR% × `trail_atr_mult`. پس با عوض شدن تایم‌فریم، استاپ با نوسان همان
  تایم‌فریم مقیاس می‌شود (درصد ثابت اشتباه است). برای درصد ثابت: `--no-adaptive`.
- **سویپ** برای پیدا کردن بهترین سناریو (tf × horizon × روش):
```bash
python3 -m scalplab sweep --data synthetic --candles 2000 --tfs 1,5,15 --horizons 4,8,16
# روی VPS با دادهٔ واقعی:
python3 -m scalplab sweep --data binance --tfs 1,5,15 --horizons 4,8,16
```
خروجی `sweep_*.json` + جدول رتبه‌بندی خالصِ پس از کارمزد.

## ۶٫۸) نصب یک‌خطی روی VPS
```bash
bash deploy/install-vps.sh
```
خودش کلون/آپدیت + systemd + اجرا می‌کند. مدل همکاری: من کد می‌زنم اینجا →
تو روی VPS `git pull` + `systemctl restart scalplab`.

## ۷) مسیر بعدی (روی PC تو)

1. اجرای `--data binance` یا CSV واقعی برای out-of-sample.
2. افزودن مدل خارجی (Ollama/LLM sentiment) به registry به‌عنوان یک خانوادهٔ دیگر.
3. meta-learner کوچک: ورودی = اسنپ‌شات ثبت‌شده، خروجی = احتمال hit (از jsonlها).
