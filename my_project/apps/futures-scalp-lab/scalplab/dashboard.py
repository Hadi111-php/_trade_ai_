"""Daashboard: HTML dashboard برای نتایج backtest.

استفاده:
    python3 -m scalplab dashboard --coin BTCUSDT --csv data/btcusdt_1h_lastyear.csv --out dash.html
    python3 -m scalplab dashboard --compare --coins BTCUSDT,ETHUSDT --csv data/btcusdt_1h_lastyear.csv
    python3 -m scalplab dashboard --coin BTCUSDT --csv data/btcusdt_1h_lastyear.csv --sensitivity
"""
from __future__ import annotations

import io, os, sys, json, csv, math, contextlib
from collections import defaultdict
from datetime import datetime

from .trader_brain import TraderConfig, TraderBrain, load_trader_config, run_trader
from .indicators import build_snapshot
from .regimes import compute_regimes
from .data import csv_candles
from .logger import JsonlWriter
from .runner import DEFAULT_PARAMS


# ──────────────────────────────────────────────────────────────────────────
# اجرای backtest و دریافتِ trades
# ──────────────────────────────────────────────────────────────────────────

def _run_one(cfg: TraderConfig):
    """backtest اجرا کن و tradesِ close را از journal برگردان."""
    # حذفِ journalِ قدیمی (JsonlWriter append می‌کند — باید fresh باشد)
    jp = os.path.join(cfg.out_dir, f"trader_trades_{cfg.run_id}.jsonl")
    if os.path.exists(jp):
        os.remove(jp)
    sp = os.path.join(cfg.out_dir, f"trader_signals_{cfg.run_id}.jsonl")
    if os.path.exists(sp):
        os.remove(sp)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_trader(cfg)
    trades = []
    with open(jp) as f:
        for line in f:
            d = json.loads(line)
            if d.get("type") == "close":
                trades.append(d)
    return trades, buf.getvalue()


def _avg_vol(csv_path):
    rows = list(csv.reader(open(csv_path)))[1:]
    vols = [float(r[5]) for r in rows if r[5]]
    return (sum(vols) / len(vols)) if vols else 1.0


# ──────────────────────────────────────────────────────────────────────────
# metrics
# ──────────────────────────────────────────────────────────────────────────

def metrics(trades):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gw = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in losses)
    pf = gw / gl if gl > 0 else 0.0
    tot = sum(t["pnl"] for t in trades)
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / n * 100) if n else 0,
        "pf": pf, "expectancy": tot / n if n else 0,
        "total_pnl": tot, "avg_win": gw / len(wins) if wins else 0,
        "avg_loss": -gl / len(losses) if losses else 0,
    }


# ──────────────────────────────────────────────────────────────────────────
# SVG charts (بدون numpy/pandas — pure string)
# ──────────────────────────────────────────────────────────────────────────

def svg_equity(trades, w=760, h=220):
    """Cumulative PnL line chart."""
    if not trades:
        return f'<svg width="{w}" height="{h}"></svg>'
    ts = sorted(trades, key=lambda t: t["ts"])
    for t in ts:
        t["_cum"] = t.get("_cum", 0) + t["pnl"]
    cums = [t["_cum"] for t in ts]
    xs = list(range(len(ts)))
    lo, hi = min(cums), max(cums)
    if hi == lo: hi = lo + 1
    pad_l, pad_b, pad_t = 40, 25, 10
    def px(i): return pad_l + i * (w - pad_l - 5) / max(len(ts)-1, 1)
    def py(c): return h - pad_b - (c - lo) * (h - pad_b - pad_t) / (hi - lo)
    pts = " ".join(f"{px(i):.1f},{py(c):.1f}" for i, c in enumerate(cums))
    zero_y = py(0)
    zero_line = f'<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{w-5}" y2="{zero_y:.1f}" stroke="#ccc" stroke-dasharray="3"/>' if lo < 0 < hi else ""
    return f'''<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{w}" height="{h}" fill="#1a1a2e"/>
  {zero_line}
  <polyline points="{pts}" fill="none" stroke="#4ade80" stroke-width="1.5"/>
  <circle cx="{px(len(ts)-1):.1f}" cy="{py(cums[-1]):.1f}" r="3" fill="#4ade80"/>
  <text x="{pad_l}" y="{h-5}" fill="#888" font-size="10">{ts[0]['ts']}</text>
  <text x="{w-70}" y="{h-5}" fill="#888" font-size="10">{datetime.utcfromtimestamp(ts[-1]['ts']/1000).strftime('%Y-%m-%d')}</text>
  <text x="5" y="{py(hi)+4:.0f}" fill="#888" font-size="9">{hi:+.1f}</text>
  <text x="5" y="{py(lo)+12:.0f}" fill="#888" font-size="9">{lo:+.1f}</text>
</svg>'''


def svg_bars(title, labels, values, w=370, h=210, fmt="{:.1f}"):
    """Horizontal bar chart. values و labels موازی."""
    n = len(labels)
    if n == 0:
        return f'<div class="card"><h4>{title}</h4><p class="muted">بدون داده</p></div>'
    maxv = max(abs(v) for v in values) if values else 1
    if maxv == 0: maxv = 1
    row_h = (h - 40) / max(n, 1)
    bars = []
    for i, (lab, val) in enumerate(zip(labels, values)):
        y = 15 + i * row_h
        bw = abs(val) / maxv * (w - 90)
        color = "#4ade80" if val >= 0 else "#f87171"
        off = 45 if val >= 0 else 45 - bw
        bars.append(f'<text x="0" y="{y+10:.0f}" fill="#ccc" font-size="9">{lab}</text>'
                    f'<rect x="{off:.1f}" y="{y:.0f}" width="{bw:.1f}" height="{row_h-4:.0f}" fill="{color}" opacity="0.8"/>'
                    f'<text x="{off+bw+3:.1f}" y="{y+row_h/2+3:.0f}" fill="#aaa" font-size="9">{fmt.format(val)}</text>')
    return f'''<div class="card"><h4>{title}</h4>
<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">
{"".join(bars)}
</svg></div>'''


# ──────────────────────────────────────────────────────────────────────────
# distribution analysis
# ──────────────────────────────────────────────────────────────────────────

def dist_by_reason(trades):
    d = defaultdict(lambda: [0, 0.0])
    for t in trades:
        d[t["reason"]][0] += 1; d[t["reason"]][1] += t["pnl"]
    return list(d.items())


def dist_by_regime(trades):
    d = defaultdict(lambda: [0, 0.0])
    for t in trades:
        r = t.get("regime_entry", "?")
        d[r][0] += 1; d[r][1] += t["pnl"]
    return list(d.items())


def dist_by_volume(trades, avg_vol):
    def bk(r):
        if r < 0.5: return "<0.5"
        if r < 0.75: return "0.5-0.75"
        if r < 1.0: return "0.75-1"
        if r < 1.5: return "1-1.5"
        if r < 2.0: return "1.5-2"
        return ">2"
    d = defaultdict(lambda: [0, 0.0])
    for t in trades:
        vr = t["volume_entry"] / avg_vol if avg_vol else 1
        d[bk(vr)][0] += 1; d[bk(vr)][1] += t["pnl"]
    return list(d.items())


def dist_by_time(trades):
    d = defaultdict(lambda: [0, 0.0])
    for t in trades:
        hr = (t["ts"] // 3600000) % 24
        d[hr][0] += 1; d[hr][1] += t["pnl"]
    return [(f"{h:02d}:00", d[h][1]) for h in range(24)]


# ──────────────────────────────────────────────────────────────────────────
# HTML assembly
# ──────────────────────────────────────────────────────────────────────────

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f0f1a;color:#e2e2e2;margin:0;padding:20px}
h1{color:#4ade80;margin:0 0 4px} h2{color:#888;font-size:14px;margin:20px 0 8px}
.sub{color:#888;font-size:12px;margin-bottom:16px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.card{background:#1a1a2e;border-radius:8px;padding:12px 16px;border:1px solid #2a2a40;flex:1;min-width:120px}
.card h4{margin:0 0 6px;font-size:11px;color:#888;text-transform:uppercase}
.card .v{font-size:20px;font-weight:bold}
.pos{color:#4ade80}.neg{color:#f87171}.neu{color:#fbbf24}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card-grid{background:#1a1a2e;border-radius:8px;padding:12px;border:1px solid #2a2a40}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:6px 10px;border-bottom:1px solid #2a2a40;text-align:left}
th{color:#888}
.sens th,.sens td{text-align:center}
.legend{font-size:11px;color:#888;margin-top:8px}
"""


def card(title, val, cls=""):
    return f'<div class="card"><h4>{title}</h4><div class="v {cls}">{val}</div></div>'


def summary_cards(m):
    pf_cls = "pos" if m["pf"] >= 1 else "neg"
    ex_cls = "pos" if m["expectancy"] >= 0 else "neg"
    pnl_cls = "pos" if m["total_pnl"] >= 0 else "neg"
    return (
        card("Profit Factor", f'{m["pf"]:.3f}', pf_cls)
        + card("Expectancy/trade", f'{m["expectancy"]:+.2f}', ex_cls)
        + card("Win Rate", f'{m["win_rate"]:.1f}%', "neu")
        + card("Trades", f'{m["n"]}', "neu")
        + card("Total PnL", f'{m["total_pnl"]:+.2f}', pnl_cls)
        + card("Avg Win/Loss", f'{m["avg_win"]:+.1f}/{m["avg_loss"]:+.1f}', "neu")
    )


def generate_html(coin, csv_path, cfg, trades, avg_vol, sens_rows=None, split_info=None):
    m = metrics(trades)
    title = f"📊 داشبورد Backtest — {coin}"
    sub = f"{csv_path} | {len(trades)} trades | settings: risk={cfg.risk_per_trade_pct}% fixed={cfg.fixed_risk} rr={cfg.take_profit_rr} entry={cfg.entry_mode}"

    body = [f"<h1>{title}</h1><div class='sub'>{sub}</div>"]
    body.append(f"<div class='cards'>{summary_cards(m)}</div>")

    body.append("<h2>📈 Curve موجودی (Cumulative PnL)</h2>")
    body.append(svg_equity(trades))

    body.append("<h2>🔍 تفکیک سود/ضرر</h2><div class='grid'>")
    byr = dist_by_reason(trades)
    body.append(svg_bars("خروج — PnL", [f"{k}" for k, _ in byr], [v[1] for _, v in byr]))
    byg = dist_by_regime(trades)
    body.append(svg_bars("رژیمِ ورود — PnL", [f"{k}" for k, _ in byg], [v[1] for _, v in byg]))
    byv = dist_by_volume(trades, avg_vol)
    body.append(svg_bars("ratio حجمِ ورود — PnL", [f"{k}×" for k, _ in byv], [v[1] for _, v in byv]))
    byt = dist_by_time(trades)
    body.append(svg_bars("ساعت (UTC) — PnL", [k for k, _ in byt], [v for _, v in byt]))
    body.append("</div>")

    if split_info:
        body.append("<h2>✅ تفکیک in-sample / out-of-sample</h2>")
        body.append("<table><tr><th>فترة</th><th>معاملات</th><th>PF</th><th>Expectancy</th><th>verdict</th></tr>")
        for label, m2 in split_info:
            v = "✅ real" if m2["pf"] >= 1 else "❌ overfit"
            body.append(f"<tr><td>{label}</td><td>{m2['n']}</td><td>{m2['pf']:.3f}</td>"
                        f"<td>{m2['expectancy']:+.2f}</td><td class='{'pos' if m2['pf']>=1 else 'neg'}'>{v}</td></tr>")
        body.append("</table>")

    if sens_rows:
        body.append("<h2>⚡ threshold sensitivity (robustness check)</h2>")
        body.append("<table class='sens'><tr><th>threshold</th><th>n</th><th>PF</th><th>Expectancy</th></tr>")
        for thr, n, pf, ex in sens_rows:
            cls = "pos" if pf >= 1 else "neg"
            body.append(f"<tr><td>{thr}</td><td>{n}</td><td class='{cls}'>{pf:.3f}</td><td>{ex:+.2f}</td></tr>")
        body.append("</table>")
        body.append("<div class='legend'>⚠️ اگر PF ثابت است across threshold → robust. اگر جهش دارد → overfitting.</div>")

    body.append("<div class='legend'>✅ PF≥1 | ❌ PF<1 | داده واقعی Bybit | ریسک ثابت ۱۰ USDT | slippage 0.05%</div>")

    return f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(body)}</body></html>"


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def _build_cfg(coin, csv_path, trader_argv):
    from .trader_brain import load_trader_config
    cfg = load_trader_config(trader_argv)
    cfg.symbol = coin
    cfg.csv_path = csv_path
    cfg.data_mode = "csv"
    if not cfg.run_id:
        cfg.run_id = f"dash-{coin}-{int(datetime.utcnow().timestamp())}"
    return cfg


def main(argv=None):
    import argparse
    argv = list(argv if argv is not None else sys.argv[1:])
    p = argparse.ArgumentParser(prog="scalplab dashboard", description="HTML dashboard backtest")
    p.add_argument("--coin", default="BTCUSDT")
    p.add_argument("--csv", default="data/btcusdt_1h_lastyear.csv")
    p.add_argument("--out", default="dashboard.html")
    p.add_argument("--compare", action="store_true")
    p.add_argument("--coins", default="BTCUSDT,ETHUSDT")
    p.add_argument("--sensitivity", action="store_true")
    p.add_argument("--split", action="store_true")
    args, trader_argv = p.parse_known_args(argv)

    if args.compare:
        return _do_compare(args, trader_argv)
    if args.split:
        return _do_split(args, trader_argv)
    if args.sensitivity:
        return _do_sensitivity(args, trader_argv)
    return _do_single(args, trader_argv)


def _do_single(args, trader_argv):
    cfg = _build_cfg(args.coin, args.csv, trader_argv)
    trades, _ = _run_one(cfg)
    avg_vol = _avg_vol(args.csv)
    html = generate_html(args.coin, args.csv, cfg, trades, avg_vol)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    m = metrics(trades)
    print(f"✅ dashboard: {args.out} | {args.coin} trades={m['n']} PF={m['pf']:.3f} exp={m['expectancy']:+.2f}")
    return 0


def _do_compare(args, trader_argv):
    coins = [c.strip() for c in args.coins.split(",")]
    rows = []
    for coin in coins:
        csv_path = f"data/{coin.lower()}_1h_lastyear.csv"
        cfg = _build_cfg(coin, csv_path, trader_argv)
        trades, _ = _run_one(cfg)
        m = metrics(trades)
        rows.append((coin, m))
    # comparison HTML
    html = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
    html += "<h1>📊 مقایسهเหรียญ‌ها</h1>"
    html += "<table><tr><th>coin</th><th>trades</th><th>win%</th><th>PF</th><th>expectancy</th><th>total PnL</th></tr>"
    for coin, m in rows:
        pf_cls = "pos" if m["pf"] >= 1 else "neg"
        html += f"<tr><td>{coin}</td><td>{m['n']}</td><td>{m['win_rate']:.1f}%</td>"
        html += f"<td class='{pf_cls}'>{m['pf']:.3f}</td><td>{m['expectancy']:+.2f}</td><td>{m['total_pnl']:+.2f}</td></tr>"
    html += "</table>"
    html += "<div class='legend'>✅ PF≥1 | ❌ PF<1 | ریسک ثابت ۱۰ USDT</div></body></html>"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ comparison dashboard: {args.out}")
    for coin, m in rows:
        print(f"  {coin}: trades={m['n']} PF={m['pf']:.3f}")
    return 0


def _do_split(args, trader_argv):
    """in-sample/out-of-sample split (70/30 chronological)."""
    import tempfile, os
    cfg = _build_cfg(args.coin, args.csv, trader_argv)
    from .data import csv_candles
    candles = csv_candles(cfg)
    n = len(candles)
    split = int(n * 0.7)
    train_path = args.csv.replace(".csv", "_train.csv")
    test_path = args.csv.replace(".csv", "_test.csv")
    for path, cs in [(train_path, candles[:split]), (test_path, candles[split:])]:
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for c in cs:
                w.writerow([c.ts, c.o, c.h, c.l, c.c, c.v])
    split_info = []
    for label, path in [("TRAIN (70%)", train_path), ("TEST (30%)", test_path)]:
        c2 = _build_cfg(args.coin, path, trader_argv)
        c2.run_id = f"dash-split-{label[:6]}"
        trades, _ = _run_one(c2)
        split_info.append((label, metrics(trades)))
    html = generate_html(args.coin, args.csv, cfg, trades, _avg_vol(args.csv), split_info=split_info)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ split dashboard: {args.out}")
    for label, m in split_info:
        v = "✅ real" if m["pf"] >= 1 else "❌ overfit"
        print(f"  {label}: n={m['n']} PF={m['pf']:.3f} → {v}")
    return 0


def _do_sensitivity(args, trader_argv):
    """sweep volume entry threshold — robustness check."""
    cfg = _build_cfg(args.coin, args.csv, trader_argv)
    trades, _ = _run_one(cfg)
    avg_vol = _avg_vol(args.csv)
    sens_rows = []
    for thr in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        c2 = _build_cfg(args.coin, args.csv, trader_argv)
        c2.vol_entry_filter = True
        c2.vol_entry_lo = thr
        c2.vol_entry_hi = 99
        c2.run_id = f"dash-sens-{thr}"
        t2, _ = _run_one(c2)
        m = metrics(t2)
        sens_rows.append((thr, m["n"], m["pf"], m["expectancy"]))
    html = generate_html(args.coin, args.csv, cfg, trades, avg_vol, sens_rows=sens_rows)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ sensitivity dashboard: {args.out}")
    for thr, n, pf, ex in sens_rows:
        print(f"  thr={thr}: n={n} PF={pf:.3f} exp={ex:+.2f}")
    return 0


if __name__ == "__main__":
    import argparse
    main()
