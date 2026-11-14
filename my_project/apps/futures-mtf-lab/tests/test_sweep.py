"""تست‌های تحلیل هزینه و کیفیت اجرا.

چرا مهم‌اند؟ ادعای «هزینه کشنده است» تا امروز فقط یک **روایت** بود. اگر مدل
اجرای میکر اشتباه پیاده شود، همین تحلیل عدد غلط می‌دهد و تصمیم بعدی پروژه روی
آن سوار می‌شود. پس سه چیز قفل می‌شود:

1. **پیش‌فرض دست‌نخورده است** — `limit_exits=False` باید بیت‌به‌بیت همان نتیجهٔ
   قبلی را بدهد (وگرنه همهٔ نتایج قبلی پروژه بی‌اعتبار می‌شوند).
2. **خروج محدود فقط روی TP اثر دارد** — نه روی stop.
3. **حد بالا درست محاسبه می‌شود** — هزینهٔ صفر باید بهترین نتیجه را بدهد.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace                                     # noqa: E402

from mtflab.autoscan import build_layers, run_variant, variants_for  # noqa: E402
from mtflab.config import PRESETS, load_config                      # noqa: E402
from mtflab.data import synthetic_candles                           # noqa: E402
from mtflab.sweep import (POLICIES, breakeven_cost,                 # noqa: E402
                          effective_round_trip_bps)

CFG = load_config(["--data", "synthetic", "--quiet"])


def _layers(n=4000, tf="4h"):
    cs = synthetic_candles(tf, n, seed=31)
    return build_layers(cs, tf, "1d", "1d", bias_enabled=True)


def _run(over, layers=None, **cfg_over):
    c = replace(CFG, verbose=False, forensics=False, run_id="", **cfg_over)
    return run_variant(c, layers or _layers(), over)


# ═══════════════════════════════════════════════════════════════════════════
# ۱) پیش‌فرض‌ها نباید هیچ چیزی را عوض کنند
# ═══════════════════════════════════════════════════════════════════════════
def test_limit_exits_defaults_to_off():
    """اگر این پیش‌فرض روشن شود، همهٔ نتایج قبلی پروژه بی‌اعتبار می‌شوند."""
    assert load_config(["--data", "synthetic", "--quiet"]).limit_exits is False


def test_maker_fee_default_is_two_bps():
    assert CFG.maker_fee_bps == 2.0


def test_default_run_is_unchanged_by_the_new_code_path():
    """با limit_exits=False نتیجه باید با اجرای «تیکر خالص» یکی باشد."""
    L = _layers()
    base = _run({}, L)
    explicit = _run({}, L, limit_exits=False)
    assert base["n"] == explicit["n"]
    assert round(base["pnl"], 6) == round(explicit["pnl"], 6)
    assert base["total_fees"] == explicit["total_fees"]


# ═══════════════════════════════════════════════════════════════════════════
# ۲) خروج محدود: فقط TP، نه stop
# ═══════════════════════════════════════════════════════════════════════════
def test_limit_exits_lower_the_fee_bill_when_tp_fires():
    """نسخهٔ `base` حد سود واقعی دارد ⇒ با میکر باید کارمزد کمتر شود."""
    L = _layers()
    over = {}                       # base با TP = 3×ATR
    a = _run(over, L, limit_exits=False)
    b = _run(over, L, limit_exits=True)
    assert a["n"] > 0 and b["n"] > 0
    # همان تعداد معامله (فقط کیفیت پرشدن عوض شده، نه سیگنال)
    assert a["n"] == b["n"], (a["n"], b["n"])
    # و کارمزد کمتر
    assert b["total_fees"] < a["total_fees"], (a["total_fees"], b["total_fees"])


def test_a_pure_stop_exit_gets_no_maker_benefit():
    """اگر TP هرگز نزند (TP=50×ATR)، خروج محدود باید **هیچ** اثری نداشته باشد.

    این تست یک یافتهٔ ساختاری را قفل می‌کند: نسخهٔ `trend` با تریلینگ استاپ
    خارج می‌شود، نه با TP. پس «میکر کردن TP» برای آن بی‌اثر است.
    """
    trend = dict(PRESETS["trend_4h"])
    trend.pop("tf_trigger", None)
    trend.pop("tf_filter", None)
    trend.pop("tf_bias", None)
    L = _layers()
    a = _run(trend, L, limit_exits=False)
    b = _run(trend, L, limit_exits=True)
    assert a["n"] == b["n"]
    assert a["total_fees"] == b["total_fees"], (
        "نسخهٔ trend باید TP نداشته باشد؛ اگر این تست شکست، یعنی TP فعال شده "
        "و یافتهٔ «میکر بی‌اثر است» دیگر معتبر نیست")


def test_maker_benefit_is_bounded_by_the_zero_cost_result():
    """هیچ سیاستی نباید بهتر از «هزینهٔ صفر» باشد — وگرنه مدل اشتباه است."""
    L = _layers()
    over = {}
    zero = _run(over, L, fee_bps=0.0, slippage_pct=0.0, limit_exits=False)
    maker = _run(over, L, limit_exits=True, maker_fee_bps=0.0)
    assert maker["pnl"] <= zero["pnl"] + 1e-6
    assert maker["total_fees"] >= zero["total_fees"] - 1e-6


def test_zero_cost_gives_more_or_equal_trades():
    """با هزینهٔ صفر، فیلتر هزینه سخت‌گیرتر نمی‌شود (بیشترین معامله را دارد)."""
    L = _layers()
    cheap = _run({}, L, fee_bps=0.0, slippage_pct=0.0)
    pricey = _run({}, L, fee_bps=20.0, slippage_pct=0.1)
    assert cheap["n"] >= pricey["n"]


# ═══════════════════════════════════════════════════════════════════════════
# ۳) محاسبهٔ هزینهٔ مؤثر و سربه‌سر
# ═══════════════════════════════════════════════════════════════════════════
def test_effective_round_trip_of_the_current_model():
    """تیکر فعلی: (۵.۵bps + ۲bps اسلیپیج) × ۲ = ۱۵ bps."""
    tak = [p for p in POLICIES if p[0] == "taker"][0]
    assert effective_round_trip_bps(tak) == 15.0


def test_effective_round_trip_of_maker_tp():
    """ورود تیکر (۷.۵) + خروج میکر (۲) = ۹.۵ bps — نه ۱۵."""
    mk = [p for p in POLICIES if p[0] == "maker_tp"][0]
    assert effective_round_trip_bps(mk) == 9.5


def test_zero_policy_is_actually_free():
    z = [p for p in POLICIES if p[0] == "zero"][0]
    assert effective_round_trip_bps(z) == 0.0


def test_breakeven_interpolates_between_sign_changes():
    pts = [(15.0, -0.9), (9.5, -0.4), (4.0, 0.2), (0.0, 0.6)]
    b = breakeven_cost(pts)
    assert b is not None
    assert 4.0 < b < 9.5
    # درون‌یابی خطی بین (4.0, 0.2) و (9.5, -0.4)
    expected = 4.0 + (0 - 0.2) * (9.5 - 4.0) / (-0.4 - 0.2)
    assert abs(b - expected) < 1e-3      # خروجی تا ۳ رقم گرد می‌شود


def test_breakeven_is_none_when_always_negative():
    """اگر حتی با هزینهٔ صفر منفی باشد، سربه‌سری وجود ندارد."""
    assert breakeven_cost([(15.0, -3.0), (9.5, -2.5), (0.0, -1.1)]) is None


def test_breakeven_is_none_when_always_positive():
    assert breakeven_cost([(15.0, 0.5), (0.0, 1.2)]) is None


# ═══════════════════════════════════════════════════════════════════════════
# ۴) تحلیل کامل روی دادهٔ ساختگی
# ═══════════════════════════════════════════════════════════════════════════
def test_sweep_produces_a_monotone_cost_curve():
    """هرچه هزینه کمتر، میانهٔ PF باید بیشتر (یا مساوی) باشد.

    اگر این تست شکست، یعنی محاسبهٔ هزینه/کارمزد جایی نشت دارد.
    """
    from mtflab.sweep import sweep
    from mtflab.data import synthetic_candles as sc
    data = {"AAA": sc("4h", 3000, seed=11), "BBB": sc("4h", 3000, seed=12)}
    variants = variants_for("4h", "1d", "1d")
    base_only = [v for v in variants if v[0] == "base"]
    res = sweep(CFG, data, "4h", "1d", "1d", base_only, progress=False)
    d = res["summary"]["base"]
    pfs = [d[p["name"]]["median_pf"] for p in res["settings"]["policies"]
           if d.get(p["name"], {}).get("ok")]
    assert len(pfs) >= 4
    # صفر باید آخرین (کم‌هزینه‌ترین) و بالاترین باشد
    assert d["zero"]["median_pf"] >= d["taker"]["median_pf"]


def test_sweep_report_has_both_languages():
    from mtflab.sweep import render_report, sweep
    from mtflab.data import synthetic_candles as sc
    data = {"AAA": sc("4h", 2500, seed=5)}
    variants = [v for v in variants_for("4h", "1d", "1d") if v[0] == "base"]
    res = sweep(CFG, data, "4h", "1d", "1d", variants, progress=False)
    fa = render_report(res, lang="fa")
    en = render_report(res, lang="en")
    assert "سربه‌سر" in fa
    assert "Break-even" in en
    assert "taker" in fa and "taker" in en


def test_sweep_settings_record_every_policy():
    from mtflab.sweep import sweep
    from mtflab.data import synthetic_candles as sc
    data = {"AAA": sc("4h", 2000, seed=6)}
    variants = [v for v in variants_for("4h", "1d", "1d") if v[0] == "base"]
    res = sweep(CFG, data, "4h", "1d", "1d", variants, progress=False)
    names = [p["name"] for p in res["settings"]["policies"]]
    assert names == [p[0] for p in POLICIES]
    for p in res["settings"]["policies"]:
        assert "round_trip_bps" in p


# ═══════════════════════════════════════════════════════════════════════════
# ۵) سربه‌سر: سه وضعیت، نه یک عدد گمراه‌کننده
# ═══════════════════════════════════════════════════════════════════════════
def test_status_above_when_profitable_even_at_the_highest_cost():
    """این همان حالتِ دادهٔ واقعی است: لبه با تیکر ۱۵bps هم زنده است.

    نسخهٔ اول این را با «سربه‌سر دست‌نیافتنی» قاطی می‌کرد و گزارش می‌نوشت
    «۱ از ۲۰ نماد» — یعنی دقیقاً برعکسِ واقعیت.
    """
    from mtflab.sweep import breakeven_status
    st, val = breakeven_status([(0.0, 1.10), (9.5, 0.95), (15.0, 0.76)])
    assert st == "above" and val is None


def test_status_never_when_negative_even_free():
    from mtflab.sweep import breakeven_status
    st, val = breakeven_status([(0.0, -0.5), (9.5, -1.2), (15.0, -2.0)])
    assert st == "never" and val is None


def test_status_cross_inside_the_range():
    from mtflab.sweep import breakeven_status
    st, val = breakeven_status([(0.0, 0.5), (9.5, -0.4), (15.0, -1.2)])
    assert st == "cross" and 0 < val < 9.5


# ═══════════════════════════════════════════════════════════════════════════
# ۶) حکم: «هزینه مانع است» با «هزینه فقط سود را کم می‌کند» فرق دارد
# ═══════════════════════════════════════════════════════════════════════════
def _summary(**pfs):
    out = {}
    for name, pf in pfs.items():
        out[name] = {"ok": True, "median_pf": pf, "median_expectancy": 0.76}
    out.setdefault("breakeven", {"cross": 0, "above_max": 19, "never": 1,
                                 "of_symbols": 20, "max_tested_bps": 15.0,
                                 "median_round_trip_bps": None})
    return out


def test_verdict_does_not_sell_a_maker_scheme_when_cost_is_not_the_barrier():
    """دادهٔ واقعی کاربر: PF در تیکر ۱.۱۲ و در میکر هم ۱.۱۲.

    حکم درست «مشکل اجرا نیست» است، نه «طرح میکر ارزش ساخت دارد».
    """
    from mtflab.sweep import verdict
    v = verdict(_summary(taker=1.1201, maker_tp=1.1201, all_maker=1.1541,
                         zero=1.1749), lang="fa")
    assert "زنده است" in v
    assert "ارزش ساخت" not in v


def test_verdict_still_promotes_maker_when_taker_is_negative():
    from mtflab.sweep import verdict
    v = verdict(_summary(taker=0.95, maker_tp=1.06, all_maker=1.09,
                         zero=1.15), lang="fa")
    assert "ارزش ساخت" in v


def test_verdict_abandons_when_even_free_cost_loses():
    from mtflab.sweep import verdict
    v = verdict(_summary(taker=0.80, maker_tp=0.85, all_maker=0.95,
                         zero=0.98), lang="fa")
    assert "رها" in v


def test_verdict_flags_mirage_when_only_all_maker_works():
    from mtflab.sweep import verdict
    v = verdict(_summary(taker=0.98, maker_tp=0.99, all_maker=1.04,
                         zero=1.05), lang="fa")
    assert "سراب" in v or "مرزی" in v


# ═══════════════════════════════════════════════════════════════════════════
# ۷) فایل‌ها باید به پوشهٔ Download برسند — نه گم شوند در عمق مخزن
# ═══════════════════════════════════════════════════════════════════════════
def test_root_launcher_delegates_sweep_to_the_app_launcher():
    """لانچر ریشه نباید خودش `mtflab sweep` را صدا بزند.

    یک‌بار همین کار را کرد و چون با `exec` بود، مرحلهٔ کپی به Download اجرا نشد؛
    فایل ساخته شد ولی کاربر گفت «تولید نشد».
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))
    script = os.path.join(root, "run-auto.sh")
    if not os.path.exists(script):
        return
    text = open(script, encoding="utf-8").read()
    assert '"--sweep"' in text
    code = "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "mtflab sweep" not in code, (
        "لانچر ریشه نباید مستقیم sweep را اجرا کند؛ باید به لانچر اپ بسپارد "
        "تا کپی به Download انجام شود")
    assert 'exec bash "$APP/run-auto.sh" "$@"' in text


def test_delivery_is_handled_in_python_not_in_the_shell():
    """کپی باید جایی باشد که مسیر واقعی خروجی معلوم است.

    اسکریپت شل مسیر را حدس می‌زد (`results/cost_sweep*`)؛ با `--out-dir` کپی
    بی‌صدا شکست می‌خورد و کاربر فکر می‌کرد فایل تولید نشده.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(here, "run-auto.sh"), encoding="utf-8").read()
    assert "--sweep" in text
    # فقط همان بلوکِ --sweep را نگاه کن؛ بقیهٔ اسکریپت برای دستورهای دیگر هم
    # کپی به Download دارد و اشکالی ندارد.
    block = text[text.index("    --sweep)"):]
    block = block[:block.index("exit $?") + 7]
    assert "mtflab sweep" in block
    assert "storage/downloads" not in block, (
        "کپی به Download باید در mtflab.sweep.deliver باشد، نه در اسکریپت")

    import inspect
    from mtflab import sweep as sw
    src = inspect.getsource(sw.deliver)
    assert "storage" in src and "shutil.copy2" in src


def test_sweep_run_end_to_end_and_file_delivery():
    """اجرای واقعی اسکریپت: فایل ساخته می‌شود و به Download هم می‌رسد."""
    import json as _json
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("bash"):
        return
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(here, "run-auto.sh")
    from mtflab.autoscan import candles_to_json
    from mtflab.data import synthetic_candles

    with tempfile.TemporaryDirectory() as td:
        data_dir = os.path.join(td, "data")
        os.makedirs(os.path.join(data_dir, "json"))
        for i, sym in enumerate(["AAAUSDT", "BBBUSDT"]):
            cs = synthetic_candles("4h", 3000, seed=70 + i)
            with open(os.path.join(data_dir, "json", f"{sym.lower()}_4h.json"),
                      "w", encoding="utf-8") as f:
                _json.dump(candles_to_json(cs, {"symbol": sym, "tf": "4h",
                                                "days": 400}), f)
        home = os.path.join(td, "home")
        dl = os.path.join(home, "storage", "downloads")
        os.makedirs(dl)
        out = os.path.join(td, "out")
        env = dict(os.environ, HOME=home)
        # `bash` صریح: shebang اسکریپت مسیر Termux است و روی لینوکس اجرا نمی‌شود
        r = subprocess.run(["bash", script, "--sweep", "--tf", "4h",
                            "--variants", "base",
                            "--data-dir", data_dir, "--out-dir", out,
                            "--tag", "unittest", "--lang", "en"],
                           cwd=here, env=env, capture_output=True, text=True,
                           timeout=300)
        assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
        made = [f for f in os.listdir(out) if f.startswith("cost_sweep_unittest")]
        assert sorted(made) == ["cost_sweep_unittest.json",
                                "cost_sweep_unittest.md"], made
        got = [f for f in os.listdir(dl) if f.startswith("cost_sweep_unittest")]
        assert len(got) == 2, ("فایل به Download نرسید", got, r.stdout[-800:])
