"""تست‌های «سلامت سیستم»: چرا سیگنالی نیست؟

هدف کاربر روشن است: وقتی سیگنالی نیست باید بتواند «کار می‌کند» را از «خراب
است» تشخیص دهد. پس چهار چیز باید دقیق باشد: ساعت کندل، تازگی داده، گرم‌کردن
لایه‌ها، و حکمی که این‌ها را با دروازه‌های واقعی موتور ترکیب می‌کند.
"""
import json
import os
import sys
import tempfile
import time
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import health                                       # noqa: E402
from mtflab.config import load_config                           # noqa: E402
from mtflab.data import Candle, synthetic_candles, tf_to_ms      # noqa: E402


def _cfg(**kw):
    c = load_config(["--data", "synthetic", "--quiet"])
    base = dict(verbose=False, forensics=False, run_id="", symbol="",
                tf_trigger="4h", tf_filter="1d", tf_bias="1d")
    base.update(kw)
    return replace(c, **base)


def _ms(s: str) -> int:
    """«2026-01-01T10:00:00Z» → میلی‌ثانیه"""
    return int(time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) * 1000)


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ساعت کندل
# ══════════════════════════════════════════════════════════════════════════
def test_candle_clock_boundaries():
    now = _ms("2026-01-01T10:00:00Z")
    c = health.candle_clock("4h", now_ms=now)
    step = tf_to_ms("4h")
    assert c["forming_open_ms"] == now - (now % step)          # کندل ۰۸–۱۲
    assert c["last_closed_open_ms"] == c["forming_open_ms"] - step   # ۰۴–۰۸
    assert c["next_close_ms"] == c["forming_open_ms"] + step
    assert c["seconds_to_next"] == 2 * 3600
    assert c["step_minutes"] == 240


def test_candle_clock_right_before_close():
    now = _ms("2026-01-01T11:59:30Z")
    c = health.candle_clock("4h", now_ms=now)
    assert 0 < c["seconds_to_next"] <= 60


# ══════════════════════════════════════════════════════════════════════════
#  ۲) گرم‌کردن
# ══════════════════════════════════════════════════════════════════════════
def test_warmup_ready_with_long_history():
    w = health.warmup_status(synthetic_candles("4h", 1600, seed=301), _cfg())
    assert w["ok"] is True
    rows = {r["layer"]: r for r in w["rows"]}
    assert rows["trigger"]["have"] == 1600
    assert rows["bias"]["have"] > 200 and rows["bias"]["ready"]


def test_warmup_short_history_is_reported_with_numbers():
    w = health.warmup_status(synthetic_candles("4h", 120, seed=301), _cfg())
    assert w["ok"] is False
    miss = {r["layer"]: r for r in w["missing"]}
    assert "bias" in miss and miss["bias"]["shortfall"] > 0
    assert miss["bias"]["need"] > miss["bias"]["have"]


# ══════════════════════════════════════════════════════════════════════════
#  ۳) تازگی داده و دروازه‌ها برای یک نماد
# ══════════════════════════════════════════════════════════════════════════
def test_symbol_status_counts_behind_bars():
    cs = synthetic_candles("4h", 300, seed=303)
    step = tf_to_ms("4h")
    # سه کندل بعد از آخرین کندلِ کش: یعنی داده ۲ کندل از «آخرین بسته» عقب است
    clock = health.candle_clock("4h", now_ms=int(cs[-1].open_time_ms) + 3 * step + 10)
    r = health.symbol_status("BTCUSDT", cs, _cfg(), clock)
    assert r["behind_bars"] == 2 and r["fresh"] is False, r
    # یک کندل بعد از آخرین کندل: همان لحظه، داده به‌روز است
    clock2 = health.candle_clock("4h", now_ms=int(cs[-1].open_time_ms) + step + 10)
    r2 = health.symbol_status("BTCUSDT", cs, _cfg(), clock2)
    assert r2["fresh"] is True and r2["behind_bars"] == 0
    assert {g["id"] for g in r2["gates"]} >= {"bias", "filter", "trigger", "cost"}


def test_pending_bars_respect_state():
    cs = synthetic_candles("4h", 300, seed=303)
    clock = health.candle_clock("4h", now_ms=int(cs[-1].open_time_ms) + tf_to_ms("4h") + 10)
    r = health.symbol_status("BTCUSDT", cs, _cfg(), clock, last_bar_ms=cs[-4].open_time_ms)
    assert r["pending_bars"] == 3


# ══════════════════════════════════════════════════════════════════════════
#  ۴) حکم: اولویت‌ها
# ══════════════════════════════════════════════════════════════════════════
def _row(state="دور", fresh=True, behind=0, bars=500, readiness=0.4):
    return {"symbol": "X", "bars": bars, "fresh": fresh, "behind_bars": behind,
            "state": state, "readiness": readiness, "blocking": "—"}


def test_verdict_priority_order():
    clock = health.candle_clock("4h", now_ms=_ms("2026-01-01T10:00:00Z"))
    ok_warm = {"ok": True, "rows": [], "missing": []}
    assert health.verdict([], ok_warm, clock)["code"] == "no_data"
    assert health.verdict([_row(bars=0)], ok_warm, clock)["code"] == "no_data"
    assert health.verdict([_row(fresh=False, behind=5)], ok_warm, clock)["code"] == "stale"
    assert health.verdict([_row()], {"ok": False, "missing": [
        {"layer": "bias", "have": 10, "need": 200, "tf": "1d"}]}, clock)["code"] == "warmup"
    assert health.verdict([_row(state="سیگنال")], ok_warm, clock)["code"] == "signal"
    assert health.verdict([_row(state="نزدیک", readiness=0.8)], ok_warm,
                          clock)["code"] == "idle_near"
    v = health.verdict([_row()], ok_warm, clock)
    assert v["code"] == "idle" and "منتظر کندل بعدی" in v["label"]


# ══════════════════════════════════════════════════════════════════════════
#  ۵) وضعیت کامل + ژورنال
# ══════════════════════════════════════════════════════════════════════════
def test_system_health_reports_journal_and_heartbeat():
    with tempfile.TemporaryDirectory() as td:
        j = os.path.join(td, "journal.jsonl")
        st = os.path.join(td, "state.json")
        with open(j, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "open", "ts": 1000}) + "\n")
            f.write(json.dumps({"type": "close", "ts": 2000}) + "\n")
        with open(st, "w", encoding="utf-8") as f:
            json.dump({"symbols": {"BTCUSDT": {"last_bar_ms": 5000}},
                       "variant": "base", "equity": 1000.0}, f)
        cs = synthetic_candles("4h", 400, seed=303)
        h = health.system_health({"BTCUSDT": cs}, _cfg(), state_path=st, journal_path=j)
        assert h["journal"]["opens"] == 1 and h["journal"]["closes"] == 1
        assert h["heartbeat"]["last_processed"]["BTCUSDT"] == 5000
        assert h["verdict"]["code"] in ("stale", "warmup", "idle", "idle_near", "signal")
        assert h["rows"][0]["bars"] == 400


def test_render_contains_countdown_and_gates():
    cs = synthetic_candles("4h", 400, seed=303)
    h = health.system_health({"BTCUSDT": cs}, _cfg())
    txt = health.render_text(h)
    assert "سلامت سیستم" in txt and "کندل 4h" in txt
    assert "گرم‌کردن لایه‌ها" in txt


def test_cli_health_without_data_returns_2():
    with tempfile.TemporaryDirectory() as td:
        assert health.health_command(["--data-dir", td]) == 2


def test_cli_health_with_cache_returns_0():
    from mtflab.autoscan import candles_to_json
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "json"))
        cs = synthetic_candles("4h", 400, seed=303)
        with open(os.path.join(td, "json", "btcusdt_4h.json"), "w", encoding="utf-8") as f:
            json.dump(candles_to_json(cs, {"symbol": "BTCUSDT", "tf": "4h"}), f)
        assert health.health_command(["--data-dir", td, "--tf", "4h"]) == 0


def test_dashboard_shows_health_card_and_route():
    from mtflab import labweb
    assert 'id="sysHealth"' in labweb.PAGE
    assert '"sysCount"' in labweb.PAGE
    src = open(labweb.__file__, encoding="utf-8").read()
    assert '"/api/system"' in src
    assert "system_health" in src
