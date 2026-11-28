"""تست‌های «مغز دوم».

مهم‌ترین خاصیتی که این تست‌ها قفل می‌کنند: **نگاه به آینده**. اگر walk-forward
حتی یک نمونه از آینده را در آموزش ببیند، هر عددی که از مدل در بیاید بی‌اعتبار
است — همان اشتباهی که کل پروژه یک‌بار بابتش هزینه داد.
"""
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                            # noqa: E402

from mtflab.brain import (FEATURES, GATE, _feat_row, auc, brain_command,     # noqa: E402
                          bucket_table, build_dataset, filter_test, fit_logistic,
                          judge, predict, sign_stability, split_blocks,
                          walk_forward)
from mtflab.config import MTFConfig                                        # noqa: E402
from mtflab.data import synthetic_candles                                  # noqa: E402


def _row(i, y, r=None, p=None):
    r = (1.0 if y else -1.0) if r is None else r
    d = {n: 0.0 for n, _ in FEATURES}
    d.update({"symbol": "X", "entry_ts": 1_700_000_000_000 + i * 14_400_000,
              "exit_ts": 1_700_000_000_000 + (i + 1) * 14_400_000,
              "r": r, "pnl": r * 10.0, "y": y, "rule": "stop_trail", "bars": 3})
    if p is not None:
        d["p"] = p
    return d


# ═══════════════════════════════════════════════════════════════════════════
# ۱) مجموعه داده
# ═══════════════════════════════════════════════════════════════════════════
def test_feature_row_reads_only_entry_time_fields():
    t = {"indicators_entry": {"atr_pct": 1.2, "adx": 30, "rsi": 55, "don_pos": 0.8,
                              "bb_pos": 0.9, "bb_width": 0.03, "vol_z": 1.5,
                              "structure_score": -1.5, "ema_main_slope_pct": 0.4},
         "indicators_filter_entry": {"ema_main_slope_pct": 0.9},
         "confidence_entry": 0.77, "trigger_mode": "breakout",
         # این‌ها باید نادیده گرفته شوند (اطلاعات آینده)
         "mfe_pct": 99.0, "mae_pct": -99.0, "r_multiple": 9.9}
    row = _feat_row(t)
    assert row is not None
    assert set(row) == {n for n, _ in FEATURES}
    assert row["confidence"] == 0.77 and row["mode_breakout"] == 1.0
    assert row["slope_filter"] == 0.9 and row["atr_pct"] == 1.2
    assert "mfe_pct" not in row and "r_multiple" not in row


def test_feature_row_is_none_without_indicators():
    assert _feat_row({"confidence_entry": 0.5}) is None


def test_build_dataset_on_synthetic_engine_trades():
    uni = {"A": synthetic_candles("4h", 1200, seed=5),
           "B": synthetic_candles("4h", 1200, seed=6)}
    cfg = replace(MTFConfig(data_mode="synthetic", tf_trigger="4h", tf_filter="1d",
                            tf_bias="1d", verbose=False, forensics=False, run_id="",
                            symbol="", filter_adx_min=0.0, filter_slope_min_pct=0.0,
                            alignment_version="C", bias_enabled=False,
                            trigger_entry_modes=["breakout"],
                            take_profit_atr_mult=50.0, trail_atr_mult=3.0,
                            trail_start_r=1.0))
    rows = build_dataset(uni, cfg, "4h", "1d", "1d")
    assert rows, "روی دادهٔ مصنوعی باید معامله ساخته شود"
    assert all(r["rule"] != "end_of_data" for r in rows)
    assert all(0 <= r["y"] <= 1 for r in rows)
    assert [r["entry_ts"] for r in rows] == sorted(r["entry_ts"] for r in rows)


# ═══════════════════════════════════════════════════════════════════════════
# ۲) بلوک‌بندی و walk-forward (بدون نگاه به آینده)
# ═══════════════════════════════════════════════════════════════════════════
def test_blocks_are_chronological_and_cover_everything():
    rows = [_row(i, i % 2) for i in range(100)]
    blocks = split_blocks(rows, 4)
    assert sum(len(b) for b in blocks) == 100
    assert len(blocks) == 4
    for a, b in zip(blocks, blocks[1:]):
        assert max(x["entry_ts"] for x in a) < min(x["entry_ts"] for x in b)


def test_walk_forward_refuses_tiny_datasets():
    rows = [_row(i, i % 2) for i in range(60)]
    try:
        walk_forward(rows, 4)
        raise AssertionError("باید خطا می‌داد")
    except ValueError:
        pass


def test_walk_forward_never_trains_on_the_future():
    rows = [_row(i, i % 2) for i in range(120)]
    preds, blocks, coefs = walk_forward(rows, 4)
    assert preds and coefs
    # هر پیش‌بینی فقط از بلوک‌های بعد از نمونه‌های آموزش آمده است
    first_test_ts = min(x["entry_ts"] for x in blocks[1])
    assert all(x["entry_ts"] >= first_test_ts for x in preds)
    # و تعداد فولدهای آموزش = یکی کمتر از تعداد بلوک‌ها
    assert len(coefs) == len(blocks) - 1


def test_walk_forward_prediction_count_matches_test_blocks():
    rows = [_row(i, random.Random(1).randint(0, 1)) for i in range(160)]
    preds, blocks, _ = walk_forward(rows, 4)
    assert len(preds) == sum(len(b) for b in blocks[1:])


# ═══════════════════════════════════════════════════════════════════════════
# ۳) مدل
# ═══════════════════════════════════════════════════════════════════════════
def test_logistic_learns_a_separable_signal():
    rng = random.Random(3)
    X, y = [], []
    for _ in range(200):
        v = rng.gauss(0, 1)
        X.append([v, rng.gauss(0, 0.1)])
        y.append(1 if v > 0 else 0)
    w, b = fit_logistic(X, y)
    ps = predict(w, b, X)
    acc = sum(1 for p, t in zip(ps, y) if (p > 0.5) == bool(t)) / len(y)
    assert acc > 0.9, acc
    assert w[0] > 0 and abs(w[0]) > abs(w[1])


def test_auc_bounds():
    assert auc([{"p": 0.9, "y": 1}, {"p": 0.1, "y": 0}]) == 1.0
    assert auc([{"p": 0.1, "y": 1}, {"p": 0.9, "y": 0}]) == 0.0
    assert auc([{"p": 0.5, "y": 1}, {"p": 0.5, "y": 0}]) == 0.5
    assert auc([{"p": 0.5, "y": 1}]) is None


# ═══════════════════════════════════════════════════════════════════════════
# ۴) سنجه‌ها و دروازه
# ═══════════════════════════════════════════════════════════════════════════
def test_buckets_show_monotonic_expectancy_when_signal_is_real():
    preds = [_row(i, 1 if i > 50 else 0, r=(2.0 if i > 50 else -1.0), p=i / 100)
             for i in range(100)]
    b = bucket_table(preds, 4)
    assert len(b) == 4
    exps = [x["expectancy_r"] for x in b]
    assert exps == sorted(exps), exps
    assert sum(x["n"] for x in b) == 100


def test_filter_test_is_positive_when_noise_is_dropped():
    preds = [_row(i, 0, r=-1.0, p=i / 200) for i in range(60)] + \
            [_row(100 + i, 1, r=2.0, p=0.6 + i / 500) for i in range(40)]
    ft = filter_test(preds, 0.30)
    assert ft["ok"] and ft["expectancy_kept"] > ft["expectancy_all"] > ft["expectancy_dropped"]


def test_judge_requires_all_checks():
    good = {
        "n_oof": 400,
        "buckets": [{"expectancy_r": -0.5}, {"expectancy_r": 0.0},
                    {"expectancy_r": 0.2}, {"expectancy_r": 0.4}],
        "filter": {"ok": True, "n_kept": 280, "ci": {"significant": True,
                                                     "observed": 0.2, "ci": [0.05, 0.4]}},
        "coefficients": [{"stability": 1.0}, {"stability": 0.9}, {"stability": 0.8}],
    }
    assert judge(good)["passed"] is True
    assert len(judge(good)["checks"]) == 6
    bad = json.loads(json.dumps(good))
    bad["buckets"][0]["expectancy_r"] = 0.32          # اختلاف چهارک‌ها کم
    bad["buckets"][-1]["expectancy_r"] = 0.40
    assert judge(bad)["passed"] is False
    negative = json.loads(json.dumps(good))
    negative["buckets"][0]["expectancy_r"] = -0.90    # اختلاف زیاد ولی خودِ بالا هم ضررده
    negative["buckets"][-1]["expectancy_r"] = -0.30
    assert judge(negative)["passed"] is False
    unstable = json.loads(json.dumps(good))
    unstable["coefficients"][0]["stability"] = 0.4
    assert judge(unstable)["passed"] is False
    tiny = json.loads(json.dumps(good))
    tiny["n_oof"] = 20
    assert judge(tiny)["passed"] is False


def test_sign_stability_reports_per_fold_signs():
    coefs = [(1, [0.5, -0.2]), (2, [0.4, 0.1]), (3, [0.6, -0.3])]
    st = sign_stability(coefs)
    top = {s["name"]: s for s in st}
    n0 = FEATURES[0][0]
    assert top[n0]["stability"] == 1.0 and top[n0]["sign"] == 1
    assert top[n0]["per_fold"] == [0.5, 0.4, 0.6]


# ═══════════════════════════════════════════════════════════════════════════
# ۵) CLI از روی مجموعه دادهٔ ذخیره‌شده
# ═══════════════════════════════════════════════════════════════════════════
def test_cli_from_saved_dataset_writes_report():
    with tempfile.TemporaryDirectory() as td:
        ds = os.path.join(td, "ds.jsonl")
        rng = random.Random(7)
        with open(ds, "w", encoding="utf-8") as f:
            for i in range(200):
                strong = rng.random() < 0.5
                y = 1 if (strong and rng.random() < 0.8) else (1 if rng.random() < 0.2 else 0)
                d = _row(i, y, r=(1.5 if y else -1.0))
                d[FEATURES[0][0]] = 1.0 if strong else -1.0
                d["symbol"] = "X"
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        out = os.path.join(td, "out")
        rc = brain_command(["--from-dataset", ds, "--out-dir", out, "--folds", "4",
                            "--lang", "en", "--dataset", os.path.join(td, "x.jsonl")])
        assert rc == 0
        assert os.path.exists(os.path.join(out, "brain_report.md"))
        with open(os.path.join(out, "brain_report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        assert rep["n_trades"] == 200 and rep["n_oof"] > 0
        assert rep["judge"]["checks"] and rep["gate"] == GATE
        assert rep["coefficients"] and rep["buckets"]
