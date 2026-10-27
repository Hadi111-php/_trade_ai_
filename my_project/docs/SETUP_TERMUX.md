# راه‌اندازی روی Termux (آندروید)

Termux یک لینوکس کامپила (community) روی گوشی است. موتور پایتون سکالپ‌لب بدون
آینه (pip/numpy) روی آن اجرا می‌شود.

## ۱. نصب Termux

- دانلود از [F-Droid](https://f-droid.org/packages/com.termux/) (Google Play نسخه‌ی قدیمی دارد).
- باز کردن Termux.

## ۲. نصب ابزار

```bash
pkg update && pkg upgrade
pkg install python git
```

## ۳. کلون مخزن

```bash
git clone https://github.com/Hadi111-php/_trade_ai_.git
cd _trade_ai_/my_project/apps/futures-scalp-lab
```

## ۴. خودآزمایی + اجرا

```bash
python3 -m scalplab selftest
python3 -m scalplab trader --data synthetic --symbol BTCUSDT --tf 1m --max-ticks 1500 --run-id trader-demo-1
```

## ۵. اجرای زنده (فقط اگر اینترنت گوشی دسترسی به Binance/Bybit دارد)

```bash
python3 -m scalplab trader --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever
```

## ۶. اگر شدند نیاز به npm/PWA روی Termux

PWA جاوااسکریپت نیازمند Node.js است. می‌توانی با `pkg install nodejs` آن را نصب
کنی، ولی PWA بهتر است روی PC یا VPS اجرا شود:

```bash
pkg install nodejs
cd ../futures-pwa
npm install && npm start
```

## ۷. keep-alive background

برای اجرای بلندمدت در پس‌زمینه:

```bash
nohup python3 -m scalplab trader --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever > scalp.log 2>&1 &
```

Stop: `kill %1` یا `pkill -f scalplab`.
