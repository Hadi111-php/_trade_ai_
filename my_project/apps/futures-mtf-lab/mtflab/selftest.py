"""خودآزمایی (selftest) — همان چیزی که قبل از هر push باید سبز باشد.

شامل:
1. تست‌های واحد (tests/test_*.py) با تست‌رانر داخلی
2. علی‌بودن موتور روی دادهٔ مصنوعی (prefix invariance)
3. حسابرسی نشتی هم‌ترازی روی دادهٔ واقعی/مصنوعی
4. سلامت فیلتر هزینه (ردِ سیگنال کم‌دامنه)
5. کنترل: نسخهٔ A باید از نسخهٔ C سخت‌گیرانه‌تر باشد (تعداد معامله کمتر)
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from typing import List, Tuple

from .config import MTFConfig
from .data import load_layers, resample_up, synthetic_candles
from .engine import run_backtest
from .fees import FeeConfig, passes_cost_filter, round_trip_cost_pct


def _run_unit_tests() -> Tuple[bool, str]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = os.path.join(root, "tests", "run_tests.py")
    if not os.path.exists(runner):
        return False, "tests/run_tests.py پیدا نشد"
    import subprocess
    p = subprocess.run([sys.executable, runner], cwd=root, capture_output=True, text=True)
    tail = "\n".join(p.stdout.strip().splitlines()[-4:])
    return p.returncode == 0, tail


def _causality_check() -> Tuple[bool, str]:
    # دادهٔ مصنوعی فقط برای «تولید سیگنال» است؛ اعداد سود/زیانش معنا ندارد.
    # bias_ema_period کوچک تا warmup در طول دادهٔ مصنوعی جا شود.
    cfg = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                    candles=2000, seed=17, verbose=False, forensics=False,
                    alignment_version="A", min_edge_multiplier=0.0,
                    bias_ema_period=20, bias_slope_min_pct=0.0,
                    filter_slope_min_pct=0.0, filter_confirm_bars=1)
    trig = synthetic_candles("1h", 2000, seed=17)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    full = run_backtest(replace(cfg), {"trigger": trig, "filter": filt, "bias": bias})
    if not full["trades"]:
        return False, "سیگنالی تولید نشد → تست علی‌بودن بی‌اثبات است (تنظیمات دادهٔ تست را ببین)"
    cut = full["trades"][-1]["ts"]
    sub = {"trigger": [c for c in trig if c.open_time_ms <= cut],
           "filter": [c for c in filt if c.open_time_ms <= cut],
           "bias": [c for c in bias if c.open_time_ms <= cut]}
    pref = run_backtest(replace(cfg), sub)
    a = [(t["ts"], t["side"], t["entry"]) for t in full["trades"][:-1]]
    b = [(t["ts"], t["side"], t["entry"]) for t in pref["trades"][:-1]]
    ok = all(x == y for x, y in zip(a, b))
    return ok, f"{len(a)} معامله روی دادهٔ کامل vs prefix → {'یکسان' if ok else 'متفاوت'}"


def _leakage_check() -> Tuple[bool, str]:
    from .alignment import align_multi_timeframe, leakage_audit
    trig = synthetic_candles("1h", 500, seed=21)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    bars = align_multi_timeframe(trig, 60, filt, 240, bias, 1440)
    audit = leakage_audit(bars, 240, 1440)
    return audit["clean"], f"{audit['bars_checked']} کندل بررسی شد، {audit['violations']} نقض"


def _cost_filter_check() -> Tuple[bool, str]:
    fee = FeeConfig.from_bps(5.5, 0.02)
    cost = round_trip_cost_pct(fee)
    ok = (not passes_cost_filter(cost * 0.5, fee, 1.5)) and passes_cost_filter(cost * 3, fee, 1.5)
    return ok, f"هزینهٔ رفت‌وبرگشت {cost:.4f}% · حداقل edge لازم {cost*1.5:.4f}%"


def _strictness_check() -> Tuple[bool, str]:
    """کنترل رفتاری: A (سخت‌گیرانه) باید <= C (فقط فیلتر) معامله کند."""
    cfg = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h", tf_bias="1d",
                    candles=3000, seed=9, verbose=False, forensics=False,
                    min_edge_multiplier=0.0, filter_confirm_bars=1,
                    bias_ema_period=20, bias_slope_min_pct=0.0,
                    filter_slope_min_pct=0.0)
    layers, _ = load_layers(cfg)
    a = run_backtest(replace(cfg, alignment_version="A"), layers)["summary"]
    c = run_backtest(replace(cfg, alignment_version="C"), layers)["summary"]
    b = run_backtest(replace(cfg, alignment_version="B", score_min=0.55), layers)["summary"]
    ok = a["trades"] <= c["trades"]
    return ok, f"A={a['trades']} معامله، B={b['trades']}، C={c['trades']}"


def run_selftest() -> int:
    checks: List[Tuple[str, Tuple[bool, str]]] = []
    t0 = time.time()
    print("=" * 70)
    print("  🧪 خودآزمایی Futures MTF Lab")
    print("=" * 70)

    for name, fn in [("تست‌های واحد (alignment/fees/pitfalls)", _run_unit_tests),
                     ("علی‌بودن موتور (prefix invariance)", _causality_check),
                     ("حسابرسی نشتی هم‌ترازی", _leakage_check),
                     ("فیلتر هزینه (edge ≥ 1.5×)", _cost_filter_check),
                     ("کنترل سخت‌گیری نسخه‌های A/B/C", _strictness_check)]:
        try:
            res = fn()
        except Exception as e:                          # noqa: BLE001
            res = (False, f"خطا: {e}")
        checks.append((name, res))
        print(f"{'✅ PASS' if res[0] else '❌ FAIL'}  {name}\n         {res[1]}")

    failed = [n for n, r in checks if not r[0]]
    print("-" * 70)
    print(f"نتیجه: {len(checks) - len(failed)}/{len(checks)} PASS · {time.time()-t0:.1f}s")
    if failed:
        print("❌ موارد شکست‌خورده: " + "، ".join(failed))
        return 1
    print("✅ همهٔ خودآزمایی‌ها پاس شدند — آمادهٔ commit.")
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
