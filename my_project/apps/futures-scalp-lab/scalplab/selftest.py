"""خودآزمایی: (۱) علی بودن اندیکاتورها، (۲) سلامت خط پایهٔ تصادفی.

اجرا: python -m scalplab selftest
"""
from __future__ import annotations

import tempfile

from .config import LabConfig
from .data import synthetic_candles
from .indicators import build_snapshot
from .logger import JsonlWriter
from .runner import DEFAULT_PARAMS, run_one_seed
from .validation import metrics


def _test_causality() -> bool:
    cfg = LabConfig(candles=600)
    candles = synthetic_candles(cfg, seed=1)
    full = build_snapshot(candles, dict(DEFAULT_PARAMS))
    prefix = build_snapshot(candles[:400], dict(DEFAULT_PARAMS))
    for i in range(400):
        a, b = full[i], prefix[i]
        if (a is None) != (b is None):
            print(f"  FAIL causality@{i}: warmup mismatch")
            return False
        if a is None:
            continue
        for key in a:
            if a[key] is None or b[key] is None:
                if a[key] is not b[key]:
                    print(f"  FAIL causality@{i}.{key}")
                    return False
            elif abs(a[key] - b[key]) > 1e-6:
                print(f"  FAIL causality@{i}.{key}: {a[key]} != {b[key]}")
                return False
    return True


def _test_control() -> bool:
    cfg = LabConfig(candles=2000, seeds=[1], horizon=6, out_dir=tempfile.mkdtemp())
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as s, \
         tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as o:
        sw, ow = JsonlWriter(s.name), JsonlWriter(o.name)
    _, per, _ = run_one_seed(cfg, 1, sw, ow)
    sw.close(); ow.close()
    m = metrics(per.get("random_control", []))
    hg = m.get("hit_gross", 0.5)
    ok = m["n"] >= 50 and 0.42 <= hg <= 0.58
    print(f"  control: n={m['n']} hit_gross={hg:.3f} (باید ~0.5)")
    return ok


def _test_adaptive_hunter() -> bool:
    from .hunter import AdaptiveHunter
    from .data import Candle

    candles = [Candle(ts=i, o=100, h=101 + i, l=99, c=100 + i, v=1) for i in range(4)]
    hunter = AdaptiveHunter(["ema_cross"])
    initial = hunter.weights["ema_cross"]
    hunter.queue(0, "ema_cross", 1, 100, horizon=2, fee_frac=0.001,
                 candle_count=len(candles))
    hunter.advance(0, candles)
    hunter.advance(1, candles)
    if hunter.weights["ema_cross"] != initial or hunter.updates:
        print("  FAIL hunter updated before outcome matured")
        return False
    updates = hunter.advance(2, candles)
    if len(updates) != 1 or updates[0]["updated_at_i"] < updates[0]["outcome_i"]:
        print(f"  FAIL hunter maturity audit: {updates}")
        return False

    # Enabling Hunter must not change the base models or random control.
    cfg = LabConfig(candles=500, seeds=[2], horizon=5, cooldown=4,
                    adaptive_hunter=False, out_dir=tempfile.mkdtemp())
    def run(enabled):
        cfg.adaptive_hunter = enabled
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as s:
            with tempfile.NamedTemporaryFile(suffix=".jsonl") as o:
                return run_one_seed(cfg, 2, JsonlWriter(s.name), JsonlWriter(o.name))
    _, baseline, _ = run(False)
    _, with_hunter, diag = run(True)
    if any(baseline.get(k) != with_hunter.get(k)
           for k in baseline if k != "adaptive_hunter"):
        print("  FAIL hunter changed baseline/control outcomes")
        return False
    if "adaptive_hunter" not in with_hunter or not diag["updates"]:
        print("  FAIL hunter did not produce scored signals / delayed updates")
        return False
    if any(event["updated_at_i"] < event["outcome_i"] for event in diag["updates"]):
        print("  FAIL hunter causality audit timestamps")
        return False
    return True


def _test_engine() -> bool:
    from .engine import RiskEngine, RiskConfig
    ok = True

    # ۱) سقف ۴ معامله همزمان
    e = RiskEngine(RiskConfig(max_concurrent=4), fee_bps=0)
    for k in range(6):
        e.on_signal(1, 100.0, k, f"m{k}", 0.6)
    if len(e.positions) != 4:
        print(f"  FAIL max_concurrent: {len(e.positions)} != 4"); ok = False

    # ۲) trailing stop سود را قفل می‌کند
    e = RiskEngine(RiskConfig(stop_pct=0.005, trail_pct=0.003), fee_bps=0)
    e.on_signal(1, 100.0, 0, "t", 0.7)
    for p in (101, 105, 110, 109.0):
        e.tick(p, p)
    if not e.closed or e.closed[0]["net_pct"] <= 0 or "trail" not in e.closed[0]["reason"]:
        print(f"  FAIL trailing: {e.closed}"); ok = False

    # ۳) stop اولیه ضرر را می‌بندد
    e = RiskEngine(RiskConfig(stop_pct=0.005), fee_bps=0)
    e.on_signal(1, 100.0, 0, "s", 0.6)
    e.tick(99.0, 1)
    if not e.closed or not e.closed[0]["loss"]:
        print(f"  FAIL stop-loss: {e.closed}"); ok = False

    # ۴) circuit breaker: ۲ ضرر → بستن همه + توقف
    e = RiskEngine(RiskConfig(cb_losses=2, stop_pct=0.005, max_concurrent=4), fee_bps=0)
    e.on_signal(1, 100.0, 0, "a", 0.6)
    e.on_signal(1, 100.0, 1, "b", 0.6)
    e.tick(99.0, 2)          # هر دو ضرر
    if not e.halted or e.positions:
        print(f"  FAIL cb: halted={e.halted} open={len(e.positions)}"); ok = False
    e.on_signal(1, 100.0, 3, "c", 0.6)   # بعد از halt باید reject شود
    if e.positions:
        print("  FAIL cb reject: position opened after halt"); ok = False

    return ok


def _test_regimes() -> bool:
    """تشخیص ۳ حالت روند روی داده مصنوعی، و اینکه تریدر با روند موافق معامله کند."""
    from .regimes import compute_regimes
    from .trader_brain import TraderBrain, TraderConfig
    cfg = LabConfig(candles=2000)
    candles = synthetic_candles(cfg, seed=5)
    regs = compute_regimes(candles, {})
    names = {r["regime"] for r in regs if r}
    for want in ("uptrend", "downtrend", "sideways"):
        if want not in names:
            print(f"  FAIL regime: {want} پیدا نشد")
            return False

    # تریدر هرگز برخلاف روند معامله نمی‌کند
    tc = TraderConfig(symbol="BTCUSDT", data_mode="synthetic")
    brain = TraderBrain(tc)
    from .runner import DEFAULT_PARAMS
    from .indicators import build_snapshot
    snaps = build_snapshot(candles, dict(DEFAULT_PARAMS))
    bad = 0
    for i, r in enumerate(regs):
        if r is None or snaps[i] is None:
            continue
        d = brain.decide(candles, r, snaps[i], i, candles[i].ts)
        if d["action"] == "ENTER":
            bias = {"uptrend": 1, "downtrend": -1, "sideways": 0}[r["regime"]]
            if bias == 0 and r["regime"] == "sideways" and not tc.range_trade:
                continue  # رنج و صبر — انتظار HOLD/WAIT
            if bias != 0 and d["direction"] != bias:
                bad += 1
    if bad:
        print(f"  FAIL trader: {bad} معامله برخلاف روند")
        return False
    return True


def run_selftest() -> int:
    ok1 = _test_causality()
    print("causality (no lookahead):", "PASS" if ok1 else "FAIL")
    ok2 = _test_control()
    print("random control sanity:", "PASS" if ok2 else "FAIL")
    ok_hunter = _test_adaptive_hunter()
    print("adaptive hunter (delayed labels / baseline parity):", "PASS" if ok_hunter else "FAIL")
    ok3 = _test_engine()
    print("risk engine (max4/trail/stop/cb):", "PASS" if ok3 else "FAIL")
    ok4 = _test_regimes()
    print("regimes + trader discipline:", "PASS" if ok4 else "FAIL")
    all_ok = ok1 and ok2 and ok_hunter and ok3 and ok4
    print("SELFTEST:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1
