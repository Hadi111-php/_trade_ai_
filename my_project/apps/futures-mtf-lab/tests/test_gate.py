"""تست‌های «دروازهٔ پذیرش»: FAIL یعنی چه و برای عبور چه لازم است.

اعدادِ فیکسچر، **همان گزارش واقعیِ کاربر** است (۴ نماد، ۳۶۵ روز):
`trend` با ۷۵ معامله، میانهٔ PF ۱٫۴۷، p=۰٫۱۲۵ و ۴/۴ برد در برابر پایه.
هدف تست: همین اعداد باید «نماد کم است» و «معناداری ریاضیاتاً ناممکن است» را
جدا نشان دهند — نه اینکه همه را در یک کلمهٔ FAIL گم کنند.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import gate                                            # noqa: E402
from mtflab.autoscan import short_history_note                     # noqa: E402


def _report(n_symbols=4, days=365):
    """ساختاری عیناً مثل `auto_scan_*.json` واقعی."""
    symbols = [f"S{i}USDT" for i in range(n_symbols)]
    agg = {}
    for vid, trades, pf, exp, prof, py, sign in (
            ("base", 76, 0.6285, -2.2669, 25.0, 25.0, None),
            ("trend", 75, 1.4719, 3.7601, 75.0, 75.0, {"wins": 4, "of": 4, "p_value": 0.125})):
        agg[vid] = {
            "ok": True, "n_symbols": n_symbols, "total_trades": trades,
            "total_pnl": 180.41 if vid == "trend" else -201.62,
            "median_pf": pf, "median_expectancy": exp,
            "profitable_symbols": int(round(prof * n_symbols / 100)),
            "profitable_symbols_pct": prof,
            "positive_years": 1, "years_n": n_symbols, "positive_years_pct": py,
            "positive_years_core": 1, "core_years_n": n_symbols, "positive_years_core_pct": py,
            "sign_vs_base": sign,
            "checks": {"symbols": n_symbols >= 8, "trades": trades >= 100,
                       "profitable_symbols": prof >= 60, "positive_years": py >= 60,
                       "median_pf": pf >= 1.05,
                       "significance": bool(sign and sign["p_value"] <= 0.1)},
            "survived": False,
        }
    return {"version": 1, "generated_at": "2026-11-17 09:35 UTC",
            "settings": {"symbols": symbols, "days": days, "tf_trigger": "4h",
                         "tf_filter": "1d", "tf_bias": "1d", "source": "json"},
            "gate": dict(gate.DEFAULT_GATE), "aggregate": agg,
            "per_symbol": {}, "coverage": {s: {} for s in symbols},
            "rankings": [], "winner": "trend", "survived": [], "errors": []}


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ریاضیات آزمون علامت
# ══════════════════════════════════════════════════════════════════════════
def test_min_sign_p_is_two_times_half_power_n():
    assert gate.min_sign_p(4) == 0.125
    assert abs(gate.min_sign_p(8) - 0.0078125) < 1e-9
    assert gate.min_sign_p(1) == 1.0
    assert gate.min_sign_p(0) == 1.0


def test_significance_impossible_with_four_symbols():
    r = gate.readiness(_report())
    assert abs(r["sign_p_floor"] - 0.125) < 1e-9
    trend = [v for v in r["variants"] if v["variant"] == "trend"][0]
    sig = [c for c in trend["checks"] if c["name"].startswith("معناداری")][0]
    assert sig["ok"] is False
    assert "ناممکن" in sig["hint"]          # نه «ضعیف»، بلکه «با ۴ نماد ممکن نیست»


# ══════════════════════════════════════════════════════════════════════════
#  ۲) جدا کردن «نماد کم» از «نتیجه بد»
# ══════════════════════════════════════════════════════════════════════════
def test_best_variant_keeps_good_checks_and_names_only_sample_walls():
    r = gate.readiness(_report())
    best = r["best"]
    assert best["variant"] == "trend"
    assert set(best["failed"]) == {"نماد", "معامله", "معناداری (در برابر پایه)"}
    # شرط‌های کیفی پاس شده‌اند
    passed = {c["name"] for c in best["checks"] if c["ok"]}
    assert {"نمادهای سودده", "سال‌های مثبت", "میانهٔ PF"} <= passed


def test_next_steps_quantify_what_is_missing():
    r = gate.readiness(_report())
    steps = "\n".join(gate._next_steps(r))
    assert "4 نماد** دیگر" in steps           # ۸ − ۴
    assert "معناداری" in steps and "0.125" in steps
    assert "`--days 730`" in steps            # یک سالِ تنها، یک رژیم


def test_render_text_is_readable_markdown():
    txt = gate.render_text(_report(), "/tmp/auto_scan_year.json")
    assert "# دروازهٔ پذیرش" in txt
    assert "| `trend` |" in txt
    assert "برای عبور از دروازه" in txt
    assert "auto_scan_year.json" in txt


# ══════════════════════════════════════════════════════════════════════════
#  ۳) CLI
# ══════════════════════════════════════════════════════════════════════════
def test_cli_reads_file_and_returns_1_when_not_survived():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "auto_scan_year.json")
        json.dump(_report(), open(p, "w", encoding="utf-8"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gate.gate_command([p])
        assert rc == 1                              # هیچ نسخه‌ای قبول نشد
        assert "دروازهٔ پذیرش" in buf.getvalue()


def test_cli_without_report_explains_what_to_run():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gate.gate_command(["--results-dir", td])
        assert rc == 2
        assert "run-auto.sh --source json" in buf.getvalue()


def test_latest_report_picks_newest():
    with tempfile.TemporaryDirectory() as td:
        old = os.path.join(td, "auto_scan_old.json")
        new = os.path.join(td, "auto_scan_year.json")
        for p in (old, new):
            json.dump(_report(), open(p, "w", encoding="utf-8"))
        os.utime(old, (1, 1))
        assert gate.latest_report(td).endswith("auto_scan_year.json")


# ══════════════════════════════════════════════════════════════════════════
#  ۴) یادداشتِ «تاریخ کوتاه»: کش کوتاه ≠ نماد تازه
# ══════════════════════════════════════════════════════════════════════════
def test_short_cache_is_not_mistaken_for_young_listing():
    cov = {"BTCUSDT": {"integrity": {"front_gap_days": 1094.93, "span_days": 365.0}},
           "ETHUSDT": {"integrity": {"front_gap_days": 1094.93, "span_days": 365.0}}}
    note = short_history_note(cov, 1460, fa=False)
    assert "cache" in note.lower() and "365" in note
    assert "young listings" in note


def test_single_young_symbol_keeps_its_own_explanation():
    cov = {"BTCUSDT": {"integrity": {"front_gap_days": 0.0, "span_days": 1460.0}},
           "NEWUSDT": {"integrity": {"front_gap_days": 900.0, "span_days": 560.0}}}
    note = short_history_note(cov, 1460, fa=False)
    assert "listed after the window start" in note
    assert "cache" not in note.lower()


# ══════════════════════════════════════════════════════════════════════════
#  ۵) گزارش خالی ≠ FAIL
# ══════════════════════════════════════════════════════════════════════════
def test_empty_report_is_not_a_failure_verdict():
    rep = {"gate": dict(gate.DEFAULT_GATE), "aggregate": {}, "settings": {}}
    r = gate.readiness(rep)
    assert r["empty"] is True
    txt = gate.render_text(rep)
    assert "گزارش خالی است" in txt
    assert "کش خالی" in txt                 # علت، نه شرمندگی
    assert "| نسخه |" not in txt            # جدولِ بی‌معنا چاپ نمی‌شود


def test_empty_report_exit_code_is_2_not_1():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "auto_scan_empty.json")
        json.dump({"gate": dict(gate.DEFAULT_GATE), "aggregate": {},
                   "settings": {"symbols": [], "days": 365}}, open(p, "w", encoding="utf-8"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gate.gate_command([p])
        assert rc == 2
        assert "گزارش خالی" in buf.getvalue()
