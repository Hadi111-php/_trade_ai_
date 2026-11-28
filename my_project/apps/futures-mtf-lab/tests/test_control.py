"""تست‌های «گزارش کنترل»: یک دستور، یک فایل، برای فرستادن به بازبین.

سه چیز باید تضمین شود:
۱) فایل‌ها واقعاً ساخته می‌شوند و اعدادِ داخلشان از `health`/`ops` می‌آیند
   (نه عدد دستی و نه عدد ساختگی).
۲) گزارش **هیچ‌چیز** را در ژورنال/`state` تغییر نمی‌دهد — هش قبل و بعد یکی است.
۳) حالت‌های خراب (بدون داده، عقب‌ماندگی، ژورنال خالی) به‌جای پنهان‌شدن،
   در چک‌لیست به‌صورت ❌/⚠️ دیده می‌شوند.
"""
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import control                                       # noqa: E402
from mtflab.config import load_config                            # noqa: E402
from mtflab.data import synthetic_candles                        # noqa: E402


def _cfg(**kw):
    c = load_config(["--data", "synthetic", "--quiet"])
    base = dict(verbose=False, forensics=False, run_id="", symbol="",
                tf_trigger="4h", tf_filter="1d", tf_bias="1d")
    base.update(kw)
    return replace(c, **base)


def _uni(n=400):
    return {"BTCUSDT": synthetic_candles("4h", n, seed=11),
            "ETHUSDT": synthetic_candles("4h", n, seed=12)}


def _now_after(uni):
    """«الان» را یک گام بعد از آخرین کندل می‌گذاریم تا داده تازه شمرده شود."""
    last = max(c[-1].open_time_ms for c in uni.values())
    return int(last) + 4 * 3600 * 1000 + 10


def _journal(path, n=2):
    """ژورنال مینیمال با یک بسته — فقط برای شمارش، نه برای آمار."""
    rows = []
    for i in range(n):
        rows.append({"id": f"t{i}", "symbol": "BTCUSDT", "side": "LONG",
                     "status": "closed" if i == 0 else "open",
                     "entry_ms": 1_700_000_000_000 + i, "r": 0.5})
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return path


def _hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ══════════════════════════════════════════════════════════════════════════
#  ۱) ساخت فایل و محتوا
# ══════════════════════════════════════════════════════════════════════════
def test_collect_writes_md_and_json():
    with tempfile.TemporaryDirectory() as td:
        jp = _journal(os.path.join(td, "journal.jsonl"))
        rep = control.collect(_uni(), _cfg(), state_path=os.path.join(td, "state.json"),
                              journal_path=jp, out_dir=os.path.join(td, "out"))
        p = rep["paths"]
        assert os.path.isfile(p["md"]) and os.path.isfile(p["json"])
        assert p["stem"].startswith("control_")
        md = open(p["md"], encoding="utf-8").read()
        assert "گزارش کنترل" in md and "چک‌لیست" in md
        # نمادها با عدد واقعی، نه صفر
        assert "BTCUSDT" in md and "400" in md   # تعداد کندل واقعی، نه صفر
        data = json.load(open(p["json"], encoding="utf-8"))
        assert data["version"] == control.VERSION
        assert len(data["health"]["rows"]) == 2


def test_sha_matches_files():
    with tempfile.TemporaryDirectory() as td:
        rep = control.collect(_uni(), _cfg(), out_dir=os.path.join(td, "out"))
        p = rep["paths"]
        assert p["sha256"]["md"] == control.sha256_of(p["md"])
        assert p["sha256"]["json"] == control.sha256_of(p["json"])


def test_checks_reflect_real_health_numbers():
    with tempfile.TemporaryDirectory() as td:
        uni = _uni(1600)          # بایاس ۱d به ۲۰۰ کندل روزانه نیاز دارد
        rep = control.collect(uni, _cfg(), out_dir=os.path.join(td, "out"),
                              now_ms=_now_after(uni))
        by = {c["name"]: c for c in rep["checks"]}
        # «الان» یک گام بعد از آخرین کندل است ⇒ تازگی باید ✅ باشد
        assert by["تازگی داده"]["ok"] is True
        assert by["گرم‌شدن لایه‌ها"]["ok"] is True
        assert "trigger" in by["گرم‌شدن لایه‌ها"]["detail"]
        assert by["حکم"]["ok"] is True


# ══════════════════════════════════════════════════════════════════════════
#  ۲) بی‌اثر بودن
# ══════════════════════════════════════════════════════════════════════════
def test_no_writes_to_journal_or_state():
    with tempfile.TemporaryDirectory() as td:
        jp = _journal(os.path.join(td, "journal.jsonl"))
        sp = os.path.join(td, "state.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"symbols": {}, "equity": 1000.0}, f)
        h_j, h_s = _hash(jp), _hash(sp)
        control.collect(_uni(), _cfg(), state_path=sp, journal_path=jp,
                        out_dir=os.path.join(td, "out"))
        assert _hash(jp) == h_j and _hash(sp) == h_s


def test_write_false_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out")
        rep = control.collect(_uni(120), _cfg(), out_dir=out, write=False)
        assert not os.path.exists(out)
        assert "paths" not in rep
        assert rep["checks"]


# ══════════════════════════════════════════════════════════════════════════
#  ۳) حالت‌های خراب پنهان نمی‌شوند
# ══════════════════════════════════════════════════════════════════════════
def test_empty_universe_is_reported_not_faked():
    with tempfile.TemporaryDirectory() as td:
        rep = control.collect({}, _cfg(), data_dir=os.path.join(td, "nope"),
                              out_dir=os.path.join(td, "out"))
        by = {c["name"]: c for c in rep["checks"]}
        assert by["داده در کش"]["ok"] is False
        assert by["تازگی داده"]["ok"] is False
        assert by["حکم"]["ok"] is False
        assert rep["ok"] is False
        md = open(rep["paths"]["md"], encoding="utf-8").read()
        assert "❌" in md and "no_data" in md


def test_stale_data_is_flagged():
    with tempfile.TemporaryDirectory() as td:
        # کندل‌های قدیمی (۲۰۲۱) ⇒ باید «عقب» را نشان دهد
        uni = {"BTCUSDT": synthetic_candles("4h", 300, seed=5)}   # شروع ۲۰۲۳ ⇒ کهنه
        rep = control.collect(uni, _cfg(), out_dir=os.path.join(td, "out"))
        by = {c["name"]: c for c in rep["checks"]}
        assert by["تازگی داده"]["ok"] is False
        row = rep["health"]["rows"][0]
        assert row["behind_bars"] > 0 and row["fresh"] is False


def test_empty_journal_is_warning_not_failure():
    with tempfile.TemporaryDirectory() as td:
        rep = control.collect(_uni(120), _cfg(), journal_path=os.path.join(td, "none.jsonl"),
                              out_dir=os.path.join(td, "out"))
        by = {c["name"]: c for c in rep["checks"]}
        assert by["ژورنال"]["ok"] is None        # ⚠️ نه ❌
        assert "0 باز" in by["ژورنال"]["detail"]


def test_pending_processing_is_detected():
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "state.json")
        # state می‌گوید تا یک کندل قبل پردازش شده ⇒ باید «عقب» پیدا شود
        first = int(_uni(5)["BTCUSDT"][-3].open_time_ms)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"symbols": {"BTCUSDT": {"last_bar_ms": first}}}, f)
        rep = control.collect(_uni(), _cfg(), state_path=sp, out_dir=os.path.join(td, "out"))
        by = {c["name"]: c for c in rep["checks"]}
        assert by["پردازش تا آخرین کندل"]["ok"] is False
        assert "BTCUSDT" in by["پردازش تا آخرین کندل"]["detail"]


# ══════════════════════════════════════════════════════════════════════════
#  ۴) CLI و داشبورد
# ══════════════════════════════════════════════════════════════════════════
def test_cli_stdout_mode_prints_markdown(capsys=None):
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = control.control_command(["--data-dir", os.path.join(td, "nope"),
                                          "--out", os.path.join(td, "out"),
                                          "--stdout"])
        out = buf.getvalue()
        assert rc == 1                                  # داده نیست ⇒ کد ۱
        assert "گزارش کنترل" in out and "چک‌لیست" in out
        assert not os.path.exists(os.path.join(td, "out"))


def test_cli_writes_files_and_prints_paths(tmp_path=None):
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            control.control_command(["--data-dir", os.path.join(td, "nope"),
                                     "--out", td])
        out = buf.getvalue()
        assert "📄" in out and "sha256" in out
        assert any(n.endswith(".md") for n in os.listdir(td))
        assert any(n.endswith(".json") for n in os.listdir(td))


def test_dashboard_route_and_button_exist():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "mtflab", "labweb.py"), encoding="utf-8").read()
    assert "/api/control" in src
    assert "/api/control/file" in src
    assert 'id="opsControl"' in src
    assert "control_report" in src


def test_run_auto_flag_and_main_dispatch():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sh = open(os.path.join(root, "run-auto.sh"), encoding="utf-8").read()
    assert "--control|--report)" in sh and "-m mtflab control" in sh
    mn = open(os.path.join(root, "mtflab", "__main__.py"), encoding="utf-8").read()
    assert '"control", "report"' in mn and "control_command" in mn


def test_run_auto_has_evaluate_flag():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sh = open(os.path.join(root, "run-auto.sh"), encoding="utf-8").read()
    assert "--evaluate|--eval)" in sh
    # گام‌ها به ترتیب و با همان ابزارهای موجود
    for piece in ("-m mtflab ops --probe", "-m mtflab ops --sync",
                  "-m mtflab live --offline --backfill 400", "-m mtflab health",
                  "-m mtflab control"):
        assert piece in sh, piece
    assert "--offline" in sh


def test_health_and_control_tolerate_lang_flag():
    """run-auto روی ترمکس خودش `--lang en` اضافه می‌کند؛ نباید آرگومان‌خطا بدهد."""
    import contextlib
    import io
    from mtflab import health
    with tempfile.TemporaryDirectory() as td:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = health.health_command(["--data-dir", os.path.join(td, "nope"),
                                        "--lang", "en"])
        assert rc == 2                      # «داده نیست»، نه خطای argparse
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = control.control_command(["--data-dir", os.path.join(td, "nope"),
                                           "--out", td, "--lang", "en"])
        assert rc2 == 1
        assert "گزارش کنترل" in buf2.getvalue()


# ══════════════════════════════════════════════════════════════════════════
#  ۵) گزارشِ واقعیِ گوشی: «۳۰ روز داده داری، ۱۷۱ روز کم است»
# ══════════════════════════════════════════════════════════════════════════
def test_days_needed_matches_phone_report():
    """دقیقاً همان ردیف‌های گزارش کاربر: bias(1d) 29/200 و filter(1d) 29/50."""
    missing = [{"layer": "filter", "tf": "1d", "shortfall": 21},
               {"layer": "bias", "tf": "1d", "shortfall": 171}]
    assert control._days_needed(missing) == 171
    # روی ۴h، ۲۱ کندل یعنی ~۳.۵ روز ⇒ ۴ روز
    assert control._days_needed([{"layer": "x", "tf": "4h", "shortfall": 21}]) == 4
    assert control._days_needed([]) == 0


def test_warmup_check_tells_how_many_days_to_download():
    with tempfile.TemporaryDirectory() as td:
        uni = {s: synthetic_candles("4h", 180, seed=40 + i)
               for i, s in enumerate(("BTCUSDT", "ETHUSDT"))}
        rep = control.collect(uni, _cfg(), out_dir=os.path.join(td, "out"),
                              now_ms=_now_after(uni))
        by = {c["name"]: c for c in rep["checks"]}
        w = by["گرم‌شدن لایه‌ها"]
        assert w["ok"] is False
        assert "کمبود تاریخ" in w["detail"] and "روز" in w["detail"]
        assert "--days" in w["fix"] and "--evaluate" in w["fix"]
        md = open(rep["paths"]["md"], encoding="utf-8").read()
        assert "کمبود تاریخ" in md and "**171 روز**" in md


def test_symbols_table_shows_pending_processing_column():
    with tempfile.TemporaryDirectory() as td:
        rep = control.collect(_uni(200), _cfg(), out_dir=os.path.join(td, "out"),
                              now_ms=_now_after(_uni(200)))
        md = open(rep["paths"]["md"], encoding="utf-8").read()
        assert "عقبِ پردازش" in md


def test_evaluate_accepts_days_for_real_download():
    sh = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "run-auto.sh"), encoding="utf-8").read()
    assert "--days)" in sh and "--days=*)" in sh
    assert 'ops --download --days "$_DAYS"' in sh
    assert "evaluate --days" in sh


def test_evaluate_converts_comma_symbols_for_live():
    """`live --symbols` آرگومان جدا می‌خواهد؛ «A,B» باید به «A B» تبدیل شود."""
    sh = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "run-auto.sh"), encoding="utf-8").read()
    assert "IFS=','" in sh
    assert "_SL=(--symbols" in sh
    assert '"${_SL[@]+"${_SL[@]}"}"' in sh       # live با نسخهٔ فاصله‌دار اجرا می‌شود


def test_year_branch_runs_the_seven_steps_in_order():
    """`--year` باید یک مسیر کامل و لاگ‌دار باشد، نه چند دستور پراکنده."""
    sh = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "run-auto.sh"), encoding="utf-8").read()
    assert "--year|--one-year)" in sh
    order = ["== ۱/۷", "== ۲/۷", "== ۳/۷", "== ۴/۷", "== ۵/۷", "== ۶/۷", "== ۷/۷"]
    pos = [sh.find(x) for x in order]
    assert all(p > 0 for p in pos) and pos == sorted(pos)
    # ابزارهای هر گام
    for piece in ("-m mtflab ops --download --days", "-m mtflab live --offline --backfill 400",
                  "-m mtflab health", "-m mtflab autoscan --source json",
                  "-m mtflab control", "-m mtflab gate --tag"):
        assert piece in sh, piece
    # خروجی لاگ‌دار + راهنمای بیدار ماندن گوشی
    assert "results/year_run_" in sh and "termux-wake-lock" in sh
    # پیش‌پرواز: با کش خالی و --offline نباید ۴۰ دقیقه وقت تلف کند
    assert "هیچ فایل 4h نیست" in sh and "exit 2" in sh
    # پیش‌فرض ۱۰ نماد (دروازه ۸ می‌خواهد)
    line = [l for l in sh.splitlines() if "_SYMS=\"BTCUSDT" in l][0]
    assert line.count(",") == 9
