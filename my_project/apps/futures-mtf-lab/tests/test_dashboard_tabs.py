"""تست تب‌های جدید داشبورد: «ورود اصلاح‌شده» و «آزمایشگاه خروج».

چرا تست داشبورد؟ چون داشبورد تنها خروجی است که کاربر *می‌بیند*. یک کلید
جا‌افتاده در payload، به‌جای خطا، یک بخش خالی یا «None» نشان می‌دهد — یعنی
خطای خاموش. این تست‌ها همان خطاهای خاموش را به خطای بلند تبدیل می‌کنند.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.dashboard import render, tab_entry_quality, tab_exit_lab  # noqa: E402


def _trade(ts, pnl, reason="take_profit"):
    return {"ts": ts, "side": 1, "entry": 100.0, "exit": 102.0, "pnl": pnl,
            "r_multiple": 1.2, "reason": reason, "trigger_mode": "pullback",
            "regime": "uptrend", "bars_held": 6, "fees": 0.1}


def _summary(exp, pf, n=42, ret=3.37, dd=-4.57):
    return {"trades": n, "win_rate": 0.5, "profit_factor": pf, "expectancy": exp,
            "return_pct": ret, "max_drawdown_pct": dd, "total_fees": 4.2,
            "positions_opened": n, "avg_legs_per_position": 1.0, "partial_legs": 0}


def _run(exp=0.802, pf=1.137, n=42):
    return {"summary": _summary(exp, pf, n), "label": "دادهٔ واقعی CSV",
            "trades": [_trade(1700000000000 + i * 3600000, 5.0 if i % 2 else -2.0)
                       for i in range(12)],
            "equity_curve": [{"ts": 1700000000000 + i * 3600000, "equity": 1000 + i}
                             for i in range(12)]}


def _scn(id_, name, short, subtitle, desc, exp=0.0, pf=1.0, n=20, **extra):
    d = {"id": id_, "name": name, "short_name": short, "subtitle": subtitle,
         "description": desc, "runs": {"normalized": _run(exp, pf, n)}}
    d.update(extra)
    return d


def _payload():
    return {
        "generated_at": "2026-01-01 00:00 UTC",
        "subtitle": "BTCUSDT · test",
        "initial_equity": 1000.0,
        "data": {"path": "x.csv", "candles": 8760,
                 "start_ts": 1700000000000, "end_ts": 1730000000000},
        "cost_models": {"normalized": {"label": "یکسان", "fee_bps": 5.5,
                                       "slippage_pct": 0.02,
                                       "risk_per_trade_pct": 1.0,
                                       "max_concurrent": 1},
                        "native": {"label": "پیش‌فرض", "old": {}, "new": {}}},
        "scenarios": {
            "old": _scn("old", "🧠 قدیم", "قدیم", "1h", "توضیح قدیم",
                        exp=-0.331, pf=0.943, n=163),
            "new": _scn("new", "🧩 جدید", "جدید", "1h/4h/1d", "توضیح جدید",
                        exp=-0.790, pf=0.871, n=107,
                        versions={"A": {"summary": _summary(-0.79, 0.871),
                                        "label": "A"}}),
            "new_eq": {
                "id": "new_eq", "name": "✨ ورود اصلاح‌شده",
                "short_name": "اصلاح‌شده",
                "subtitle": "1h/4h/1d · pullback + climax",
                "description": "آزمون",
                "runs": {"normalized": _run()},
            },
        },
        "entry_quality": {
            "preset_overrides": {"trigger_entry_modes": ["pullback"],
                                 "trigger_max_range_atr": 1.0},
            "bootstrap_vs_new": {"ok": True, "observed_diff": 1.59,
                                 "ci95": [-3.26, 6.27], "note": "⚠️ معنادار نیست"},
            "bootstrap_vs_old": {"ok": True, "observed_diff": 1.13,
                                 "ci95": [-2.5, 5.0], "note": "⚠️ معنادار نیست"},
        },
        "exit_matrix": {
            "entries": ["base", "entry_quality"],
            "policy_ids": ["base", "no_trail", "trail_tight"],
            "cells": {
                "base": {
                    "base": {"label": "فعلی", "full": {"n": 107, "expectancy": -0.79,
                                                       "profit_factor": 0.87},
                             "train": {"n": 60, "expectancy": -1.7},
                             "oos": {"n": 32, "expectancy": 0.13}, "robust": False},
                    "no_trail": {"label": "بدون تریلینگ", "full": {"n": 96, "expectancy": -0.19,
                                                                   "profit_factor": 0.97},
                                 "train": {"n": 55, "expectancy": -1.4},
                                 "oos": {"n": 30, "expectancy": 0.72}, "robust": False},
                    "trail_tight": {"label": "تریلینگ تنگ", "full": {"n": 113, "expectancy": -0.12,
                                                                     "profit_factor": 0.98},
                                    "train": {"n": 60, "expectancy": -0.56},
                                    "oos": {"n": 33, "expectancy": 0.07}, "robust": False},
                },
                "entry_quality": {
                    "base": {"label": "فعلی", "full": {"n": 42, "expectancy": 0.80,
                                                       "profit_factor": 1.14},
                             "train": {"n": 20, "expectancy": 0.35},
                             "oos": {"n": 7, "expectancy": 3.30}, "robust": True},
                    "no_trail": {"label": "بدون تریلینگ", "full": {"n": 38, "expectancy": 1.04,
                                                                   "profit_factor": 1.15},
                                 "train": {"n": 18, "expectancy": 0.08},
                                 "oos": {"n": 6, "expectancy": 3.30}, "robust": True},
                    "trail_tight": {"label": "تریلینگ تنگ", "full": {"n": 45, "expectancy": -0.36,
                                                                     "profit_factor": 0.94},
                                    "train": {"n": 22, "expectancy": -0.9},
                                    "oos": {"n": 8, "expectancy": 1.1}, "robust": False},
                },
            },
            "summary": {
                "base": {"best_policy": "trail_tight", "best_expectancy": -0.12,
                         "robust_policies": [], "robust_count": 0, "significance": None},
                "entry_quality": {"best_policy": "no_trail", "best_expectancy": 1.04,
                                  "robust_policies": ["base", "no_trail"], "robust_count": 2,
                                  "significance": {"ok": True, "observed": 0.24,
                                                   "ci95": [-6.32, 6.81],
                                                   "note": "⚠️ معنادار نیست"}},
            },
            "verdict": {"trail_helps_again": False, "helped_ids": [],
                        "base_entry_best_expectancy": -0.12,
                        "entry_quality_best_expectancy": 1.04,
                        "note": "حتی با ورودِ بهتر هم هیچ تریلینگی از TP ثابت بهتر نشد"},
        },
        "best_version": "A",
        "health_new": {},
        "validation": {},
        "health": {"tests": [{"pass": True, "name": "تست علی‌بودن", "detail": "ok"},
                             {"pass": False, "name": "تست نمونه", "detail": "نمایشی"}],
                   "leakage": {"clean": True, "bars_checked": 8760},
                   "gaps": {}, "pitfalls": [["دام ۱", "پوشش"]], "runs": []},
        "verdict": {"winner": "old", "text": "متن حکم", "detail_rows": [], "new_wins": 1,
                    "old_wins": 3},
        "verdict_eq": {"winner": "new", "text": "حکم ورود اصلاح‌شده", "detail_rows": [],
                       "new_wins": 3, "old_wins": 1},
    }


def test_entry_quality_tab_shows_overrides_and_caveat():
    html = tab_entry_quality(_payload())
    assert "trigger_entry_modes" in html
    assert "trigger_max_range_atr" in html
    assert "overfit" in html, "هشدار overfit باید در تب باشد"
    assert "None" not in html


def test_exit_lab_tab_renders_matrix_and_verdict():
    html = tab_exit_lab(_payload())
    assert "آزمایشگاه خروج" in html
    for label in ("فعلی", "بدون تریلینگ", "تریلینگ تنگ"):
        assert label in html
    assert "حتی با ورودِ بهتر" in html
    assert "None" not in html
    # Δ باید برای سیاست no_trail محاسبه شده باشد: 1.04 - (-0.19) = 1.23
    assert "1.23" in html


def test_exit_lab_tab_degrades_gracefully():
    p = _payload()
    p["exit_matrix"] = {"error": "نمونهٔ کافی نیست"}
    html = tab_exit_lab(p)
    assert "ساخته نشد" in html and "None" not in html
    assert "داده‌ای برای این تب نیست" not in html


def test_full_render_contains_new_tabs_and_no_error_box():
    payload = _payload()
    html = render(payload, title="تست", strict=True)   # strict: هیچ خطایی مجاز نیست
    assert "tab-eq" in html and "tab-exit" in html
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    assert html.count("<section") >= 7
    assert "این تب ساخته نشد" not in html
    assert "ورود اصلاح‌شده" in html and "آزمایشگاه خروج" in html


def test_broken_tab_does_not_kill_dashboard_but_is_visible():
    """لایهٔ ایمنی داشبورد: تب خراب → پیام روشن، نه صفحهٔ سفید."""
    payload = _payload()
    del payload["scenarios"]["old"]                    # تب مقایسه را می‌شکند
    html = render(payload, title="تست")                # strict=False
    assert "این تب ساخته نشد" in html
    assert "آزمایشگاه خروج" in html, "تب سالم باید همچنان رندر شود"
    try:
        render(payload, title="تست", strict=True)
    except KeyError:
        pass
    else:
        raise AssertionError("در حالت strict باید خطا بالا بیاید")
