# راه‌اندازی روی گوشی آندروید

دو مسیر برای گوشی:

## مسیر A — Termux (پیشنهادی، دقیق‌تر)

تکرار `docs/SETUP_TERMUX.md`:

1. نصب Termux از [F-Droid](https://f-droid.org/packages/com.termux/).
2. `pkg update && pkg upgrade && pkg install python git`.
3. `git clone https://github.com/Hadi111-php/_trade_ai_.git`.
4. `cd _trade_ai_/my_project/apps/futures-scalp-lab`.
5. `python3 -m scalplab selftest` → باید PASS باشد.
6. `python3 -m scalplab trader --data synthetic ...` برای تست.

## مسیر B — با پوشیدن پوشه (بدون git)

اگر git روی گوشی راحت نیست، پوشه‌ی `my_project` را compress (zip) کن و روی
گوشی extract کن:

1. روی PC: `zip -r my_project.zip my_project/` (از داخل مخزن).
2. انتقال zip به گوشی (via USB / Telegram / cloud).
3. روی گوشی: extract و در Termux:

```bash
cd my_project/apps/futures-scalp-lab
python3 -m scalplab selftest
python3 -m scalplab trader --data synthetic --symbol BTCUSDT --tf 1m --max-ticks 1500
```

## بدون git، آپدیت कैसे کنیم؟

اگر کلون نداری، هر بار نسخه‌ی جدید را zip کن و روی گوشی refresh کن. یا
alignment‌ی `pull` روی Termux اگر git نصب شده:

```bash
git pull --ff-only origin main
```

## نکات ایمنی روی گوشی

- **هیچ کلید API روی گوشی ذخیره نکن.** LIVE فعال نیست و باید نباشد.
- داده‌ی مصنوعی فقط برای تست است؛ روی smartphone نباید live اجرا کرد مگر با
  آگاهی کامل و روی VPS معتبر.
- بهترین کار: گوشی فقط برای دیدن داشبورد و PC/VPS برای معامله‌ی واقعی.
