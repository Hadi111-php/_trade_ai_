"""بخش وب داشبورد کارگاه — HTML/JS و سرور (کتابخانهٔ استاندارد).

جدا شده از `desk.py` تا منطق آماری و لایهٔ نمایش قاطی نشوند و تست هر کدام
ساده بماند. هیچ فایل خارجی/CDN بارگذاری نمی‌شود: روی گوشیِ بی‌اینترنت هم کار
می‌کند.
"""
from __future__ import annotations

import errno
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qsl, urlsplit, unquote

PAGE = r"""<!doctype html>
<html lang="fa" dir="rtl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>کارگاه اتوترید مجازی</title>
<style>
:root{--bg:#0b0f16;--panel:#141a24;--panel2:#1a2230;--line:#26303f;--fg:#e6edf3;
--dim:#8b98a9;--ok:#3ddc97;--warn:#ffb454;--bad:#ff6b6b;--acc:#6aa9ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Vazirmatn,-apple-system,Tahoma,sans-serif;font-size:14px}
header{padding:14px 14px 0}
.brand{font-size:18px;font-weight:700;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pill{font-size:11px;border:1px solid var(--line);border-radius:999px;padding:2px 8px;color:var(--dim);font-weight:400}
.meta{color:var(--dim);font-size:12px;margin-top:6px;line-height:1.7}
.demo{background:#3a2a12;border:1px solid #6b4a1f;color:#ffd7a1;padding:8px 12px;border-radius:10px;margin-top:10px;font-size:12px}
nav{display:flex;gap:6px;padding:12px 14px 0;overflow-x:auto}
nav button{background:var(--panel);color:var(--dim);border:1px solid var(--line);border-radius:10px;padding:9px 14px;font-size:13px;font-family:inherit;cursor:pointer;white-space:nowrap}
nav button.on{background:var(--acc);color:#06101f;border-color:var(--acc);font-weight:700}
main{padding:12px 14px 60px;max-width:1100px}
section{display:none} section.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:10px 0 16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.card .k{color:var(--dim);font-size:11px} .card .v{font-size:17px;font-weight:700;margin-top:4px}
h3{font-size:14px;margin:18px 0 8px;color:#cdd9e6}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;font-size:12.5px;vertical-align:top}
th{background:var(--panel2);color:var(--dim);font-weight:600;font-size:11.5px;white-space:nowrap}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
tr:last-child td{border-bottom:none}
.pos{color:var(--ok)} .neg{color:var(--bad)} .mut{color:var(--dim)}
.tag{font-size:10.5px;border-radius:6px;padding:1px 6px;border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.tag.risk{color:var(--ok);border-color:#245c45;background:#10241c}
.note{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:12px;color:#c3cedb;line-height:1.9;margin:10px 0}
.warn{border-color:#6b4a1f;background:#241a0f;color:#ffd7a1}
.bad{border-color:#5c2424;background:#241010;color:#ffb3b3}
.good{border-color:#245c45;background:#10241c;color:#a9f0cf}
button.act{background:var(--acc);color:#06101f;border:none;border-radius:10px;padding:10px 16px;font-weight:700;font-family:inherit;font-size:13px;cursor:pointer}
button.act:disabled{opacity:.5}
button.ghost{background:transparent;color:var(--dim);border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-family:inherit;font-size:12px;cursor:pointer}
input,select{background:#0f1520;border:1px solid var(--line);border-radius:9px;color:var(--fg);padding:9px 10px;font-family:inherit;font-size:13px;width:100%}
input[type=checkbox]{width:auto}
label{font-size:12px;color:var(--dim);display:block;margin-bottom:4px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}
.knob{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.knob .t{font-size:12.5px;margin-bottom:6px}
.knob .h{font-size:10.5px;color:var(--dim);margin-top:6px;line-height:1.7}
.knob.changed{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc) inset}
pre{background:#0f1520;border:1px solid var(--line);border-radius:10px;padding:10px;overflow:auto;font-size:11px;line-height:1.6;direction:ltr;text-align:left;max-height:420px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
.syms{display:flex;flex-wrap:wrap;gap:6px}
.syms label{display:flex;align-items:center;gap:6px;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:6px 9px;margin:0;font-size:12px;color:var(--fg)}
.spin{color:var(--dim);font-size:12px}
.spin:after{content:" …";animation:dots 1.2s infinite}
@keyframes dots{0%,20%{content:" ."}40%{content:" .."}60%,100%{content:" ..."}}
</style></head><body>
<header>
  <div class="brand">🧪 کارگاه اتوترید مجازی <span class="pill">PAPER · بدون سفارش واقعی</span></div>
  <div class="meta" id="meta">…</div>
  <div class="demo" id="demo" style="display:none"></div>
</header>
<nav>
  <button data-tab="live" class="on">زنده</button>
  <button data-tab="signals">سیگنال‌ها</button>
  <button data-tab="shadow">دفتر خبر</button>
  <button data-tab="ops">مدیریت کلان</button>
  <button data-tab="lab">آزمایشگاه</button>
  <button data-tab="runs">آزمایش‌ها</button>
  <button data-tab="watch">شکار زنده</button>
  <button data-tab="exit">خروج زودهنگام</button>
  <button data-tab="v10">V10 Pro</button>
  <button data-tab="patterns">کارنامهٔ الگوها</button>
  <button data-tab="algos">الگوریتم‌ها</button>
  <button data-tab="brain">مغز دوم</button>
  <button data-tab="help">راهنما</button>
</nav>
<main>
  <section id="tab-live" class="on">
    <div class="card" id="sysHealth" style="margin-bottom:10px"></div>
    <div class="cards" id="liveCards"></div>
    <div class="row"><button class="act" id="stepBtn">قدم بعدی (گرفتن کندل تازه)</button>
      <span class="spin" id="stepMsg" style="display:none"></span>
      <button class="ghost" id="refreshBtn">تازه‌سازی</button></div>
    <div id="liveBody"></div>
  </section>

  <section id="tab-signals">
    <div class="card" id="sigValid" style="margin-bottom:10px"></div>
    <div class="row">
      <button class="act" id="manualBtn">🎯 گرفتن سیگنال دستی (مجازی)</button>
      <span class="spin" id="manualMsg" style="display:none"></span>
      <button class="ghost" id="sigReload">تازه‌سازی</button>
    </div>
    <div id="manualResult"></div>
    <div class="grid2">
      <div><label>نماد</label><select id="fSym"><option value="">همه</option></select></div>
      <div><label>قاعدهٔ بست</label><select id="fRule"><option value="">همه</option></select></div>
      <div><label>وضعیت</label><select id="fStatus"><option value="">همه</option>
        <option value="closed">بسته‌شده</option><option value="open">باز</option></select></div>
      <div><label>فقط بسته‌شده با قاعدهٔ ضدضرر؟</label>
        <label style="color:var(--fg)"><input type="checkbox" id="fRisk"> بله</label></div>
    </div>
    <div class="note">هر ردیف یک سیگنال است با شناسهٔ یکتا. روی ردیف بزن تا <b>پروندهٔ کامل</b>
      باز شود: قیمت‌ها، حد ضرر و سود، کارمزد، کندلِ ورود و خروج، اندیکاتورهای هر دو لحظه،
      و الگوهایی که سیگنال را ساختند یا تأییدش کردند.</div>
    <div id="sigTable"></div>
    <div id="sigDetail"></div>
  </section>

  <section id="tab-shadow">
    <div class="card" style="margin-bottom:10px">
      <div class="k">📰 دفتر خبر — «آن منبع سیگنال چقدر معتبر بود؟»</div>
      <div class="mut" style="margin-top:6px;line-height:1.8">
        وقتی خبری می‌آید و بازار زیر و رو می‌شود، این‌جا همان لحظه یک سیگنال
        <b>کاغذی</b> می‌زنی. جهت را خودت انتخاب می‌کنی (BUY/SELL).<br>
        <b>روی سیستم اثر ندارد:</b> سرمایه، اسلات، ژورنال و آمار اصلی دست نمی‌خورند
        (فایل جدا: <code>shadow.jsonl</code>).<br>
        <b>خروج خودکار با همان تنظیمات:</b> حد ضرر، حد سود، تریل، سربه‌سر و سقف
        زمانی — همان اعدادی که موتور اصلی می‌زند.
        <span id="shCfg" class="mut"></span>
      </div>
    </div>
    <div class="grid2">
      <div><label>نماد</label><select id="shSym"></select></div>
      <div><label>یادداشت خبر (اختیاری)</label>
        <input id="shNote" placeholder="مثلاً: تصویب ETF / هک صرافی / جلسهٔ فدرال"
          style="width:100%;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:10px;padding:9px 11px;font-family:inherit"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <button class="act" id="shBuy" style="background:#12351f;border-color:#2f7a4a">🟢 BUY (LONG)</button>
      <button class="act" id="shSell" style="background:#3a1414;border-color:#8b3a3a">🔴 SELL (SHORT)</button>
      <span class="spin" id="shMsg" style="display:none"></span>
      <button class="ghost" id="shReload">تازه‌سازی</button>
    </div>
    <div id="shResult"></div>
    <div id="shScore"></div>
    <div id="shTable"></div>
  </section>
  <section id="tab-ops">
    <div class="card" style="margin-bottom:10px">
      <div class="k">🗄️ مدیریت کلان — دادهٔ واقعی، آزمون‌های مستقل، معاینهٔ نصب</div>
      <div class="mut" style="margin-top:6px;line-height:1.8">
        کارهای سنگین این‌جا در <b>پس‌زمینه</b> اجرا می‌شوند تا صفحه قفل نشود.
        هر اجرا گزارش مستقل خودش را در <code>results/ops/</code> می‌نویسد و
        <b>هیچ‌چیز</b> در ژورنال معاملات، سرمایه یا آمار اعتبارسنجی نمی‌نویسد.
      </div>
      <div id="opsData" style="margin-top:8px;font-size:13px"></div>
    </div>

    <div class="row">
      <button class="ghost" id="opsProbe">🌐 بررسی دسترسی به داده</button>
      <button class="act" id="opsSync">♻️ به‌روزرسانی داده (۳۰ روز)</button>
      <button class="act" id="opsDownload">⬇️ دانلود یک‌ساله</button>
      <button class="act" id="opsExitStyles">🧪 آزمایش خروج (ثابت/شناور)</button>
      <button class="ghost" id="opsDoctor">🩺 معاینهٔ نصب</button>
      <button class="ghost" id="opsControl">📋 گزارش کنترل (یک فایل)</button>
    </div>
    <div id="opsMsg" class="mut" style="margin-top:6px"></div>
    <div id="opsControlOut" class="mut" style="margin-top:8px"></div>

    <div id="opsJobs"></div>
    <div id="opsReports"></div>
  </section>
  <section id="tab-lab">
    <div class="note">اینجا می‌توانی تنظیمات را عوض کنی و <b>روی همان داده</b> نتیجه را ببینی.
      ولی هر اجرا سه چیز را کنار نتیجه می‌نویسد تا گول نخوریم:
      <b>شمارهٔ آزمایش روی این داده</b>، <b>Δ با بازهٔ اطمینان ۹۰٪</b> نسبت به خط پایه، و
      <b>نتیجهٔ ۳۰٪ آخرِ بازه (بیرون‌نمونه)</b>. دروازه را <b>قبل</b> از دیدن نتیجه بنویس.</div>
    <div class="knob" style="margin-bottom:10px">
      <div class="t">دروازهٔ قبولی (از قبل)</div>
      <div class="grid2">
        <div><label>حداقل expectancy (R)</label><input id="gExp" type="number" step="0.01" value="0"></div>
        <div><label>حداقل تعداد معامله</label><input id="gN" type="number" step="10" value="100"></div>
        <div><label>بخش بیرون‌نمونه مثبت باشد؟</label>
          <label style="color:var(--fg)"><input type="checkbox" id="gOos" checked> بله</label></div>
        <div><label>Δ نسبت به خط پایه معنادار باشد؟</label>
          <label style="color:var(--fg)"><input type="checkbox" id="gCi"> بله</label></div>
      </div>
    </div>
    <div class="knob" style="margin-bottom:10px">
      <div class="t">تیم (الگو + تنظیماتِ نام‌دار)</div>
      <div class="grid2">
        <div><label>الگوی پایه</label><select id="teamSel"></select></div>
        <div><label>تیم ذخیره‌شده</label><select id="savedSel"><option value="">— هیچ —</option></select></div>
      </div>
      <div class="row" style="margin:8px 0 0">
        <input id="teamName" placeholder="اسم تیم تازه" style="flex:1;min-width:160px">
        <button class="ghost" id="teamSave">ذخیرهٔ تنظیمات فعلی به‌عنوان تیم</button>
        <button class="ghost" id="teamDel">حذف تیم انتخاب‌شده</button>
      </div>
      <div class="h" id="teamMsg">تیم فقط یک اسم برای یک دستهٔ تنظیمات است — اعتبار آماری نمی‌دهد.
        هر اجرا باز هم شمارهٔ آزمایش روی این داده و Δ با خط پایهٔ همان تیم را ثبت می‌کند.</div>
    </div>
    <div><label>اسم این آزمایش (فرضیه‌ات را بنویس)</label>
      <input id="runLabel" placeholder="مثال: تریل پهن‌تر، شاید روندهای بزرگ را نگه دارد"></div>
    <h3>نمادها</h3><div class="syms" id="syms"></div>
    <h3>تنظیمات <span class="mut" id="changedCount"></span></h3>
    <div id="knobs"></div>
    <div class="row"><button class="act" id="runBtn">اجرای آزمایش</button>
      <button class="ghost" id="resetBtn">برگرد به خط پایه</button>
      <span class="spin" id="runMsg" style="display:none"></span></div>
    <div id="runResult"></div>
  </section>

  <section id="tab-watch">
    <div class="note">هر نماد: <b>چه شرطی پاس است، چه شرطی نه، و وزن آمادگی</b>.
      وزن از همان شرط‌های واقعی موتور ساخته می‌شود (بایاس، فیلتر، تریگر، هزینه، اعتماد).
      <span id="watchMeta" class="mut"></span></div>
    <div class="row">
      <input id="wSearch" placeholder="جستجوی نماد…" style="flex:1;min-width:120px;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:10px;padding:9px 11px;font-family:inherit">
      <select id="wState"><option value="">همهٔ حالت‌ها</option>
        <option value="سیگنال">سیگنال</option><option value="نزدیک">نزدیک</option>
        <option value="دور">دور</option></select>
      <select id="wSort"><option value="ready">مرتب: آمادگی</option>
        <option value="sym">مرتب: نماد</option><option value="miss">مرتب: شرط‌های مانده</option></select>
      <button class="ghost" id="wReload">تازه‌سازی</button>
    </div>
    <div class="row"><label style="display:flex;gap:6px;align-items:center">
      <input type="checkbox" id="wOnlyNear"> فقط سیگنال و نزدیک</label></div>
    <div id="watchTable"></div>
    <div class="note">برای دیدن جزئیات هر نماد، روی ردیف بزن. اگر «شکار زنده» را اجرا نکرده‌ای:
      <code>bash run-auto.sh --watch</code></div>
  </section>

  <section id="tab-v10">
    <div class="note">سناریوی <b>V10 Pro</b> (بازگشت به میانگین: باند بولینگر + RSI + حجم)
      — جدا از الگوهای MTF، روی همان داده و همان هزینه. اعداد پروپوزال
      <b>ادعای تأییدنشده</b> است؛ فقط عددِ اجرای خودمان معتبر است.</div>
    <div class="row"><span id="v10Meta" class="mut"></span></div>
    <div class="cards" id="v10Cards"></div>
    <div class="row">
      <input id="v10Search" placeholder="جستجوی نماد…" style="flex:1;min-width:120px;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:10px;padding:9px 11px;font-family:inherit">
      <select id="v10Sort"><option value="score">مرتب: نزدیکی</option>
        <option value="sym">مرتب: نماد</option></select>
      <button class="ghost" id="v10Reload">تازه‌سازی</button>
    </div>
    <div id="v10Prox"></div>
    <div id="v10Trades"></div>
    <div class="note">اگر خالی است: <code>python3 -m mtflab v10 --compare --proximity</code>
      (یا <code>bash run-auto.sh --v10</code>).</div>
  </section>

  <section id="tab-algos">
    <div class="note">هر الگوریتم با <b>فرمول</b> و <b>مقدار فعلی پارامترهایش</b>.
      عددها از خود کد خوانده می‌شوند؛ اگر پارامتری عوض شود، همین‌جا عوض می‌شود.
      <span id="algosMeta" class="mut"></span></div>
    <div class="row">
      <input id="algosSearch" placeholder="جستجو در الگوها و فرمول‌ها…"
        style="flex:1;min-width:140px;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:10px;padding:9px 11px;font-family:inherit">
      <button class="ghost" id="algosReload">تازه‌سازی</button>
    </div>
    <div id="algosBody"></div>
  </section>

  <section id="tab-patterns">
    <div class="note">هر سیگنال می‌گوید بابت <b>کدام الگوها</b> بود. این‌جا معلوم می‌شود
      کدام الگو سود داد و کدام نه — با قاعدهٔ ثابت: زیر ۳۰ نمونه حکمی نمی‌دهیم.</div>
    <div class="row"><span id="patMeta" class="mut"></span></div>
    <div class="cards" id="patCards"></div>
    <div id="patPlan"></div>
    <div id="patByAlgo"></div>
    <div id="patByVote"></div>
    <div class="note">برای پر شدن: <code>bash run-auto.sh --live</code> ·
      گزارش کامل: <code>bash run-auto.sh --patterns</code></div>
  </section>

  <section id="tab-exit">
    <div class="note">همان دغدغهٔ «زود بسته شد»: برای هر معامله، <b>بیشترین سود شناور (MFE)</b>
      با سود واقعی مقایسه می‌شود. «سودِ ریخته‌شده» = MFE − نتیجه.</div>
    <div class="row">
      <input id="eSearch" placeholder="جستجو (نماد/قاعده)…" style="flex:1;min-width:120px;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:10px;padding:9px 11px;font-family:inherit">
      <select id="eCat"><option value="">همهٔ دسته‌ها</option>
        <option value="برندهٔ پس‌داده‌شده">برندهٔ پس‌داده‌شده</option>
        <option value="کوتاه‌شده">کوتاه‌شده</option><option value="خوب">خوب</option>
        <option value="ضرر پس از سود">ضرر پس از سود</option>
        <option value="حد ضرر سالم">حد ضرر سالم</option></select>
      <select id="eSort"><option value="give">مرتب: سود ریخته</option>
        <option value="r">مرتب: R</option><option value="ts">مرتب: زمان</option></select>
      <button class="ghost" id="eReload">تازه‌سازی</button>
    </div>
    <div class="cards" id="exitCards"></div>
    <div id="exitTable"></div>
  </section>

  <section id="tab-brain">
    <div class="note">«مغز دوم» یک مدل کوچک است که کنار اتوترید می‌نشیند تا سیگنال‌ها را
      <b>رتبه</b> بدهد یا کم‌اعتمادها را رد کند — نه این‌که سیگنال تازه بسازد.
      این صفحه فقط آخرین گزارش آزمون را نشان می‌دهد؛ ساختنش دستی است:
      <code>bash run-auto.sh --brain</code> (روی دادهٔ کش‌شده، بدون شبکه).</div>
    <div class="knob" style="margin-bottom:10px">
      <div class="t">آستانهٔ برچسبِ دیدگاه</div>
      <div class="grid2">
        <div><label>صعودی اگر احتمال ≥</label>
          <input id="bLong" type="number" step="0.01" min="0.51" max="0.95" value="0.55"></div>
        <div><label>نزولی اگر احتمال ≤</label>
          <input id="bShort" type="number" step="0.01" min="0.05" max="0.49" value="0.45"></div>
      </div>
      <div class="row" style="margin:8px 0 0">
        <button class="ghost" id="bSave">ذخیره</button>
        <span class="spin" id="bMsg" style="display:none"></span>
      </div>
      <div class="h">این دو عدد <b>فقط برچسب</b> را عوض می‌کنند (صعودی/نزولی/بی‌طرف).
        هیچ معامله‌ای از آن‌ها خوانده نمی‌شود — قرارداد نظاره‌گر دست‌نخورده است.
        آموزش مدل جداگانه است: <code>bash run-auto.sh --brain-view --train</code></div>
    </div>
    <h3>دیدگاه فعلی روی هر نماد (قبل از سیگنال)</h3>
    <div id="brainViews"></div>
    <div id="brainBody"></div>
  </section>

  <section id="tab-help">
    <div class="note">این صفحه برای وقتی است که نمی‌خواهی فکر کنی «این عدد خوب است یا نه».
      سه قانون کافی است؛ بقیه‌اش جزئیات است.</div>

    <h3>سه عددی که باید هر بار ببینی</h3>
    <div class="cards">
      <div class="card"><div class="k">تعداد معامله (n)</div>
        <div class="v">زیر ۳۰ = هیچ نتیجه‌ای نگیر</div></div>
      <div class="card"><div class="k">expectancy (R)</div>
        <div class="v">میانگین سود هر معامله به واحد ریسک</div></div>
      <div class="card"><div class="k">بیرون‌نمونه (۳۰٪ آخر)</div>
        <div class="v">اگر این منفی است، بقیه را باور نکن</div></div>
    </div>

    <h3>هر تب چه می‌کند</h3>
    <div class="note">
      <b>زنده</b>: کارت «سلامت سیستم» (کندل بعدی، تازگی داده، گرم‌شدن لایه‌ها، دروازهٔ بسته)، سرمایهٔ مجازی، معاملات باز، و «چرا وارد نشد». دکمهٔ «قدم بعدی» یک کندل تازه می‌گیرد.<br>
      <b>سیگنال‌ها</b>: هر سیگنال یک پرونده دارد؛ روی ردیف بزن تا ببینی با کدام الگو وارد شد و با کدام قاعده بسته شد.<br>
      <b>آزمایشگاه</b>: الگو را عوض کن، تنظیمات را تغییر بده و روی همان داده ببین چه می‌شود. دروازهٔ قبولی را <b>قبل</b> پر کن.<br>
      <b>آزمایش‌ها</b>: همهٔ اجراها ذخیره‌اند — حتی بدها. اگر فقط بهترین را نگه داریم، خودمان را گول زده‌ایم.<br>
      <b>مغز دوم</b>: یک مشاور کوچک. فقط نظر می‌دهد؛ تصمیم مال الگوریتم است. آستانه‌های آن فقط برچسب را عوض می‌کنند.
    </div>

    <h3>پنج قانون طلایی</h3>
    <div class="note">
      ۱. با سه معامله هیچ قضاوتی نکن. با نرخ برد ۳۵٪، سه ضرر پشت‌سرهم در ۲۷٪ مواقع طبیعی است.<br>
      ۲. دروازه را قبل از دیدن نتیجه بنویس؛ بعد از دیدن، فقط «توجیه» می‌نویسی.<br>
      ۳. هر بار که پارامتر عوض می‌کنی، یک آزمایش به دفتر اضافه می‌شود. پنجاه آزمایش = پنجاه نگاه.<br>
      ۴. دادهٔ نمایشی (demo) ساختگی است؛ برای یادگیری دکمه‌ها خوب است، برای نتیجه نه.<br>
      ۵. «تیم» یعنی یک دسته تنظیماتِ نام‌دار — نه یک لبهٔ تأییدشده.
    </div>

    <h3>«ضرر کرد، اشتباه بود؟»</h3>
    <div class="note">
      نه لزوماً. اول ببین <b>با کدام قاعده بسته شد</b>: اگر با حد ضرر/تریلینگ بسته شد، سیستم کارش را کرده —
      ضرر را کوچک نگه داشته. اگر با «پایان داده» یا «سقف زمان» بسته شد، آن‌وقت باید الگو را بازبینی کرد.
      فهرست کامل قاعده‌ها در تب «سیگنال‌ها» با برچسب «قاعدهٔ ضدضرر» می‌آید.
    </div>

    <h3>فایل‌ها و کد</h3>
    <div class="note">
      نقشهٔ کامل فایل‌ها (الگوها، تنظیمات، موتور، رصد) در <code>docs/ENGINE_MAP_FA.md</code> است و
      بستهٔ مستقل موتور با <code>python3 -m mtflab bundle</code> در
      <code>exports/autotrade_core/</code> ساخته می‌شود.
    </div>
  </section>

  <section id="tab-runs">
    <div class="note">همهٔ آزمایش‌ها ذخیره می‌شوند (در <code>results/live_lab/runs/</code>).
      هیچ آزمایشی دور ریخته نمی‌شود — چون اگر فقط بهترین را نگه داریم، دقیقاً همان
      تورِ overfitting است. روی ردیف بزن تا جزئیاتش باز شود.</div>
    <div id="runsTable"></div>
    <div id="runDetail"></div>
  </section>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = (v, d=2) => (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(d);
const sgn = v => (v === null || v === undefined) ? "—" : (v > 0 ? "pos" : (v < 0 ? "neg" : ""));
const R = v => v === null || v === undefined ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2);
async function api(p, opt) {
  const r = await fetch(p, opt);
  if (!r.ok) throw new Error((await r.text()).slice(0, 300));
  return await r.json();
}
function table(headers, rows) {
  if (!rows.length) return `<div class="mut" style="padding:8px">داده‌ای نیست</div>`;
  return `<table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead>
  <tbody>${rows.map(r=>`<tr>${r.map((c,i)=>`<td class="${i>0?'num':''}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function cards(items) {
  return items.map(([k,v,cls]) => `<div class="card"><div class="k">${k}</div><div class="v ${cls||''}">${v}</div></div>`).join("");
}

/* ── تب‌ها ─────────────────────────────────────────────────────────── */
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("on"));
  document.querySelectorAll("section").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); $("#tab-" + b.dataset.tab).classList.add("on");
  if (b.dataset.tab === "live") loadSystem();
  if (b.dataset.tab === "signals") loadSignals();
  if (b.dataset.tab === "runs") loadRuns();
  if (b.dataset.tab === "brain") loadBrain();
  if (b.dataset.tab === "watch") loadWatch();
  if (b.dataset.tab === "exit") loadExit();
  if (b.dataset.tab === "v10") loadV10();
  if (b.dataset.tab === "patterns") loadPatterns();
  if (b.dataset.tab === "algos") loadAlgos();
  if (b.dataset.tab === "shadow") loadShadow();
  if (b.dataset.tab === "ops") loadOps();
  if (b.dataset.tab === "signals") loadValidation();
});

/* ── الگوریتم‌ها ───────────────────────────────────────────────────── */
let ALGOS = null;
function renderAlgos() {
  if (!ALGOS || !ALGOS.sections) { $("#algosBody").innerHTML = `<div class="mut">کاتالوگ بار نشد</div>`; return; }
  const q = ($("#algosSearch").value || "").trim().toLowerCase();
  const hit = it => !q || JSON.stringify(it).toLowerCase().includes(q);
  $("#algosMeta").textContent = ` · ${ALGOS.counts.items} مورد · تایم‌فریم ${ALGOS.tf.trigger}/${ALGOS.tf.filter}/${ALGOS.tf.bias}`;
  $("#algosBody").innerHTML = ALGOS.sections.map(sec => {
    const items = (sec.items || []).filter(hit);
    if (!items.length) return "";
    return `<h3 style="margin-top:14px">${esc(sec.title)}</h3>
      ${sec.note ? `<div class="mut" style="font-size:11px;margin-bottom:6px">${esc(sec.note)}</div>` : ""}
      ${items.map(it => `<div class="card" style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
          <div><b>${esc(it.label)}</b> <span class="mut">(${esc(it.id)} · ${esc(it.kind)})</span></div>
          <div class="mut" style="font-size:11px">${esc(it.source || "")}</div>
        </div>
        <div style="font-size:12px;margin-top:4px">${esc(it.summary || "")}</div>
        ${(it.formulas || []).map(f => `<div style="margin-top:8px">
          <div class="mut" style="font-size:11px">${esc(f.title)}</div>
          <pre style="background:#0d1420;border:1px solid var(--line);border-radius:8px;padding:8px;overflow:auto;font-size:12px">${esc(f.expr)}</pre>
          ${f.values ? `<div style="font-size:11px">مقادیر فعلی: <code>${esc(f.values)}</code></div>` : ""}
        </div>`).join("")}
      </div>`).join("")}`;
  }).join("") || `<div class="mut">چیزی با این جستجو پیدا نشد.</div>`;
}
async function loadAlgos() {
  try { ALGOS = await api("/api/algorithms"); } catch (e) { ALGOS = null; }
  renderAlgos();
}
$("#algosSearch").oninput = renderAlgos;
$("#algosReload").onclick = loadAlgos;


/* ── دفتر خبر (اعتبارسنجی منبع، بی‌اثر روی سیستم) ───────────────────── */
let SHADOW = null;
function _num(x, d) { return (x === null || x === undefined || x === "") ? "—"
  : Number(x).toFixed(d === undefined ? 4 : d); }
function _shFillSyms() {
  const sel = $("#shSym"); if (!sel || !SHADOW) return;
  const cur = sel.value;
  const syms = SHADOW.symbols || [];
  if (sel.dataset.n !== String(syms.length)) {
    sel.innerHTML = syms.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    sel.dataset.n = String(syms.length);
  }
  if (cur && syms.includes(cur)) sel.value = cur;
}
function renderShadow() {
  const box = $("#shScore"), tbl = $("#shTable");
  if (!SHADOW) { box.innerHTML = `<div class="mut">دفتر خبر بار نشد.</div>`; tbl.innerHTML = ""; return; }
  _shFillSyms();
  const cfg = SHADOW.cfg || {};
  $("#shCfg").textContent = ` · الگو: ${SHADOW.variant} · حد ضرر ${cfg.stop_atr_mult}×ATR`
    + ` · حد سود ${(cfg.take_profit_atr_mult && cfg.take_profit_atr_mult < 50) ? cfg.take_profit_atr_mult + "×ATR" : "بدون TP"}`
    + ` · تریل ${cfg.trail_enabled ? cfg.trail_atr_mult + "×ATR" : "خاموش"}`
    + ` · کارمزد ${cfg.fee_bps}bps + اسلیپیج ${cfg.slippage_pct}٪`;

  const sc = SHADOW.scorecard || {}, ov = sc.overall || {};
  const verdict = (v) => v ? `<span class="${v.code === "keep" ? "ok" : (v.code === "drop" ? "bad" : "mut")}">${esc(v.label)}</span>` : "—";
  const srcRows = (sc.by_source || []).map(x => `<tr><td><code>${esc(x.id)}</code></td>
    <td class="num">${x.n}</td><td class="num">${x.win_rate == null ? "—" : x.win_rate + "٪"}</td>
    <td class="num">${x.expectancy_r == null ? "—" : x.expectancy_r}</td><td>${verdict(x.verdict)}</td></tr>`).join("");
  const agrRows = (sc.by_agreement || []).filter(x => x.n).map(x => `<tr><td>${esc(x.label)}</td>
    <td class="num">${x.n}</td><td class="num">${x.win_rate}٪</td>
    <td class="num">${x.expectancy_r}</td><td>${verdict(x.verdict)}</td></tr>`).join("");
  box.innerHTML = `<div class="card" style="margin:10px 0">
    <div class="k">کارنامهٔ اعتبار منبع</div>
    <div style="margin-top:6px;font-size:13px">
      بسته‌شده: <b>${ov.n || 0}</b> · باز: <b>${sc.open_n || 0}</b>
      · نرخ برد: <b>${ov.win_rate == null ? "—" : ov.win_rate + "٪"}</b>
      · expectancy: <b>${ov.expectancy_r == null ? "—" : ov.expectancy_r + " R"}</b>
      ${sc.verdict ? " · " + verdict(sc.verdict) : ""}
    </div>
    <div class="mut" style="margin-top:4px;font-size:12px">${esc(sc.note || "")}</div>
    ${srcRows ? `<div style="margin-top:10px" class="mut">به تفکیک الگویی که همان لحظه رأی داد:</div>
      <table style="margin-top:4px"><thead><tr><th>منبع</th><th>n</th><th>برد</th>
      <th>expectancy</th><th>حکم</th></tr></thead><tbody>${srcRows}</tbody></table>` : ""}
    ${agrRows ? `<div style="margin-top:10px" class="mut">هم‌جهتی با بایاس تایم‌فریم بالا:</div>
      <table style="margin-top:4px"><thead><tr><th>گروه</th><th>n</th><th>برد</th>
      <th>expectancy</th><th>حکم</th></tr></thead><tbody>${agrRows}</tbody></table>` : ""}
  </div>`;

  const rows = (SHADOW.rows || []).map((r, i) => {
    const st = r.status === "closed" ? `<span class="ok">بسته</span>` : `<span class="mut">باز</span>`;
    const votes = ((r.source || {}).votes || {}).ids || [];
    const agree = (r.source || {}).agree;
    const agreeTxt = agree === true ? "هم‌جهت" : (agree === false ? "خلاف بایاس" : "—");
    const rv = r.r_multiple != null ? r.r_multiple : r.unrealized_r;
    const pv = r.net_pct != null ? r.net_pct : r.unrealized_pct;
    return `<tr data-sh="${i}">
      <td><b>${esc(r.symbol)}</b></td>
      <td>${r.side === "LONG" ? "🟢 BUY" : "🔴 SELL"}</td>
      <td class="num">${_num(r.entry)}</td>
      <td class="num">${_num(r.stop)}</td>
      <td class="num">${r.take == null ? "—" : _num(r.take)}</td>
      <td class="num">${_num(r.stop_dist)}</td>
      <td>${st}${r.reason ? ` <span class="mut">(${esc(r.reason)})</span>` : ""}</td>
      <td class="num">${rv == null ? "—" : _num(rv, 2)}</td>
      <td class="num ${pv > 0 ? "ok" : (pv < 0 ? "bad" : "")}">${pv == null ? "—" : _num(pv, 2) + "٪"}</td>
      <td>${votes.length ? votes.map(v => `<code>${esc(v)}</code>`).join("، ") : "—"}</td>
      <td class="mut">${esc(agreeTxt)}</td>
      <td class="mut">${esc(r.note || "")}</td>
      <td>${new Date(r.bar_ts).toLocaleString("fa-IR")}</td>
      <td>${r.status === "open" ? `<button class="ghost shclose" data-id="${esc(r.id)}">بستن دستی</button>` : "—"}</td>
    </tr>`;
  }).join("");
  tbl.innerHTML = rows ? `<div class="card"><div class="k">سیگنال‌های خبری</div>
    <table style="margin-top:6px"><thead><tr><th>نماد</th><th>جهت</th><th>ورود</th>
    <th>حد ضرر</th><th>حد سود</th><th>فاصله</th><th>وضعیت</th><th>R</th><th>%</th>
    <th>منبع (رأی)</th><th>بایاس</th><th>یادداشت</th><th>کندل</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="mut" style="margin-top:6px;font-size:11px">R و درصد با کارمزد و اسلیپیج محاسبه شده‌اند. «—» یعنی هنوز داده‌ای نیست.</div>
    </div>` : `<div class="card mut">هنوز سیگنال خبری ثبت نشده. نماد را انتخاب کن و BUY یا SELL را بزن.</div>`;
  document.querySelectorAll(".shclose").forEach(b => b.onclick = () => shadowClose(b.dataset.id));
}
async function loadShadow() {
  try { SHADOW = await api("/api/shadow"); } catch (e) { SHADOW = null; }
  renderShadow();
}
async function shadowTake(side) {
  const sym = ($("#shSym") || {}).value || "";
  if (!sym) { alert("اول نماد را انتخاب کن."); return; }
  const note = ($("#shNote") || {}).value || "";
  const msg = $("#shMsg");
  msg.style.display = "inline"; msg.textContent = "در حال ثبت…";
  const q = new URLSearchParams({symbol: sym, side: side, note: note});
  let r = null;
  try { r = await api("/api/shadow_open?" + q.toString()); }
  catch (e) { r = {ok: false, note: "خطای شبکه"}; }
  msg.style.display = "none";
  $("#shResult").innerHTML = `<div class="card" style="margin:10px 0">
    <div class="k">${r.ok ? "✅ ثبت شد" : "⚠️ ثبت نشد"}</div>
    <div class="mut" style="margin-top:4px">${esc(r.note || "")}</div>
    ${r.trade ? `<div style="margin-top:6px;font-size:12px">
      منبع همان لحظه: ${(((r.trade.source || {}).votes || {}).ids || []).map(v => `<code>${esc(v)}</code>`).join("، ") || "هیچ الگویی شرط ورود نداشت"}
      · بایاس: ${esc(((r.trade.source || {}).bias) || "—")}
      · قیمت از: ${esc(r.trade.price_source === "ticker" ? "قیمت زندهٔ بازار" : "بستهٔ آخرین کندل")}
    </div>` : ""}
  </div>`;
  if (r.book) { SHADOW = Object.assign({}, SHADOW, r.book); }
  await loadShadow();
}
async function shadowClose(id) {
  if (!confirm("این سیگنال خبری دستی بسته شود؟ (قیمت = بستهٔ آخرین کندل)")) return;
  let r = null;
  try { r = await api("/api/shadow_close?id=" + encodeURIComponent(id)); }
  catch (e) { r = {ok: false, note: "خطای شبکه"}; }
  if (!r.ok) alert(r.note || "بسته نشد");
  await loadShadow();
}
$("#shBuy").onclick = () => shadowTake("LONG");
$("#shSell").onclick = () => shadowTake("SHORT");
$("#shReload").onclick = loadShadow;



/* ── سلامت سیستم (چرا سیگنالی نیست؟) ───────────────────────────────── */
let SYS = null, SYS_TICK = null;
function _mmss(sec) {
  if (sec == null) return "—";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}
function _sysCountdown() {
  if (!SYS || !SYS.clock || !SYS.clock.next_close_ms) return;
  const el = $("#sysCount");
  if (!el) return;
  const left = Math.max(0, Math.round((SYS.clock.next_close_ms - Date.now()) / 1000));
  el.textContent = _mmss(left);
}
function renderSystem() {
  const box = $("#sysHealth");
  if (!box) return;
  if (!SYS) { box.innerHTML = `<div class="mut">سلامت سیستم خوانده نشد.</div>`; return; }
  const v = SYS.verdict || {}, c = SYS.clock || {}, w = SYS.warmup || {}, j = SYS.journal || {};
  const cls = v.code === "signal" ? "ok" : (["stale", "no_data", "warmup", "error"].includes(v.code) ? "bad" : "");
  const rows = (SYS.rows || []).map(r => `<tr>
    <td><b>${esc(r.symbol)}</b></td>
    <td class="num">${r.bars}</td>
    <td>${esc(r.last_candle_utc || "—")}</td>
    <td class="num ${r.fresh ? "ok" : "bad"}">${r.behind_bars == null ? "—" : (r.fresh ? "به‌روز" : r.behind_bars + " کندل عقب")}</td>
    <td>${esc(r.state || "—")}${r.readiness != null ? ` <span class="mut">${Math.round(r.readiness * 100)}٪</span>` : ""}</td>
    <td class="mut" style="font-size:11px">${esc(r.blocking || "—")}</td>
  </tr>`).join("");
  const warm = (w.rows || []).map(x => `<span class="mut" style="margin-left:10px">
    ${x.ready ? "✅" : "❌"} ${esc(x.layer)} (${esc(x.tf)}): ${x.have}/${x.need}</span>`).join("");
  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
      <div class="k ${cls}">${v.code === "signal" ? "🎯" : "🩺"} ${esc(v.label || "—")}</div>
      <div class="mut" style="font-size:12px">
        کندل ${esc((c.tf || ""))} · آخرین بسته: ${esc(c.last_closed_utc || "—")}
        · بستهٔ بعدی: ${esc(c.next_close_utc || "—")} (تا <b id="sysCount">${_mmss(c.seconds_to_next)}</b>)
      </div>
    </div>
    <div style="margin-top:6px;font-size:13px">${esc(v.detail || "")}</div>
    ${rows ? `<table style="margin-top:8px"><thead><tr><th>نماد</th><th>کندل</th>
      <th>آخرین کندل</th><th>تازگی</th><th>وضعیت</th><th>مانع</th></tr></thead>
      <tbody>${rows}</tbody></table>` : ""}
    <div style="margin-top:8px;font-size:11px">گرم‌کردن لایه‌ها:${warm || " —"}</div>
    <div class="mut" style="margin-top:4px;font-size:11px">ژورنال: ${j.opens || 0} ورود ·
      ${j.closes || 0} خروج · آخرین رکورد: ${esc(j.last_record_utc || "—")}
      ${SYS.note ? " · " + esc(SYS.note) : ""}</div>`;
  if (!SYS_TICK) SYS_TICK = setInterval(_sysCountdown, 1000);
}
async function loadSystem() {
  try { SYS = await api("/api/system"); } catch (e) { SYS = null; }
  renderSystem();
}

/* ── مدیریت کلان (داده + آزمون‌های مستقل) ─────────────────────────── */
let OPS = null, OPS_TIMER = null;
function _kb(n) { return n == null ? "—" : (n / 1024).toFixed(0) + " KB"; }
function renderOps() {
  const d = (OPS && OPS.data) || {};
  const net = OPS && OPS.network;
  $("#opsData").innerHTML = `
    <div>فایل داده: <b>${d.files || 0}</b> · نمادها: <b>${(d.symbols || []).length}</b>
      · بازه: <b>${d.oldest || "—"} → ${d.newest || "—"}</b> · حجم: <b>${_kb(d.bytes)}</b>
      ${d.by_tf && Object.keys(d.by_tf).length ? " · " + Object.entries(d.by_tf).map(([k, v]) => `${k}×${v}`).join("، ") : ""}</div>
    <div style="margin-top:4px">دسترسی به دادهٔ بازار:
      <b class="${net ? "ok" : "mut"}">${net ? "آخرین اجرا سالم بود" : "بررسی نشده / ناموفق"}</b>
      ${net ? ` <span class="mut">(${esc(net)})</span>` : ""}</div>`;

  const jobs = (OPS && OPS.jobs) || [];
  $("#opsJobs").innerHTML = jobs.length ? `<div class="card" style="margin:10px 0">
    <div class="k">کارها</div>
    <table style="margin-top:6px"><thead><tr><th>کار</th><th>وضعیت</th><th>زمان</th>
    <th>خلاصه</th></tr></thead><tbody>
    ${jobs.slice(0, 10).map(j => `<tr>
      <td><b>${esc(j.title || j.kind)}</b><div class="mut" style="font-size:11px">${esc(j.started_utc || "")}</div></td>
      <td>${j.status === "done" ? '<span class="ok">تمام</span>'
        : (j.status === "error" ? '<span class="bad">خطا</span>' : '<span class="mut">در حال اجرا…</span>')}</td>
      <td class="num">${j.duration_s == null ? "—" : j.duration_s + "s"}</td>
      <td style="font-size:12px">${esc(_opsSummary(j))}
        ${(j.log || []).length ? `<details style="margin-top:4px"><summary class="mut">گزارش اجرا</summary>
          <pre style="white-space:pre-wrap;font-size:11px;max-height:220px;overflow:auto">${esc((j.log || []).join("\n"))}</pre></details>` : ""}
      </td></tr>`).join("")}
    </tbody></table></div>` : "";

  const reps = (OPS && OPS.reports) || [];
  $("#opsReports").innerHTML = reps.length ? `<div class="card" style="margin:10px 0">
    <div class="k">گزارش‌های مستقل</div>
    <div class="mut" style="font-size:11px;margin-top:4px">هر اجرا یک فایل جدا؛ روی نام بزن تا محتوایش باز شود.</div>
    <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px">
      ${reps.map(r => `<button class="ghost opsrep" data-id="${esc(r.id)}"
        style="font-size:11px">📄 ${esc(r.name)}</button>`).join("")}
    </div>
    <pre id="opsReportText" style="white-space:pre-wrap;font-size:11px;max-height:420px;overflow:auto;margin-top:8px"></pre>
    </div>` : `<div class="card mut" style="margin:10px 0">هنوز گزارشی ساخته نشده.</div>`;
  document.querySelectorAll(".opsrep").forEach(b => b.onclick = () => showOpsReport(b.dataset.id));

  if ((OPS && (OPS.running || []).length) && !OPS_TIMER) {
    OPS_TIMER = setTimeout(async () => { OPS_TIMER = null; await loadOps(); }, 2500);
  }
}
function _opsSummary(j) {
  const s = j.summary || {};
  if (j.status === "error") return j.error || "خطا";
  if (s.total_bars != null) return `${s.total_bars} کندل در ${(s.saved || []).length} فایل`;
  if (s.updated) return `${s.updated.reduce((a, x) => a + (x.added || 0), 0)} کندل تازه`;
  if (s.entries != null) return `${s.entries} ورود مشترک · ${s.policies} سیاست · صدر: ${(s.top || {}).label || "—"}`;
  if (s.ok != null && s.checks != null) return s.ok ? "همه‌چیز سالم" : "مشکل پیدا شد (گزارش را ببین)";
  if (s.base_url) return "دسترسی سالم";
  return "";
}
async function loadOps() {
  try { OPS = await api("/api/ops"); } catch (e) { OPS = null; }
  renderOps();
}
async function opsRun(kind, q) {
  const msg = $("#opsMsg");
  msg.textContent = "در حال شروع…";
  let r = null;
  try { r = await api("/api/ops/start?kind=" + encodeURIComponent(kind) + (q || "")); }
  catch (e) { r = {ok: false, note: "خطای شبکه"}; }
  msg.textContent = r.ok ? (r.note || "شروع شد") : ("⚠️ " + (r.note || "شروع نشد"));
  await loadOps();
}
async function showOpsReport(id) {
  let r = null;
  try { r = await api("/api/ops/report?id=" + encodeURIComponent(id)); }
  catch (e) { r = {text: "خطا در خواندن گزارش"}; }
  $("#opsReportText").textContent = r.text || r.error || "";
}
$("#opsProbe").onclick = () => opsRun("probe");
$("#opsSync").onclick = () => opsRun("sync", "&sync_days=30");
$("#opsDownload").onclick = () => {
  if (!confirm("دانلود یک‌ساله از Bybit شروع شود؟ (چند دقیقه طول می‌کشد و در پس‌زمینه اجرا می‌شود)")) return;
  opsRun("download", "&days=365");
};
$("#opsExitStyles").onclick = () => opsRun("exitstyles", "&tf=auto&variant=base");
$("#opsDoctor").onclick = () => opsRun("doctor");
$("#opsControl").onclick = async () => {
  const box = $("#opsControlOut");
  box.textContent = "در حال ساخت گزارش…";
  let r = null;
  try { r = await api("/api/control"); } catch (e) { r = null; }
  if (!r || r.error) { box.textContent = "⚠️ گزارش ساخته نشد" + (r && r.error ? ": " + r.error : ""); return; }
  box.innerHTML =
    '<div><b>' + (r.summary || "—") + '</b></div>' +
    '<div style="margin-top:6px">📄 <a href="/api/control/file?fmt=md" download>دریافت گزارش .md</a>' +
    ' · 🧾 <a href="/api/control/file?fmt=json" download>JSON</a></div>' +
    '<pre style="white-space:pre-wrap;max-height:360px;overflow:auto;margin-top:8px;font-size:12px"></pre>';
  const pre = box.querySelector("pre");
  if (pre) pre.textContent = r.md_text || "";
};

/* ── کارنامهٔ الگوها ───────────────────────────────────────────────── */
let PAT = {available: false};
function _pct(x) { return x == null ? "—" : x.toFixed(1) + "٪"; }
function _r(x) { return x == null ? "—" : x.toFixed(3) + "R"; }
function renderPatterns() {
  const D = PAT;
  if (!D.available) {
    $("#patMeta").textContent = "";
    $("#patCards").innerHTML = "";
    $("#patPlan").innerHTML = `<div class="mut" style="padding:10px">${D.hint || D.reason || "چیزی نیست"}</div>`;
    $("#patByAlgo").innerHTML = ""; $("#patByVote").innerHTML = "";
    return;
  }
  const c = D.card || {}, plan = D.plan || {};
  $("#patMeta").textContent = ` · ${c.signals_total} سیگنال · ${c.closed_total} بسته · ` +
    `${c.voted_signals} با رأی الگو · ${c.unvoted_signals} بدون رأی`;
  const conf = (c.confluence || {}).multi || {}, solo = (c.confluence || {}).solo || {};
  $("#patCards").innerHTML = [
    v10Card("نگه‌دار", (plan.keep || []).length, "pos"),
    v10Card("نامزد حذف", (plan.drop || []).length, "neg"),
    v10Card("داده کافی نیست", (plan.need_more || []).length),
    v10Card("expectancy هم‌گرا", _r(conf.expectancy_r)),
    v10Card("expectancy تک‌الگو", _r(solo.expectancy_r)),
  ].join("");
  const fmt = x => `<b>${x.id}</b> (${_r(x.expectancy_r)}، n=${x.n})`;
  $("#patPlan").innerHTML = `<div class="card" style="margin:10px 0">
    <div class="k">پیشنهاد (قاعده: n ≥ ۳۰ و expectancy &gt; ۰ ⇒ نگه‌دار)</div>
    <div style="margin-top:6px">${(plan.keep || []).length ? "🟢 " + plan.keep.map(fmt).join("، ") : "🟢 —"}</div>
    <div class="pos" style="margin-top:4px">${(plan.drop || []).length ? "🔴 " + plan.drop.map(fmt).join("، ") : "🔴 هیچ الگویی نامزد حذف نیست"}</div>
    <div class="mut" style="margin-top:4px">${(plan.need_more || []).length ? "⏳ " + plan.need_more.map(x => `<b>${x.id}</b> (n=${x.n})`).join("، ") : ""}</div>
  </div>`;

  const byAlgo = c.by_algorithm || {};
  const algoRows = Object.values(byAlgo);
  $("#patByAlgo").innerHTML = algoRows.length ? `<table><thead><tr>
    <th>الگویی که سیگنال ساخت</th><th>سیگنال</th><th>بسته</th><th>نرخ برد</th>
    <th>expectancy</th><th>ضریب سود</th><th>حکم</th></tr></thead><tbody>
    ${algoRows.map(d => `<tr><td><b>${d.id}</b></td><td class="num">${d.signals}</td>
      <td class="num">${d.closed}</td><td class="num">${_pct(d.win_rate)}</td>
      <td class="num ${d.expectancy_r > 0 ? "pos" : "neg"}">${_r(d.expectancy_r)}</td>
      <td class="num">${d.profit_factor ?? "—"}</td><td>${d.verdict}</td></tr>`).join("")}
    </tbody></table>` : "";

  const byVote = Object.values(c.by_pattern_vote || {});
  $("#patByVote").innerHTML = byVote.length ? `<table style="margin-top:10px"><thead><tr>
    <th>الگو (رأی)</th><th>حضور</th><th>expectancy</th><th>تنها</th>
    <th>با تأیید دیگران</th><th>حکم</th></tr></thead><tbody>
    ${byVote.map(v => `<tr><td><b>${v.id}</b></td><td class="num">${v.signals}</td>
      <td class="num ${v.expectancy_r > 0 ? "pos" : "neg"}">${_r(v.expectancy_r)}</td>
      <td class="num">${_r((v.solo || {}).expectancy_r)} <span class="mut">(${(v.solo || {}).n || 0})</span></td>
      <td class="num">${_r((v.concurrent || {}).expectancy_r)} <span class="mut">(${(v.concurrent || {}).n || 0})</span></td>
      <td>${v.verdict}</td></tr>`).join("")}
    </tbody></table>` : "";
}
async function loadPatterns() {
  try { PAT = await api("/api/patterns"); }
  catch (e) { PAT = {available: false, hint: "خطا در خواندن کارنامه"}; }
  renderPatterns();
}

/* ── V10 Pro ───────────────────────────────────────────────────────── */
let V10 = {available: false, rows: [], trades: []};
function v10Card(k, v, cls) {
  return `<div class="card"><div class="k">${k}</div><div class="v ${cls || ""}">${v}</div></div>`;
}
function renderV10() {
  const D = V10;
  if (!D.available) {
    $("#v10Meta").textContent = " · گزارشی نیست";
    $("#v10Cards").innerHTML = "";
    $("#v10Prox").innerHTML = `<div class="mut" style="padding:10px">${D.hint || ""}</div>`;
    $("#v10Trades").innerHTML = "";
    return;
  }
  const s = D.summary || {};
  const age = D.stale_sec == null ? "" : ` · ${Math.round(D.stale_sec / 60)} دقیقه پیش`;
  const src = (D.data && D.data.sources) ? D.data.sources.join("، ") : "نامشخص";
  const warn = (D.data && D.data.labeled === false) ? " · ⚠️ منبع داده برچسب ندارد" : "";
  $("#v10Meta").textContent = ` · ${D.tf || ""} · ورود ${D.entry || ""} · داده: ${src}${warn}${age}`;
  const cls = x => (x > 0 ? "pos" : x < 0 ? "neg" : "");
  $("#v10Cards").innerHTML = [
    v10Card("معامله", s.n ?? "—"),
    v10Card("نرخ برد", (s.win_rate == null ? "—" : s.win_rate.toFixed(1) + "٪")),
    v10Card("expectancy", (s.expectancy_r == null ? "—" : s.expectancy_r.toFixed(3) + "R"), cls(s.expectancy_r)),
    v10Card("ضریب سود", (s.profit_factor == null ? "—" : s.profit_factor.toFixed(2)), cls((s.profit_factor || 1) - 1)),
    v10Card("بیشترین افت", (s.max_dd_pct == null ? "—" : s.max_dd_pct.toFixed(1) + "٪"), "neg"),
    v10Card("هزینهٔ کل", (s.fees_pct_total ?? "—") + "٪", "neg"),
  ].join("");

  const q = ($("#v10Search").value || "").trim().toUpperCase();
  const sort = $("#v10Sort").value;
  let rows = (D.rows || []).filter(r => !q || (r.symbol || "").toUpperCase().includes(q));
  if (sort === "sym") rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
  else rows.sort((a, b) => Math.max(b.short_score, b.long_score) - Math.max(a.short_score, a.long_score));
  $("#v10Prox").innerHTML = rows.length ? `<table><thead><tr>
    <th>نماد</th><th>قیمت</th><th>LONG</th><th>SHORT</th><th>RSI</th><th>حجم×</th><th>سیگنال</th>
    </tr></thead><tbody>${rows.map(r => `<tr>
      <td><b>${r.symbol}</b></td><td class="num">${r.price ?? "—"}</td>
      <td style="min-width:110px">${readinessBar(Math.round(r.long_score || 0))}</td>
      <td style="min-width:110px">${readinessBar(Math.round(r.short_score || 0))}</td>
      <td class="num">${r.rsi ?? "—"}</td><td class="num">${r.vol_ratio ?? "—"}</td>
      <td class="${r.signal ? "pos" : "mut"}">${r.signal ? r.signal.side : "—"}</td>
    </tr>`).join("")}</tbody></table>` : `<div class="mut" style="padding:10px">نزدیکی ثبت نشده.</div>`;

  const ts = (D.trades || []).slice(-20).reverse();
  $("#v10Trades").innerHTML = ts.length ? `<table style="margin-top:10px"><thead><tr>
    <th>نماد</th><th>جهت</th><th>ورود</th><th>خروج</th><th>R</th><th>قاعده</th><th>کندل</th>
    </tr></thead><tbody>${ts.map(t => `<tr>
      <td>${t.symbol || "—"}</td>
      <td class="${t.side === "LONG" ? "pos" : "neg"}">${t.side}</td>
      <td class="num">${t.entry}</td><td class="num">${t.exit}</td>
      <td class="num ${t.r > 0 ? "pos" : "neg"}">${t.r}</td>
      <td>${t.reason_fa || t.reason}</td><td class="num">${t.bars}</td>
    </tr>`).join("")}</tbody></table>` : "";
}
async function loadV10() {
  try {
    V10 = await api("/api/v10");
  } catch (e) {
    V10 = {available: false, rows: [], trades: [], hint: "خطا در خواندن گزارش"};
  }
  renderV10();
}
$("#v10Search").oninput = renderV10;
$("#v10Sort").onchange = renderV10;
$("#v10Reload").onclick = loadV10;

/* ── شکار زنده ─────────────────────────────────────────────────────── */
let WATCH = {rows: [], n: 0};
function readinessBar(pct) {
  const cls = pct >= 75 ? "pos" : (pct >= 45 ? "" : "neg");
  return `<div style="display:flex;align-items:center;gap:7px">
    <div style="flex:1;height:7px;background:#0d1420;border-radius:6px;overflow:hidden">
      <div style="width:${Math.max(2, Math.min(100, pct))}%;height:100%;background:${
        pct >= 75 ? "var(--pos,#4ade80)" : pct >= 45 ? "#eab308" : "#64748b"}"></div>
    </div><b class="num ${cls}">${pct}٪</b></div>`;
}
function renderWatch() {
  const q = ($("#wSearch").value || "").trim().toUpperCase();
  const st = $("#wState").value;
  const onlyNear = $("#wOnlyNear").checked;
  const sort = $("#wSort").value;
  let rows = (WATCH.rows || []).filter(r => {
    if (q && !(r.symbol || "").toUpperCase().includes(q)) return false;
    if (st && r.state !== st) return false;
    if (onlyNear && !["سیگنال", "نزدیک"].includes(r.state)) return false;
    return true;
  });
  if (sort === "sym") rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
  else if (sort === "miss") rows.sort((a, b) => (a.missing || []).length - (b.missing || []).length);
  else rows.sort((a, b) => (b.readiness || 0) - (a.readiness || 0));
  $("#watchMeta").textContent = WATCH.n
    ? ` · ${WATCH.n} نماد · ${WATCH.signals} سیگنال · ${WATCH.near} نزدیک · ${WATCH.created_utc || ""}${WATCH.intra_candle ? " · داخل کندل (تقریبی)" : ""}`
    : " · هنوز پیمایشی ثبت نشده";
  if (!rows.length) {
    $("#watchTable").innerHTML = `<div class="mut" style="padding:10px">چیزی نیست.
      برای پر شدن: <code>bash run-auto.sh --watch --once</code></div>`;
    return;
  }
  $("#watchTable").innerHTML = `<table><thead><tr>
    <th>نماد</th><th>قیمت</th><th>آمادگی</th><th>حالت</th><th>مانده</th><th>توضیح</th>
    </tr></thead><tbody>${rows.map((r, i) => `<tr data-wi="${i}" style="cursor:pointer">
      <td><b>${r.symbol}</b></td>
      <td class="num">${r.price ?? "—"}</td>
      <td style="min-width:130px">${readinessBar(Math.round((r.readiness || 0) * 100))}</td>
      <td class="${r.state === "سیگنال" ? "pos" : r.state === "نزدیک" ? "" : "mut"}">${r.state}</td>
      <td class="num">${(r.missing || []).length}</td>
      <td class="mut" style="font-size:11px">${(r.blocking || "").slice(0, 70)}</td>
    </tr>`).join("")}</tbody></table>
    <div id="watchDetail"></div>`;
  $("#watchTable").querySelectorAll("tr[data-wi]").forEach(tr => tr.onclick = () => {
    const r = rows[Number(tr.dataset.wi)];
    $("#watchDetail").innerHTML = `<div class="card" style="margin-top:10px">
      <div class="k">${r.symbol} — شرط‌ها</div>
      <table><thead><tr><th>شرط</th><th>وزن</th><th>وضعیت</th><th>جزئیات</th></tr></thead>
      <tbody>${(r.checks || []).map(c => `<tr>
        <td>${c.fa}</td><td class="num">${c.weight}</td>
        <td class="${c.ok ? "pos" : "neg"}">${c.ok ? "پاس" : "نه"}</td>
        <td class="mut" style="font-size:11px">${c.detail}</td></tr>`).join("")}</tbody></table>
      </div>`;
  });
}
async function loadWatch() {
  try {
    WATCH = await api("/api/watch");
  } catch (e) {
    WATCH = {rows: [], n: 0};
  }
  renderWatch();
}
$("#wSearch").oninput = renderWatch;
$("#wState").onchange = renderWatch;
$("#wSort").onchange = renderWatch;
$("#wOnlyNear").onchange = renderWatch;
$("#wReload").onclick = loadWatch;

/* ── خروج زودهنگام ─────────────────────────────────────────────────── */
let EXITS = {trades: [], overall: {}};
function renderExit() {
  const q = ($("#eSearch").value || "").trim().toUpperCase();
  const cat = $("#eCat").value;
  const sort = $("#eSort").value;
  let rows = (EXITS.trades || []).filter(t => {
    if (q && !(`${t.symbol} ${t.rule}`.toUpperCase().includes(q))) return false;
    if (cat && t.category !== cat) return false;
    return true;
  });
  if (sort === "r") rows.sort((a, b) => (a.r || 0) - (b.r || 0));
  else if (sort === "ts") rows.sort((a, b) => (a.ts || 0) - (b.ts || 0));
  else rows.sort((a, b) => (b.give_back_r || 0) - (a.give_back_r || 0));
  const o = EXITS.overall || {};
  $("#exitCards").innerHTML = cards([
    ["معامله", EXITS.n || 0, ""],
    ["expectancy", R(o.expectancy_r) + "R", (o.expectancy_r || 0) >= 0 ? "pos" : "neg"],
    ["میانهٔ MFE", R(o.median_mfe_r) + "R", ""],
    ["سودِ ریخته", (EXITS.leak_total_r || 0).toFixed(2) + "R", (EXITS.leak_total_r || 0) > 0 ? "neg" : "pos"],
  ]);
  if (!rows.length) {
    $("#exitTable").innerHTML = `<div class="mut" style="padding:10px">معامله‌ای نیست.
      اول <code>bash run-auto.sh --live</code> را چند بار بزن.</div>`;
    return;
  }
  $("#exitTable").innerHTML = table(
    ["نماد", "R", "MFE(R)", "سود ریخته", "قاعده", "دسته", "کندل"],
    rows.map(t => [t.symbol, R(t.r), R(t.mfe_r),
      (t.give_back_r === null || t.give_back_r === undefined) ? "—" : t.give_back_r.toFixed(2),
      t.rule, t.category, t.bars ?? "—"]));
}
async function loadExit() {
  try { EXITS = await api("/api/exit"); } catch (e) { EXITS = {trades: [], overall: {}}; }
  renderExit();
}
$("#eSearch").oninput = renderExit;
$("#eCat").onchange = renderExit;
$("#eSort").onchange = renderExit;
$("#eReload").onclick = loadExit;

/* ── زنده ──────────────────────────────────────────────────────────── */
async function loadLive() {
  const o = await api("/api/overview");
  const st = o.state || {}, rep = o.report || {};
  const eq = Number(st.equity || 0), peak = Number(st.peak_equity || eq);
  const dd = peak ? (eq - peak) / peak * 100 : 0;
  $("#meta").innerHTML = `الگوریتم <b>${esc(o.variant)}</b> · ${esc(o.tf)} · داده
    <span class="pill">${esc(o.data_fp||"—")}</span> · ${o.symbols_cached.length} نماد کش‌شده ·
    ${o.runs} آزمایش ثبت‌شده · ${esc(o.now)}`;
  if (o.demo) {
    $("#demo").style.display = "block";
    $("#demo").textContent = "⚠️ حالت نمایشی: کندل‌ها مصنوعی‌اند (نه بازار واقعی). فقط برای دیدن ساختار داشبورد.";
  }
  $("#liveCards").innerHTML = cards([
    ["سرمایهٔ مجازی", "$" + num(eq), ""],
    ["اوج", "$" + num(peak), ""],
    ["افت از اوج", num(dd,2) + "%", dd < -1 ? "neg" : ""],
    ["سیگنال", rep.opens ?? 0, ""],
    ["بسته‌شده", rep.closes ?? 0, ""],
    ["باز", rep.open_now ?? 0, ""],
  ]);
  let h = "";
  const algo = rep.by_algorithm || {};
  const algoRows = Object.entries(algo).map(([k,d]) => [
    `<code>${esc(k)}</code>`, d.signals, d.closed,
    d.win_rate === null ? "—" : num(d.win_rate*100,1)+"%",
    `<span class="${sgn(d.expectancy_r)}">${R(d.expectancy_r)}</span>`,
    `<span class="${sgn(d.pnl)}">${num(d.pnl)}$</span>`,
    Object.entries(d.patterns||{}).map(([p,n])=>`${esc(p)}×${n}`).join(", ") || "—"
  ]);
  h += `<h3>کدام الگوریتم، چند سیگنال</h3>` + table(["الگوریتم","سیگنال","بسته","نرخ برد","انتظار (R)","سود","الگو"], algoRows);

  const ruleRows = Object.entries(rep.by_rule||{}).map(([k,e]) => [
    `<code>${esc(k)}</code><div class="mut">${esc(e.fa||"")}</div>`, e.count,
    num((e.share||0)*100,0)+"%",
    e.is_risk_control ? `<span class="tag risk">✅ ضدضرر</span>` : `<span class="tag">—</span>`,
    `<span class="${sgn(e.pnl)}">${num(e.pnl)}$</span>`
  ]);
  h += `<h3>کدام قاعده بست — و آیا برای کم‌کردن ضرر بود</h3>` + table(["قاعده","تعداد","سهم","ضدضرر؟","سود"], ruleRows);

  const open = rep.open_positions || [];
  if (open.length) {
    h += `<h3>سیگنال‌های باز</h3>` + table(["نماد","جهت","ورود","استاپ","از","الگو","الگوریتم"],
      open.map(p => [esc(p.symbol), esc(p.side), esc(p.entry), esc(p.stop),
        esc(new Date(p.open_ts).toISOString().slice(0,16).replace("T"," ")),
        esc(p.mode), `<code>${esc(p.algorithm)}</code>`]));
  }
  const recent = rep.recent || [];
  if (recent.length) {
    h += `<h3>آخرین سیگنال‌های بسته‌شده</h3>` + table(["سیگنال","نماد","ورود","خروج","R","سود","بست با"],
      recent.slice(0,12).map(r => {
        const id = String(r.signal_id||"").replace(":closed","").split(":").slice(-1)[0];
        return [`<code>${esc(r.algorithm)}:${esc(id)}</code>`, esc(r.symbol), esc(r.entry), esc(r.exit),
          `<span class="${sgn(r.r_multiple)}">${R(r.r_multiple)}</span>`,
          `<span class="${sgn(r.pnl)}">${num(r.pnl)}$</span>`,
          `<code>${esc(r.rule)}</code> ${r.is_risk_control?'<span class="tag risk">✅</span>':''}`];
      }));
  }
  const vet = Object.entries(rep.vetoes||{}).filter(([k,v]) => v > 0);
  if (vet.length) {
    h += `<h3>سیگنال‌هایی که رد شدند</h3>` + table(["دلیل","تعداد"],
      vet.sort((a,b)=>b[1]-a[1]).map(([k,v]) => [`<code>${esc(k)}</code> — ${esc((o.veto_labels||{})[k]||"")}`, v]));
  }
  if (!Object.keys(algo).length) {
    h += `<div class="note">هنوز هیچ سیگنالی ثبت نشده. دکمهٔ «قدم بعدی» را بزن (یا در
      Termux: <code>bash run-auto.sh --live</code>).</div>`;
  }
  $("#liveBody").innerHTML = h;
}

$("#refreshBtn").onclick = () => loadLive().then(loadSignals);
$("#stepBtn").onclick = async () => {
  $("#stepBtn").disabled = true; $("#stepMsg").style.display = "inline";
  $("#stepMsg").textContent = "در حال گرفتن کندل تازه و اجرای موتور";
  try {
    const r = await api("/api/step", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    $("#stepMsg").textContent = r.ok ? "انجام شد — گزارش تازه شد" : ("نشد: " + (r.note||"خطا"));
    await loadLive(); await loadSignals();
  } catch (e) { $("#stepMsg").textContent = "خطا: " + e.message; }
  $("#stepBtn").disabled = false;
  setTimeout(()=>{ $("#stepMsg").style.display="none"; }, 6000);
};

/* ── سیگنال‌ها ─────────────────────────────────────────────────────── */
let SIGS = [];
function fillSelect(sel, values) {
  const cur = sel.value;
  sel.innerHTML = `<option value="">همه</option>` + values.map(v=>`<option>${esc(v)}</option>`).join("");
  sel.value = cur;
}
let FACETS = null;
let VALID = null;
async function loadValidation() {
  try { VALID = await api("/api/validation"); } catch (e) { VALID = null; }
  if (!VALID) { $("#sigValid").innerHTML = ""; return; }
  const ok = VALID.complete;
  $("#sigValid").innerHTML = `<div class="k">وضعیت اعتبارسنجی</div>
    <div style="margin-top:6px">
      <span class="${ok ? "pos" : "neg"}">${esc(VALID.status)}</span>
      · ${VALID.n} معاملهٔ بسته‌شده (آستانه ${VALID.min_n})
      · expectancy کل: <b class="${sgn(VALID.expectancy_r)}">${R(VALID.expectancy_r)}</b>
      · بیرون‌نمونه (۳۰٪ آخر): <b class="${sgn(VALID.oos_expectancy_r)}">${R(VALID.oos_expectancy_r)}</b>
      <span class="mut">(n=${VALID.oos_n})</span>
    </div>
    <div class="mut" style="margin-top:4px;font-size:11px">${esc(VALID.note)} ${esc(VALID.manual_note || "")}</div>`;
}
async function loadSignals() {
  if (!FACETS) {                       // فهرست کامل یک‌بار؛ وگرنه با فیلتر، گزینه‌ها کم می‌شوند
    const all = await api("/api/signals?limit=2000");
    FACETS = {syms: [...new Set(all.map(s=>s.symbol))].sort(),
              rules: [...new Set(all.map(s=>s.rule).filter(Boolean))].sort()};
    fillSelect($("#fSym"), FACETS.syms); fillSelect($("#fRule"), FACETS.rules);
  }
  const q = new URLSearchParams({symbol:$("#fSym").value, rule:$("#fRule").value,
    status:$("#fStatus").value, only_risk:$("#fRisk").checked ? "1" : ""});
  SIGS = await api("/api/signals?" + q.toString());
  const tv = t => t ? new Date(t).toISOString().slice(5,16).replace("T"," ") : "—";
  const rows = SIGS.map((s,i) => {
    const o = s.open_candle || {}, x = s.exit_candle || {};
    const votes = (s.votes || []);
    return [`<code>${esc(String(s.id).split(":").slice(1).join(":"))}</code>`,
      `<b>${esc(s.symbol)}</b>`,
      esc(tv(s.ts)) + `<div class="mut" style="font-size:10px">O ${num(o.open)} H ${num(o.high)} L ${num(o.low)} C ${num(o.close)}</div>`,
      esc(s.mode) + (votes.length > 1 ? ` <span class="tag risk" title="${esc(votes.join(", "))}">هم‌گرا ${votes.length}</span>` : ""),
      num(s.entry), num(s.stop), num(s.take),
      (s.fees_total == null ? "—" : num(s.fees_total) + "$"),
      `<span class="${sgn(s.r)}">${R(s.r)}</span>`,
      `<span class="${sgn(s.pnl)}">${num(s.pnl)}$</span>`,
      esc(s.status==="open"?"باز":"بسته") + (s.origin === "manual" ? ' <span class="tag risk">دستی</span>' : ""),
      s.rule ? `<code>${esc(s.rule)}</code>` : "—",
      s.status === "closed" ? (esc(tv(s.exit_ts)) + `<div class="mut" style="font-size:10px">O ${num(x.open)} H ${num(x.high)} L ${num(x.low)} C ${num(x.close)}</div>`) : "—"];
  });
  $("#sigTable").innerHTML = `<div class="mut" style="margin:8px 0">${SIGS.length} سیگنال ·
      «حد ضرر/حد سود» لحظهٔ ورود است · کندل‌ها با O/H/L/C نمایش داده می‌شوند</div>` +
    table(["شناسه","نماد","کندل ورود","الگو","ورود","حد ضرر","حد سود","کارمزد","R","سود","وضعیت","بست با","کندل خروج"], rows);
  [...$("#sigTable").querySelectorAll("tbody tr")].forEach((tr,i) => {
    tr.style.cursor = "pointer";
    tr.onclick = () => showSignal(SIGS[i]);
  });
  $("#sigDetail").innerHTML = "";
}
function _indTable(obj) {
  const ent = Object.entries(obj || {});
  if (!ent.length) return `<div class="mut">ثبت نشده</div>`;
  return `<table><tbody>${ent.map(([k,v]) =>
    `<tr><td class="mut">${esc(k)}</td><td class="num">${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("")}</tbody></table>`;
}
function _candleBox(c, title) {
  if (!c) return `<div class="card"><div class="k">${title}</div><div class="mut">ثبت نشده</div></div>`;
  return `<div class="card"><div class="k">${title}</div>
    <div style="font-size:12px;line-height:1.9">
      <div>زمان کندل: <code>${esc(new Date(c.ts).toISOString().replace("T"," ").slice(0,16))}</code></div>
      <div>O <b>${num(c.open)}</b> · H <b>${num(c.high)}</b> · L <b>${num(c.low)}</b> · C <b>${num(c.close)}</b></div>
      <div>حجم: ${num(c.volume)}</div>
    </div></div>`;
}
function showSignal(s) {
  const votes = s.votes || [];
  const fees = (s.fee_open != null || s.fee_close != null)
    ? `ورود ${num(s.fee_open)}$ + خروج ${num(s.fee_close)}$ = <b>${num(s.fees_total)}$</b>` : "—";
  $("#sigDetail").innerHTML = `<h3>پروندهٔ سیگنال <code>${esc(s.id)}</code></h3>
    <div class="note">الگوریتم <b>${esc(s.algorithm)}</b> · الگو <b>${esc(s.mode)}</b> ·
      رژیم <b>${esc(s.regime)}</b> · منبع: <b>${s.origin === "manual" ? "دستی" : "خودکار"}</b> ·
      ${s.rule ? `بست با <b>${esc(s.rule)}</b> ${s.is_risk_control?'<span class="tag risk">قاعدهٔ ضدضرر</span>':''}` : '<b>هنوز باز</b>'}
      ${votes.length ? `<br>الگوهای تأییدکننده: ${votes.map(v=>`<code>${esc(v)}</code>`).join("، ")}` : ""}</div>
    <div class="grid2">
      ${_candleBox(s.open_candle, "لحظهٔ ورود (کندل بستهٔ سیگنال)")}
      ${_candleBox(s.exit_candle, "لحظهٔ خروج")}
    </div>
    <div class="grid2">
      <div class="card"><div class="k">سفارش و ریسک</div>
        <table><tbody>
          <tr><td class="mut">جهت</td><td class="num">${esc((s.raw_open||{}).order ? s.raw_open.order.side : "—")}</td></tr>
          <tr><td class="mut">ورود</td><td class="num">${num(s.entry)}</td></tr>
          <tr><td class="mut">حد ضرر</td><td class="num">${num(s.stop)}</td></tr>
          <tr><td class="mut">حد سود</td><td class="num">${num(s.take)}</td></tr>
          <tr><td class="mut">حجم</td><td class="num">${num(s.qty)}</td></tr>
          <tr><td class="mut">ارزش</td><td class="num">${num(s.notional)}$</td></tr>
          <tr><td class="mut">ریسک</td><td class="num">${num(s.risk_amount)}$</td></tr>
          <tr><td class="mut">کارمزد</td><td class="num">${fees}</td></tr>
          <tr><td class="mut">نتیجه</td><td class="num ${sgn(s.r)}">${R(s.r)} · ${num(s.pnl)}$</td></tr>
        </tbody></table></div>
      <div class="card"><div class="k">اندیکاتورهای لحظهٔ ورود</div>${_indTable(s.open_indicators)}</div>
    </div>
    <div class="card"><div class="k">اندیکاتورهای لحظهٔ خروج</div>
      ${s.status === "closed" ? (s.has_close_snapshot ? _indTable(s.exit_indicators)
        : `<div class="mut">برای این سیگنال قدیمی ثبت نشده — از این نسخه به بعد ثبت می‌شود.</div>`)
        : `<div class="mut">هنوز باز است</div>`}</div>
    <details style="margin-top:10px"><summary class="mut">دادهٔ خام (JSON)</summary>
      <pre>${esc(JSON.stringify({open:s.raw_open, close:s.raw_close}, null, 1))}</pre></details>`;
  $("#sigDetail").scrollIntoView({behavior:"smooth", block:"start"});
}
async function manualSignal() {
  const btn = $("#manualBtn"), msg = $("#manualMsg");
  if (!confirm("یک قدم روی دادهٔ واقعی اجرا شود؟ اگر شرط ورود برقرار باشد، یک سیگنال «مجازی» مثل همیشه ثبت می‌شود.")) return;
  btn.disabled = true; msg.style.display = "inline"; msg.textContent = "در حال اجرا…";
  let r = null;
  try { r = await api("/api/manual_signal"); } catch (e) { r = {ok:false, note:"خطای شبکه"}; }
  btn.disabled = false; msg.style.display = "none";
  const rows = (r.signals || []).map(x => `<tr>
    <td><b>${esc(x.symbol)}</b></td><td>${esc(x.side)}</td><td class="num">${num(x.entry)}</td>
    <td class="num">${num(x.stop)}</td><td class="num">${num(x.take)}</td>
    <td>${esc(x.mode || "—")}</td>
    <td>${(x.votes || []).map(v=>`<code>${esc(v)}</code>`).join("، ") || "—"}</td></tr>`).join("");
  $("#manualResult").innerHTML = `<div class="card" style="margin:10px 0">
    <div class="k">${r.ok ? "✅ قدم اجرا شد" : "⚠️ اجرا نشد"}</div>
    <div class="mut" style="margin-top:4px">${esc(r.note || "")}</div>
    ${rows ? `<table style="margin-top:8px"><thead><tr><th>نماد</th><th>جهت</th><th>ورود</th>
      <th>حد ضرر</th><th>حد سود</th><th>الگو</th><th>رأی الگوها</th></tr></thead>
      <tbody>${rows}</tbody></table>` : ""}
    ${(r.signals || []).length ? `<div class="mut" style="margin-top:6px">سیگنال‌های دستی با برچسب «manual» در ژورنال ذخیره شدند.</div>` : ""}
  </div>`;
  FACETS = null;
  await loadSignals(); await loadValidation();
}
$("#manualBtn").onclick = manualSignal;
$("#sigReload").onclick = () => { FACETS = null; loadValidation(); loadSignals(); };
$("#fSym").onchange = loadSignals; $("#fRule").onchange = loadSignals;
$("#fStatus").onchange = loadSignals; $("#fRisk").onchange = loadSignals;

/* ── آزمایشگاه ─────────────────────────────────────────────────────── */
let SCHEMA = null, BASE = {}, CURV = "", TEAM_OV = {};
function valuesFor(vid, extra) {
  const v = (SCHEMA.variants || []).find(x => x.id === vid);
  const base = Object.assign({}, (v && v.values) || SCHEMA.baseline_values || {});
  return Object.assign(base, extra || {});
}
async function loadSchema() {
  SCHEMA = await api("/api/schema");
  $("#teamSel").innerHTML = (SCHEMA.variants || []).map(v =>
    `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join("");
  $("#syms").innerHTML = SCHEMA.symbols.map(s =>
    `<label><input type="checkbox" class="sym" value="${esc(s)}" checked>${esc(s)}</label>`).join("")
    || `<span class="mut">هیچ داده‌ای در کش نیست</span>`;
  await loadTeams();
  const bs = SCHEMA.brain_settings || {};
  if ($("#bLong")) $("#bLong").value = bs.long_th ?? 0.55;
  if ($("#bShort")) $("#bShort").value = bs.short_th ?? 0.45;
  setVariant((SCHEMA.variant && SCHEMA.variant.id) || "trend", {});
}
function setVariant(vid, extra) {
  CURV = vid || (SCHEMA.variant && SCHEMA.variant.id) || "";
  TEAM_OV = Object.assign({}, extra || {});
  BASE = valuesFor(CURV, TEAM_OV);
  if ($("#teamSel")) $("#teamSel").value = CURV;
  renderKnobs();
}
function renderKnobs() {
  const groups = {};
  SCHEMA.knobs.forEach(k => (groups[k.g] = groups[k.g] || []).push(k));
  let h = "";
  for (const [g, knobs] of Object.entries(groups)) {
    h += `<h3>${esc(g)}</h3><div class="grid2">`;
    for (const k of knobs) {
      const v = BASE[k.k];
      h += `<div class="knob" id="knob-${k.k}"><div class="t">${esc(k.fa)} <span class="mut">(${esc(k.k)})</span></div>`;
      if (k.t === "bool") {
        h += `<label style="color:var(--fg)"><input type="checkbox" data-k="${k.k}" ${v?"checked":""}> روشن</label>`;
      } else if (k.t === "choice") {
        h += `<select data-k="${k.k}">${k.choices.map(c=>`<option ${c===v?"selected":""}>${c}</option>`).join("")}</select>`;
      } else if (k.t === "modes") {
        const cur = Array.isArray(v) ? v : [];
        h += `<div class="row" style="margin:0">${["breakout","pullback"].map(m=>
          `<label style="color:var(--fg)"><input type="checkbox" data-m="${k.k}" value="${m}" ${cur.includes(m)?"checked":""}> ${m}</label>`).join("")}</div>`;
      } else {
        h += `<input type="number" data-k="${k.k}" value="${v}" min="${k.lo}" max="${k.hi}" step="${k.st}">`;
      }
      if (k.note) h += `<div class="h">${esc(k.note)}</div>`;
      h += `</div>`;
    }
    h += `</div>`;
  }
  $("#knobs").innerHTML = h;
  document.querySelectorAll("[data-k],[data-m]").forEach(el =>
    el.addEventListener("input", () => { markChanged(); }));
  markChanged();
}
async function loadTeams() {
  const r = await api("/api/teams");
  SCHEMA.teams = r.teams || [];
  $("#savedSel").innerHTML = `<option value="">— هیچ —</option>` +
    SCHEMA.teams.map(t => `<option value="${esc(t.id)}">${esc(t.name)} · ${esc(t.variant_label || t.variant)}</option>`).join("");
}
function currentOverrides() {
  const out = {};
  document.querySelectorAll("[data-k]").forEach(el => {
    const k = el.dataset.k, kn = SCHEMA.knobs.find(x=>x.k===k);
    let v;
    if (kn.t === "bool") v = el.checked;
    else if (kn.t === "choice") v = el.value;
    else v = el.value === "" ? BASE[k] : Number(el.value);
    if (JSON.stringify(v) !== JSON.stringify(BASE[k])) out[k] = v;
  });
  const modes = {};
  document.querySelectorAll("[data-m]").forEach(el => {
    const k = el.dataset.m;
    modes[k] = modes[k] || [];
    if (el.checked) modes[k].push(el.value);
  });
  for (const [k, v] of Object.entries(modes)) {
    if (JSON.stringify(v.sort()) !== JSON.stringify((BASE[k]||[]).slice().sort())) out[k] = v;
  }
  return out;
}
function markChanged() {
  const o = currentOverrides();
  document.querySelectorAll(".knob").forEach(el => el.classList.remove("changed"));
  for (const k of Object.keys(o)) { const el = $("#knob-"+k); if (el) el.classList.add("changed"); }
  $("#changedCount").textContent = Object.keys(o).length
    ? `— ${Object.keys(o).length} تغییر نسبت به خط پایه` : "— بدون تغییر (همان الگوریتم فعلی)";
}
$("#resetBtn").onclick = () => setVariant(CURV, TEAM_OV);
/* ── تیم‌ها ─────────────────────────────────────────────────────────── */
$("#teamSel").onchange = () => setVariant($("#teamSel").value, {});
$("#savedSel").onchange = () => {
  const id = $("#savedSel").value;
  if (!id) return;
  const t = (SCHEMA.teams || []).find(x => x.id === id);
  if (!t) return;
  setVariant(t.variant, t.overrides || {});
  if (!$("#runLabel").value.trim()) $("#runLabel").value = t.name;
  $("#teamMsg").textContent = `تیم «${t.name}» بارگذاری شد — ${Object.keys(t.overrides||{}).length} تنظیم.`;
};
$("#teamSave").onclick = async () => {
  const name = $("#teamName").value.trim();
  if (!name) { $("#teamMsg").textContent = "اول اسم تیم را بنویس."; return; }
  const overrides = Object.assign({}, TEAM_OV, currentOverrides());
  try {
    const t = await api("/api/teams", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({name, variant: CURV, overrides, note: $("#runLabel").value})});
    $("#teamMsg").textContent = `✅ تیم «${t.name}» ذخیره شد (${Object.keys(t.overrides||{}).length} تنظیم).`;
    await loadTeams();
    $("#savedSel").value = t.id;
  } catch (e) { $("#teamMsg").textContent = "خطا: " + e.message; }
};
$("#teamDel").onclick = async () => {
  const id = $("#savedSel").value;
  if (!id) { $("#teamMsg").textContent = "اول یک تیم ذخیره‌شده را انتخاب کن."; return; }
  try {
    await api("/api/teams", {method:"DELETE", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({id})});
    $("#teamMsg").textContent = "🗑 تیم حذف شد.";
    $("#savedSel").value = "";
    await loadTeams();
  } catch (e) { $("#teamMsg").textContent = "خطا: " + e.message; }
};
$("#bSave").onclick = async () => {
  $("#bMsg").style.display = "inline"; $("#bMsg").textContent = "ذخیره";
  try {
    await api("/api/brain/settings", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({long_th: Number($("#bLong").value), short_th: Number($("#bShort").value)})});
    $("#bMsg").textContent = "✅ ذخیره شد — فقط برچسب عوض می‌شود";
    loadBrainViews();
  } catch (e) { $("#bMsg").textContent = "خطا: " + e.message; }
  setTimeout(() => { $("#bMsg").style.display = "none"; }, 2500);
};
$("#runBtn").onclick = async () => {
  const overrides = Object.assign({}, TEAM_OV, currentOverrides());
  const symbols = [...document.querySelectorAll(".sym:checked")].map(x=>x.value);
  const gate = {min_expectancy_r: Number($("#gExp").value),
                min_trades: Number($("#gN").value),
                require_oos_positive: $("#gOos").checked,
                require_ci_excludes_zero: $("#gCi").checked};
  $("#runBtn").disabled = true; $("#runMsg").style.display = "inline";
  $("#runMsg").textContent = "در حال اجرا روی داده (بدون شبکه)";
  try {
    const rec = await api("/api/run", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({overrides, gate, label:$("#runLabel").value, symbols,
                            variant: CURV})});
    showRun(rec, "#runResult");
    loadRuns(true);
  } catch (e) {
    $("#runResult").innerHTML = `<div class="note bad">خطا: ${esc(e.message)}</div>`;
  }
  $("#runBtn").disabled = false; $("#runMsg").style.display = "none";
};
function showRun(rec, target) {
  const m = rec.metrics || {}, oos = rec.out_of_sample || {}, ins = rec.in_sample || {};
  const v = rec.verdict || {checks:[]};
  const d = rec.delta_vs_baseline;
  let h = `<h3>نتیجهٔ آزمایش</h3>`;
  h += `<div class="note ${v.passed ? "good" : "bad"}">${v.passed ? "✅" : "❌"} ${esc(v.note)}
    ${v.checks.length ? " — " + v.checks.map(c =>
      `${esc(c.fa)}: <b>${c.got===null||c.got===undefined?"—":esc(Array.isArray(c.got)?("["+c.got.join(", ")+"]"):(typeof c.got==="number"?num(c.got,3):c.got))}</b> ${c.ok?"✅":"❌"}`).join(" · ") : ""}
    </div>`;
  if (rec.trial_warning) h += `<div class="note warn">🎲 ${esc(rec.trial_warning)}</div>`;
  h += `<div class="cards">${cards([
    ["معامله", m.n ?? 0], ["انتظار (R)", `<span class="${sgn(m.expectancy_r)}">${R(m.expectancy_r)}</span>`],
    ["نرخ برد", m.win_rate===null||m.win_rate===undefined?"—":num(m.win_rate*100,1)+"%"],
    ["سود/زیان", `<span class="${sgn(m.pnl)}">${num(m.pnl)}$</span>`],
    ["PF", m.profit_factor===null||m.profit_factor===undefined?"—":num(m.profit_factor,2)],
    ["حداکثر افت", m.max_dd_pct===null?"—":num(m.max_dd_pct,1)+"%"],
  ])}</div>`;
  h += `<div class="cards">${cards([
    ["بیرون‌نمونه (۳۰٪ آخر): R", `<span class="${sgn(oos.expectancy_r)}">${R(oos.expectancy_r)}</span>`],
    ["بیرون‌نمونه: تعداد", oos.n ?? 0],
    ["درون‌نمونه: R", `<span class="${sgn(ins.expectancy_r)}">${R(ins.expectancy_r)}</span>`],
    ["Δ نسبت به خط پایه", d ? `<span class="${sgn(d.observed)}">${R(d.observed)}</span>` : "—"],
    ["بازهٔ ۹۰٪ Δ", d ? `[${num(d.ci[0])} , ${num(d.ci[1])}]` : "—"],
    ["معنادار؟", d ? (d.significant ? "✅ بله" : "❌ نه") : "—"],
  ])}</div>`;
  h += `<div class="note">تیم <b>${esc(rec.variant_label || rec.variant || "—")}</b> · شناسهٔ اجرا <code>${esc(rec.run_id)}</code> · هش تنظیمات
    <code>${esc(rec.digest)}</code> · آزمایش شمارهٔ <b>${rec.trial_index}</b> روی این داده ·
    ${rec.symbols.length} نماد · ${rec.n_bars} کندل</div>`;
  const ov = Object.entries(rec.overrides||{});
  h += `<div class="note">تغییرات نسبت به خط پایه: ` +
    (ov.length ? ov.map(([k,x])=>`<code>${esc(k)}=${esc(JSON.stringify(x))}</code>`).join(" · ") : "هیچ (خودِ الگوریتم فعلی)") + `</div>`;
  h += `<h3>کدام قاعده بست</h3>` + table(["قاعده","تعداد","انتظار (R)","سود","ضدضرر؟"],
    Object.entries(rec.by_rule||{}).sort((a,b)=>b[1].n-a[1].n).map(([k,e]) =>
      [`<code>${esc(k)}</code>`, e.n, `<span class="${sgn(e.expectancy_r)}">${R(e.expectancy_r)}</span>`,
       `<span class="${sgn(e.pnl)}">${num(e.pnl)}$</span>`,
       e.is_risk_control?`<span class="tag risk">✅</span>`:"—"]));
  h += `<h3>الگوی ورود</h3>` + table(["الگو","تعداد","انتظار (R)","نرخ برد"],
    Object.entries(rec.by_pattern||{}).map(([k,e]) =>
      [`<code>${esc(k)}</code>`, e.n, `<span class="${sgn(e.expectancy_r)}">${R(e.expectancy_r)}</span>`,
       e.win_rate===null?"—":num(e.win_rate*100,1)+"%"]));
  h += `<h3>به تفکیک نماد</h3>` + table(["نماد","تعداد","انتظار (R)","سود"],
    Object.entries(rec.by_symbol||{}).sort((a,b)=>b[1].n-a[1].n).map(([k,e]) =>
      [esc(k), e.n, `<span class="${sgn(e.expectancy_r)}">${R(e.expectancy_r)}</span>`,
       `<span class="${sgn(e.pnl)}">${num(e.pnl)}$</span>`]));
  h += `<div class="row"><a class="ghost" style="text-decoration:none" href="/api/runs/${encodeURIComponent(rec.run_id)}" target="_blank">JSON کامل این آزمایش</a></div>`;
  document.querySelector(target).innerHTML = h;
}

/* ── مغز دوم ───────────────────────────────────────────────────────── */
async function loadBrainViews() {
  const v = await api("/api/brain/views");
  if (!v.available) {
    $("#brainViews").innerHTML = `<div class="note">مدل مغز ساخته نشده. در Termux:
      <code>bash run-auto.sh --brain-view --train</code></div>`;
    return;
  }
  const rows = Object.entries(v.views || {}).map(([sym, x]) => {
    if (!x.available) return [esc(sym), "—", "—", "—", esc(x.reason || "")];
    const lean = x.lean === "long" ? "🟢 صعودی" : (x.lean === "short" ? "🔴 نزولی" : "⚪ بی‌طرف");
    const drv = (x.drivers || []).map(d => `${esc(d.fa)} ${d.contrib > 0 ? "+" : ""}${num(d.contrib, 2)}`).join(" · ");
    return [esc(sym), lean, num(x.p_up * 100, 1) + "%", num(x.confidence * 100, 1) + "%", drv];
  });
  const m = v.model || {};
  $("#brainViews").innerHTML =
    `<div class="note">مدل <code>${esc(m.version)}</code> · هش <code>${esc(m.digest)}</code> ·
      AUC بیرون‌نمونه ${m.oof && m.oof.auc !== undefined ? esc(m.oof.auc) : "—"} ·
      آموزش تا ${esc(new Date(m.trained_through_ts || 0).toISOString().slice(0,10))} ·
      <b>فقط مشاهده</b></div>` +
    table(["نماد","دیدگاه","احتمال صعود","اطمینان","محرک‌ها"], rows);
}
async function loadBrain() {
  loadBrainViews();
  const b = await api("/api/brain");
  if (!b.available) {
    $("#brainBody").innerHTML = `<div class="note">هنوز گزارشی ساخته نشده. در Termux بزن:
      <code>bash run-auto.sh --brain</code></div>`;
    return;
  }
  const j = b.judge || {checks:[]};
  let h = `<div class="note ${j.passed ? "good" : "bad"}">${esc(j.verdict || "")}</div>`;
  h += `<div class="cards">${cards([
    ["معامله", b.n_trades ?? "—"], ["پیش‌بینی بیرون‌نمونه", b.n_oof ?? "—"],
    ["AUC", b.auc ?? "—"], ["نرخ برد پایه", num((b.base_win_rate||0)*100,1)+"%"],
    ["expectancy پایه", R(b.base_expectancy_r)],
    ["بلوک‌های زمانی", b.folds ?? "—"],
  ])}</div>`;
  h += `<h3>دروازهٔ ازپیش‌نوشته</h3>` + table(["شرط","نتیجه","وضعیت"],
    (j.checks||[]).map(c => [esc(c.fa),
      esc(Array.isArray(c.got) ? "["+c.got.map(g=>g===null?"—":Number(g).toFixed?Number(g).toFixed(2):g).join(", ")+"]" : (c.got===null||c.got===undefined?"—":c.got)),
      c.ok ? "✅" : "❌"]));
  h += `<h3>پیش‌بینی بیرون‌نمونه به تفکیک چهارک</h3>` + table(
    ["چهارک","تعداد","بازهٔ احتمال","expectancy (R)","نرخ برد","سود"],
    (b.buckets||[]).map(x => [x.part, x.n, `${num(x.p_lo,2)}–${num(x.p_hi,2)}`,
      `<span class="${sgn(x.expectancy_r)}">${R(x.expectancy_r)}</span>`,
      num(x.win_rate*100,1)+"%", `<span class="${sgn(x.pnl)}">${num(x.pnl)}$</span>`]));
  const ft = b.filter || {};
  if (ft.ok) {
    h += `<div class="note">فیلتر (رد ${Math.round((ft.skip_frac||0)*100)}٪ کم‌اعتماد):
      نگه‌داشته <b>${ft.n_kept}</b> با expectancy <b>${R(ft.expectancy_kept)}</b> ·
      ردشده <b>${ft.n_dropped}</b> با <b>${R(ft.expectancy_dropped)}</b> ·
      Δ نسبت به همه <b>${R(ft.delta_kept_vs_all)}</b> ·
      بازهٔ ۹۰٪: ${esc(JSON.stringify((ft.ci||{}).ci))} — ${esc((ft.ci||{}).note||"")}</div>`;
  }
  h += `<h3>ضرایب مدل</h3>` + table(["ویژگی","توضیح","علامت","پایداری","ضریب میانگین"],
    (b.coefficients||[]).map(c => [`<code>${esc(c.name)}</code>`, esc(c.fa),
      (c.sign>0?"＋":(c.sign<0?"－":"۰")),
      c.stability===null?"—":num(c.stability*100,0)+"%",
      c.mean_coef===null?"—":R(c.mean_coef)]));
  $("#brainBody").innerHTML = h;
}

/* ── آزمایش‌ها ─────────────────────────────────────────────────────── */
async function loadRuns(silent) {
  const runs = await api("/api/runs");
  runs.sort((a,b)=>b.trial_index-a.trial_index);
  if (!runs.length) { $("#runsTable").innerHTML = `<div class="note">هنوز آزمایشی ثبت نشده.</div>`; return; }
  const rows = runs.map(r => {
    const d = r.delta_vs_baseline;
    return [esc(r.created), `<b>#${r.trial_index}</b>`, esc(r.label||"—"),
      `<code>${esc(r.digest)}</code>`,
      r.metrics.n, `<span class="${sgn(r.metrics.expectancy_r)}">${R(r.metrics.expectancy_r)}</span>`,
      `<span class="${sgn((r.out_of_sample||{}).expectancy_r)}">${R((r.out_of_sample||{}).expectancy_r)}</span>`,
      d ? `[${num(d.ci[0])} , ${num(d.ci[1])}]` : "—",
      (r.verdict||{}).passed ? "✅" : "❌"];
  });
  $("#runsTable").innerHTML = table(["زمان","#","فرضیه","هش","n","R","R بیرون‌نمونه","بازهٔ Δ","دروازه"], rows);
  [...$("#runsTable").querySelectorAll("tbody tr")].forEach((tr,i) => {
    tr.style.cursor = "pointer";
    tr.onclick = async () => {
      const rec = await api("/api/runs/" + encodeURIComponent(runs[i].run_id));
      showRun(rec, "#runDetail");
      $("#runDetail").scrollIntoView({behavior:"smooth"});
    };
  });
  if (!silent) $("#runDetail").innerHTML = "";
}

/* ── شروع ──────────────────────────────────────────────────────────── */
loadLive(); loadSchema().then(loadSignals).catch(e => console.error(e));
setInterval(loadLive, 60000);
</script></body></html>
"""


def make_handler(lab):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MTFLabDesk/1.0"

        # -- helpers ---------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, obj, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")

        def _err(self, code: int, msg: str) -> None:
            self._json({"error": msg}, code)

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0:
                return {}
            raw = self.rfile.read(min(n, 2_000_000))
            try:
                return json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}

        def log_message(self, fmt, *args):        # لاگ کوتاه، بدون نویز
            if "/api/" in (args[0] if args else ""):
                return
            print(f"  · {self.address_string()} {fmt % args}")

        # -- routes ----------------------------------------------------
        def do_GET(self):
            u = urlsplit(self.path)
            path = unquote(u.path)
            q = dict(parse_qsl(u.query))
            try:
                if path in ("/", "/index.html"):
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/overview":
                    self._json(lab.overview())
                elif path == "/api/schema":
                    self._json(lab.schema())
                elif path == "/api/watch":
                    self._json(lab.watch_report())
                elif path == "/api/exit":
                    self._json(lab.exit_report())
                elif path == "/api/algorithms":
                    self._json(lab.algorithms())
                elif path == "/api/validation":
                    self._json(lab.validation_status())
                elif path == "/api/manual_signal":
                    # یک قدم واقعی؛ `?offline=1` فقط برای تست/دمو (بدون شبکه)
                    self._json(lab.manual_signal(offline=(q.get("offline") == "1")))
                elif path == "/api/system":
                    self._json(lab.system_health())
                elif path == "/api/control":
                    self._json(lab.control_report())
                elif path == "/api/control/file":
                    rep = lab.control_report()
                    fmt = "json" if q.get("fmt") == "json" else "md"
                    pth = ((rep.get("paths") or {}).get(fmt)
                           or (rep.get("paths") or {}).get("md") or "")
                    if not pth or not os.path.isfile(pth):
                        self._err(404, "گزارش ساخته نشد")
                    else:
                        with open(pth, "rb") as fh:
                            body = fh.read()
                        ctype = ("application/json; charset=utf-8" if fmt == "json"
                                 else "text/markdown; charset=utf-8")
                        name = os.path.basename(pth)
                        self.send_response(200)
                        self.send_header("Content-Type", ctype)
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Content-Disposition",
                                         'attachment; filename="' + name + '"')
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        try:
                            self.wfile.write(body)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                elif path == "/api/ops":
                    self._json(lab.ops_status())
                elif path == "/api/ops/start":
                    _syms = [x for x in (q.get("symbols", "") or "").split(",") if x.strip()]
                    _tfs = [x for x in (q.get("tfs", "") or "").split(",") if x.strip()]
                    self._json(lab.ops_start(
                        kind=q.get("kind", ""),
                        days=int(q.get("days", 365) or 365),
                        sync_days=int(q.get("sync_days", 30) or 30),
                        tf=q.get("tf", "auto") or "auto",
                        variant=q.get("variant", "base") or "base",
                        symbols=_syms or None, tfs=_tfs or None))
                elif path == "/api/ops/report":
                    self._json(lab.ops_report(q.get("id", "")))
                elif path == "/api/shadow":
                    self._json(lab.shadow_payload())
                elif path == "/api/shadow_open":
                    self._json(lab.shadow_take(
                        symbol=q.get("symbol", ""), side=q.get("side", ""),
                        note=q.get("note", ""),
                        offline=(q.get("offline") == "1")))
                elif path == "/api/shadow_close":
                    self._json(lab.shadow_close(q.get("id", "")))
                elif path == "/api/patterns":
                    self._json(lab.pattern_report())
                elif path == "/api/v10":
                    self._json(lab.v10_report())
                elif path == "/api/brain":
                    self._json(lab.brain_report())
                elif path == "/api/brain/views":
                    self._json(lab.brain_views())
                elif path == "/api/signals":
                    self._json(lab.signals(
                        symbol=q.get("symbol", ""), rule=q.get("rule", ""),
                        only_risk=q.get("only_risk") in ("1", "true", "on"),
                        status=q.get("status", ""),
                        limit=int(q.get("limit", 300) or 300)))
                elif path == "/api/teams":
                    self._json({"teams": lab.teams()})
                elif path == "/api/brain/settings":
                    self._json(lab.brain_settings())
                elif path == "/api/runs":
                    self._json(lab.runs())
                elif path.startswith("/api/runs/"):
                    rec = lab.run_detail(path[len("/api/runs/"):])
                    self._json(rec if rec else {"error": "not found"},
                               200 if rec else 404)
                elif path == "/api/health":
                    self._json({"ok": True, "version": "1.0",
                                "runs": len(lab.runs())})
                else:
                    self._err(404, "unknown path")
            except Exception as e:                                 # noqa: BLE001
                self._err(500, f"{type(e).__name__}: {e}")

        def do_DELETE(self):
            path = unquote(urlsplit(self.path).path)
            body = self._body()
            try:
                if path == "/api/teams":
                    ok = lab.delete_team(str(body.get("id") or ""))
                    self._json({"ok": ok, "teams": lab.teams()}, 200 if ok else 404)
                else:
                    self._err(404, "unknown path")
            except Exception as e:                                 # noqa: BLE001
                self._err(500, f"{type(e).__name__}: {e}")

        def do_POST(self):
            path = unquote(urlsplit(self.path).path)
            body = self._body()
            try:
                if path == "/api/run":
                    rec = lab.run_experiment(
                        overrides=body.get("overrides") or {},
                        label=body.get("label") or "",
                        gate=body.get("gate") or {},
                        symbols=body.get("symbols") or None,
                        variant=body.get("variant") or None)
                    self._json(rec)
                elif path == "/api/teams":
                    t = lab.save_team(name=body.get("name") or "",
                                      overrides=body.get("overrides") or {},
                                      variant=body.get("variant") or None,
                                      note=body.get("note") or "")
                    self._json(t)
                elif path == "/api/brain/settings":
                    self._json(lab.save_brain_settings(body.get("long_th"),
                                                       body.get("short_th")))
                elif path == "/api/step":
                    from .desk import run_step
                    self._json(run_step(lab))
                elif path == "/api/reload":
                    uni = lab.universe(reload=True)
                    lab._baselines.clear()
                    self._json({"ok": True, "symbols": sorted(uni),
                                "data_fp": lab.data_fp})
                else:
                    self._err(404, "unknown path")
            except Exception as e:                                 # noqa: BLE001
                self._err(500, f"{type(e).__name__}: {e}")

    return Handler


def serve(lab, host: str = "0.0.0.0", port: int = 8770) -> ThreadingHTTPServer:
    """سرور را روی همان پورت می‌سازد (بدون جایگزین)."""
    srv = ThreadingHTTPServer((host, port), make_handler(lab))
    return srv


def bind_server(lab, host: str = "0.0.0.0", port: int = 8770,
                tries: int = 10) -> ThreadingHTTPServer:
    """سرور را می‌سازد و اگر پورت اشغال بود، پورت بعدی را امتحان می‌کند.

    **چرا:** روی گوشی، یک `--dash` قدیمی که با `Ctrl+C` بسته نشده یا در تب
    دیگری از Termux زنده مانده، پورت ۸۷۷۰ را نگه می‌دارد. آن‌وقت اجرای تازه با
    `OSError: [Errno 98] Address already in use` می‌میرد و کاربر فقط یک
    traceback می‌بیند. حالا خودش پورت آزاد بعدی را برمی‌دارد و می‌گوید کدام.

    ترتیب: `port`, `port+1`, …، و در آخر پورت تصادفی سیستم (`0`) تا هرگز
    «بالا نیامدن» بی‌دلیل نداشته باشیم.
    """
    candidates = [port + i for i in range(max(1, int(tries)))] + [0]
    hosts = [host]
    if host not in ("127.0.0.1", "localhost"):
        hosts.append("127.0.0.1")          # اگر 0.0.0.0 بسته باشد، فقط محلی
    last: Optional[OSError] = None
    for h in hosts:
        for p in candidates:
            try:
                return ThreadingHTTPServer((h, p), make_handler(lab))
            except OSError as e:                                # noqa: PERF203
                if e.errno not in (errno.EADDRINUSE, errno.EACCES,
                                   errno.EADDRNOTAVAIL):
                    raise
                last = e
    raise last if last else OSError("no free port")
