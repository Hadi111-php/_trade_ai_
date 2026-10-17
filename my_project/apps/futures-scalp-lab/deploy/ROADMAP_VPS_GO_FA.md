# نقشهٔ راه: GitHub → VPS → (بعداً) Go

## ۱) آیا GitHub می‌تونه «هاست» باشه؟ **نه برای اجرای دائمی.**
- **GitHub Actions** = اجرای **موقتی/زمان‌بندی‌شده** (هر چند ساعت یک batch). برای
  تست و جمع‌آوری گزارش عالیه (همین الان `ci/scalplab-cloud.yml` آماده‌ست) ولی
  نمی‌تونه یه daemon **۲۴/۷** نگه داره (هر job حداکثر چند ساعت و بعد kill می‌شه).
- **GitHub Pages** = فقط فایل استاتیک؛ نمی‌تونه backend/Next.js یا لب رو اجرا کنه.
→ پس: **تست روی Actions، اجرای دائمی روی VPS.** برنامهٔ تو درسته.

## ۲) راه‌اندازی VPS (سبک و ارزان)
```
# روی VPS (اوبونتو):
sudo apt update && sudo apt install -y python3 git
git clone -b arena/01a0255b-main-arena-conn https://github.com/HaadiTaba111/Main_Arena_conn.git /opt/Main_Arena_conn
cd /opt/Main_Arena_conn/apps/futures-scalp-lab
sudo cp deploy/scalplab.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now scalplab
sudo systemctl status scalplab     # دیدن وضعیت
journalctl -u scalplab -f          # دیدن لاگ زنده
```
- با `--light` مصرف CPU/شبکه کمه؛ یه VPS ارزون (۱ core / ۱GB) کافیه.
- این هنوز **PAPER** است؛ LIVE تا عبور از دروازهٔ اعتبارسنجی فعال نمی‌شه.

## ۳) آیا به Go تبدیل کنیم؟ **بعد از نتیجه، فقط لایهٔ داغ — نه کل سیستم.**
واقعیت سرعت:
| محور | Python | Go |
|---|---|---|
| حلقهٔ CPU-bound | کند | ~۱۰–۱۰۰× سریع‌تر |
| همزمانی چند نماد | GIL/threads سنگین | goroutine سبک (هزاران) |
| مصرف حافظه | بالا | کم |
| سرعت توسعه/آزمایش علمی | عالی | کندتر |

**اما** bottleneck لبِ فعلی CPU نیست — شبکه (انتظار کندل) و محاسبهٔ کوچکه؛ پس
Go الان تفاوت محسوسی نمی‌ده. چیزی که Whale Hunter رو سبک کرد **ایندکس‌سازی و
جاروب دقیق‌تر** بود (بهبود الگوریتم)، نه زبان — و این زبان‌مستقله.

**توصیه:** اول با Python نتیجهٔ آماری بگیر (چرخهٔ علمی سریعه). وقتی خواستی
«اسکن همزمان چند نماد + اجرای زندهٔ کم‌تاخیر» بری، فقط لایهٔ اسکن/اجرا رو به Go
بنویس و بخش علمی/اعتبارسنجی رو مشترک نگه دار. تبدیل زودهنگام = بازنویسی +
بازاعتبارسنجیِ بیهوده.
