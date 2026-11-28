"""تست‌های لایهٔ تشخیص (diagnose).

چرا این تست‌ها لازم‌اند: گزارش تشخیص، مبنای «تصمیم» است. اگر خودِ ابزار
اشتباه اندازه بگیرد، تحلیل هم اشتباه می‌شود. پس دست‌کم سه چیز را قفل می‌کنیم:
1. خروجی‌های diagnose ساختار ثابت داشته باشند (کلیدهای گزارش موجود باشند)
2. آزمون فلات، «قله» و «فلات» را از هم تشخیص بدهد
3. گزارش مارک‌داون واقعاً روی دیسک نوشته شود و همهٔ بخش‌های اصلی را داشته باشد
"""
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.config import MTFConfig                                     # noqa: E402
from mtflab.data import resample_up, synthetic_candles                 # noqa: E402
from mtflab.diagnose import (diagnose, leak_map, run_setup_experiments,  # noqa: E402
                             run_setup_sweep, setup_significance,
                             write_diagnosis_report)
from mtflab.engine import run_backtest                                 # noqa: E402


def _layers(n=2400, seed=7):
    trig = synthetic_candles("1h", n, seed=seed)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    return {"trigger": trig, "filter": filt, "bias": bias}


def _cfg(**over):
    base = MTFConfig(data_mode="synthetic", tf_trigger="1h", tf_filter="4h",
                     tf_bias="1d", candles=2400, seed=7, verbose=False,
                     forensics=False, min_edge_multiplier=0.0,
                     filter_confirm_bars=1, bias_ema_period=20,
                     bias_slope_min_pct=0.0, filter_slope_min_pct=0.0)
    return replace(base, **over) if over else base


def test_diagnose_has_all_report_keys():
    cfg, layers = _cfg(), _layers()
    d = diagnose(cfg, layers, progress=False)
    for k in ("base", "autopsy", "policies", "setups", "leaks",
              "autopsy_rows", "policy_significance"):
        assert k in d, f"کلید {k} در خروجی diagnose نیست"
    assert d["base"]["summary"]["trades"] >= 0
    for k in ("capture_ratio_pct", "stop_premature_pct",
              "losers_were_once_green_pct", "by_group"):
        assert k in d["autopsy"], f"کلید {k} در کالبدشکافی نیست"


def test_setup_experiments_shape_and_robust_rule():
    cfg, layers = _cfg(), _layers()
    su = run_setup_experiments(cfg, layers)
    assert su["n_experiments"] == len(su["rows"]) >= 5
    assert su["rows"][0]["id"] == "base"
    for r in su["rows"]:
        for k in ("full", "train", "oos", "gain_full", "gain_oos", "robust"):
            assert k in r, f"کلید {k} در ردیف آزمایش نیست"
        # قاعدهٔ پایداری: مثبت‌بودن در هر دو بازه با نمونهٔ کافی
        expected = (r["train"]["n"] >= 5 and r["oos"]["n"] >= 5
                    and r["train"]["expectancy"] > 0 and r["oos"]["expectancy"] > 0)
        assert r["robust"] == expected
    # پایه نسبت به خودش صفر بهبود دارد
    assert abs(su["rows"][0]["gain_full"]) < 1e-9


def test_plateau_detection_distinguishes_spike_from_flat():
    """نقشهٔ آزمون فلات باید «قلهٔ تنها» را از «فلات» جدا کند."""
    cfg, layers = _cfg(), _layers()
    axes = run_setup_sweep(cfg, layers)
    assert len(axes) == 4
    for ax in axes:
        assert ax["of"] == len(ax["points"]) >= 4
        assert 0 <= ax["positive"] <= ax["of"]
        assert ax["plateau_len"] <= ax["of"]
        pos = [p["exp"] > 0 for p in ax["points"]]
        longest, cur = 0, 0
        for flag in pos:
            cur = cur + 1 if flag else 0
            longest = max(longest, cur)
        assert longest == ax["plateau_len"], "محاسبهٔ طول فلات اشتباه است"
        if ax["plateau_len"] >= 3 and ax["positive"] >= 3:
            assert "فلات" in ax["verdict"]
        else:
            assert "قله" in ax["verdict"]


def test_leak_map_buckets_are_complete_and_sum_to_trades():
    """همهٔ معاملات باید دقیقاً در یک سبد بیفتند (وگرنه نقشهٔ نشت گمراه‌کننده است)."""
    cfg, layers = _cfg(), _layers()
    res = run_backtest(replace(cfg, run_id=""), layers)
    lk = leak_map(res, cfg)
    n_trades = res["summary"]["trades"]
    for name in ("trigger_mode", "regime", "side", "bars_held",
                 "volatility_atr_pct"):
        rows = lk["buckets"].get(name, [])
        assert rows, f"سبد {name} خالی است"
        assert sum(r["n"] for r in rows) == n_trades, (
            f"سبد {name}: مجموع {sum(r['n'] for r in rows)} != {n_trades} معامله")
    # سبدهای بار-نگه‌داری باید صعودی و بدون همپوشانی باشند
    keys = [r["key"] for r in lk["buckets"]["bars_held"]]
    assert keys == sorted(keys, key=lambda k: int(k.split("-")[0].rstrip("+")))


def test_significance_returns_ci_or_honest_note():
    cfg, layers = _cfg(), _layers()
    su = run_setup_experiments(cfg, layers)
    sig = setup_significance(cfg, layers, su)
    assert isinstance(sig, dict)
    for k, v in sig.items():
        assert "note" in v, f"خروجی معناداری {k} یادداشت ندارد"
        if v.get("ok"):
            lo, hi = v["ci95"]
            assert lo <= hi
            assert isinstance(v["significant"], bool)


def test_report_written_with_all_sections():
    cfg, layers = _cfg(), _layers()
    d = diagnose(cfg, layers, progress=False)
    d["setup_significance"] = setup_significance(cfg, layers, d["setups"])
    sweeps = run_setup_sweep(cfg, layers)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "sub", "diagnosis.md")
        path = write_diagnosis_report(d, cfg, out, sweeps=sweeps)
        assert path == out and os.path.exists(out)
        text = open(out, encoding="utf-8").read()
        for marker in ("## ۱)", "## ۲)", "## ۳)", "## ۴)", "## ۵)",
                       "## ۶)", "## ۷)", "## ۸)", "## ۹)", "## ۱۰)"):
            assert marker in text, f"بخش {marker} در گزارش نیست"
        assert "سود شناور" in text
        assert "توصیهٔ معاملاتی نیست" in text
        assert text.count("|---") >= 3, "جدول‌های مارک‌داون ساخته نشده‌اند"
