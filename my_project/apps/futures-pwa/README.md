# Futures Scalp Lab — Bybit Live / Paper First

این نسخه برای **Bybit V5 public market data** ساخته شده است:

- حالت پیش‌فرض: `BYBIT LIVE`
- endpointهای بازار: `v5/market/tickers` و `v5/market/kline` با `category=linear`
- کندل در حال تشکیل به‌صورت پیش‌فرض از امتیازدهی حذف می‌شود تا validation روی کندل بسته‌شده انجام شود.
- در خطای شبکه/محدودیت منطقه‌ای، قیمت قدیمی یا مصنوعی جایگزین نمی‌شود؛ نماد `DATA ERROR` نشان می‌دهد و سفارش Paper جدید ساخته نمی‌شود.
- `Mock Local` و `Mock Server` فقط با انتخاب صریح در Settings برای تست UI هستند.

## اجرا

```bash
npm start
# http://localhost:8787
```

پروکسی سرور فقط درخواست عمومی بازار Bybit را forward می‌کند و هیچ API Secretی لازم ندارد. اگر دامنه پیش‌فرض در شبکه/منطقه مجاز نیست، از دامنه رسمی مجاز برای حساب خودت استفاده کن:

```bash
BYBIT_API_URL=https://api.bytick.com npm start
```

## Paper Trading

Paper به‌صورت پیش‌فرض فعال است و این موارد را ثبت می‌کند:

- fee ورود و fee خروج به‌صورت جداگانه
- round-trip fee تخمینی روی کارت سیگنال
- اسلیپیج ورودی
- gross PnL و net PnL بعد از هر دو fee
- win-rate فقط بر مبنای معاملات بسته‌شده و Net PnL
- Profit Factor، Expectancy، Max Drawdown و میانگین زمان نگهداری
- stop loss، take profit، حداکثر زمان نگهداری و daily loss limit

Fee پیش‌فرض قابل تغییر است؛ مقدار واقعی Taker fee حساب/سطح VIP خودت را در Settings وارد کن. Funding، latency و تفاوت اجرای Backend هنوز در این آزمایشگاه مدل نشده‌اند.

## Real Trading

- `Real` همیشه با `OFF` شروع می‌شود.
- فعال‌سازی به عبارت `I ACCEPT RISK` نیاز دارد.
- داده Mock اجازه ارسال واقعی ندارد.
- مقصد payload از Settings قابل انتخاب است: `lbank-futures` یا `bitunix-futures`.
- مسیر داخلی `/api/lbank/order` فقط `DRY_RUN_ONLY` است.
- برای سفارش واقعی باید `realWebhookUrl` را به Backend امن خودت بدهی؛ API Key/Secret و منطق امضای LBank/Bitunix باید فقط روی Backend بماند و Withdraw خاموش باشد.
- PWA مستقیماً به کیف پول یا API Secret وصل نمی‌شود؛ Backend امن تو محل اتصال به حساب خودت است.

در داشبورد، جدول `ورودی دیتای بازار` منبع، قیمت Ticker، زمان آخرین کندل بسته، تعداد کندل و سن داده را نشان می‌دهد؛ نمودار هم با انتخاب نماد تغییر می‌کند و JSON ورودی Parse‌شده را نمایش می‌دهد.

سه پروفایل ریسک `low / medium / high` برای مقایسه نتیجه‌ها وجود دارد. هر معامله با پروفایل خودش tag می‌شود و گزارش روی پروفایل انتخابی فیلتر می‌شود؛ بنابراین می‌توانی Low را چند روز، سپس Medium و High را جداگانه مقایسه کنی. گزارش Paper شامل Win-rate، Net PnL، Fees، Profit Factor، Expectancy و Max Drawdown است.

کلاس‌های اصلی در `src/js` ماژولار و مستقل هستند: `MarketClient`، `MomentumScalpStrategy`، `PaperBroker`، `PerformanceReport`، `PriceChart`، `RealBroker`، `SettingsStore` و `DashboardView`.
