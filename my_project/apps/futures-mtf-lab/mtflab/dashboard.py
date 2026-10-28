"""داشبورد HTML خودکفا با تب‌های جداگانه (بدون هیچ وابستگی خارجی).

پنج تب:
  1) 🔀 مقایسه  — سناریوی قدیم در برابر جدید (KPI + منحنی موجودی + حکم نهایی)
  2) 🧠 سناریوی قدیم — TraderBrain (تک‌تایم‌فریم) با تفکیک رژیم/دلیل/ساعت
  3) 🧩 سناریوی جدید — MTF با مقایسهٔ نسخه‌های A/B/C و آمار وتوی لایه‌ها
  4) ✅ اعتبارسنجی — split، walk-forward، مونت‌کارلو، حساسیت، خط‌های پایه
  5) 🛡️ سلامت و دام‌ها — تست‌های ضد lookahead، گپ داده، چک‌لیست overfit

همه چیز در یک فایل HTML؛ CSS/JS داخلی؛ نمودارها SVG تولیدشده در پایتون.
"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

CSS = """
:root{--bg:#0d1017;--panel:#151a24;--panel2:#1b2230;--line:#26303f;--txt:#e6edf3;
--muted:#8b98a9;--green:#3ddc97;--red:#ff6b6b;--amber:#f7c948;--blue:#5aa9ff;--violet:#b98bff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:Vazirmatn,-apple-system,"Segoe UI",Roboto,Tahoma,sans-serif;font-size:14px;line-height:1.7}
header{padding:18px 22px 10px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#141a24,#0d1017)}
h1{margin:0;font-size:20px;font-weight:700}
h1 .tag{font-size:11px;font-weight:400;color:var(--muted);border:1px solid var(--line);
padding:2px 8px;border-radius:999px;margin-inline-start:8px;vertical-align:middle}
.sub{color:var(--muted);font-size:12px;margin-top:6px}
.tabs{display:flex;gap:4px;padding:10px 18px 0;border-bottom:1px solid var(--line);
background:var(--bg);overflow-x:auto;position:sticky;top:0;z-index:5}
.tab{padding:9px 15px;border:1px solid transparent;border-bottom:none;border-radius:9px 9px 0 0;
cursor:pointer;color:var(--muted);white-space:nowrap;font-size:13px;background:transparent}
.tab:hover{color:var(--txt);background:var(--panel)}
.tab.active{color:var(--txt);background:var(--panel);border-color:var(--line);
box-shadow:inset 0 2px 0 var(--green)}
main{padding:16px 18px 60px;max-width:1500px;margin:0 auto}
.pane{display:none}.pane.active{display:block}
h2{font-size:15px;color:var(--muted);font-weight:600;margin:22px 0 10px;
display:flex;align-items:center;gap:8px}
h2::after{content:"";flex:1;height:1px;background:var(--line)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:11px 13px}
.card .k{font-size:11px;color:var(--muted);margin-bottom:4px}
.card .v{font-size:19px;font-weight:700;letter-spacing:.2px}
.card .h{font-size:10.5px;color:var(--muted);margin-top:2px}
.pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--amber)}.dim{color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.grid2,.grid3{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:12px 14px;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{color:var(--muted);font-weight:600;background:var(--panel2);position:sticky;top:0}
tr:hover td{background:#1a212d}
.badge{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;border:1px solid var(--line)}
.badge.ok{color:var(--green);border-color:#1e5c46;background:#0f2b22}
.badge.bad{color:var(--red);border-color:#5c1e1e;background:#2b1010}
.badge.warn{color:var(--amber);border-color:#5c4a1e;background:#2b2410}
.note{background:var(--panel2);border:1px solid var(--line);border-inline-start:3px solid var(--blue);
padding:10px 13px;border-radius:9px;font-size:12.5px;color:#c7d2de;margin:10px 0}
.note.warn{border-inline-start-color:var(--amber)}
.note.bad{border-inline-start-color:var(--red)}
.note.ok{border-inline-start-color:var(--green)}
footer{color:var(--muted);font-size:11.5px;padding:16px 18px;border-top:1px solid var(--line);text-align:center}
.legend{font-size:11px;color:var(--muted);margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:3px;border-radius:2px;margin-inline-end:5px;vertical-align:middle}
details{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:8px 12px;margin:8px 0}
summary{cursor:pointer;color:var(--muted);font-size:12.5px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;direction:ltr;text-align:left}
"""

JS = """
function showTab(id,el){
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  var pane=document.getElementById(id); if(pane)pane.classList.add('active');
  if(el)el.classList.add('active');
  try{localStorage.setItem('mtf_tab',id);}catch(e){}
  window.scrollTo({top:0,behavior:'smooth'});
}
function sortTable(th){
  var table=th.closest('table'), idx=Array.from(th.parentNode.children).indexOf(th);
  var rows=Array.from(table.tBodies[0].rows);
  var asc=th.dataset.asc!=='1'; th.dataset.asc=asc?'1':'0';
  rows.sort(function(a,b){
    var x=a.cells[idx].dataset.v||a.cells[idx].innerText;
    var y=b.cells[idx].dataset.v||b.cells[idx].innerText;
    var nx=parseFloat(x), ny=parseFloat(y);
    if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;
    return asc?String(x).localeCompare(String(y),'fa'):String(y).localeCompare(String(x),'fa');
  });
  rows.forEach(r=>table.tBodies[0].appendChild(r));
}
document.addEventListener('DOMContentLoaded',function(){
  var last=null; try{last=localStorage.getItem('mtf_tab');}catch(e){}
  var el=last?document.getElementById(last):null;
  if(el){el.classList.add('active');
    document.querySelectorAll('.tab').forEach(function(t){
      if(t.getAttribute('onclick')&&t.getAttribute('onclick').indexOf("'"+last+"'")>=0)t.classList.add('active');
      else t.classList.remove('active');});
  }
  document.querySelectorAll('th').forEach(function(th){
    th.style.cursor='pointer'; th.title='کلیک = مرتب‌سازی'; th.addEventListener('click',function(){sortTable(th);});
  });
});
"""


# ----------------------------------------------------------------------------
# ابزارهای کوچک
# ----------------------------------------------------------------------------
def esc(x) -> str:
    return html.escape(str(x if x is not None else "—"))


def fnum(x, nd: int = 2, sign: bool = False, dash: str = "—") -> str:
    if x is None:
        return dash
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return "∞" if x > 0 else dash
    try:
        v = float(x)
    except (TypeError, ValueError):
        return esc(x)
    if sign:
        return f"{v:+,.{nd}f}"
    return f"{v:,.{nd}f}"


def fpct(x, nd: int = 1, sign: bool = True) -> str:
    if x is None:
        return "—"
    v = float(x)
    return (f"{v:+.{nd}f}%" if sign else f"{v:.{nd}f}%")


def cls(x, good_high: bool = True) -> str:
    if x is None:
        return "dim"
    v = float(x)
    if good_high:
        return "pos" if v > 0 else ("neg" if v < 0 else "dim")
    return "neg" if v > 0 else ("pos" if v < 0 else "dim")


def ts2date(ts_ms) -> str:
    if not ts_ms:
        return "—"
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "—"


def ts2short(ts_ms) -> str:
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return "—"


def kpi(label: str, value: str, sub: str = "", klass: str = "") -> str:
    return (f'<div class="card"><div class="k">{esc(label)}</div>'
            f'<div class="v {klass}">{value}</div>'
            f'<div class="h">{esc(sub)}</div></div>')


def table(headers: Sequence[str], rows: Sequence[Sequence[str]],
          raw: bool = False) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for r in rows:
        tds = "".join(
            (f"<td>{c}</td>" if raw else f"<td>{esc(c)}</td>") for c in r)
        body.append(f"<tr>{tds}</tr>")
    return (f'<div class="panel"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


# ----------------------------------------------------------------------------
# نمودارها (SVG خالص)
# ----------------------------------------------------------------------------
def svg_lines(series: List[dict], w: int = 1000, h: int = 300,
              title: str = "", pct: bool = False) -> str:
    """series = [{name, color, points:[(x_ts, y_value)], dash?}]"""
    series = [s for s in series if s.get("points")]
    if not series:
        return '<div class="panel dim">نموداری برای نمایش نیست</div>'
    xs = [p[0] for s in series for p in s["points"]]
    ys = [p[1] for s in series for p in s["points"]]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 == x0:
        x1 = x0 + 1
    pad = (y1 - y0) * 0.08 or 1.0
    y0, y1 = y0 - pad, y1 + pad
    pl, pr, pt, pb = 54, 14, 16, 26

    def px(x):
        return pl + (x - x0) / (x1 - x0) * (w - pl - pr)

    def py(y):
        return h - pb - (y - y0) / (y1 - y0) * (h - pt - pb)

    grid, labels = [], []
    for k in range(5):
        yy = y0 + (y1 - y0) * k / 4
        grid.append(f'<line x1="{pl}" y1="{py(yy):.1f}" x2="{w-pr}" y2="{py(yy):.1f}" '
                    f'stroke="#26303f" stroke-width="1"/>')
        lab = f"{yy:+.1f}%" if pct else f"{yy:,.0f}"
        labels.append(f'<text x="{pl-7}" y="{py(yy)+4:.1f}" fill="#8b98a9" font-size="10" '
                      f'text-anchor="end">{lab}</text>')
    if y0 < 0 < y1:
        grid.append(f'<line x1="{pl}" y1="{py(0):.1f}" x2="{w-pr}" y2="{py(0):.1f}" '
                    f'stroke="#5aa9ff" stroke-width="1" stroke-dasharray="4 3" opacity=".55"/>')
    paths = []
    for s in series:
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in s["points"])
        dash = ' stroke-dasharray="5 3"' if s.get("dash") else ""
        paths.append(f'<polyline points="{pts}" fill="none" stroke="{s["color"]}" '
                     f'stroke-width="{s.get("width",1.9)}"{dash}/>')
    xlabs = (f'<text x="{pl}" y="{h-7}" fill="#8b98a9" font-size="10">{ts2short(x0)}</text>'
             f'<text x="{w-pr}" y="{h-7}" fill="#8b98a9" font-size="10" '
             f'text-anchor="end">{ts2short(x1)}</text>')
    legend = "".join(f'<span><i style="background:{s["color"]}"></i>{esc(s["name"])}</span>'
                     for s in series)
    t = f'<div class="dim" style="font-size:12px;margin-bottom:6px">{esc(title)}</div>' if title else ""
    return (f'<div class="panel">{t}<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">'
            f'{"".join(grid)}{"".join(labels)}{"".join(paths)}{xlabs}</svg>'
            f'<div class="legend">{legend}</div></div>')


def svg_bars(labels: Sequence[str], values: Sequence[float], title: str = "",
             w: int = 520, h: int = 220, fmt: str = "{:+.2f}") -> str:
    n = len(labels)
    if n == 0:
        return ""
    vmax = max(abs(v) for v in values) or 1.0
    row_h = (h - 30) / n
    mid = (w - 120) / 2 + 90
    out = []
    for i, (lab, val) in enumerate(zip(labels, values)):
        y = 12 + i * row_h
        bw = abs(val) / vmax * (w - 130) / 2
        color = "#3ddc97" if val >= 0 else "#ff6b6b"
        x = mid if val >= 0 else mid - bw
        out.append(f'<text x="{w-6}" y="{y+row_h/2+3:.1f}" fill="#8b98a9" font-size="10" '
                   f'text-anchor="end">{esc(lab)}</text>'
                   f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bw,1):.1f}" '
                   f'height="{row_h-4:.1f}" fill="{color}" opacity=".82" rx="2"/>'
                   f'<text x="{w-6}" y="{y+row_h/2+3:.1f}" fill="none">{val}</text>')
    t = f'<div class="dim" style="font-size:12px;margin-bottom:4px">{esc(title)}</div>' if title else ""
    return (f'<div class="panel">{t}<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">'
            f'<line x1="{mid}" y1="8" x2="{mid}" y2="{h-14}" stroke="#26303f"/></svg>'
            f'<div class="legend"><span><i style="background:#3ddc97"></i>مثبت</span>'
            f'<span><i style="background:#ff6b6b"></i>منفی</span></div></div>')


def svg_hist(hist: Sequence[dict], title: str = "", w: int = 620, h: int = 220,
             color: str = "#5aa9ff") -> str:
    if not hist:
        return ""
    n = len(hist)
    cmax = max(d["count"] for d in hist) or 1
    bw = (w - 70) / n
    bars = []
    for i, d in enumerate(hist):
        bh = d["count"] / cmax * (h - 60)
        x = 50 + i * bw
        y = h - 34 - bh
        bars.append(f'<rect x="{x+1:.1f}" y="{y:.1f}" width="{bw-2:.1f}" height="{bh:.1f}" '
                    f'fill="{color}" opacity=".8" rx="2"/>')
        if i % max(1, n // 6) == 0:
            bars.append(f'<text x="{x:.1f}" y="{h-16}" fill="#8b98a9" font-size="9">{d["lo"]:,.0f}</text>')
    t = f'<div class="dim" style="font-size:12px;margin-bottom:4px">{esc(title)}</div>' if title else ""
    return (f'<div class="panel">{t}<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">'
            f'{"".join(bars)}</svg></div>')


def cumulative(trades: Sequence[dict]) -> List[tuple]:
    out, eq = [], 0.0
    for t in sorted(trades, key=lambda x: x.get("ts", 0)):
        eq += t.get("pnl", 0.0)
        out.append((t.get("ts", 0), eq))
    return out


# ----------------------------------------------------------------------------
# تب ۱ — مقایسه
# ----------------------------------------------------------------------------
def _run_card(run: dict) -> str:
    s = run.get("summary", {}) or {}
    return (
        kpi("Profit Factor", fnum(s.get("profit_factor"), 3),
            "≥1 یعنی سودده", cls((s.get("profit_factor") or 0) - 1))
        + kpi("Expectancy", fnum(s.get("expectancy"), 2, True) + " $",
              "به‌ازای هر معامله", cls(s.get("expectancy")))
        + kpi("Win Rate", fpct((s.get("win_rate") or 0) * 100, 1, False), "", "neu")
        + kpi("معاملات", fnum(s.get("trades"), 0), "", "neu")
        + kpi("بازده", fpct(s.get("return_pct")), "روی موجودی اولیه", cls(s.get("return_pct")))
        + kpi("Max DD", fpct(s.get("max_drawdown_pct"), 2, False), "افت بیشینه", "neg")
    )


def tab_compare(payload: dict) -> str:
    old = payload["scenarios"]["old"]
    new = payload["scenarios"]["new"]
    cm = payload.get("cost_models", {})
    rows = []
    for cm_key, cm_label in (("normalized", "یکسان‌سازی‌شده (عادلانه)"), ("native", "پیش‌فرض خودش")):
        for sc, scn in (("old", old), ("new", new)):
            r = scn["runs"].get(cm_key)
            if not r:
                continue
            s = r["summary"]
            rows.append([
                cm_label, scn["short_name"], r.get("label", ""),
                fnum(s.get("trades"), 0), fpct((s.get("win_rate") or 0) * 100, 1, False),
                fnum(s.get("profit_factor"), 3), fnum(s.get("expectancy"), 2, True),
                fpct(s.get("return_pct")), fpct(s.get("max_drawdown_pct"), 2, False),
                fnum(s.get("total_fees"), 2),
            ])
    h = ['<h2>مقایسهٔ سناریوها</h2>']
    h.append(f'<div class="note">دادهٔ یکسان: <b class="mono">{esc(payload["data"]["path"])}</b> · '
             f'{fnum(payload["data"]["candles"],0)} کندل · '
             f'{ts2short(payload["data"]["start_ts"])} → {ts2short(payload["data"]["end_ts"])}<br>'
             f'هزینهٔ یکسان‌سازی‌شده: کارمزد <b>{cm.get("normalized",{}).get("fee_bps")}bps</b> + '
             f'اسلیپیج <b>{cm.get("normalized",{}).get("slippage_pct")}%</b> هر طرف، '
             f'ریسک <b>{cm.get("normalized",{}).get("risk_per_trade_pct")}%</b> موجودی، '
             f'حداکثر <b>{cm.get("normalized",{}).get("max_concurrent")}</b> معاملهٔ همزمان.'
             f'<br>در حالت «پیش‌فرض خودش»، هر سناریو با تنظیمات پیش‌فرض خودش اجرا شده '
             f'(مقایسهٔ واقع‌گرایانه‌تر ولی بخشی از اختلاف از هزینه/تعداد معامله می‌آید).</div>')
    h.append(table(["مدل هزینه", "سناریو", "برچسب داده", "معاملات", "Win%", "PF",
                    "Expectancy$", "بازده%", "MaxDD%", "کارمزد$"], rows))

    # KPI دو ستونه
    h.append('<div class="grid2" style="margin-top:12px">')
    for scn, title, color in ((old, "🧠 سناریوی قدیم", "#b98bff"), (new, "🧩 سناریوی جدید", "#3ddc97")):
        r = scn["runs"].get("normalized") or {}
        h.append(f'<div><h2 style="margin-top:0">{title} — {esc(scn["subtitle"])}</h2>'
                 f'{_run_card(r)}</div>')
    h.append('</div>')

    # منحنی موجودی هم‌پوشان
    series = []
    for scn, color in ((old, "#b98bff"), (new, "#3ddc97")):
        r = scn["runs"].get("normalized")
        if r and r.get("equity_curve"):
            pts = [(p["ts"], p["equity"] - payload.get("initial_equity", 1000.0))
                   for p in r["equity_curve"]]
            if len(pts) > 1200:
                step = len(pts) // 1200 + 1
                pts = pts[::step]
            series.append({"name": f'{scn["short_name"]} (PnL تجمعی)',
                           "color": color, "points": pts, "width": 2})
    h.append('<h2>منحنی موجودی (PnL تجمعی، هزینهٔ یکسان)</h2>')
    h.append(svg_lines(series, title="محور افقی: زمان · محور عمودی: سود/زیان تجمعی دلاری"))

    # حکم نهایی
    v = payload.get("verdict", {})
    tone = "ok" if v.get("winner") == "new" else ("warn" if v.get("winner") == "tie" else "bad")
    h.append(f'<h2>حکم نهایی</h2><div class="note {tone}">{v.get("text", "")}</div>')
    if v.get("detail_rows"):
        h.append(table(["معیار", "سناریوی قدیم", "سناریوی جدید", "برنده"],
                       v["detail_rows"]))
    return "".join(h)


# ----------------------------------------------------------------------------
# تب ۲/۳ — جزئیات هر سناریو
# ----------------------------------------------------------------------------
def _dist_by(trades: Sequence[dict], key: str, top: int = 10) -> tuple:
    d: Dict[str, List[float]] = {}
    for t in trades:
        k = str(t.get(key) or "—")
        d.setdefault(k, []).append(t.get("pnl", 0.0))
    items = sorted(d.items(), key=lambda kv: -sum(kv[1]))[:top]
    return [k for k, _ in items], [round(sum(v), 2) for _, v in items]


def _hour_dist(trades: Sequence[dict]) -> tuple:
    d = {h: 0.0 for h in range(24)}
    for t in trades:
        try:
            hh = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).hour
        except (ValueError, OSError, OverflowError, KeyError):
            continue
        d[hh] += t.get("pnl", 0.0)
    return [f"{h:02d}" for h in range(24)], [round(d[h], 2) for h in range(24)]


def _scenario_tab(scn: dict, payload: dict, extra_html: str = "") -> str:
    run = scn["runs"].get("normalized") or scn["runs"].get("native") or {}
    s = run.get("summary", {})
    trades = run.get("trades", [])
    h = [f'<h2>{esc(scn["name"])}</h2>',
         f'<div class="note">{scn.get("description","")}</div>',
         _run_card(run)]

    if trades:
        pts = [(t["ts"], t.get("cum", 0.0)) for t in _with_cum(trades)]
        if len(pts) > 1500:
            step = len(pts) // 1500 + 1
            pts = pts[::step]
        h.append('<h2>منحنی سود/زیان تجمعی</h2>')
        h.append(svg_lines([{"name": "PnL تجمعی", "color": "#3ddc97", "points": pts}]))

        h.append('<h2>تفکیک سود/ضرر</h2><div class="grid2">')
        labels, vals = _dist_by(trades, "reason")
        h.append(svg_bars(labels, vals, "دلیل خروج — PnL تجمعی ($)"))
        labels, vals = _dist_by(trades, "regime")
        h.append(svg_bars(labels, vals, "رژیم هنگام ورود — PnL ($)"))
        labels, vals = _dist_by(trades, "trigger_mode")
        if any(l != "—" for l in labels):
            h.append(svg_bars(labels, vals, "حالت تریگر — PnL ($)"))
        labels, vals = _hour_dist(trades)
        h.append(svg_bars(labels, vals, "ساعت UTC — PnL ($)", h=300))
        h.append('</div>')

        # بهترین/بدترین معاملات
        best = sorted(trades, key=lambda t: -t.get("pnl", 0))[:5]
        worst = sorted(trades, key=lambda t: t.get("pnl", 0))[:5]
        rows = []
        for t in best + worst:
            rows.append([ts2date(t.get("ts")), "LONG" if t.get("side", 1) > 0 else "SHORT",
                         fnum(t.get("entry"), 2), fnum(t.get("exit"), 2),
                         fnum(t.get("pnl"), 2, True), fnum(t.get("r_multiple"), 2, True),
                         esc(t.get("reason", "")), esc(t.get("trigger_mode", "")),
                         fnum(t.get("bars_held"), 0)])
        h.append('<h2>بهترین و بدترین معاملات</h2>')
        h.append(table(["زمان", "جهت", "ورود", "خروج", "PnL$", "R", "دلیل خروج",
                        "تریگر", "کندل"], rows))
    else:
        h.append('<div class="note warn">این سناریو هیچ معامله‌ای در این بازه نداشت.</div>')

    h.append(extra_html)
    return "".join(h)


def _with_cum(trades: Sequence[dict]) -> List[dict]:
    out, cum = [], 0.0
    for t in sorted(trades, key=lambda x: x.get("ts", 0)):
        cum += t.get("pnl", 0.0)
        d = dict(t)
        d["cum"] = round(cum, 4)
        out.append(d)
    return out


def tab_old(payload: dict) -> str:
    scn = payload["scenarios"]["old"]
    run = scn["runs"].get("normalized") or {}
    s = run.get("summary", {})
    extra = [f'<h2>آمار وتوی لایه‌ها</h2>',
             '<div class="note">سناریوی قدیم تک‌تایم‌فریمی است؛ «رژیم» و «تریگر» روی همان '
             'کندل‌ها محاسبه می‌شوند (بدون هم‌ترازی چندتایم‌فریمی).</div>']
    if s.get("veto_stats"):
        rows = [[esc(k), fnum(v, 0)] for k, v in sorted(s["veto_stats"].items(),
                                                        key=lambda kv: -kv[1]) if v]
        extra.append(table(["دلیل رد/وتو", "تعداد"], rows))
    return _scenario_tab(scn, payload, "".join(extra))


def tab_new(payload: dict) -> str:
    scn = payload["scenarios"]["new"]
    run = scn["runs"].get("normalized") or {}
    s = run.get("summary", {})
    h = [f'<h2>مقایسهٔ نسخه‌های هم‌راستایی A / B / C</h2>',
         '<div class="note"><b>A</b> = AND سخت‌گیرانه (بایاس ∧ فیلتر ∧ تریگر) · '
         '<b>B</b> = امتیاز وزنی (آستانه‌دار) · '
         '<b>C</b> = فقط فیلتر رژیم (بایاس نادیده).<br>'
         'هدف: نشان دادن اینکه «سخت‌گیری بیشتر» کمیت را فدای کیفیت می‌کند یا نه.</div>']
    rows = []
    for v, vr in (scn.get("versions") or {}).items():
        st = vr.get("summary", {})
        rows.append([f"نسخه {v}", fnum(st.get("trades"), 0),
                     fpct((st.get("win_rate") or 0) * 100, 1, False),
                     fnum(st.get("profit_factor"), 3), fnum(st.get("expectancy"), 2, True),
                     fpct(st.get("return_pct")), fpct(st.get("max_drawdown_pct"), 2, False)])
    if rows:
        h.append(table(["نسخه", "معاملات", "Win%", "PF", "Expectancy$", "بازده%", "MaxDD%"], rows))
    ver = payload.get("best_version")
    if ver and (scn.get("versions") or {}).get(ver, {}).get("summary"):
        st = scn["versions"][ver]["summary"]
        h.append(f'<div class="note ok">نسخهٔ برتر بر اساس expectancy: <b>{esc(ver)}</b> '
                 f'با PF={fnum(st.get("profit_factor"),3)} و '
                 f'expectancy={fnum(st.get("expectancy"),2,True)}$ '
                 f'(انتخاب پس‌ازواقع‌بینی است — برای معاملهٔ واقعی باید فقط روی '
                 f'train انتخاب شود؛ همین کار در walk-forward انجام شده).</div>')

    extra = ['<h2>آمار وتوی لایه‌ها — چرا معامله نکرد؟</h2>']
    if s.get("veto_stats"):
        rows2 = [[esc(k), fnum(v, 0)] for k, v in sorted(s["veto_stats"].items(),
                                                         key=lambda kv: -kv[1]) if v]
        extra.append(table(["لایه/دلیل", "تعداد کندل"], rows2))
    if s.get("trigger_stats"):
        rows3 = [[esc(k), fnum(v, 0)] for k, v in s["trigger_stats"].items()]
        extra.append(table(["حالت تریگر", "تعداد"], rows3))
    health = payload.get("health_new", {})
    if health:
        cov = health.get("alignment_coverage", {})
        aud = health.get("leakage_audit", {})
        extra.append('<h2>سلامت هم‌ترازی</h2>')
        extra.append(
            f'<div class="note {"ok" if aud.get("clean") else "bad"}">'
            f'حسابرسی نشتی: <b>{"✅ پاک" if aud.get("clean") else "❌ نقض"}</b> · '
            f'{fnum(aud.get("bars_checked"),0)} کندل بررسی شد · '
            f'پوشش لایهٔ فیلتر: <b>{fpct((cov.get("filter_coverage") or 0)*100, 2, False)}</b> · '
            f'پوشش بایاس: <b>{fpct((cov.get("bias_coverage") or 0)*100, 2, False)}</b></div>')
    return _scenario_tab(scn, payload, "".join(h + extra))


# ----------------------------------------------------------------------------
# تب ۴ — اعتبارسنجی
# ----------------------------------------------------------------------------
def tab_validation(payload: dict) -> str:
    v = payload.get("validation") or {}
    if not v:
        return ('<div class="note warn">اعتبارسنجی اجرا نشده. با '
                '<span class="mono">--validate</span> دوباره اجرا کنید.</div>')
    h = ['<h2>خلاصهٔ اعتبارسنجی</h2>']
    ov = v.get("overfit", {})
    sc = ov.get("score", 0)
    tone = "ok" if sc >= 0.85 else ("warn" if sc >= 0.5 else "bad")
    h.append(f'<div class="note {tone}"><b>{ov.get("verdict","")}</b><br>'
             f'چک‌لیست overfit: {fnum(ov.get("passed"),0)} از {fnum(ov.get("total"),0)} '
             f'مورد پاس شد ({fpct(sc*100,0,False)}).</div>')

    rows = [[("✅" if c["pass"] else "❌"), esc(c["name"]), f'<span class="mono">{esc(c["detail"])}</span>']
            for c in ov.get("checks", [])]
    if rows:
        h.append(table(["نتیجه", "بررسی", "جزئیات"], rows, raw=True))

    # split
    sp = v.get("split", {})
    h.append('<h2>تقسیم train / validation / out-of-sample</h2>')
    rows = []
    for seg in sp.get("segments", []):
        rows.append([seg["segment"], fnum(seg["candles"], 0), fnum(seg["n"], 0),
                     fpct((seg["win_rate"] or 0) * 100, 1, False), fnum(seg["profit_factor"], 3),
                     fnum(seg["expectancy"], 2, True), fpct(seg["max_drawdown_pct"], 2, False)])
    if rows:
        h.append(table(["بخش", "کندل", "معاملات", "Win%", "PF", "Expectancy$", "MaxDD%"], rows))
    note = (sp.get("verdict") or {}).get("note", "")
    h.append(f'<div class="note {"ok" if (sp.get("verdict") or {}).get("pass") else "warn"}">'
             f'افت train→OOS: <b>{fnum(sp.get("degradation_train_to_oos"), 2, True)}</b> · {esc(note)}</div>')

    # walk-forward
    wf = v.get("walk_forward", {})
    h.append('<h2>Walk-forward</h2>')
    rows = [[w["window"], fnum(w["test_candles"], 0), fnum(w["n"], 0),
             fpct((w["win_rate"] or 0) * 100, 1, False), fnum(w["profit_factor"], 3),
             fnum(w["expectancy"], 2, True), fnum(w.get("selected_adx_min"), 1)]
            for w in wf.get("windows", [])]
    if rows:
        h.append(table(["پنجره", "کندل test", "معاملات", "Win%", "PF", "Expectancy$",
                        "ADX انتخابی"], rows))
    if wf.get("windows"):
        h.append(svg_bars([f"W{w['window']}" for w in wf["windows"]],
                          [w["expectancy"] for w in wf["windows"]],
                          "Expectancy هر پنجرهٔ out-of-sample ($)"))
    h.append(f'<div class="note {"ok" if "✅" in (wf.get("verdict") or "") else "warn"}">'
             f'{esc(wf.get("verdict",""))} · پنجره‌های سودده: '
             f'{fnum(wf.get("profitable_windows"),0)}/{fnum(wf.get("n_windows"),0)} · '
             f'میانگین {fnum(wf.get("mean_expectancy"),3,True)} · '
             f'انحراف {fnum(wf.get("std_expectancy"),3)}</div>')

    # monte carlo
    mc = v.get("monte_carlo", {})
    h.append('<h2>مونت‌کارلو (bootstrap پیامد معاملات)</h2>')
    if mc.get("simulations"):
        h.append('<div class="cards">'
                 + kpi("P(سود)", fpct(mc["p_profit"] * 100, 1, False), "احتمال سودده بودن",
                       "pos" if mc["p_profit"] >= 0.6 else "neg")
                 + kpi("P(ورشکستگی)", fpct(mc["p_ruin"] * 100, 1, False),
                       f"افت ≥{mc['ruin_threshold_pct']}%", "neg" if mc["p_ruin"] > 0.1 else "pos")
                 + kpi("PnL صدک ۵", fnum(mc["total_pnl_p5"], 1, True), "سناریوی بدبینانه", "neg")
                 + kpi("PnL میانه", fnum(mc["total_pnl_median"], 1, True), "", "neu")
                 + kpi("PnL صدک ۹۵", fnum(mc["total_pnl_p95"], 1, True), "سناریوی خوش‌بینانه", "pos")
                 + kpi("MaxDD میانه", fpct(mc["max_dd_p50"], 1, False), "", "neu")
                 + '</div>')
        h.append(svg_hist(mc.get("histogram", []), "توزیع کل PnL در شبیه‌سازی‌ها ($)"))
    else:
        h.append(f'<div class="note warn">{esc(mc.get("note",""))}</div>')

    # baselines
    b = v.get("baselines", {})
    h.append('<h2>خط‌های پایه — آیا MTF ارزش افزوده دارد؟</h2>')
    ovs = v.get("overall", {})
    rows = [[("سناریوی MTF (نسخهٔ منتخب)"),
             fnum(ovs.get("n"), 0), fpct((ovs.get("win_rate") or 0) * 100, 1, False),
             fnum(ovs.get("profit_factor"), 3), fnum(ovs.get("expectancy"), 2, True),
             fpct(ovs.get("return_pct")), fpct(ovs.get("max_drawdown_pct"), 2, False)]]
    st = b.get("single_timeframe", {})
    if st:
        rows.append(["تک‌تایم‌فریم (بدون فیلتر/بایاس)", fnum(st.get("n"), 0),
                     fpct((st.get("win_rate") or 0) * 100, 1, False),
                     fnum(st.get("profit_factor"), 3), fnum(st.get("expectancy"), 2, True),
                     fpct(st.get("return_pct")), fpct(st.get("max_drawdown_pct"), 2, False)])
    rc = b.get("random_control", {})
    if rc:
        rows.append(["کنترل تصادفی", fnum(rc.get("n"), 0),
                     fpct((rc.get("win_rate") or 0) * 100, 1, False),
                     fnum(rc.get("profit_factor"), 3), fnum(rc.get("expectancy"), 2, True),
                     fpct(rc.get("return_pct")), fpct(rc.get("max_drawdown_pct"), 2, False)])
    bh = b.get("buy_hold", {})
    if bh:
        rows.append(["Buy & Hold", "—", "—", "—", "—",
                     fpct(bh.get("return_pct")), fpct(bh.get("max_drawdown_pct"), 2, False)])
    h.append(table(["روش", "معاملات", "Win%", "PF", "Expectancy$", "بازده%", "MaxDD%"], rows))
    if st and ovs:
        edge = (ovs.get("expectancy") or 0) - (st.get("expectancy") or 0)
        h.append(f'<div class="note {"ok" if edge > 0 else "bad"}">'
                 f'ارزش افزودهٔ لایه‌های MTF نسبت به تک‌تایم‌فریم: '
                 f'<b>{fnum(edge, 3, True)}$</b> در هر معامله '
                 f'({fnum((ovs.get("n") or 0) - (st.get("n") or 0), 0, True)} معامله). '
                 f'{"✅ فیلتر چندتایم‌فریمی بهتر بود" if edge > 0 else "❌ فیلتر چندتایم‌فریمی برتری نشان نداد"}</div>')

    # sensitivity
    se = v.get("sensitivity", {})
    if se.get("grid"):
        h.append(f'<h2>تحلیل حساسیت ({fnum(se.get("trials"),0)} آزمایش)</h2>')
        for name, rs in se["grid"].items():
            rows = [[fnum(r["value"], 2), fnum(r["n"], 0), fnum(r["profit_factor"], 3),
                     fnum(r["expectancy"], 2, True), fpct(r["return_pct"])] for r in rs]
            h.append(f'<details><summary>{esc(name)} — PF از '
                     f'{fnum(min(x["profit_factor"] or 0 for x in rs),2)} تا '
                     f'{fnum(max(x["profit_factor"] or 0 for x in rs),2)}</summary>'
                     + table(["مقدار", "معاملات", "PF", "Expectancy$", "بازده%"], rows)
                     + '</details>')
        h.append(f'<div class="note {"ok" if se.get("robust") else "warn"}">'
                 f'گسترهٔ PF: {fnum(se.get("pf_min"),3)} … {fnum(se.get("pf_max"),3)} '
                 f'(spread={fnum(se.get("pf_spread"),3)}) · {esc(se.get("note",""))}</div>')
    return "".join(h)


# ----------------------------------------------------------------------------
# تب ۵ — سلامت و دام‌ها
# ----------------------------------------------------------------------------
def tab_health(payload: dict) -> str:
    hl = payload.get("health", {})
    h = ['<h2>خودآزمایی و تست‌های ضد lookahead</h2>']
    rows = []
    for t in hl.get("tests", []):
        rows.append([('<span class="badge ok">PASS</span>' if t["pass"]
                      else '<span class="badge bad">FAIL</span>'),
                     esc(t["name"]), f'<span class="mono">{esc(t.get("detail",""))}</span>'])
    if rows:
        h.append(table(["وضعیت", "تست", "جزئیات"], rows, raw=True))

    lg = hl.get("leakage", {})
    h.append(f'<div class="note {"ok" if lg.get("clean") else "bad"}">'
             f'حسابرسی نشتی هم‌ترازی (سناریوی جدید): '
             f'<b>{"✅ هیچ نقضی یافت نشد" if lg.get("clean") else "❌ نقض"}</b> — '
             f'{fnum(lg.get("bars_checked"),0)} کندل تریگر بررسی شد.</div>')

    gaps = hl.get("gaps", {})
    if gaps:
        h.append('<h2>بهداشت داده (گپ‌ها — بدون پرکردن کورکورانه)</h2>')
        rows = [[esc(layer), esc(g.get("tf")), fnum(g.get("candles"), 0),
                 fnum(g.get("missing_candles"), 0), fpct(g.get("missing_pct"), 3, False),
                 '<span class="badge ok">پاک</span>' if g.get("clean")
                 else '<span class="badge warn">گپ دارد</span>'] for layer, g in gaps.items()]
        h.append(table(["لایه", "تایم‌فریم", "کندل", "گم‌شده", "درصد", "وضعیت"], rows, raw=True))

    pit = hl.get("pitfalls", [])
    if pit:
        h.append('<h2>دام‌های پوشش‌داده‌شده (docs/pitfalls.md)</h2>')
        h.append(table(["#", "دام", "چطور پوشش داده شد"],
                       [[i + 1, esc(p[0]), esc(p[1])] for i, p in enumerate(pit)]))

    runs = hl.get("runs", [])
    if runs:
        h.append('<h2>ردپای اجرا (reproducibility)</h2>')
        h.append(table(["فایل", "توضیح"],
                       [[f'<span class="mono">{esc(r[0])}</span>', esc(r[1])] for r in runs], raw=True))

    h.append('<div class="note warn">⚠️ همهٔ اعداد این داشبورد <b>PAPER</b> هستند. '
             'LIVE عمداً پیاده‌سازی نشده است. تا وقتی خروجی روی دادهٔ واقعی و '
             'out-of-sample و با اختلاف آماری معنادار از خط پایه برنده نشود، '
             'هیچ سرمایهٔ واقعی نباید درگیر شود.</div>')
    return "".join(h)


# ----------------------------------------------------------------------------
# رندر نهایی
# ----------------------------------------------------------------------------
def render(payload: dict, title: str = "داشبورد مقایسهٔ سناریوها") -> str:
    tabs = [
        ("tab-compare", "🔀 مقایسه", tab_compare(payload)),
        ("tab-old", "🧠 سناریوی قدیم", tab_old(payload)),
        ("tab-new", "🧩 سناریوی جدید", tab_new(payload)),
        ("tab-validation", "✅ اعتبارسنجی", tab_validation(payload)),
        ("tab-health", "🛡️ سلامت و دام‌ها", tab_health(payload)),
    ]
    buttons = "".join(
        f'<button class="tab{" active" if i == 0 else ""}" '
        f'onclick="showTab(\'{tid}\',this)">{esc(lab)}</button>'
        for i, (tid, lab, _) in enumerate(tabs))
    panes = "".join(
        f'<section class="pane{" active" if i == 0 else ""}" id="{tid}">{body}</section>'
        for i, (tid, _, body) in enumerate(tabs))

    gen = payload.get("generated_at", "")
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head>
<body>
<header>
  <h1>{esc(title)}<span class="tag">PAPER · فقط شبیه‌سازی</span></h1>
  <div class="sub">{esc(payload.get("subtitle",""))} · ساخته‌شده: {esc(gen)}</div>
</header>
<nav class="tabs">{buttons}</nav>
<main>{panes}</main>
<footer>
  Futures MTF Lab + Futures Scalp Lab · دادهٔ عمومی Bybit/CSV · بدون API key ·
  <b>LIVE غیرفعال</b> · این داشبورد هیچ توصیهٔ سرمایه‌گذاری نیست.
</footer>
<script>{JS}</script>
</body></html>"""


def write_dashboard(payload: dict, path: str, title: str = "داشبورد مقایسهٔ سناریوها") -> str:
    html_str = render(payload, title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_str)
    return path
