"""بخش وب داشبورد کارگاه — HTML/JS و سرور (کتابخانهٔ استاندارد).

جدا شده از `desk.py` تا منطق آماری و لایهٔ نمایش قاطی نشوند و تست هر کدام
ساده بماند. هیچ فایل خارجی/CDN بارگذاری نمی‌شود: روی گوشیِ بی‌اینترنت هم کار
می‌کند.
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
  <button data-tab="lab">آزمایشگاه</button>
  <button data-tab="runs">آزمایش‌ها</button>
</nav>
<main>
  <section id="tab-live" class="on">
    <div class="cards" id="liveCards"></div>
    <div class="row"><button class="act" id="stepBtn">قدم بعدی (گرفتن کندل تازه)</button>
      <span class="spin" id="stepMsg" style="display:none"></span>
      <button class="ghost" id="refreshBtn">تازه‌سازی</button></div>
    <div id="liveBody"></div>
  </section>

  <section id="tab-signals">
    <div class="grid2">
      <div><label>نماد</label><select id="fSym"><option value="">همه</option></select></div>
      <div><label>قاعدهٔ بست</label><select id="fRule"><option value="">همه</option></select></div>
      <div><label>وضعیت</label><select id="fStatus"><option value="">همه</option>
        <option value="closed">بسته‌شده</option><option value="open">باز</option></select></div>
      <div><label>فقط بسته‌شده با قاعدهٔ ضدضرر؟</label>
        <label style="color:var(--fg)"><input type="checkbox" id="fRisk"> بله</label></div>
    </div>
    <div class="note">هر ردیف یک سیگنال است با شناسهٔ یکتا. روی ردیف بزن تا <b>پروندهٔ کامل</b> همان
      سیگنال (الگوریتم، الگو، اندیکاتورها، سفارش، و قاعده‌ای که بستش) باز شود.</div>
    <div id="sigTable"></div>
    <div id="sigDetail"></div>
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
  if (b.dataset.tab === "signals") loadSignals();
  if (b.dataset.tab === "runs") loadRuns();
});

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
  const rows = SIGS.map((s,i) => {
    const d = new Date(s.ts).toISOString().slice(0,16).replace("T"," ");
    return [`<code>${esc(String(s.id).split(":").slice(1).join(":"))}</code>`,
      esc(s.symbol), esc(d), esc(s.mode), esc(s.status==="open"?"باز":"بسته"),
      `<span class="${sgn(s.r)}">${R(s.r)}</span>`,
      `<span class="${sgn(s.pnl)}">${num(s.pnl)}$</span>`,
      s.rule ? `<code>${esc(s.rule)}</code> ${s.is_risk_control?'<span class="tag risk">✅</span>':''}` : "—"];
  });
  $("#sigTable").innerHTML = `<div class="mut" style="margin:8px 0">${SIGS.length} سیگنال</div>` +
    table(["شناسه","نماد","زمان","الگو","وضعیت","R","سود","بست با"], rows);
  [...$("#sigTable").querySelectorAll("tbody tr")].forEach((tr,i) => {
    tr.style.cursor = "pointer";
    tr.onclick = () => showSignal(SIGS[i]);
  });
  $("#sigDetail").innerHTML = "";
}
function showSignal(s) {
  $("#sigDetail").innerHTML = `<h3>پروندهٔ سیگنال <code>${esc(s.id)}</code></h3>` +
    `<div class="note">الگوریتم <b>${esc(s.algorithm)}</b> (هش <code>${esc(s.digest)}</code>) ·
      الگو <b>${esc(s.mode)}</b> · رژیم <b>${esc(s.regime)}</b> ·
      ${s.rule ? `بست با <b>${esc(s.rule)}</b> ${s.is_risk_control?'<span class="tag risk">قاعدهٔ ضدضرر</span>':''}` : '<b>هنوز باز</b>'}</div>
     <pre>${esc(JSON.stringify({open:s.raw_open, close:s.raw_close}, null, 1))}</pre>`;
  $("#sigDetail").scrollIntoView({behavior:"smooth", block:"start"});
}
$("#fSym").onchange = loadSignals; $("#fRule").onchange = loadSignals;
$("#fStatus").onchange = loadSignals; $("#fRisk").onchange = loadSignals;

/* ── آزمایشگاه ─────────────────────────────────────────────────────── */
let SCHEMA = null, BASE = {};
async function loadSchema() {
  SCHEMA = await api("/api/schema");
  BASE = SCHEMA.baseline_values || {};
  $("#syms").innerHTML = SCHEMA.symbols.map(s =>
    `<label><input type="checkbox" class="sym" value="${esc(s)}" checked>${esc(s)}</label>`).join("")
    || `<span class="mut">هیچ داده‌ای در کش نیست</span>`;
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
$("#resetBtn").onclick = () => loadSchema();
$("#runBtn").onclick = async () => {
  const overrides = currentOverrides();
  const symbols = [...document.querySelectorAll(".sym:checked")].map(x=>x.value);
  const gate = {min_expectancy_r: Number($("#gExp").value),
                min_trades: Number($("#gN").value),
                require_oos_positive: $("#gOos").checked,
                require_ci_excludes_zero: $("#gCi").checked};
  $("#runBtn").disabled = true; $("#runMsg").style.display = "inline";
  $("#runMsg").textContent = "در حال اجرا روی داده (بدون شبکه)";
  try {
    const rec = await api("/api/run", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({overrides, gate, label:$("#runLabel").value, symbols})});
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
  h += `<div class="note">شناسهٔ اجرا <code>${esc(rec.run_id)}</code> · هش تنظیمات
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
                elif path == "/api/signals":
                    self._json(lab.signals(
                        symbol=q.get("symbol", ""), rule=q.get("rule", ""),
                        only_risk=q.get("only_risk") in ("1", "true", "on"),
                        status=q.get("status", ""),
                        limit=int(q.get("limit", 300) or 300)))
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

        def do_POST(self):
            path = unquote(urlsplit(self.path).path)
            body = self._body()
            try:
                if path == "/api/run":
                    rec = lab.run_experiment(
                        overrides=body.get("overrides") or {},
                        label=body.get("label") or "",
                        gate=body.get("gate") or {},
                        symbols=body.get("symbols") or None)
                    self._json(rec)
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
    srv = ThreadingHTTPServer((host, port), make_handler(lab))
    return srv
