"""تست‌های اتوترید مجازی و **انتساب کامل** سیگنال‌ها.

مهم‌ترین تست این فایل، `test_live_replay_matches_backtest` است: اگر پخش زنده
با بک‌تست یکی نباشد، هر آماری که از آن در بیاید بی‌اعتبار است. بقیهٔ تست‌ها
چیزهایی را قفل می‌کنند که کاربر صریح خواست:

  • هر سیگنال باید بگوید از **کدام الگوریتم** و **کدام الگو** آمده.
  • هر بستن باید بگوید **کدام قاعده** بستش و آیا آن قاعده برای کم‌کردن ضرر بود.
  • بستن باید به همان سیگنالِ باز **پیوند** داشته باشد (شناسهٔ یکتا).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                     # noqa: E402

from mtflab.config import MTFConfig                                 # noqa: E402
from mtflab.data import resample_up, synthetic_candles              # noqa: E402
from mtflab.engine import run_backtest                              # noqa: E402
from mtflab.live import (RULE_META, append_jsonl, cfg_digest,       # noqa: E402
                         load_state, normalize_reason, pos_from_state,
                         pos_to_state, read_journal, render, rule_meta,
                         save_state, summarize)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#: پیش‌فرض «روندکاوی» (همان که در `live --variant trend` روی داده واقعی می‌نشیند)
TREND = dict(bias_enabled=False, trigger_entry_modes=["breakout"],
             take_profit_atr_mult=50.0, trail_atr_mult=3.0, trail_start_r=1.0)


def _cfg(**over):
    """کانفیگ تست: فیلترهای نرم‌شده تا روی داده مصنوعی واقعاً سیگنال بسازد.

    فیلترهای سختِ پیش‌فرض (ADX/شیب) روی داده مصنوعی صفر معامله می‌دهند و آن‌وقت
    تستِ «زنده == بک‌تست» تهی از معنا می‌شود؛ پس عمداً بازشان می‌کنیم.
    """
    base = MTFConfig(data_mode="synthetic", tf_trigger="4h", tf_filter="1d",
                     tf_bias="1d", verbose=False, forensics=False, run_id="",
                     min_edge_multiplier=0.0, candles=1500, seed=11,
                     filter_adx_min=0.0, filter_slope_min_pct=0.0,
                     alignment_version="C", **TREND)
    return replace(base, **over) if over else base


def _candles(n=1500, seed=11):
    return synthetic_candles("4h", n, seed=seed)


# ═══════════════════════════════════════════════════════════════════════════
# ۱) انتساب: الگوریتم، الگو، و قاعدهٔ بستن
# ═══════════════════════════════════════════════════════════════════════════
def test_every_exit_rule_maps_to_a_known_attribution():
    """هیچ دلیلی نباید «ناشناس» بماند — وگرنه گزارش انتساب دروغ می‌شود."""
    for reason in ("stop_loss", "stop/trail", "breakeven", "take_profit",
                   "time_stop", "regime_flip_confirmed_3", "giveback",
                   "partial_take_1R", "end_of_data"):
        m = rule_meta(reason)
        assert m["rule"] in RULE_META, (reason, m)
        assert m["fa"] and m["en"]


def test_stop_rules_are_flagged_as_loss_reduction():
    """خواستهٔ کاربر: «اگر الگویی برای ضرر کمتر گذاشتیم، مشخص باشد»."""
    for r in ("stop_loss", "stop/trail", "breakeven", "giveback",
              "regime_flip_confirmed_2"):
        assert rule_meta(r)["is_risk_control"] is True, r
    for r in ("take_profit", "end_of_data"):
        assert rule_meta(r)["is_risk_control"] is False, r


def test_reason_normalisation_handles_engine_variants():
    assert normalize_reason("stop/trail") == "stop_trail"
    assert normalize_reason("regime_flip_confirmed_5") == "regime_flip"
    assert normalize_reason("partial_take_1R") == "partial_take"
    assert normalize_reason("") == "unknown"


def test_cfg_digest_changes_when_parameters_change():
    a = cfg_digest({"trail_atr_mult": 3.0})
    b = cfg_digest({"trail_atr_mult": 4.0})
    assert a != b and len(a) == 10


# ═══════════════════════════════════════════════════════════════════════════
# ۲) وضعیت ماندگار
# ═══════════════════════════════════════════════════════════════════════════
def test_state_roundtrip_survives_position_serialisation():
    cs = _candles(50)
    from mtflab.engine import Position
    pos = Position(symbol="X", direction=1, entry=100.0, qty=1.0, notional=100.0,
                   stop_initial=98.0, take=130.0, stop_current=99.0, high_water=101.0,
                   low_water=99.5, open_ts=cs[3].open_time_ms, open_bar=3,
                   confidence=0.7, score=0.6, risk_amount=2.0, equity_before=1000.0,
                   initial_qty=1.0, path=[{"ts": 1, "c": 100.0}])
    back = pos_from_state(pos_to_state(pos))
    assert back.symbol == "X" and back.entry == 100.0
    assert back.stop_current == 99.0 and back.open_ts == pos.open_ts
    assert back.path == [{"ts": 1, "c": 100.0}]


def test_state_file_is_written_atomically_and_read_back():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "state.json")
        st = load_state(p)
        assert st["counters"]["signals"] == 0
        st["equity"] = 1234.5
        save_state(p, st)
        assert load_state(p)["equity"] == 1234.5
        assert not os.path.exists(p + ".tmp")


def test_corrupt_journal_line_is_skipped_not_fatal():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "j.jsonl")
        append_jsonl(p, {"type": "open", "id": "a"})
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"type": "close", "id": trunca')     # قطعی وسط نوشتن
        append_jsonl(p, {"type": "close", "id": "b"})
        recs = read_journal(p)
        assert [r["id"] for r in recs] == ["a", "b"]


# ═══════════════════════════════════════════════════════════════════════════
# ۳) مهم‌ترین: پخش زنده == بک‌تست
# ═══════════════════════════════════════════════════════════════════════════
def test_live_replay_matches_backtest():
    """همان داده، همان موتور: تعداد معامله، سود و دلیل خروج باید یکی باشد."""
    from mtflab.live import LiveRunner

    cs = _candles(1500, seed=11)
    cfg = _cfg(min_edge_multiplier=0.0)
    layers = {"trigger": cs,
              "filter": resample_up(cs, "4h", "1d")[0],
              "bias": resample_up(cs, "4h", "1d")[0]}
    bt = run_backtest(cfg, layers)

    with tempfile.TemporaryDirectory() as td:
        runner = LiveRunner(cfg, "trend", "test", {}, os.path.join(td, "s.json"),
                            os.path.join(td, "j.jsonl"))
        r = runner.run_symbol("X", cs, backfill=len(cs))
        jr = read_journal(os.path.join(td, "j.jsonl"))
    opens = [x for x in jr if x["type"] == "open"]
    closes = [x for x in jr if x["type"] == "close"]
    assert len(opens) == len(bt["trades"]), (len(opens), len(bt["trades"]))
    assert r["closed"] == len(closes)

    # بک‌تست در آخرین کندل پوزیشنِ باز را با «پایان داده» می‌بندد؛ زندگی واقعی
    # چنین بستنی ندارد. پس مقایسه فقط روی معاملاتِ **واقعاً بسته‌شده** است...
    bt_closed = [t for t in bt["trades"] if normalize_reason(t["reason"]) != "end_of_data"]
    assert len(closes) == len(bt_closed), (len(closes), len(bt_closed))
    bt_pnl = sum(t["pnl"] for t in bt_closed)
    live_pnl = sum(c["result"]["pnl"] for c in closes)
    assert abs(bt_pnl - live_pnl) < 0.01, (bt_pnl, live_pnl)
    bt_reasons = sorted(normalize_reason(t["reason"]) for t in bt_closed)
    lv_reasons = sorted(c["closed_by"]["rule"] for c in closes)
    assert bt_reasons == lv_reasons

    # ...و پوزیشنِ آخری که در بک‌تست «پایان داده» خورد، در پخش زنده باید
    # هنوز باز بماند و با همان قیمت ورود در حالت ذخیره شده باشد.
    still = [t for t in bt["trades"] if normalize_reason(t["reason"]) == "end_of_data"]
    held = runner.state["open"]
    if still:
        assert len(held) == 1, held
        assert abs(held[0]["entry"] - still[-1]["entry"]) < 1e-4, (held[0]["entry"], still[-1]["entry"])
        assert held[0]["symbol"] == "X"       # نماد باید همان باشد، نه پیش‌فرض موتور


def test_second_run_does_not_reopen_the_same_bars():
    """اجرای دوباره روی همان داده نباید سیگنال تکراری بسازد."""
    from mtflab.live import LiveRunner
    cs = _candles(1200, seed=13)
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as td:
        sp, jp = os.path.join(td, "s.json"), os.path.join(td, "j.jsonl")
        r1 = LiveRunner(cfg, "trend", "t", {}, sp, jp)
        a = r1.run_symbol("X", cs, backfill=len(cs))
        r1.save()
        r2 = LiveRunner(cfg, "trend", "t", {}, sp, jp)
        b = r2.run_symbol("X", cs, backfill=len(cs))
        r2.save()
    assert a["opened"] > 0
    assert b["new_bars"] == 0 and b["opened"] == 0


def test_incremental_runs_equal_one_big_run():
    """سه اجرای پشت‌سرهم = یک اجرای کامل (حالت باید کامل بازیابی شود)."""
    from mtflab.live import LiveRunner
    cs = _candles(1200, seed=17)
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as td:
        sp, jp = os.path.join(td, "s.json"), os.path.join(td, "j.jsonl")
        one = LiveRunner(cfg, "trend", "t", {}, os.path.join(td, "s1.json"),
                         os.path.join(td, "j1.jsonl"))
        full = one.run_symbol("X", cs, backfill=len(cs))
        for cut in (700, 900, 1200):
            r = LiveRunner(cfg, "trend", "t", {}, sp, jp)
            r.run_symbol("X", cs[:cut], backfill=len(cs))
            r.save()
        jr_a = read_journal(os.path.join(td, "j1.jsonl"))
        jr_b = read_journal(jp)
    a_pnl = sum(x["result"]["pnl"] for x in jr_a if x["type"] == "close")
    b_pnl = sum(x["result"]["pnl"] for x in jr_b if x["type"] == "close")
    assert full["opened"] > 0
    # پوزیشن‌های باز در پایان ممکن است متفاوت باشند، ولی معاملات بسته‌شده باید نزدیک باشند
    assert abs(a_pnl - b_pnl) < max(5.0, abs(a_pnl) * 0.05), (a_pnl, b_pnl)


# ═══════════════════════════════════════════════════════════════════════════
# ۴) محتوای سند سیگنال
# ═══════════════════════════════════════════════════════════════════════════
def test_open_record_carries_full_attribution():
    from mtflab.live import LiveRunner
    cs = _candles(1200, seed=19)
    with tempfile.TemporaryDirectory() as td:
        r = LiveRunner(_cfg(), "trend", "روندکاوی", {"trail_atr_mult": 3.0},
                       os.path.join(td, "s.json"), os.path.join(td, "j.jsonl"))
        r.run_symbol("BTCUSDT", cs, backfill=len(cs))
        jr = read_journal(os.path.join(td, "j.jsonl"))
    opens = [x for x in jr if x["type"] == "open"]
    assert opens, "هیچ سیگنالی ساخته نشد"
    o = opens[0]
    assert o["algorithm"]["id"] == "trend"
    assert o["algorithm"]["label"] == "روندکاوی"
    assert o["algorithm"]["cfg_digest"] and o["algorithm"]["tf"] == "4h/1d/1d"
    assert o["entry_pattern"]["mode"] in ("breakout", "pullback")
    assert "trigger_reason" in o["entry_pattern"]
    assert o["layers"]["filter"]["dir"] in (-1, 0, 1)
    assert o["context"]["structure"] in (-1, 0, 1)
    assert o["order"]["entry"] > 0 and o["order"]["stop"] > 0
    assert o["order"]["side"] in ("LONG", "SHORT")


def test_close_record_links_back_to_its_open_signal():
    from mtflab.live import LiveRunner
    cs = _candles(1500, seed=23)
    with tempfile.TemporaryDirectory() as td:
        r = LiveRunner(_cfg(), "trend", "t", {}, os.path.join(td, "s.json"),
                       os.path.join(td, "j.jsonl"))
        r.run_symbol("BTCUSDT", cs, backfill=len(cs))
        jr = read_journal(os.path.join(td, "j.jsonl"))
    opens = {x["id"] for x in jr if x["type"] == "open"}
    closes = [x for x in jr if x["type"] == "close"]
    assert closes, "هیچ معامله‌ای بسته نشد"
    for c in closes:
        assert c["open_id"] in opens, (c["open_id"], list(opens)[:3])
        assert c["closed_by"]["rule"] in RULE_META
        assert "is_risk_control" in c["closed_by"]
        assert c["result"]["r_multiple"] is not None


def test_engine_state_roundtrip_keeps_cooldown_and_vetoes():
    """cool-down/فیوز با **زمان** ذخیره می‌شوند و شمارندهٔ «چرا وارد نشد» هم می‌ماند."""
    from mtflab.alignment import AlignedBar
    from mtflab.engine import MTFEngine
    from mtflab.live import _restore_engine, engine_state
    cs = _candles(60, seed=11)
    eng = MTFEngine(_cfg(), None, None)
    bars = [AlignedBar(low_tf_candle=c, higher_tf_candle=c, bias_tf_candle=c)
            for c in cs]
    eng.cooldown_until_bar = 10
    eng.cb_until_bar = 7
    eng.filter_flip_streak = 3
    eng.veto_stats["slots"] = 4
    saved = engine_state(eng, bars)
    assert saved["cooldown_until_ts"] == cs[10].open_time_ms
    assert saved["veto_stats"]["slots"] == 4

    fresh = MTFEngine(_cfg(), None, None)
    _restore_engine(fresh, saved, bars)
    assert fresh.cooldown_until_bar == 10 and fresh.cb_until_bar == 7
    assert fresh.filter_flip_streak == 3
    assert fresh.veto_stats["slots"] == 4


def test_report_lists_recent_signals_with_their_closing_rule():
    """جدول «آخرین سیگنال‌ها» باید شناسه، قاعدهٔ بست و پرچم ضدضرر را نشان دهد."""
    from mtflab.live import LiveRunner
    cs = _candles(1500, seed=23)
    with tempfile.TemporaryDirectory() as td:
        r = LiveRunner(_cfg(), "trend", "t", {}, os.path.join(td, "s.json"),
                       os.path.join(td, "j.jsonl"))
        r.run_symbol("BTCUSDT", cs, backfill=len(cs))
        jr = read_journal(os.path.join(td, "j.jsonl"))
    rep = summarize(jr)
    assert rep["recent"], "جدول سیگنال‌های اخیر خالی است"
    r0 = rep["recent"][0]
    assert r0["signal_id"] and r0["rule"] in RULE_META
    assert r0["is_risk_control"] in (True, False)
    assert r0["r_multiple"] is not None and r0["pnl"] is not None
    txt = render(rep, r.state, lang="fa")
    assert "آخرین سیگنال‌های بسته‌شده" in txt
    assert "stop_loss" in txt or "stop_trail" in txt


# ═══════════════════════════════════════════════════════════════════════════
# ۵) گزارش رصد
# ═══════════════════════════════════════════════════════════════════════════
def test_summary_counts_by_algorithm_and_by_rule():
    from mtflab.live import LiveRunner
    cs = _candles(1500, seed=29)
    with tempfile.TemporaryDirectory() as td:
        r = LiveRunner(_cfg(), "trend", "t", {}, os.path.join(td, "s.json"),
                       os.path.join(td, "j.jsonl"))
        r.run_symbol("BTCUSDT", cs, backfill=len(cs))
        r.save()
        jr = read_journal(os.path.join(td, "j.jsonl"))
        rep = summarize(jr)
        md = render(rep, r.state, lang="fa")
        en = render(rep, r.state, lang="en")
    assert rep["opens"] > 0 and rep["closes"] > 0
    assert "trend" in rep["by_algorithm"]
    assert sum(e["count"] for e in rep["by_rule"].values()) == rep["closes"]
    assert "کدام قاعده بست" in md
    assert "Which rule closed it" in en
    assert "✅ بله" in md or "—" in md


def test_open_position_is_never_silently_dropped_when_window_shrinks():
    """اگر کندلِ ورود از پنجرهٔ داده بیرون بیفتد، پوزیشن نباید غیب شود.

    این حالت وقتی رخ می‌دهد که با `--days` کوچک‌تر اجرا کنی و یک پوزیشنِ باز
    قدیمی‌تر از پنجره داشته باشی. پوزیشن باید در حالت بماند (با `restore_gap`)
    و همچنان یک جایگاه را اشغال کند، وگرنه ممکن است دوبار وارد شود.
    """
    from mtflab.live import LiveRunner
    cs = _candles(1500, seed=11)
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as td:
        sp, jp = os.path.join(td, "s.json"), os.path.join(td, "j.jsonl")
        r = LiveRunner(cfg, "trend", "t", {}, sp, jp)
        r.run_symbol("X", cs, backfill=len(cs))
        r.save()
        # پوزیشنِ باز را دستی به گذشته ببر تا بیرون از پنجرهٔ بعدی بیفتد
        assert r.state["open"], "برای این تست باید یک پوزیشن باز بماند"
        st = load_state(sp)
        st["open"][0]["open_ts"] = cs[0].open_time_ms - 999 * 3_600_000
        st["engine"] = {}                       # مثل حالتی که وضعیت موتور نیست
        save_state(sp, st)

        r2 = LiveRunner(cfg, "trend", "t", {}, sp, jp)
        out = r2.run_symbol("X", cs[-50:], backfill=0)
        assert out["restore_gap"] == 1, out
        assert len(r2.state["open"]) == 1, r2.state["open"]
        # با `backfill=0` و پنجرهٔ کوتاه، کندل تازه‌ای نیست؛ پس ورود تازه هم نباید باشد
        assert out["opened"] == 0, out


def test_summary_of_empty_journal_is_safe():
    rep = summarize([])
    assert rep["opens"] == 0 and rep["closes"] == 0
    render(rep, {"equity": 1000.0, "peak_equity": 1000.0}, lang="fa")


# ═══════════════════════════════════════════════════════════════════════════
# ۶) اجرای واقعی اسکریپت با کش محلی
# ═══════════════════════════════════════════════════════════════════════════
def test_live_cli_runs_offline_from_cache_and_writes_reports():
    if not shutil.which("bash"):
        return
    from mtflab.autoscan import candles_to_json
    with tempfile.TemporaryDirectory() as td:
        data = os.path.join(td, "data")
        os.makedirs(os.path.join(data, "json"))
        for i, sym in enumerate(("AAAUSDT", "BBBUSDT")):
            cs = synthetic_candles("4h", 1500, seed=31 + i)
            with open(os.path.join(data, "json", f"{sym.lower()}_4h.json"),
                      "w", encoding="utf-8") as f:
                json.dump(candles_to_json(cs, {"symbol": sym, "tf": "4h",
                                               "days": 250}), f)
        out = os.path.join(td, "out")
        state = os.path.join(td, "live", "state.json")
        journal = os.path.join(td, "live", "journal.jsonl")
        env = dict(os.environ, HOME=os.path.join(td, "home"))
        os.makedirs(os.path.join(td, "home"), exist_ok=True)
        r = subprocess.run(
            [sys.executable, "-m", "mtflab", "live", "--offline",
             "--data-dir", data, "--symbols", "AAAUSDT", "BBBUSDT",
             "--backfill", "400", "--state", state, "--journal", journal,
             "--out-dir", out, "--lang", "en"],
            cwd=HERE, env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        assert os.path.exists(os.path.join(out, "live_report.md"))
        assert os.path.exists(os.path.join(out, "live_report.json"))
        recs = read_journal(journal)
        assert any(x["type"] == "open" for x in recs)

        # اجرای دوم: وضعیت باید ادامه پیدا کند، نه از صفر شروع شود
        r2 = subprocess.run(
            [sys.executable, "-m", "mtflab", "live", "--offline",
             "--data-dir", data, "--symbols", "AAAUSDT", "BBBUSDT",
             "--state", state, "--journal", journal, "--out-dir", out,
             "--lang", "en"], cwd=HERE, env=env, capture_output=True, text=True,
            timeout=300)
        assert r2.returncode == 0, (r2.stdout + r2.stderr)[-2000:]
        assert "new bars: 0" in r2.stdout or "کندل تازه: 0" in r2.stdout
