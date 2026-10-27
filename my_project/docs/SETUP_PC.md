# راه‌اندازی روی PC (Windows / لینوکس / WSL)

## ۱. کلون مخزن

```bash
git clone https://github.com/Hadi111-php/_trade_ai_.git
cd _trade_ai_/my_project
```

## ۲. موتور پایتون (futures-scalp-lab)

**نیازی به pip/numpy/pandas نیست — فقط پایتون ۳.۱۰+.**

### ویندوز
- دانلود و نصب [Python](https://www.python.org/downloads/) (tick روی «Add Python to PATH»).
- باز کردن PowerShell/CMD:

```powershell
cd _trade_ai_/my_project/apps/futures-scalp-lab
python -m scalplab selftest
python -m scalplab trader --data synthetic --symbol BTCUSDT --tf 1m --max-ticks 1500 --run-id trader-demo-1
```

### لینوکس / WSL

```bash
cd _trade_ai_/my_project/apps/futures-scalp-lab
python3 -m scalplab selftest
python3 -m scalplab trader --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever
```

### حالت خودکار (AUTO) روی PC

```bash
python3 -m scalplab auto --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever --trade
```

برای Windows، `start-auto.bat` و `start-trade.bat` موجود است (دابل‌کلیک).

## ۳. PWA جاوااسکریپت (futures-pwa)

**نیازمند Node.js (مقدار پیشنهادی v۱۸+).**

```bash
cd _trade_ai_/my_project/apps/futures-pwa
npm install
npm start          # http://localhost:8787
```

### اگر Bybit در شبکه تو محدود است:

```bash
BYBIT_API_URL=https://api.bytick.com npm start
```

## ۴. اجرای زنده از PC

- سکالپ‌لب روی **دادهٔ واقعی Binance/Bybit** فقط کندل بسته را می‌خواند (PAPER).
- PWA روی پورت `8787` داشبورد زنده می‌سازد؛ در حالت پیش‌فرض Paper ON است.
- **Real** همیشه OFF شروع می‌شود؛ فعال‌سازی به عبارت `I ACCEPT RISK` نیاز دارد.

## ۵. git pull برای آپدیت

```bash
git pull --ff-only origin main
```

## ۶. تست npm

```bash
npm run check   # syntax check تمام فایل‌های js
```
