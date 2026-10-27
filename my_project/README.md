# 🏛️ مرکز فرماندهی تریدر فیوچرز (Futures Trader Command Center)
### Hadi Tabatabaei (TaHa111)

مخزن یک‌پارچه با دو اپلیکیشن互补 برای ترید فیوچرز. همه‌چیز **فقط کتابخانهٔ
استاندارد** و بدون numpy/pandas — روی هر PC، WSL، Termux و همین سندباکس اجرا می‌شود.

> **اصل طلایی:** هیچ عددی «سود واقعی» نیست مگر روی دادهٔ واقعی و out-of-sample
> اجرا شده باشد. خروجی‌های مصنوعی فقط اعتبارسنجیِ **مکانیزم**‌اند.

---

## 📦 ساختار مخزن

```
my_project/
├── README.md                    ← این فایل (راه‌اندازی کلی)
├── README-FA.md                 ← گزارش کامل DSA v4 (تفصیلی)
├── docs/
│   ├── SETUP_TERMUX.md          ← راه‌اندازی روی Termux (آندروید)
│   ├── SETUP_PC.md              ← راه‌اندازی روی ویندوز / لینوکس / WSL
│   └── SETUP_PHONE.md           ← راه‌اندازی روی گوشی آندروید
└── apps/
    ├── futures-scalp-lab/       ← 🧠 موتور پایتون: سیگنال + روند + PAPER
    │   ├── scalplab/            ← کد اصلی (regimes، trader_brain، models، engine …)
    │   ├── results/             ← گزارش‌ها و لاگ‌های نمونه
    │   ├── TRADER_ROLE.md       ← نقش معامله‌گر فیوچرز (تفصیلی)
    │   └── README_FA.md          ← راهنمای کامل سکالپ‌لب
    └── futures-pwa/             ← 📱 PWA جاوااسکریپت: داشبورد زنده + پوکسی چند صرافی
        ├── server.js            ← سرور پوکسی Bybit/OKX/Binance/CoinGecko
        ├── src/js/              ← استراتژی، broker، view، chart …
        └── README.md
```

---

## 🚀 راه‌اندازی سریع (PC)

```bash
# ۱. کلون
git clone https://github.com/Hadi111-php/_trade_ai_.git
cd _trade_ai_/my_project

# ۲. موتور پایتون (سکالپ‌لب) — نیازی به pip/numpy ندارد
cd apps/futures-scalp-lab
python3 -m scalplab selftest                       # خودآزمایی (باید PASS باشد)
python3 -m scalplab trader --data synthetic \
    --symbol BTCUSDT --tf 1m --max-ticks 1500 --run-id trader-demo-1

# ۳. PWA جاوااسکریپت (از Microsoft/Windows/PC)
cd ../futures-pwa
npm install && npm start                           # http://localhost:8787
```

برای راه‌اندازی دقیق‌تر، `docs/SETUP_PC.md`، `docs/SETUP_TERMUX.md` و
`docs/SETUP_PHONE.md` را بخوان.

---

## 🧠 نقش معامله‌گر فیوچرز (TraderBrain)

الگوریتم‌های **تشخیص ۳ حالت بازار** (صعودی / نزولی / رنج) + موتور تصمیم‌گیری
معامله‌گر (فقط با روند موافق، مدیریت ریسک، PAPER). تفصیل کامل در
**[`apps/futures-scalp-lab/TRADER_ROLE.md`](apps/futures-scalp-lab/TRADER_ROLE.md)**.

```bash
python3 -m scalplab trader --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever
```

---

## 📊 دو اپلیکیشن

| اپلیکیشن | کار |
|---|---|
| **`futures-scalp-lab`** | موتور پایتون: پنج خانواده‌ی مدل سیگنال + توافق ensemble + اعتبارسنجی walk-forward + موتور ریسک PAPER + **TraderBrain** (تشخیص ۳ روند). |
| **`futures-pwa`** | وب‌اپلیکیشن PWA: پوکسی چند صرافی (Bybit → OKX → Binance → CoinGecko)، استراتژی momentum، broker کاغذی، kill-switch، پروفایل ریسک low/medium/high. |

---

## 🔒 ایمنی

- **LIVE عمداً پیاده‌سازی نشده.** همه‌ی خروجی‌ها PAPER/مجازی هستند.
- لایه‌ی `live_adapter` جداست و فقط روی PC تو با کلیدهای API **لوکال** (هرگز در
  git/چت) ساخته می‌شود — و بعد از عبور از دروازه‌ی اعتبارسنجی.
- PWA هرگز به کیف‌پول یا API Secret وصل نمی‌شود؛ بمبندِ امن تو محل اتصال است.
- داده‌ی مصنوعی فقط در حالت آشکار (`mock-local`/`mock-server` یا `--data synthetic`)
  استفاده می‌شود و در گزارش‌ها صریحاً برچسب می‌خورد.
