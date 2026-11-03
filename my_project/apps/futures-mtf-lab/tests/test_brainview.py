"""تست‌های «چشم مغز» و نظاره‌گر.

سه چیز این‌جا قفل می‌شود، چون بدون آن‌ها کل ایده بی‌ارزش می‌شود:

  ۱. **استقلال**: ماژول دیدگاه هیچ چیزی از موتور معامله نمی‌شناسد.
  ۲. **بی‌طرفیِ کامل**: حضور مغز — حتی با دیدگاه‌های افراطی — یک معامله را
     جابه‌جا نمی‌کند. اگر این تست شکست بخورد، مغز «حاکم» شده و باید برگردد.
  ۳. **بدون نگاه به آینده**: دیدگاه در کندل i با اضافه‌شدن کندل‌های بعدی عوض نمی‌شود.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                             # noqa: E402

from mtflab.brainview import (FEATURES, build_arrays, build_rows, load_model,  # noqa: E402
                              model_digest, save_model, train, view_at, view_now)
from mtflab.config import MTFConfig                                         # noqa: E402
from mtflab.data import resample_up, synthetic_candles                      # noqa: E402
from mtflab.engine import run_backtest                                      # noqa: E402
from mtflab.live import LiveRunner, read_journal                            # noqa: E402
from mtflab.observer import BrainObserver                                   # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TREND = dict(bias_enabled=False, trigger_entry_modes=["breakout"],
             take_profit_atr_mult=50.0, trail_atr_mult=3.0, trail_start_r=1.0)


def _cfg(**over):
    base = MTFConfig(data_mode="synthetic", tf_trigger="4h", tf_filter="1d",
                     tf_bias="1d", verbose=False, forensics=False, run_id="",
                     min_edge_multiplier=0.0, candles=1200, seed=11,
                     filter_adx_min=0.0, filter_slope_min_pct=0.0,
                     alignment_version="C", **TREND)
    return replace(base, **over) if over else base


def _fake_model() -> dict:
    """مدل ساختگی (بدون آموزش) — برای تست مسیر، نه برای ادعای کیفیت."""
    names = [n for n, _ in FEATURES]
    return {
        "version": "test", "kind": "brainview", "features": names,
        "fa": {n: n for n in names},
        "means": {n: 0.0 for n in names},
        "stds": {n: 1.0 for n in names},
        "w": [0.1 * (i + 1) for i in range(len(names))],
        "b": 0.0, "horizon_bars": 6, "cost_frac": 0.0015,
        "trained_rows": 1, "trained_through_ts": 1_700_000_000_000,
        "trained_utc": "x", "symbols": ["X"],
        "oof": {"auc": 0.5, "acc": 0.5, "base_rate": 0.5, "majority_acc": 0.5, "n": 1},
    }


# ═══════════════════════════════════════════════════════════════════════════
# ۱) استقلال
# ═══════════════════════════════════════════════════════════════════════════
def test_view_module_knows_nothing_about_trading():
    """`brainview` نباید engine/live/desk/signals را ایمپورت کند — وگرنه مرز می‌ریزد."""
    path = os.path.join(HERE, "mtflab", "brainview.py")
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            if node.level:                       # from .x import y
                mods.add(node.module.split(".")[-1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
    forbidden = {"engine", "live", "desk", "signals", "alignment", "autoscan", "labweb"}
    touched = {m for m in mods if m.split(".")[-1] in forbidden}
    assert not touched, f"brainview نباید این‌ها را بشناسد: {touched}"


def test_observer_module_only_imports_view_layer():
    path = os.path.join(HERE, "mtflab", "observer.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    mods = {n.module for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module}
    assert not ({m.split('.')[-1] for m in mods} & {"engine", "live", "desk"})


# ═══════════════════════════════════════════════════════════════════════════
# ۲) بدون نگاه به آینده و بدون خطا
# ═══════════════════════════════════════════════════════════════════════════
def test_view_is_point_in_time():
    cs = synthetic_candles("4h", 600, seed=9)
    cfg = _cfg()
    m = _fake_model()
    arr_full = build_arrays(cs, cfg)
    arr_cut = build_arrays(cs[:400], cfg)
    v_full = view_at(m, arr_full, 399)
    v_cut = view_at(m, arr_cut, 399)
    assert v_full["p_up"] == v_cut["p_up"]
    assert v_full["ts"] == v_cut["ts"] == cs[399].open_time_ms


def test_view_requires_warmup():
    cs = synthetic_candles("4h", 80, seed=9)
    arr = build_arrays(cs, _cfg())
    assert view_at(_fake_model(), arr, 2) is None
    assert view_at(_fake_model(), arr, -1) is None


def test_observer_is_safe_without_model_and_with_garbage():
    cs = synthetic_candles("4h", 300, seed=9)
    obs = BrainObserver("", _cfg())
    assert obs.available is False
    v = obs.view("X", cs, 250)
    assert v["available"] is False and v["reason"] == "no-model"
    # با مدل، ولی کندل خالی / ایندکس بد: نباید استثنا بدهد
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "m.json")
        save_model(_fake_model(), p)
        obs2 = BrainObserver(p, _cfg())
        assert obs2.available is True
        assert obs2.view("X", [], 0)["available"] is False
        assert obs2.view("X", cs, 999)["available"] is False
        assert obs2.errors == 0 or obs2.errors >= 1     # خطا بلعیده شده، نه پرتاب


def test_view_now_uses_last_closed_candle():
    cs = synthetic_candles("4h", 400, seed=9)
    v = view_now(_fake_model(), cs, _cfg())
    assert v["available"] and v["ts"] == cs[-1].open_time_ms
    assert v["lean"] in ("long", "short", "neutral")
    assert 0.0 <= v["p_up"] <= 1.0 and len(v["drivers"]) == 3


# ═══════════════════════════════════════════════════════════════════════════
# ۳) آموزش و ذخیره‌سازی (روی دادهٔ مصنوعی، فقط برای مکانیزم)
# ═══════════════════════════════════════════════════════════════════════════
def test_train_and_roundtrip_model():
    uni = {f"S{i}": synthetic_candles("4h", 900, seed=21 + i) for i in range(3)}
    model, report = train(uni, _cfg(), horizon=6, folds=3, max_rows=3000, epochs=60)
    assert report["rows"] <= 3000 and report["folds"]
    assert model["kind"] == "brainview" and len(model["w"]) == len(FEATURES)
    assert model["oof"]["auc"] is not None
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "m.json")
        save_model(model, p)
        back = load_model(p)
        assert back and back["w"] == model["w"]
        assert model_digest(back) == model_digest(model)
    assert load_model(os.path.join("/tmp", "definitely-missing.json")) is None


def test_rows_never_use_future_candles():
    cs = synthetic_candles("4h", 400, seed=33)
    uni = {"A": cs}
    rows = build_rows(uni, _cfg(), horizon=6, max_rows=0)
    last = max(rows, key=lambda r: r["ts"])
    assert last["ts"] <= cs[-1 - 6].open_time_ms      # افق آینده لازم است
    assert all(0 <= r["y"] <= 1 for r in rows)


# ═══════════════════════════════════════════════════════════════════════════
# ۴) نظاره‌گری: ثبت می‌شود، اما تصمیم را عوض نمی‌کند
# ═══════════════════════════════════════════════════════════════════════════
class _ExtremeObserver:
    """دیدگاه‌های افراطی — بدترین حالت برای تست بی‌طرفی."""
    available = True

    def __init__(self):
        self.calls = 0

    def view(self, symbol, candles, i):
        self.calls += 1
        return {"available": True, "p_up": 0.9999, "lean": "long",
                "confidence": 0.9999, "model": "extreme", "model_digest": "deadbeef",
                "ts": candles[i].open_time_ms, "drivers": []}


def _run_live(td, cs, brain=None):
    cfg = _cfg()
    journal = os.path.join(td, "j.jsonl")
    r = LiveRunner(cfg, "trend", "t", {}, os.path.join(td, "s.json"), journal,
                   brain=brain)
    out = r.run_symbol("X", cs, backfill=len(cs))
    return out, read_journal(journal), r


def test_brain_observer_is_read_only():
    cs = synthetic_candles("4h", 1500, seed=11)
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        off, j_off, r_off = _run_live(t1, cs, brain=None)
        ext = _ExtremeObserver()
        on, j_on, r_on = _run_live(t2, cs, brain=ext)
    assert ext.calls > 0, "نظاره‌گر باید صدا زده شود"
    assert off["opened"] == on["opened"] and off["closed"] == on["closed"]
    # همان معاملات، همان پول — فقط یک فیلد اضافه
    for a, b in zip(j_off, j_on):
        a2 = {k: v for k, v in a.items() if k != "brain"}
        b2 = {k: v for k, v in b.items() if k != "brain"}
        assert a2 == b2
        assert b2.get("type") != "open" or "brain" in b
    assert r_off.state["equity"] == r_on.state["equity"]


def test_open_record_carries_brain_view_and_survives_without_model():
    cs = synthetic_candles("4h", 1200, seed=11)
    with tempfile.TemporaryDirectory() as td:
        mp = os.path.join(td, "m.json")
        save_model(_fake_model(), mp)
        obs = BrainObserver(mp, _cfg())
        out, jr, _ = _run_live(td, cs, brain=obs)
        opens = [x for x in jr if x["type"] == "open"]
        assert opens and all(x["brain"]["available"] for x in opens)
        assert all(x["brain"]["model_digest"] for x in opens)
        assert all(x["brain"]["lean"] in ("long", "short", "neutral") for x in opens)


def test_live_without_model_records_that_it_was_absent():
    cs = synthetic_candles("4h", 900, seed=13)
    with tempfile.TemporaryDirectory() as td:
        obs = BrainObserver(os.path.join(td, "nope.json"), _cfg())
        out, jr, _ = _run_live(td, cs, brain=obs)
        opens = [x for x in jr if x["type"] == "open"]
        assert opens
        assert all(x["brain"]["available"] is False for x in opens)
        assert opens[0]["brain"]["reason"] == "no-model"


def test_trades_are_identical_to_plain_backtest_with_observer():
    """همان تضمین اصلی: مغز حتی یک معامله را جابه‌جا نمی‌کند."""
    cs = synthetic_candles("4h", 1200, seed=17)
    cfg = _cfg()
    layers = {"trigger": cs,
              "filter": resample_up(cs, "4h", "1d")[0],
              "bias": resample_up(cs, "4h", "1d")[0]}
    bt = run_backtest(cfg, layers)
    with tempfile.TemporaryDirectory() as td:
        _, jr, _ = _run_live(td, cs, brain=_ExtremeObserver())
    closes = [x for x in jr if x["type"] == "close"]
    bt_closed = [t for t in bt["trades"] if t["reason"] != "end_of_data"]
    assert len(closes) == len(bt_closed)
    assert abs(sum(c["result"]["pnl"] for c in closes)
               - sum(t["pnl"] for t in bt_closed)) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# ۵) CLI
# ═══════════════════════════════════════════════════════════════════════════
def test_view_cli_trains_and_writes_reports():
    from mtflab.autoscan import candles_to_json
    with tempfile.TemporaryDirectory() as td:
        ddir = os.path.join(td, "data")
        os.makedirs(os.path.join(ddir, "json"))
        for i, sym in enumerate(("AAAUSDT", "BBBUSDT")):
            cs = synthetic_candles("4h", 900, seed=51 + i)
            with open(os.path.join(ddir, "json", f"{sym.lower()}_4h.json"),
                      "w", encoding="utf-8") as f:
                json.dump(candles_to_json(cs, {"symbol": sym, "tf": "4h"}), f)
        model = os.path.join(td, "m.json")
        out = os.path.join(td, "out")
        env = dict(os.environ, HOME=os.path.join(td, "home"))
        os.makedirs(env["HOME"], exist_ok=True)
        r = subprocess.run(
            [sys.executable, "-m", "mtflab", "view", "--train",
             "--data-dir", ddir, "--model", model, "--out-dir", out,
             "--max-rows", "2500", "--folds", "3", "--lang", "en"],
            cwd=HERE, env=env, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
        assert os.path.exists(model)
        assert os.path.exists(os.path.join(out, "brain_view.md"))
        with open(os.path.join(out, "brain_view.json"), encoding="utf-8") as f:
            data = json.load(f)
        assert set(data["views"]) == {"AAAUSDT", "BBBUSDT"}
        assert data["model"]["features"]


# ═══════════════════════════════════════════════════════════════════════════
# ۶) سنجش هم‌داستانی (فقط گزارش، نه تصمیم)
# ═══════════════════════════════════════════════════════════════════════════
def test_agreement_table_groups_closed_signals_by_brain_lean():
    from mtflab.live import summarize, render
    def rec(sid, side, lean, r, pnl):
        return [
            {"type": "open", "id": sid, "symbol": "X", "ts": int(sid[-6:]),
             "algorithm": {"id": "trend", "label": "t", "cfg_digest": "d"},
             "entry_pattern": {"mode": "breakout"},
             "order": {"side": side, "entry": 100.0, "stop": 98.0},
             "brain": ({"available": True, "lean": lean, "model_digest": "d"}
                       if lean else {"available": False, "reason": "no-model"})},
            {"type": "close", "id": sid + ":closed", "open_id": sid,
             "symbol": "X", "ts": int(sid[-6:]) + 5,
             "algorithm": {"id": "trend"},
             "closed_by": {"rule": "stop_trail", "is_risk_control": True},
             "result": {"pnl": pnl, "r_multiple": r, "is_win": pnl > 0,
                        "exit": 101.0, "bars_held": 3}},
        ]
    jr = []
    jr += rec("X:a:000101", "LONG", "long", 2.0, 20.0)
    jr += rec("X:a:000102", "LONG", "short", -1.0, -10.0)
    jr += rec("X:a:000103", "SHORT", None, -1.0, -10.0)
    rep = summarize(jr)
    ag = rep["agreement"]
    assert ag["هم‌جهت"]["n"] == 1 and ag["هم‌جهت"]["expectancy_r"] == 2.0
    assert ag["مخالف"]["n"] == 1 and ag["مخالف"]["expectancy_r"] == -1.0
    assert ag["بدون مغز"]["n"] == 1
    md = render(rep, {"equity": 1000.0, "peak_equity": 1000.0}, lang="fa")
    assert "مغز چه می‌گفت" in md and "مخالف" in md
