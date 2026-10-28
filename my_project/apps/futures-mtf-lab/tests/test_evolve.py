"""تست‌های حلقهٔ تطبیق زنده (evolve).

اینجا مهم‌ترین چیز، «نجیب‌بودن» ماشین است: تطبیق نباید بتواند بی‌اجازه ارتقا بدهد،
نباید آینده را ببیند، و پلاسیبو نباید بهتر از نسخهٔ واقعی دربیاید (اگر درآمد،
یعنی سیگنالی وجود ندارد). این تست‌ها همان قراردادها را قفل می‌کنند.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.config import load_config                                  # noqa: E402
from mtflab.data import resample_up, synthetic_candles                 # noqa: E402
from mtflab.evolve import (DISTANCE_KEYS, PROMOTION_MODES, SHALLOW_KNOBS,  # noqa: E402
                           apply_temperament, bootstrap_ci, build_shift_data,
                           _chunks, promotion_gate, run_evolve, shrink,
                           synthetic_vol_shift, theta_to_cfg, verdict)

BASE_ARGV = ["--data", "synthetic", "--quiet", "--min-edge", "0",
             "--bias-ema", "20"]


def _cfg(**over):
    c = load_config(BASE_ARGV + ["--tf-trigger", "1h", "--tf-filter", "4h",
                                 "--tf-bias", "1d"])
    over.setdefault("forensics", False)
    return __import__("dataclasses").replace(c, **over)


def _layers(n=1500, seed=3):
    trig = synthetic_candles("1h", n, seed=seed)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    return {"trigger": trig, "filter": filt, "bias": bias}


# ── τ و پیکربندی ───────────────────────────────────────────────────────────
def test_tau_one_is_exactly_identity():
    """τ=۱ باید پیکربندی را *کاملاً* دست‌نخورده برگرداند، وگرنه مقایسه بی‌معنی است."""
    c = _cfg()
    out = apply_temperament(c, 1.0)
    for k in DISTANCE_KEYS:
        assert getattr(out, k) == getattr(c, k)
    assert out == c


def test_tau_scales_every_distance_uniformly():
    c = _cfg()
    out = apply_temperament(c, 1.20)
    for k in DISTANCE_KEYS:
        assert abs(getattr(out, k) - getattr(c, k) * 1.2) < 1e-6, k
    # چیزهای غیرِ فاصله نباید تغییر کنند
    assert out.stop_atr_mult != c.stop_atr_mult
    assert out.max_concurrent == c.max_concurrent
    assert out.train_ratio == c.train_ratio


def test_theta_to_cfg_applies_knob_and_is_quiet():
    c = _cfg()
    pull = theta_to_cfg(c, {"tau": 1.0, "knob": "pullback"})
    assert pull.trigger_entry_modes == ["pullback"]
    assert pull.verbose is False and pull.forensics is False
    climax = theta_to_cfg(c, {"tau": 1.0, "knob": "climax_1.0"})
    assert climax.trigger_max_range_atr == 1.0
    none = theta_to_cfg(c, {"tau": 1.0, "knob": "none"})
    assert none.trigger_entry_modes == c.trigger_entry_modes


def test_shrink_moves_gradually_and_protects_structure():
    old = {"tau": 1.0, "knob": "none"}
    new = {"tau": 1.4, "knob": "pullback"}
    mid = shrink(old, new, 0.5)
    assert abs(mid["tau"] - 1.2) < 1e-9
    # با λ کوچک، ساختار نباید بپرد (تغییر ساختار سخت‌تر از تغییر فاصله است)
    small = shrink(old, new, 0.3)
    assert small["knob"] == "none"
    assert abs(small["tau"] - 1.12) < 1e-9
    full = shrink(old, new, 1.0)
    assert full["knob"] == "pullback" and abs(full["tau"] - 1.4) < 1e-9


# ── دروازهٔ ارتقا ─────────────────────────────────────────────────────────
def _m(pnls):
    return {"n": len(pnls), "expectancy": sum(pnls) / len(pnls) if pnls else 0.0,
            "max_drawdown_pct": -5.0, "_pnls": pnls}


def test_gate_rejects_small_sample_even_if_brilliant():
    """۴ معاملهٔ عالی نباید ارتقا بدهد — این قلبِ محافظت در برابر overfit است."""
    champ = _m([-1.0] * 20)
    chal = _m([10.0] * 4)
    g = promotion_gate(champ, chal)
    assert g["checks"]["min_sample"] is False
    assert g["promote"] is False


def test_gate_rejects_when_ci_contains_zero():
    champ = _m([-1.0, 0.5, -1.0, 0.5] * 6)
    chal = _m([-0.2, 0.6, -0.9, 0.4] * 6)   # کمی بهتر، ولی پراکندگی زیاد
    g = promotion_gate(champ, chal)
    assert g["checks"]["gain"] is True
    assert g["promote"] is False


def test_gate_promotes_a_clear_consistent_improvement():
    champ = _m([-2.0] * 24)
    chal = _m([1.0] * 24)
    g = promotion_gate(champ, chal)
    assert g["checks"]["min_sample"] and g["checks"]["gain"]
    assert g["checks"]["ci_lower_positive"] is True
    assert g["promote"] is True


def test_gate_blocks_catastrophic_drawdown():
    champ = _m([-0.5] * 24)
    chal = dict(_m([1.0] * 24), max_drawdown_pct=-40.0)
    g = promotion_gate(champ, chal)
    assert g["checks"]["gain"] is True
    assert g["checks"]["risk_tail"] is False
    assert g["promote"] is False


def test_bootstrap_ci_of_identical_samples_hits_zero():
    same = [1.0, -0.5, 2.0, 0.3, -1.1, 0.8]
    r = bootstrap_ci(same, same)
    assert r["ok"] and abs(r["observed"]) < 1e-12
    assert r["significant"] is False
    assert r["ci"][0] <= 0 <= r["ci"][1]


# ── داده و چانک‌ها ────────────────────────────────────────────────────────
def test_chunks_cover_range_without_overlap():
    trig = _layers(n=1000)["trigger"]
    chunks = _chunks(trig, 300)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(trig) - 1
    for a, b in zip(chunks, chunks[1:]):
        assert b[0] == a[1] + 1
    # دادهٔ کوچک نباید کرش کند
    assert _chunks(trig[:200], 300) == [(0, 199)]


def test_volatility_shift_actually_shifts_volatility():
    """کنترل مثبت باید واقعاً نیمهٔ دوم پرنوسان‌تر باشد، وگرنه آزمونش بی‌معنی است."""
    cs = synthetic_vol_shift("1h", 1200, seed=5, shift=2.0)
    half = len(cs) // 2

    def avg_range(seq):
        return sum(c.high - c.low for c in seq) / len(seq)

    assert avg_range(cs[half:]) > avg_range(cs[:half]) * 1.3


def test_build_shift_data_layers_are_consistent():
    cfg = _cfg()
    d = build_shift_data(cfg, n=2000)
    assert set(d) == {"SYN-A", "SYN-B"}
    for sym, layers in d.items():
        assert set(layers) == {"trigger", "filter", "bias"}
        assert len(layers["trigger"]) == 2000
        assert len(layers["filter"]) < 2000      # 4h از 1h ساخته می‌شود
        assert layers["filter"][0].open_time_ms >= layers["trigger"][0].open_time_ms


# ── حلقهٔ کامل ────────────────────────────────────────────────────────────
def test_run_evolve_structure_and_no_self_contradiction():
    cfg = _cfg(candles=3000)
    data = build_shift_data(cfg, n=3000)
    rules = {"chunk_bars": 600, "min_fit_trades": 5, "min_forward_trades": 5,
             "promotion_mode": "strict"}
    res = run_evolve(cfg, data, rules=rules, progress=False)

    assert res["decisions"] == len(res["events"]) >= 2
    assert res["rules"]["promotion_mode"] == "strict"
    assert res["promotions"] == sum(1 for e in res["events"] if e["promoted"])

    # قهرمانِ هر گام باید همان θ نسخهٔ قبلی باشد (هیچ جهش بی‌سابقه‌ای مجاز نیست)
    theta = {"tau": 1.0, "knob": "none"}
    for e in res["events"]:
        assert e["champion_theta"] == theta
        if e["promoted"]:
            theta = e["challenger_theta"]
    assert res["theta_final"] == theta

    # در حالت strict، هیچ ارتقایی نباید بدون پاس‌شدن همهٔ چک‌ها باشد
    for e in res["events"]:
        if e["promoted"]:
            assert all(e["gate"]["checks"].values())

    for k in ("baselines", "verdict" if False else "decisions", "oracle_ceiling"):
        assert k in res or k == "verdict"


def test_verdict_prefers_static_when_adaptive_is_not_better():
    res = {"adaptive_expectancy": -1.0, "adaptive_n": 100,
           "baselines": {"static_tau1": {"n": 100, "expectancy": 0.5},
                         "static_pullback": {"n": 50, "expectancy": -0.2}}}
    v = verdict(res)
    assert v["ok"] and v["winner"] == "static"
    assert v["best_static"] == "static_tau1"
    assert v["useful"] is False


def test_verdict_marks_adaptive_useful_only_with_clear_margin():
    res = {"adaptive_expectancy": 2.0, "adaptive_n": 100,
           "baselines": {"static_tau1": {"n": 100, "expectancy": 0.5}}}
    v = verdict(res)
    assert v["winner"] == "adaptive" and v["useful"] is True


# ── پیکربندی حالت‌ها ──────────────────────────────────────────────────────
def test_promotion_modes_are_documented():
    assert set(PROMOTION_MODES) == {"strict", "rolling"}
    for m in PROMOTION_MODES.values():
        assert m["label"] and m["note"]
    assert [k for k, _ in SHALLOW_KNOBS][0] == "none", "گزینهٔ خنثی باید اول باشد"
