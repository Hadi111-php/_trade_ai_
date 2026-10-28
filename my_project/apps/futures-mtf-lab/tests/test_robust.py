"""تست‌های «آزمون بقا» + پریست + ماتریس ورود×خروج.

اینجا سه چیز قفل می‌شود:
1. پریست‌ها فقط پارامتر عوض می‌کنند و CLI همیشه برنده است (قابل پیش‌بینی بودن)
2. ریاضیات آزمون علامت و تقسیم پنجره‌ها درست است (زیربنای حکم «بقا»)
3. قاعدهٔ بقا واقعاً می‌تواند شکست بخورد (تست منفی: نباید همیشه «موفق» بدهد)
"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.config import PRESETS, load_config                        # noqa: E402
from mtflab.data import resample_up, synthetic_candles               # noqa: E402
from mtflab.diagnose import run_policy_matrix                        # noqa: E402
from mtflab.robust import (layers_for_symbol, run_robust, sign_test_p,  # noqa: E402
                           split_windows)

BASE_ARGV = ["--data", "synthetic", "--quiet"]


def _layers(n=2400, seed=7):
    trig = synthetic_candles("1h", n, seed=seed)
    filt, _ = resample_up(trig, "1h", "4h")
    bias, _ = resample_up(trig, "1h", "1d")
    return {"trigger": trig, "filter": filt, "bias": bias}


def _cfg(**over):
    base = load_config(BASE_ARGV + ["--tf-trigger", "1h", "--tf-filter", "4h",
                                    "--tf-bias", "1d", "--bias-ema", "20",
                                    "--min-edge", "0"])
    # این‌ها فلگ CLI ندارند؛ فقط از راه کانفیگ قابل تغییرند
    base = replace(base, forensics=False, filter_confirm_bars=1,
                   bias_slope_min_pct=0.0, filter_slope_min_pct=0.0)
    return replace(base, **over) if over else base


# ── پریست‌ها ────────────────────────────────────────────────────────────────
def test_preset_applies_and_cli_wins():
    a = load_config(BASE_ARGV + ["--preset", "entry_quality"])
    assert a.preset == "entry_quality"
    for k, v in PRESETS["entry_quality"].items():
        assert getattr(a, k) == v

    b = load_config(BASE_ARGV + ["--preset", "entry_quality",
                                 "--entry-modes", "pullback", "breakout",
                                 "--max-range-atr", "2.5"])
    assert b.trigger_entry_modes == ["pullback", "breakout"]
    assert b.trigger_max_range_atr == 2.5


def test_default_preset_is_neutral():
    c = load_config(BASE_ARGV)
    assert c.preset == "base"
    assert PRESETS["base"] == {}, "پریست base باید خالی باشد تا مقایسه بی‌طرف بماند"


def test_preset_lists_are_not_shared_between_configs():
    """اگر لیست‌ها بین دو کانفیگ مشترک باشند، یک تغییر در یکی دیگری را خراب می‌کند."""
    a = load_config(BASE_ARGV + ["--preset", "entry_quality"])
    a.trigger_entry_modes.append("breakout")
    b = load_config(BASE_ARGV + ["--preset", "entry_quality"])
    assert b.trigger_entry_modes == ["pullback"]
    assert PRESETS["entry_quality"]["trigger_entry_modes"] == ["pullback"]


# ── ماتریس ورود × خروج ────────────────────────────────────────────────────
def test_policy_matrix_covers_both_entries_and_is_internally_consistent():
    cfg = _cfg(min_edge_multiplier=0.0)
    layers = _layers()
    mx = run_policy_matrix(cfg, layers, policy_ids=["base", "no_trail", "trail_tight"])
    assert set(mx["cells"]) == {"base", "entry_quality"}
    for eid, row in mx["cells"].items():
        assert len(row) == 3
        for pid, cell in row.items():
            for k in ("label", "full", "train", "oos", "robust"):
                assert k in cell
            expected = (cell["train"]["n"] >= 5 and cell["oos"]["n"] >= 5
                        and cell["train"]["expectancy"] > 0
                        and cell["oos"]["expectancy"] > 0)
            assert cell["robust"] == expected
    # بهترین سیاست باید واقعاً بیشترین expectancy را داشته باشد
    for eid, sm in mx["summary"].items():
        best = max(mx["cells"][eid], key=lambda p: mx["cells"][eid][p]["full"]["expectancy"])
        assert sm["best_policy"] == best
    v = mx["verdict"]
    assert v is not None and isinstance(v["trail_helps_again"], bool)


# ── آزمون علامت و پنجره‌ها ─────────────────────────────────────────────────
def test_sign_test_exact_values():
    assert sign_test_p(5, 5) == 0.0625      # همه برد، ولی n کوچک → معنادار نیست
    assert sign_test_p(0, 5) == 0.0625      # دوطرفه
    assert sign_test_p(4, 4) == 0.125
    assert sign_test_p(2, 4) == 1.0         # دقیقاً نصف → p=1
    assert sign_test_p(10, 10) < 0.01
    assert sign_test_p(0, 0) == 1.0


def test_split_windows_are_disjoint_and_cover_data():
    cfg = _cfg()
    layers = _layers(n=3000)
    wins = split_windows(layers, cfg, 4)
    assert len(wins) == 4
    prev_end = -1
    for w in wins:
        first = w["trigger"][0].open_time_ms
        last = w["trigger"][-1].open_time_ms
        assert first > prev_end, "پنجره‌ها باید بدون هم‌پوشانی و صعودی باشند"
        prev_end = last
    assert wins[-1]["trigger"][-1].open_time_ms == layers["trigger"][-1].open_time_ms


def test_layers_for_symbol_are_reproducible():
    """بذر مصنوعی باید پایدار باشد، وگرنه آزمون بقا بین اجراها تکرارپذیر نیست."""
    cfg = _cfg()
    a, _ = layers_for_symbol(cfg, "ETHUSDT", "synthetic")
    b, _ = layers_for_symbol(cfg, "ETHUSDT", "synthetic")
    assert [c.close for c in a["trigger"][:20]] == [c.close for c in b["trigger"][:20]]
    c, _ = layers_for_symbol(cfg, "SOLUSDT", "synthetic")
    assert [x.close for x in a["trigger"][:20]] != [x.close for x in c["trigger"][:20]]


# ── اجرای کامل آزمون بقا ──────────────────────────────────────────────────
def test_robust_runs_and_can_fail_honestly():
    cfg = _cfg(candles=3000)
    res = run_robust(cfg, ["AAA", "BBB", "CCC"], ["entry_quality"],
                     source="synthetic", n_windows=3, progress=False)
    assert res["presets"] == ["base", "entry_quality"]
    for p in res["presets"]:
        s = res["summary"][p]
        for k in ("symbols_n", "total_trades", "median_pf", "positive_windows_pct",
                  "checks", "survived"):
            assert k in s
        assert set(s["checks"]) == {"has_trades", "profitable_symbols",
                                    "positive_windows", "median_pf", "significance"}
        # حکم بقا باید برآیند واقعی همان چک‌ها باشد
        assert s["survived"] == all(s["checks"].values())
        assert len(res["per_preset"][p]["symbols"]) == 3
    # روی دادهٔ مصنوعی (نویز بدون edge) انتظار «بقا» نداریم — تست منفی
    assert res["summary"]["entry_quality"]["survived"] is False
