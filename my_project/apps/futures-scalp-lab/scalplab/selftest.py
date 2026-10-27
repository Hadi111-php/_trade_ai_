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
    _, per = run_one_seed(cfg, 1, sw, ow)
    sw.close(); ow.close()
    m = metrics(per.get("random_control", []))
    hg = m.get("hit_gross", 0.5)
    ok = m["n"] >= 50 and 0.42 <= hg <= 0.58
    print(f"  control: n={m['n']} hit_gross={hg:.3f} (باید ~0.5)")
    return ok


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
    ok3 = _test_engine()
    print("risk engine (max4/trail/stop/cb):", "PASS" if ok3 else "FAIL")
    ok4 = _test_regimes()
    print("regimes + trader discipline:", "PASS" if ok4 else "FAIL")
    all_ok = ok1 and ok2 and ok3 and ok4
    print("SELFTEST:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1
