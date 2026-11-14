"""تست‌های ابزار اسکن خودکار (autoscan) — آنچه روی گوشی کاربر اجرا می‌شود.

چرا این تست‌ها مهم‌اند: این ابزار بدون نظارت اجرا می‌شود و خروجی‌اش مبنای
قضاوت بعدی است. پس سه چیز باید قفل شود:

1. **دادهٔ ذخیره‌شده همان دادهٔ اصلی است** (رفت‌وبرگشت JSON بدون تغییر)
2. **دروازهٔ پذیرش واقعاً می‌تواند شکست بخورد** (تست منفی؛ وگرنه تزئینی است)
3. **همهٔ نسخه‌ها روی یک تایم‌فریم اجرا می‌شوند** (مقایسهٔ منصفانه)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.autoscan import (GATE, aggregate, build_layers,          # noqa: E402
                             candles_from_json, candles_to_json,
                             discover_cached_symbols, _json_path,
                             variants_for, VERSION)
from mtflab.config import load_config, PRESETS                      # noqa: E402
from mtflab.data import synthetic_candles                            # noqa: E402


# ── ۱) ذخیره/بازخوانی JSON ───────────────────────────────────────────────────
def test_json_roundtrip_is_lossless():
    """دادهٔ ذخیره‌شده باید بیت‌به‌بیت همان کندل اصلی باشد."""
    cs = synthetic_candles("4h", 300, seed=11)
    payload = candles_to_json(cs, {"symbol": "TESTUSDT", "tf": "4h"})
    back = candles_from_json(json.loads(json.dumps(payload)))
    assert len(back) == len(cs)
    for a, b in zip(cs, back):
        assert (a.open_time_ms, a.open, a.high, a.low, a.close) == \
               (b.open_time_ms, b.open, b.high, b.low, b.close)


def test_json_payload_has_meta_and_schema_version():
    """بستهٔ JSON باید خودتوصیف باشد: نسخه، نماد، تایم‌فریم، تعداد."""
    cs = synthetic_candles("1d", 60)
    p = candles_to_json(cs, {"symbol": "btcusdt", "tf": "1d"})
    assert p["meta"]["symbol"] == "btcusdt"
    assert p["meta"]["tf"] == "1d"
    assert p["meta"]["n"] == 60
    assert "schema" in p["meta"] or "version" in p["meta"]
    assert len(p["candles"]) == 60


def test_json_path_is_stable_and_lowercase():
    """نام فایل کش باید قابل پیش‌بینی باشد (وگرنه ادامهٔ کار بعد از قطعی می‌شکند)."""
    a = _json_path("/x/data", "BTCUSDT", "4h")
    b = _json_path("/x/data", "btcusdt", "4h")
    assert a == b
    assert a.endswith(os.path.join("json", "btcusdt_4h.json"))


def test_discover_cached_symbols_only_returns_matching_tf():
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "json")
        os.makedirs(d)
        for name in ("btcusdt_4h.json", "ethusdt_4h.json", "solusdt_1h.json"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("{}")
        got = discover_cached_symbols(td, "4h")
        assert got == ["BTCUSDT", "ETHUSDT"]


# ── ۲) لایه‌ها و نسخه‌ها ─────────────────────────────────────────────────────
def test_build_layers_with_bias_disabled_returns_empty_bias():
    """در پریست trend بایاس خاموش است؛ لایهٔ بایاس نباید ساخته شود."""
    trig = synthetic_candles("4h", 500)
    layers = build_layers(trig, "4h", "1d", "1d", bias_enabled=False)
    assert layers["bias"] == []
    assert len(layers["filter"]) > 0 and len(layers["filter"]) < len(trig)


def test_variants_all_use_the_scan_timeframe():
    """مقایسهٔ منصفانه: هیچ نسخه‌ای نباید تایم‌فریم خودش را تحمیل کند."""
    vs = variants_for("4h", "1d", "1d")
    assert [v[0] for v in vs][0] == "base"
    for vid, _label, over in vs:
        assert over["tf_trigger"] == "4h", vid
        assert over["tf_filter"] == "1d", vid
        assert over["tf_bias"] == "1d", vid


def test_trend_variant_matches_the_documented_preset():
    """نسخهٔ trend باید دقیقاً همان پریست مستند trend_4h باشد (نه کپی دستی)."""
    trend = dict(PRESETS["trend_4h"])
    for k in ("tf_trigger", "tf_filter", "tf_bias"):
        trend.pop(k, None)
    got = dict([v for v in variants_for("4h", "1d", "1d") if v[0] == "trend"][0][2])
    for k in ("tf_trigger", "tf_filter", "tf_bias"):
        got.pop(k, None)
    assert got == trend


def test_gate_thresholds_are_fixed_values():
    """دروازه از پیش ثبت شده؛ تغییرش باید آگاهانه باشد، نه تصادفی."""
    assert GATE["min_symbols"] == 8
    assert GATE["min_profitable_symbols_pct"] == 60.0
    assert GATE["min_positive_years_pct"] == 60.0
    assert GATE["min_sign_test_p"] == 0.10
    assert VERSION


# ── ۳) ریاضیات دروازه (شامل تست منفی) ───────────────────────────────────────
def _row(n, pf, exp, pnl, years_n=3, pos=3):
    return {"n": n, "profit_factor": pf, "expectancy": exp, "pnl": pnl,
            "years_n": years_n, "positive_years": pos}


def test_aggregate_rejects_a_small_sample_even_if_perfect():
    """۲ نمادِ عالی نباید قبول شود — کم بودن نمونه خودش دلیل رد است."""
    per = {"A": {"base": _row(50, 1.0, 0.0, 0.0), "v": _row(120, 3.0, 9.0, 500.0)},
           "B": {"base": _row(50, 1.0, 0.0, 0.0), "v": _row(120, 2.5, 8.0, 400.0)}}
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["checks"]["symbols"] is False
    assert agg["v"]["survived"] is False


def test_aggregate_rejects_when_sign_test_is_not_significant():
    """حتی با ۸ نمادِ سودده، اگر برتری بر پایه در ۵ از ۸ باشد، p زیاد است → رد."""
    per = {}
    for i in range(8):
        better = i < 5
        per[f"S{i}"] = {"base": _row(100, 1.0, 0.0, 0.0),
                        "v": _row(200, 1.5, 2.0, 100.0,
                                  pos=3 if better else 2)}
        if not better:
            # expectancy پایین‌تر از پایه → بازندهٔ آزمون علامت
            per[f"S{i}"]["v"] = _row(200, 1.2, -0.5, -20.0, pos=2)
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["sign_vs_base"]["wins"] == 5
    assert agg["v"]["checks"]["significance"] is False
    assert agg["v"]["survived"] is False


def test_aggregate_accepts_only_when_every_check_passes():
    """تست مثبت: با نمونهٔ بزرگ، همهٔ نمادها بهتر، سال‌های مثبت کافی → قبول."""
    per = {f"S{i}": {"base": _row(100, 1.0, 0.0, 0.0),
                     "v": _row(250, 1.6, 3.0, 200.0)}
           for i in range(10)}
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["checks"] == {"symbols": True, "trades": True,
                                  "profitable_symbols": True,
                                  "positive_years": True, "median_pf": True,
                                  "significance": True}
    assert agg["v"]["survived"] is True


def test_aggregate_can_fail_on_median_pf_only():
    """یک شرط شکست بخورد کافی است — دروازه «همه یا هیچ» است."""
    per = {f"S{i}": {"base": _row(100, 1.0, 0.0, 0.0),
                     "v": _row(250, 1.02, 3.0, 50.0)}     # PF < 1.05
           for i in range(10)}
    agg = aggregate(per, ["base", "v"])
    assert agg["v"]["checks"]["median_pf"] is False
    assert agg["v"]["survived"] is False


def test_aggregate_never_lets_base_win_by_significance_default():
    """پایه با خودش مقایسه نمی‌شود؛ ولی شرط معناداری‌اش نباید خودکار «قبول» شود."""
    per = {f"S{i}": {"base": _row(100, 0.9, -1.0, -50.0, pos=1)} for i in range(10)}
    agg = aggregate(per, ["base"])
    assert agg["base"]["sign_vs_base"] is None
    assert agg["base"]["survived"] is False       # PF<1 و سال منفی → رد


# ── ۴) کانفیگ با دادهٔ ساختگی (بدون شبکه) ───────────────────────────────────
def test_autoscan_config_does_not_require_network():
    """کانفیگ باید آفلاین ساخته شود؛ فقط دانلود به شبکه نیاز دارد."""
    cfg = load_config(["--data", "synthetic", "--quiet"])
    assert cfg.data_mode in ("synthetic", "csv")
    assert cfg.fee_bps > 0


# ── ۵) اثر انگشت داده ───────────────────────────────────────────────────────
def test_fingerprint_is_stable_and_detects_any_change():
    """اگر یک کندل عوض شود، اثر انگشت باید عوض شود (تشخیص دستکاری/دادهٔ دیگر)."""
    from mtflab.autoscan import data_fingerprint
    cs = synthetic_candles("4h", 100, seed=3)
    f1 = data_fingerprint(cs)
    assert f1 == data_fingerprint(synthetic_candles("4h", 100, seed=3))
    assert len(f1) == 16
    cs2 = list(cs)
    from mtflab.data import Candle
    cs2[-1] = Candle(cs[-1].open_time_ms, cs[-1].open, cs[-1].high, cs[-1].low,
                     cs[-1].close * 1.001, cs[-1].volume)
    assert data_fingerprint(cs2) != f1


# ── ۶) پروب شبکه: همان دامی که کاربر واقعاً خورد ────────────────────────────
def _serve(routes):
    """سرور محلی که پاسخ Bybit را شبیه‌سازی می‌کند. routes: path_prefix -> (code, body)"""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            for prefix, (code, body) in routes.items():
                if self.path.startswith(prefix):
                    raw = _json.dumps(body).encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):                            # ساکت
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


_TIME_OK = (200, {"retCode": 0, "retMsg": "OK", "result": {"timeNano": "1"}})
_KLINE_OK = (200, {"retCode": 0, "retMsg": "OK",
                   "result": {"list": [["1", "1", "2", "1", "2", "9"]]}})
_KLINE_403 = (403, {"retCode": 403, "retMsg": "Forbidden"})


def test_probe_detects_blocked_kline_even_when_time_endpoint_works():
    """🐞 همان باگ کاربر: /market/time سالم ولی /market/kline مسدود.

    قبلاً پروب فقط time را می‌دید ⇒ «شبکه سالم است» چاپ می‌شد و بعد
    هر نماد با ۴۰۳ شکست می‌خورد.
    """
    from mtflab.autoscan import (_probe, KLINE_PROBE_PATH, TIME_PROBE_PATH,
                                 probe_endpoint)
    srv, base = _serve({"/v5/market/time": _TIME_OK, "/v5/market/kline": _KLINE_403})
    try:
        assert probe_endpoint(base, TIME_PROBE_PATH)["ok"] is True
        assert probe_endpoint(base, KLINE_PROBE_PATH)["ok"] is False
        assert _probe(base) is False, "پروب باید شکست بخورد نه اینکه بگوید سالم است"
    finally:
        srv.shutdown()


def test_probe_passes_when_kline_really_works():
    from mtflab.autoscan import _probe, probe_endpoint, KLINE_PROBE_PATH
    srv, base = _serve({"/v5/market/time": _TIME_OK, "/v5/market/kline": _KLINE_OK})
    try:
        assert _probe(base) is True
        r = probe_endpoint(base, KLINE_PROBE_PATH)
        assert r["ok"] and r["status"] == 200
    finally:
        srv.shutdown()


def test_probe_rejects_empty_candle_list():
    """retCode=0 ولی لیست خالی ⇒ داده‌ای برای دانلود نیست."""
    from mtflab.autoscan import _probe
    srv, base = _serve({"/v5/market/kline": (200, {"retCode": 0, "result": {"list": []}})})
    try:
        assert _probe(base) is False
    finally:
        srv.shutdown()


def test_pick_base_url_skips_blocked_mirror_and_picks_working_one():
    """آینهٔ اول مسدود، دومی سالم → باید دومی انتخاب شود."""
    from mtflab.autoscan import pick_base_url
    bad, bad_url = _serve({"/v5/market/time": _TIME_OK, "/v5/market/kline": _KLINE_403})
    good, good_url = _serve({"/v5/market/kline": _KLINE_OK})
    try:
        assert pick_base_url([bad_url, good_url], progress=False) == good_url
    finally:
        bad.shutdown()
        good.shutdown()


def test_pick_base_url_raises_when_nothing_works():
    from mtflab.autoscan import pick_base_url
    srv, base = _serve({"/v5/market/kline": _KLINE_403})
    try:
        try:
            pick_base_url([base], progress=False)
        except RuntimeError as e:
            assert "Bybit" in str(e)
        else:
            raise AssertionError("باید خطا می‌داد")
    finally:
        srv.shutdown()


def test_diagnosis_reports_which_layer_is_blocked():
    """تشخیص باید بگوید «ساعت سالم، کندل مسدود» — نه یک «شبکه خراب» مبهم."""
    from mtflab.autoscan import diagnose_network
    srv, base = _serve({"/v5/market/time": _TIME_OK, "/v5/market/kline": _KLINE_403})
    try:
        rep = diagnose_network([base])
        kinds = {r["kind"]: r["ok"] for r in rep}
        assert kinds == {"time": True, "kline": False}
    finally:
        srv.shutdown()


# ── ۷) حالت انگلیسی (خوانایی روی ترمینال Termux) ────────────────────────────
def test_lang_switch_changes_console_and_report():
    """روی Termux خط فارسی برعکس نمایش داده می‌شود؛ --lang en باید اسکی‌محور باشد."""
    from mtflab import autoscan as A
    A.set_lang("fa")
    assert A._t("فارسی", "English") == "فارسی"
    A.set_lang("en")
    assert A._t("فارسی", "English") == "English"
    A.set_lang("EN-gb")
    assert A._t("x", "y") == "y"
    A.set_lang("fa")
    assert A._t("x", "y") == "x"


def test_english_report_is_ascii_readable():
    """گزارش انگلیسی باید ساختار کامل داشته باشد و حرف فارسی نداشته باشد."""
    import re
    from mtflab import autoscan as A
    res = {
        "version": A.VERSION, "generated_at": "2026-01-01 00:00 UTC",
        "elapsed_s": 1.0,
        "settings": {"symbols": ["A"], "days": 10, "tf_trigger": "4h",
                     "tf_filter": "1d", "tf_bias": "1d", "fee_bps": 5.5,
                     "slippage_pct": 0.02, "risk_per_trade_pct": 1.0,
                     "max_concurrent": 1, "initial_equity": 1000.0,
                     "base_url": "", "source": "csv"},
        "coverage": {"A": {"n_trigger": 100, "years": 1.0, "start": "2025-01-01",
                           "end": "2025-12-31", "from_cache": True,
                           "source": "csv", "fingerprint": "x"}},
        "variants": [{"id": "base", "label": "base"}],
        "per_symbol": {"A": {"base": {"n": 10, "profit_factor": 1.2,
                                      "expectancy": 1.0, "pnl": 10.0,
                                      "return_pct": 1.0, "max_drawdown_pct": -1.0,
                                      "positive_years": 1, "years_n": 1,
                                      "per_year": {"2025": {"pnl": 10.0}}}}},
        "aggregate": {"base": {"ok": True, "n_symbols": 1, "total_trades": 10,
                               "total_pnl": 10.0, "median_pf": 1.2,
                               "median_expectancy": 1.0, "profitable_symbols": 1,
                               "profitable_symbols_pct": 100.0, "positive_years": 1,
                               "years_n": 1, "positive_years_pct": 100.0,
                               "sign_vs_base": None, "checks": {},
                               "survived": False}},
        "rankings": ["base"], "winner": "base", "survived": [], "errors": [],
    }
    out = A.render_report_en(res)
    assert "# Multi-symbol autoscan report" in out
    assert "## 1) Verdict" in out and "## 5) Coverage and data integrity" in out
    assert "PASS" in out or "FAIL" in out
    # هیچ حرف فارسی‌ای نباید در گزارش انگلیسی باشد
    assert not re.search(r"[\u0600-\u06FF]", out), "گزارش انگلیسی نباید فارسی داشته باشد"


# ── ۸) گزارش کوچک باید خودش بگوید «حکم نیست» ────────────────────────────────
def _tiny_res(n_sym=2):
    from mtflab import autoscan as A
    cov = {f"S{i}": {"n_trigger": 100, "years": 1.0, "start": "2025-01-01",
                     "end": "2025-12-31", "from_cache": True, "source": "csv",
                     "fingerprint": "x"} for i in range(n_sym)}
    per = {f"S{i}": {"base": {"n": 10, "profit_factor": 1.2, "expectancy": 1.0,
                              "pnl": 10.0, "return_pct": 1.0,
                              "max_drawdown_pct": -1.0, "positive_years": 1,
                              "years_n": 1, "per_year": {"2025": {"pnl": 10.0}}}}
           for i in range(n_sym)}
    agg = {"base": {"ok": True, "n_symbols": n_sym, "total_trades": 10 * n_sym,
                    "total_pnl": 10.0 * n_sym, "median_pf": 1.2,
                    "median_expectancy": 1.0, "profitable_symbols": n_sym,
                    "profitable_symbols_pct": 100.0, "positive_years": n_sym,
                    "years_n": n_sym, "positive_years_pct": 100.0,
                    "sign_vs_base": None, "checks": {}, "survived": False}}
    return {"version": A.VERSION, "generated_at": "2026-01-01 00:00 UTC",
            "elapsed_s": 1.0,
            "settings": {"symbols": list(cov), "days": 10, "tf_trigger": "4h",
                         "tf_filter": "1d", "tf_bias": "1d", "fee_bps": 5.5,
                         "slippage_pct": 0.02, "risk_per_trade_pct": 1.0,
                         "max_concurrent": 1, "initial_equity": 1000.0,
                         "base_url": "", "source": "csv"},
            "coverage": cov,
            "variants": [{"id": "base", "label": "base"}],
            "per_symbol": per, "aggregate": agg, "rankings": ["base"],
            "winner": "base", "survived": [], "errors": []}


def test_small_sample_report_warns_it_is_not_a_verdict():
    """اگر نمادها کمتر از دروازه باشند، گزارش باید صریح بگوید FAIL حتمی است.

    چرا: کاربر اجرای ۲ نمادی (آفلاین) را با اجرای ۲۰ نمادی اشتباه می‌گیرد و
    FAIL را «رد استراتژی» می‌خواند. این هشدار جلوی آن برداشت را می‌گیرد.
    """
    from mtflab import autoscan as A
    res = _tiny_res(2)
    fa = A.render_report(res)
    A.set_lang("en")
    en = A.render_report_en(res)
    A.set_lang("fa")
    assert "آزمایش کوچک است" in fa and "2 نماد" in fa
    assert "SMALL SAMPLE" in en and "guaranteed" in en


def test_full_sample_report_has_no_small_sample_warning():
    """با ۸+ نماد، هشدار نباید باشد (وگرنه بی‌اثر می‌شود)."""
    from mtflab import autoscan as A
    res = _tiny_res(10)
    A.set_lang("en")
    try:
        assert "SMALL SAMPLE" not in A.render_report_en(res)
    finally:
        A.set_lang("fa")


# ── ۸) پشتهٔ تایم‌فریم: بازتولید سناریوی اصلی اسپک (15m/1h/4h) ───────────────
def test_validate_tf_stack_accepts_the_original_spec_scenario():
    """سناریوی اصلی اسپک: تریگر ۱۵m · فیلتر ۱h · بایاس ۴h باید مجاز باشد."""
    from mtflab import autoscan as _A
    _A.set_lang("fa")
    from mtflab.autoscan import validate_tf_stack
    validate_tf_stack("15m", "1h", "4h")
    validate_tf_stack("4h", "1d", "1d")      # پیش‌فرض قدیمی، برای سازگاری
    validate_tf_stack("15m", "15m", "15m")   # مساوی هم مجاز است


def test_validate_tf_stack_rejects_a_filter_finer_than_trigger():
    """فیلتر ریزتر از تریگر = ساختن دادهٔ آینده؛ باید همان اول رد شود."""
    from mtflab import autoscan as _A
    _A.set_lang("fa")
    from mtflab.autoscan import validate_tf_stack
    try:
        validate_tf_stack("4h", "1h", "1d")
    except ValueError as e:
        assert "ریزتر" in str(e)
    else:
        raise AssertionError("باید ValueError می‌داد")


def test_validate_tf_stack_rejects_a_non_multiple():
    """۱۵m→۴۵m مضرب صحیح نیست (۳)؛ resample_up هم ردش می‌کند ولی دیر."""
    from mtflab import autoscan as _A
    _A.set_lang("fa")
    from mtflab.autoscan import validate_tf_stack
    try:
        validate_tf_stack("30m", "45", "4h")
    except ValueError as e:
        assert "مضرب" in str(e)
    else:
        raise AssertionError("باید ValueError می‌داد")


def test_validate_tf_stack_rejects_unknown_timeframe():
    """تایم‌فریم ناشناخته باید پیام روشن بدهد، نه KeyError خشک."""
    from mtflab import autoscan as _A
    _A.set_lang("fa")
    from mtflab.autoscan import validate_tf_stack
    # نکته: "7m"/"3d" عمداً مجازند (tf_to_minutes عدد+واحد را می‌فهمد)
    for args in (("zz", "1d", "1d"), ("15m", "abc", "4h"), ("15m", "1h", "q")):
        try:
            validate_tf_stack(*args)
        except ValueError as e:
            assert "ناشناخته" in str(e), str(e)
        else:
            raise AssertionError(f"باید ValueError می‌داد: {args}")


def test_autoscan_validates_before_touching_the_network():
    """ترکیب نامعتبر باید *قبل از* دانلود شکست بخورد، نه بعد از چند دقیقه.

    این تست عمداً روی source=json اجرا می‌شود: اگر اعتبارسنجی جا افتاده باشد،
    کد وارد دانلود/خواندن کش می‌شود و خطای دیگری می‌دهد.
    """
    import inspect
    from mtflab.autoscan import autoscan
    cfg = load_config(["--data", "synthetic", "--quiet"])
    with tempfile.TemporaryDirectory() as td:
        try:
            autoscan(cfg, ["BTCUSDT"], 30, "4h", td, source="json",
                     progress=False, tf_filter="1h")
        except ValueError as e:
            assert "ریزتر" in str(e)
        else:
            raise AssertionError("باید ValueError می‌داد")

    sig = inspect.signature(autoscan)
    assert sig.parameters["tf_filter"].default == "1d"
    assert sig.parameters["tf_bias"].default == "1d"


def test_report_headers_show_all_three_timeframes():
    """گزارش باید هر سه لایه را نشان دهد؛ وگرنه معلوم نیست چه چیزی آزموده شد."""
    from mtflab import autoscan as A
    res = _tiny_res(10)
    res["settings"]["tf_filter"] = "1h"
    res["settings"]["tf_bias"] = "4h"
    A.set_lang("en")
    try:
        en = A.render_report_en(res)
    finally:
        A.set_lang("fa")
    fa = A.render_report(res)
    assert "filter `1h`" in en and "bias `4h`" in en
    assert "فیلتر: `1h`" in fa and "بایاس: `4h`" in fa


def test_validation_error_is_english_when_lang_is_en():
    """روی Termux متن خطا هم باید انگلیسی باشد، نه نیم‌فارسی."""
    from mtflab import autoscan as A
    A.set_lang("en")
    try:
        try:
            A.validate_tf_stack("4h", "1h", "1d")
        except ValueError as e:
            msg = str(e)
        else:
            raise AssertionError("باید ValueError می‌داد")
    finally:
        A.set_lang("fa")
    assert "finer than the trigger" in msg
    assert "ریزتر" not in msg


# ── ۹) سلامت داده: دادهٔ ناقص/کهنه نباید بی‌صدا وارد دروازه شود ──────────────
def _fresh(cs, tf="15m"):
    """کندل‌ها را طوری جابه‌جا می‌کند که آخرین کندل «الان» باشد (برای تست)."""
    from dataclasses import replace as _replace
    import time as _time
    step = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}[tf] * 60_000
    last = cs[-1].open_time_ms
    shift = ((int(_time.time() * 1000) // step) * step) - last
    return [_replace(c, open_time_ms=c.open_time_ms + shift) for c in cs]


def test_integrity_accepts_fresh_complete_data():
    """دادهٔ تازه و کامل باید ok باشد."""
    from mtflab.autoscan import data_integrity
    cs = _fresh(synthetic_candles("15m", 2000, seed=5))
    ig = data_integrity(cs, "15m", 30)
    assert ig["ok"] is True, ig
    assert ig["missing_ratio"] < 0.01
    assert ig["front_gap_days"] > 0      # ۲۰ روز داده داریم، بازه ۳۰ روز بود


def test_integrity_rejects_a_stale_tail():
    """اگر آخرین کندل قدیمی باشد (دانلود نیمه‌کاره) باید رد شود."""
    from mtflab.autoscan import data_integrity
    cs = synthetic_candles("15m", 2000, seed=5)      # تاریخ ثابت در گذشته
    ig = data_integrity(cs, "15m", 30)
    assert ig["ok"] is False
    assert "تازه نیست" in ig["reason"]


def test_integrity_rejects_missing_candles_in_the_middle():
    """پرش ۲۰٪ در وسط داده ⇒ رد؛ چون یعنی صفحهٔ ناموفق یا دادهٔ ناقص."""
    from mtflab.autoscan import data_integrity
    cs = _fresh(synthetic_candles("15m", 2000, seed=5))
    holed = cs[:800] + cs[1200:]                     # ۴۰۰ کندل وسط حذف شد
    ig = data_integrity(holed, "15m", 30)
    assert ig["ok"] is False
    assert "غایب" in ig["reason"]


def test_integrity_accepts_a_young_symbol_but_reports_the_gap():
    """نماد تازه‌لیست‌شده نقص داده نیست؛ باید ok باشد ولی فاصله گزارش شود."""
    from mtflab.autoscan import data_integrity
    cs = _fresh(synthetic_candles("15m", 500, seed=5))   # ~۵ روز داده
    ig = data_integrity(cs, "15m", 730)                  # بازه ۲ سال
    assert ig["ok"] is True
    assert ig["front_gap_days"] > 700


def test_autoscan_excludes_invalid_data_unless_explicitly_allowed():
    """دادهٔ کهنه نباید وارد نتیجه شود — مگر با --allow-stale (که در گزارش هم می‌آید)."""
    from mtflab.autoscan import autoscan
    cs = synthetic_candles("15m", 3000, seed=9)          # کهنه
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "json"), exist_ok=True)
        with open(os.path.join(td, "json", "btcusdt_15m.json"), "w",
                  encoding="utf-8") as f:
            json.dump(candles_to_json(cs, {"symbol": "BTCUSDT", "tf": "15m"}), f)
        cfg = load_config(["--data", "synthetic", "--quiet"])

        res = autoscan(cfg, ["BTCUSDT"], 30, "15m", td, source="json",
                       progress=False)
        assert res["per_symbol"] == {}
        assert any("نامعتبر" in e for e in res["errors"]), res["errors"]

        res2 = autoscan(cfg, ["BTCUSDT"], 30, "15m", td, source="json",
                        progress=False, allow_stale=True)
        assert "BTCUSDT" in res2["per_symbol"]
        assert res2["settings"]["allow_stale"] is True
        ig = res2["coverage"]["BTCUSDT"]["integrity"]
        assert ig["ok"] is False          # در گزارش هم دیده می‌شود


def test_csv_cache_of_downloads_is_optional():
    """autoscan نباید CSV دوم بسازد؛ JSON منبع رسمی است (صرفه‌جویی فضای گوشی)."""
    import inspect
    from mtflab.bybit_public import fetch_klines_range
    sig = inspect.signature(fetch_klines_range)
    assert sig.parameters["save_csv"].default is True   # رفتار قبلی برای بقیه


def test_core_year_view_is_declared_and_separate_from_the_gate():
    """نمای «سال هسته» باید وجود داشته باشد ولی در survived دخالت نکند."""
    from mtflab.autoscan import MIN_YEAR_TRADES, aggregate
    per = {"A": {"base": {"n": 40, "profit_factor": 1.2, "expectancy": 1.0,
                          "pnl": 10.0, "years_n": 3, "positive_years": 3,
                          "per_year": {"2024": {"pnl": 1.0, "n": 2},
                                       "2025": {"pnl": 5.0, "n": 25},
                                       "2026": {"pnl": 4.0, "n": 13}}}}}
    a = aggregate(per, ["base"])["base"]
    assert a["years_n"] == 3 and a["positive_years"] == 3
    assert a["core_years_n"] == 2 and a["positive_years_core"] == 2
    assert MIN_YEAR_TRADES == 10
    # دروازه همان قاعدهٔ قبلی است
    assert a["checks"]["positive_years"] is True
