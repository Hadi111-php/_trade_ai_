"""حالت خودکار (AUTO) — فقط PAPER / شبیه‌سازی. هرگز سفارش واقعی نمی‌گذارد.

- به‌صورت پیش‌فرض «محدود» است (--max-ticks) تا بی‌پایان اجرا نشود.
- کلید خاموشی: Ctrl-C یا تمام شدن max-ticks؛ هیچ daemon پنهانی ساخته نمی‌شود.
- LIVE trading عمداً پیاده‌سازی نشده؛ --live فقط خطای صریح می‌دهد.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from typing import List, Optional

import json as _json
import urllib.request as _urllib

from . import __version__
from .config import LabConfig
from .data import Candle, csv_candles
from .indicators import build_snapshot
from .logger import JsonlWriter, signal_to_record
from .models import Signal, build_models
from .runner import DEFAULT_PARAMS
from .validation import calibration, metrics, rank_methods

MAXBUF = 800


class SyntheticStream:
    """تولید جریانی کندل با رژیم متغیر (همان منطق synthetic_candles)."""

    def __init__(self, seed: int, start: float = 30000.0):
        self.rng = random.Random(seed)
        self.price = start
        self.ts = 1_700_000_000_000
        self.remain = 0
        self.drift = 0.0
        self.mr = 0.0
        self.anchor = start
        self.regime = "chop"

    def next(self) -> Candle:
        rng = self.rng
        if self.remain <= 0:
            self.regime = rng.choice(["trend", "trend", "meanrev", "chop", "chop"])
            self.remain = rng.randint(80, 300)
            self.anchor = self.price
            if self.regime == "trend":
                self.drift = rng.choice([-1, 1]) * rng.uniform(0.00004, 0.0002)
                self.mr = 0.0
            elif self.regime == "meanrev":
                self.drift, self.mr = 0.0, rng.uniform(0.05, 0.15)
            else:
                self.drift, self.mr = 0.0, 0.0
        self.remain -= 1
        vol = 0.0006 * rng.uniform(0.6, 1.8)
        shock = rng.gauss(0, 8 * vol) if rng.random() < 0.01 else 0.0
        ret = self.drift + rng.gauss(0, vol) + shock
        if self.regime == "meanrev":
            ret -= self.mr * (self.price - self.anchor) / self.price
        o = self.price
        c = o * math.exp(ret)
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol)) * 0.5)
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol)) * 0.5)
        v = rng.uniform(50, 200)
        self.ts += 60_000
        candle = Candle(self.ts, round(o, 2), round(hi, 2), round(lo, 2),
                        round(c, 2), round(v, 2))
        self.price = c
        return candle


def fetch_last_closed(cfg: LabConfig) -> Optional[Candle]:
    """آخر کندلِ «بسته» (Binance یا Bybit). فقط خواندنی."""
    if cfg.data_mode == "bybit":
        from .data import bybit_last_closed
        return bybit_last_closed(cfg)
    url = (f"{cfg.binance_url}?symbol={cfg.symbol}&interval={cfg.timeframe}&limit=3")
    with _urllib.urlopen(url, timeout=15) as resp:
        raw = _json.load(resp)
    if len(raw) < 2:
        return None
    r = raw[-2]
    return Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                  float(r[4]), float(r[5]))


def run_auto(cfg: LabConfig) -> int:
    if getattr(cfg, "live", False):
        print("❌ LIVE trading عمداً پیاده‌سازی نشده است. این لب فقط PAPER است. "
              "تا اعتبارسنجی آماری روی دادهٔ واقعی، فعال‌سازی LIVE توصیه نمی‌شود.")
        return 2

    if cfg.light:
        cfg.interval = max(cfg.interval, 30.0)   # درخواست شبکه کمتر
    maxbuf = 300 if cfg.light else MAXBUF        # محاسبهٔ سبک‌تر

    import os
    os.makedirs(cfg.out_dir, exist_ok=True)
    sw = JsonlWriter(os.path.join(cfg.out_dir, f"signals_{cfg.run_id}.jsonl"))
    ow = JsonlWriter(os.path.join(cfg.out_dir, f"outcomes_{cfg.run_id}.jsonl"))

    engine = None
    tw = None
    if cfg.trade:
        from .engine import RiskEngine, RiskConfig
        rc = RiskConfig(trade_size_quote=cfg.trade_size_quote, leverage=cfg.leverage,
                        max_concurrent=cfg.max_concurrent, cb_losses=cfg.cb_losses,
                        stop_pct=cfg.stop_pct, trail_pct=cfg.trail_pct,
                        adaptive=cfg.adaptive, stop_atr_mult=cfg.stop_atr_mult,
                        trail_atr_mult=cfg.trail_atr_mult)
        tw = JsonlWriter(os.path.join(cfg.out_dir, f"trades_{cfg.run_id}.jsonl"))
        engine = RiskEngine(rc, cfg.fee_bps, tw)
        print(f"⚙️  موتور ریسک PAPER فعال: size={rc.trade_size_quote} lev={rc.leverage} "
              f"max={rc.max_concurrent} cb={rc.cb_losses} stop={rc.stop_pct} trail={rc.trail_pct}")

    params = dict(DEFAULT_PARAMS)
    params["model_version"] = __version__
    seed = cfg.seeds[0] if cfg.seeds else 42
    models = build_models(params, seed)
    from collections import defaultdict
    last_fire = defaultdict(lambda: -10**9)

    buf: List[Candle] = []
    pending: List[Signal] = []
    outcomes_all: List[dict] = []
    per_model = defaultdict(list)

    # منبع جریان
    stream = None
    csv_rows = None
    if cfg.data_mode == "synthetic":
        stream = SyntheticStream(seed)
    elif cfg.data_mode == "csv":
        csv_rows = iter(csv_candles(cfg))

    fee_frac = 2 * cfg.fee_bps / 10_000
    h = cfg.horizon
    tick = 0

    def log_signal(sig: Signal):
        sw.write(signal_to_record(sig, cfg, seed))
        arrow = "🟢LONG " if sig.direction == 1 else "🔴SHORT"
        print(f"[{tick:4d}] SIGNAL {arrow} {sig.model_id:18s} "
              f"conf={sig.confidence:.2f} px={sig.entry_price} ({sig.reason})")

    while tick < cfg.max_ticks:
        # کندل بعدی
        if cfg.data_mode == "synthetic":
            buf.append(stream.next())
        elif cfg.data_mode == "csv":
            try:
                buf.append(next(csv_rows))
            except StopIteration:
                print("پایان فایل CSV.")
                break
        else:  # binance: فقط کندل بسته؛ درخواست سبک
            try:
                closed = fetch_last_closed(cfg)
            except Exception as e:
                print(f"خطای شبکه: {e}")
                closed = None
            if closed is None or (buf and closed.ts == buf[-1].ts):
                time.sleep(max(cfg.interval, 1.0))
                continue
            buf.append(closed)

        if len(buf) > maxbuf:
            buf.pop(0)
        tick += 1

        snaps = build_snapshot(buf, params)
        i = len(buf) - 1
        snap = snaps[i]
        if snap is None:
            continue
        prev = snaps[i - 1] if i > 0 else None
        price = buf[i].c

        votes = []
        for m in models:
            if m.id == "random_control":
                continue
            res = m.maybe_signal(i, buf[i].ts, snap, prev, price)
            if res:
                votes.append((m.id, m.family, res[0], res[1], res[2]))
                if i - last_fire[m.id] >= cfg.cooldown:
                    last_fire[m.id] = i
                    sig = Signal(i, buf[i].ts, m.id, m.family, res[0], res[1],
                                 res[2], price, snap, params)
                    log_signal(sig)
                    pending.append(sig)
                    if engine:
                        engine.on_signal(res[0], price, buf[i].ts, m.id, res[1],
                                         snap["atr_pct"])

        for k in range(cfg.agree_min, len(votes) + 1):
            pos = [v for v in votes if v[2] == 1]
            neg = [v for v in votes if v[2] == -1]
            d = conf = 0
            if len(pos) >= k and len(pos) > len(neg):
                d, conf = 1, sum(v[3] for v in pos) / len(pos)
            elif len(neg) >= k and len(neg) > len(pos):
                d, conf = -1, sum(v[3] for v in neg) / len(neg)
            mid = f"consensus_k{k}"
            if d and i - last_fire[mid] >= cfg.cooldown:
                last_fire[mid] = i
                sig = Signal(i, buf[i].ts, mid, "ensemble", d, conf,
                             "agreement", price, snap, params)
                log_signal(sig)
                pending.append(sig)
                if engine:
                    engine.on_signal(d, price, buf[i].ts, mid, conf, snap["atr_pct"])

        # ارزیابی سیگنال‌هایی که افقشان رسیده
        still = []
        for sig in pending:
            age = i - sig.i
            if age >= h:
                entry = sig.entry_price
                path = [sig.direction * (buf[j].c - entry) / entry
                        for j in range(sig.i + 1, i + 1)]
                rg, rn = path[-1], path[-1] - fee_frac
                o = {"signal_i": sig.i, "model_id": sig.model_id,
                     "direction": sig.direction, "confidence": sig.confidence,
                     "ret_gross_bps": round(rg * 10_000, 2),
                     "ret_net_bps": round(rn * 10_000, 2),
                     "hit_gross": rg > 0, "hit_net": rn > 0,
                     "mae_bps": round(min(min(path), 0) * 10_000, 2),
                     "mfe_bps": round(max(max(path), 0) * 10_000, 2)}
                ow.write({**o, "run_id": cfg.run_id, "seed": seed,
                          "symbol": cfg.symbol, "data_mode": cfg.data_mode})
                outcomes_all.append(o)
                per_model[sig.model_id].append(o)
            else:
                still.append(sig)
        pending = still

        if engine:
            engine.tick(price, buf[i].ts)

    sw.close()
    ow.close()
    if tw:
        tw.close()
    if engine:
        s = engine.summary()
        print(f"\n⚙️  خلاصهٔ موتور ریسک: trades={s['trades']} wins={s['wins']} "
              f"losses={s['losses']} sum_net={s['sum_net_pct']:+.3f}% "
              f"halted={s['halted']} open={s['still_open']}")

    # گزارش قابل‌نمایش برای داشبورد — با برچسب منبع داده (واقعی/مصنوعی)
    write_auto_report(cfg, per_model)


def _label(cfg: LabConfig) -> str:
    if cfg.data_mode == "binance":
        return ("دادهٔ واقعی Binance (فقط خواندنی) — PAPER؛ هنوز سود واقعی نیست")
    if cfg.data_mode == "bybit":
        return ("دادهٔ واقعی Bybit (فقط خواندنی) — PAPER؛ هنوز سود واقعی نیست")
    if cfg.data_mode == "csv":
        return "بازپخش دادهٔ CSV واقعی — PAPER؛ هنوز سود واقعی نیست"
    return "دادهٔ مصنوعی — فقط اعتبارسنجی مکانیزم؛ NOT real market"


def write_auto_report(cfg: LabConfig, per_method: dict) -> str:
    pooled_metrics = {mid: metrics(ocs) for mid, ocs in per_method.items()
                      if ocs}
    ranking = rank_methods(pooled_metrics)
    all_out = [o for ocs in per_method.values() for o in ocs]
    calib = calibration([o for o in all_out
                         if o["model_id"] != "random_control"
                         and not o["model_id"].startswith("consensus")])
    report = {
        "run_id": cfg.run_id, "lab_version": __version__,
        "config": cfg.to_dict(), "data_mode": cfg.data_mode,
        "label": _label(cfg),
        "total_signals": len(all_out),
        "pooled_metrics": pooled_metrics,
        "ranking_by_net_expectancy": ranking,
        "control": pooled_metrics.get("random_control", {}),
        "calibration_conf_vs_hit": calib,
        "per_seed": {},
        "files": {},
    }
    rpath = os.path.join(cfg.out_dir, f"report_{cfg.run_id}.json")
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    from .report import write_markdown
    write_markdown(report, os.path.join(cfg.out_dir, f"report_{cfg.run_id}.md"))
    print(f"📄 گزارش نوشته شد: {rpath}  [{cfg.data_mode}]")
    return rpath
