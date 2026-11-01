"""تست‌های کارگاه اتوترید مجازی: تنظیمات، سنجه‌ها، دروازه، و سرور.

قاعدهٔ تست‌ها: هر چیزی که می‌تواند آمار را **گمراه‌کننده** کند باید قفل شود:
  • کلید ناشناخته در تنظیمات نباید بی‌صدا اعمال شود.
  • مقدار بیرون بازه باید به بازه برگردد، نه این‌که کل اجرا را بشکند.
  • پوزیشنِ «پایان داده» نباید در سنجه‌ها به‌عنوان معاملهٔ بسته‌شده بیاید
    (وگرنه هر پارامتری که آخر بازه لانگ باشد پاداش می‌گیرد).
  • «شمارهٔ آزمایش» باید واقعاً بالا برود — این تنها سدِ multiple-testing است.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.desk import (Lab, KNOBS, sanitize_overrides, metrics,             # noqa: E402
                         data_fingerprint, rule_breakdown)
from mtflab.data import synthetic_candles                                     # noqa: E402


def _lab(td, **kw):
    return Lab(demo=True, demo_bars=900, lab_dir=os.path.join(td, "lab"), **kw)


# ═══════════════════════════════════════════════════════════════════════════
# ۱) تنظیمات کاربر
# ═══════════════════════════════════════════════════════════════════════════
def test_unknown_knob_is_ignored_not_applied():
    clean, ignored = sanitize_overrides({"stop_atr_mult": 2.0, "__class__": 1,
                                         "nonsense": "x"})
    assert clean == {"stop_atr_mult": 2.0}
    assert sorted(ignored) == ["__class__", "nonsense"]


def test_values_are_clamped_to_allowed_range():
    clean, _ = sanitize_overrides({"stop_atr_mult": 99, "trail_start_r": -5,
                                   "max_concurrent": 4.6})
    assert clean["stop_atr_mult"] == 5.0        # سقف
    assert clean["trail_start_r"] == 0.0        # کف
    assert clean["max_concurrent"] == 5         # گرد به int و در بازه


def test_bool_choice_and_modes_are_parsed():
    clean, _ = sanitize_overrides({"trail_enabled": "off", "bias_enabled": "بله",
                                   "alignment_version": "c",
                                   "trigger_entry_modes": ["breakout", "جunk"]})
    assert clean["trail_enabled"] is False
    assert clean["bias_enabled"] is True
    assert clean["alignment_version"] == "C"
    assert clean["trigger_entry_modes"] == ["breakout"]


def test_bad_choice_is_dropped():
    clean, _ = sanitize_overrides({"alignment_version": "Z"})
    assert "alignment_version" not in clean


def test_every_knob_declares_type_and_label():
    for k in KNOBS:
        assert k["k"] and k["fa"] and k["g"]
        assert k["t"] in ("float", "int", "bool", "choice", "modes")
        if k["t"] in ("float", "int"):
            assert k["lo"] < k["hi"] and k["st"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# ۲) سنجه‌ها
# ═══════════════════════════════════════════════════════════════════════════
def test_metrics_are_computed_from_positions():
    rows = [
        {"symbol": "X", "entry_ts": 1, "exit_ts": 2, "mode": "breakout",
         "rule": "stop_loss", "pnl": -10.0, "r": -1.0, "bars": 5, "is_win": False},
        {"symbol": "X", "entry_ts": 3, "exit_ts": 4, "mode": "breakout",
         "rule": "stop_trail", "pnl": 30.0, "r": 3.0, "bars": 9, "is_win": True},
    ]
    m = metrics(rows, 1000.0)
    assert m["n"] == 2 and m["win_rate"] == 0.5
    assert m["expectancy_r"] == 1.0 and m["pnl"] == 20.0
    assert m["profit_factor"] == 3.0            # ۳۰ سود / ۱۰ ضرر
    assert m["equity"] == 1020.0


def test_empty_metrics_are_safe():
    m = metrics([], 1000.0)
    assert m["n"] == 0 and m["expectancy_r"] is None and m["pnl"] == 0.0


def test_rule_breakdown_marks_loss_reduction_rules():
    rows = [{"symbol": "X", "entry_ts": 1, "exit_ts": 2, "mode": "breakout",
             "rule": "stop/trail", "pnl": 5.0, "r": 0.5, "bars": 3, "is_win": True}]
    b = rule_breakdown(rows)
    assert b["stop/trail"]["is_risk_control"] is True
    assert b["stop/trail"]["fa"]


# ═══════════════════════════════════════════════════════════════════════════
# ۳) اجرا و دروازه
# ═══════════════════════════════════════════════════════════════════════════
def test_evaluate_splits_in_sample_and_out_of_sample():
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        ev = lab.evaluate({}, symbols=["BTCUSDT", "ETHUSDT"])
        m, i, o = ev["metrics"], ev["in_sample"], ev["out_of_sample"]
        assert m["n"] > 0, "روی دادهٔ نمایشی باید معامله ساخته شود"
        assert i["n"] + o["n"] == m["n"]
        assert ev["span"][0] < ev["cut_ts"] < ev["span"][1]
        assert sum(1 for t in ev["trades"] if t["rule"] == "end_of_data") == 0


def test_digest_tracks_parameter_changes():
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        a = lab.evaluate({"trail_atr_mult": 3.0}, symbols=["BTCUSDT"])
        b = lab.evaluate({"trail_atr_mult": 5.0}, symbols=["BTCUSDT"])
        c = lab.evaluate({"trail_atr_mult": 3.0}, symbols=["BTCUSDT"])
        assert a["digest"] != b["digest"]
        assert a["digest"] == c["digest"]


def test_run_experiment_persists_and_counts_trials():
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        r1 = lab.run_experiment({"trail_atr_mult": 4.0}, label="الف",
                                symbols=["BTCUSDT", "ETHUSDT"])
        r2 = lab.run_experiment({"trail_atr_mult": 5.0}, label="ب",
                                symbols=["BTCUSDT", "ETHUSDT"])
        assert (r1["trial_index"], r2["trial_index"]) == (1, 2)
        assert "۲امین" in r2["trial_warning"] or "2امین" in r2["trial_warning"]
        assert os.path.exists(os.path.join(td, "lab", "runs", r1["run_id"] + ".json"))
        idx = lab.runs()
        assert len(idx) == 2 and idx[-1]["run_id"] == r2["run_id"]
        assert lab.run_detail(r1["run_id"])["label"] == "الف"


def test_verdict_uses_the_gate_written_before_the_run():
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        strict = lab.run_experiment({"trail_atr_mult": 4.0},
                                    gate={"min_expectancy_r": 50.0, "min_trades": 5},
                                    symbols=["BTCUSDT"])
        assert strict["verdict"]["passed"] is False
        loose = lab.run_experiment({"trail_atr_mult": 4.0},
                                   gate={"min_expectancy_r": -50.0, "min_trades": 1},
                                   symbols=["BTCUSDT"])
        assert loose["verdict"]["passed"] is True
        assert len(loose["verdict"]["checks"]) == 2


def test_delta_against_baseline_is_reported():
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        rec = lab.run_experiment({"trail_atr_mult": 5.0}, symbols=["BTCUSDT", "ETHUSDT"])
        d = rec["delta_vs_baseline"]
        assert d and d["ok"] and len(d["ci"]) == 2 and d["ci"][0] <= d["ci"][1]


def test_identical_run_without_overrides_has_no_delta():
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        rec = lab.run_experiment({}, symbols=["BTCUSDT"])
        assert rec["delta_vs_baseline"] is None


def test_fingerprint_changes_with_data():
    a = {"X": synthetic_candles("4h", 100, seed=1)}
    b = {"X": synthetic_candles("4h", 101, seed=1)}
    assert data_fingerprint(a) != data_fingerprint(b)
    assert len(data_fingerprint(a)) == 10


# ═══════════════════════════════════════════════════════════════════════════
# ۴) پروندهٔ سیگنال‌ها
# ═══════════════════════════════════════════════════════════════════════════
def test_signals_merge_open_and_close_records():
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        open_rec = {
            "type": "open", "id": "BTCUSDT:trend:1700000000000",
            "symbol": "BTCUSDT", "ts": 1700000000000, "backfilled": True,
            "algorithm": {"id": "trend", "cfg_digest": "abc1234567"},
            "entry_pattern": {"mode": "breakout", "regime_filter": "uptrend",
                              "trigger_reason": "شکست", "decision_reason": "همه‌جهت",
                              "confidence": 0.9},
            "order": {"entry": 100.0, "stop": 98.0},
        }
        close_rec = {
            "type": "close", "id": "BTCUSDT:trend:1700000000000:closed",
            "open_id": "BTCUSDT:trend:1700000000000", "symbol": "BTCUSDT",
            "ts": 1700100000000,
            "closed_by": {"rule": "stop_trail", "fa": "تریلینگ", "is_risk_control": True},
            "result": {"exit": 104.0, "pnl": 12.5, "r_multiple": 1.25, "bars_held": 6},
        }
        with open(jp, "w", encoding="utf-8") as f:
            f.write(json.dumps(open_rec, ensure_ascii=False) + "\n")
            f.write(json.dumps(close_rec, ensure_ascii=False) + "\n")
        lab = _lab(td, journal_path=jp,
                   state_path=os.path.join(td, "state.json"))
        sig = lab.signals()
        assert len(sig) == 1
        s = sig[0]
        assert s["status"] == "closed" and s["rule"] == "stop_trail"
        assert s["is_risk_control"] is True and s["r"] == 1.25
        assert s["raw_close"]["result"]["pnl"] == 12.5
        assert lab.signals(only_risk=True) and not lab.signals(rule="stop_loss")


# ═══════════════════════════════════════════════════════════════════════════
# ۵) سرور
# ═══════════════════════════════════════════════════════════════════════════
def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as r:
        return r.status, r.read()


def _post(port, path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, json.loads(r.read())


def test_server_serves_page_and_api():
    from mtflab.labweb import serve as serve_lab
    with tempfile.TemporaryDirectory() as td:
        lab = _lab(td)
        srv = serve_lab(lab, host="127.0.0.1", port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            code, body = _get(port, "/")
            assert code == 200 and "کارگاه اتوترید" in body.decode()
            code, body = _get(port, "/api/overview")
            o = json.loads(body)
            assert o["demo"] is True and o["data_fp"] and o["bars"]
            code, body = _get(port, "/api/schema")
            sc = json.loads(body)
            assert len(sc["knobs"]) == len(KNOBS) and sc["symbols"]
            code, body = _get(port, "/api/runs")
            assert json.loads(body) == []
            code, body = _get(port, "/api/brain")
            b = json.loads(body)
            assert b["available"] is False and b["hint"]

            code, rec = _post(port, "/api/run", {
                "overrides": {"trail_atr_mult": 4.0},
                "label": "سرور", "symbols": ["BTCUSDT"],
                "gate": {"min_trades": 1, "require_oos_positive": False}})
            assert code == 200 and rec["trial_index"] == 1
            assert rec["metrics"]["n"] >= 0
            code, body = _get(port, "/api/runs")
            assert len(json.loads(body)) == 1

            try:
                _get(port, "/api/nope")
                raise AssertionError("باید ۴۰۴ می‌داد")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            srv.shutdown()
            srv.server_close()


def test_every_knob_is_a_real_config_field():
    """اگر کلیدی در فرم باشد ولی در MTFConfig نباشد، هر اجرا با TypeError می‌شکست."""
    from dataclasses import fields, replace
    from mtflab.config import MTFConfig
    have = {f.name for f in fields(MTFConfig)}
    for k in KNOBS:
        assert k["k"] in have, k["k"]
    # و همه با هم روی یک کانفیگ می‌نشینند
    vals = {k["k"]: (k["lo"] + k["hi"]) / 2 if k["t"] == "float"
            else (int((k["lo"] + k["hi"]) / 2) if k["t"] == "int"
                  else (True if k["t"] == "bool"
                        else (k["choices"][-1] if k["t"] == "choice"
                              else ["breakout"])))
            for k in KNOBS}
    cfg = replace(MTFConfig(), **vals)
    assert cfg.max_concurrent >= 1
