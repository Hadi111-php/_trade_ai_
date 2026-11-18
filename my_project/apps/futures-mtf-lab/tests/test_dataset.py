"""تست‌های «مجموعه‌دادهٔ یک‌جا»: صادرات/ورود/شمارش.

هدف: کاربر یک فایل می‌فرستد و ما همان را بدون تغییر برمی‌گردانیم؛ پس باید
هیچ کندلی گم/جابه‌جا نشود و فایل خودتوصیف باشد (schema + هش).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import dataset                                        # noqa: E402


def _cache(data_dir, sym="BTCUSDT", tf="4h", n=5):
    os.makedirs(os.path.join(data_dir, "json"), exist_ok=True)
    payload = {"meta": {"symbol": sym, "tf": tf, "n": n},
               "columns": ["ts", "open", "high", "low", "close", "volume"],
               "candles": [[1_700_000_000_000 + i * 14_400_000, 100 + i, 101 + i,
                            99 + i, 100.5 + i, 10.0] for i in range(n)]}
    p = os.path.join(data_dir, "json", f"{sym.lower()}_{tf}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return p


def test_build_counts_and_schema():
    with tempfile.TemporaryDirectory() as td:
        _cache(td, "BTCUSDT", "4h", 7)
        _cache(td, "ETHUSDT", "4h", 3)
        data = dataset.load_from_cache(td, ["BTCUSDT", "ETHUSDT"], ["4h"])
        payload = dataset.build(data, days=365, tfs=["4h"])
        assert payload["schema"] == dataset.SCHEMA
        assert payload["counts"]["4h"] == 10
        assert payload["n_candles"] == 10
        assert payload["symbols"] == ["BTCUSDT", "ETHUSDT"]
        # کندل‌ها دست‌نخورده
        assert len(payload["data"]["BTCUSDT"]["4h"]["candles"]) == 7


def test_export_writes_hash_and_import_restores_files():
    with tempfile.TemporaryDirectory() as td:
        _cache(td, "BTCUSDT", "4h", 4)
        _cache(td, "BTCUSDT", "1d", 2)
        data = dataset.load_from_cache(td, ["BTCUSDT"], ["4h", "1d"])
        out = os.path.join(td, "ds.json")
        rep = dataset.write_dataset(dataset.build(data, tfs=["4h", "1d"]), out)
        assert os.path.isfile(out) and rep["sha256"] == dataset._sha256(out)

        fresh = os.path.join(td, "fresh")
        imp = dataset.import_dataset(out, fresh)
        assert imp["written"] == 2
        for tf in ("4h", "1d"):
            p = dataset.cache_path(fresh, "BTCUSDT", tf)
            assert os.path.isfile(p)
        # دور دوم: فایل‌های موجود دست‌نخورده می‌مانند
        imp2 = dataset.import_dataset(out, fresh)
        assert imp2["kept_existing"] == 2


def test_import_rejects_foreign_json():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.json")
        json.dump({"schema": "something.else", "data": {}}, open(p, "w"))
        try:
            dataset.import_dataset(p, td)
        except ValueError as e:
            assert "schema" in str(e)
        else:
            raise AssertionError("باید ValueError می‌داد")


def test_cli_export_from_cache_prints_sha():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        _cache(td, "BTCUSDT", "4h", 3)
        out = os.path.join(td, "out.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dataset.dataset_command(["--data-dir", td, "--symbols", "BTCUSDT",
                                          "--tfs", "4h", "--export", out])
        assert rc == 0
        assert os.path.isfile(out)
        text = buf.getvalue()
        assert "sha256" in text and "📦" in text
        assert "4h=3" in text                       # تفکیک واقعی، نه صفر


def test_cli_without_cache_and_without_download_exits_2():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dataset.dataset_command(["--data-dir", td, "--export",
                                          os.path.join(td, "x.json")])
        assert rc == 2
        assert "download" in buf.getvalue()


def test_default_tfs_are_for_a_4h_system():
    assert dataset.DEFAULT_TFS == ("1d", "4h", "1h")
    assert dataset.DEFAULT_DAYS >= 730          # حداقل دو رژیم


def test_run_auto_dataset_flag():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sh = open(os.path.join(root, "run-auto.sh"), encoding="utf-8").read()
    assert "--dataset|--data-pack)" in sh and "-m mtflab dataset" in sh
    mn = open(os.path.join(root, "mtflab", "__main__.py"), encoding="utf-8").read()
    assert '"dataset", "data-pack"' in mn


# ── رگرسیون باگ واقعی گوشی (۱۴۰۴/۰۸/۲۸) ──────────────────────────────────────
# نشانه: «ValueError: unknown url type: '/v5/market/kline?...'» برای هر نماد،
# سپس یک فایل dataset با ۰ کندل و هش معتبر. علت: `--base-url` خالی مستقیم به
# `urlopen` می‌رسید. این تست‌ها همان مسیر را قفل می‌کنند.

def _patch_autoscan(fetch=None, pick=None):
    from mtflab import autoscan
    old_f, old_p = autoscan.fetch_or_load, autoscan.pick_base_url
    if fetch is not None:
        autoscan.fetch_or_load = fetch
    if pick is not None:
        autoscan.pick_base_url = pick
    return lambda: (setattr(autoscan, "fetch_or_load", old_f),
                    setattr(autoscan, "pick_base_url", old_p))


def test_download_resolves_empty_base_url_before_request():
    seen = {}

    def fake_fetch(symbol, tf, days, data_dir, base_url, **kw):
        seen.setdefault("urls", set()).add(base_url)
        return [], {}

    restore = _patch_autoscan(fetch=fake_fetch,
                              pick=lambda candidates=None, progress=True: "https://api.bybit.com")
    try:
        with tempfile.TemporaryDirectory() as td:
            dataset.download(["BTCUSDT", "ETHUSDT"], ["4h"], 30, td, progress=False)
    finally:
        restore()
    assert seen["urls"] == {"https://api.bybit.com"}, seen


def test_download_rejects_relative_base_url():
    called = {"n": 0}

    def fake_fetch(*a, **kw):
        called["n"] += 1
        return [], {}

    restore = _patch_autoscan(fetch=fake_fetch)
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                dataset.download(["BTCUSDT"], ["4h"], 30, td, base_url="/v5/market/kline",
                                 progress=False)
                raise AssertionError("باید ValueError می‌داد")
            except ValueError as e:
                assert "https://" in str(e)
    finally:
        restore()
    assert called["n"] == 0


def test_download_fails_fast_when_nothing_works():
    def boom(*a, **kw):
        raise ValueError("unknown url type: '/v5/market/kline'")

    restore = _patch_autoscan(fetch=boom,
                              pick=lambda candidates=None, progress=True: "https://api.bybit.com")
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                dataset.download(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"], ["4h"],
                                 30, td, progress=False)
                raise AssertionError("باید RuntimeError می‌داد")
            except RuntimeError as e:
                assert "سه تلاش" in str(e)
    finally:
        restore()


def test_cli_never_writes_empty_dataset():
    import contextlib
    import io

    restore = _patch_autoscan(fetch=lambda *a, **kw: ([], {}),
                              pick=lambda candidates=None, progress=True: "https://api.bybit.com")
    try:
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "empty.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = dataset.dataset_command(["--data-dir", td, "--download",
                                              "--days", "30", "--tfs", "4h",
                                              "--symbols", "BTCUSDT", "--export", out])
            assert rc == 2, buf.getvalue()
            assert not os.path.exists(out), "فایل صفر-کندلی نباید نوشته شود"
            assert "خالی" in buf.getvalue()
    finally:
        restore()


def test_parallel_download_keeps_every_file_and_is_faster():
    """۲۴ فایل با jobs=6 باید هم کامل باشند و هم از حالت سریال سریع‌تر."""
    import time as _t

    def fake_fetch(symbol, tf, days, data_dir, base_url, **kw):
        _t.sleep(0.02)                       # شبکهٔ ساختگی
        p = dataset.cache_path(data_dir, symbol, tf)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"meta": {"symbol": symbol, "tf": tf},
                       "candles": [[1_700_000_000_000 + i * 60_000, 1, 1, 1, 1, 1]
                                   for i in range(3)]}, f)
        return [object()], {}

    restore = _patch_autoscan(fetch=fake_fetch,
                              pick=lambda candidates=None, progress=True: "https://api.bybit.com")
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    tfs = ["1d", "4h", "1h"]
    try:
        with tempfile.TemporaryDirectory() as td:
            t0 = _t.time()
            serial = dataset.download(syms, tfs, 30, td, progress=False, jobs=1)
            t_serial = _t.time() - t0
            with tempfile.TemporaryDirectory() as td2:
                t0 = _t.time()
                par = dataset.download(syms, tfs, 30, td2, progress=False, jobs=6)
                t_par = _t.time() - t0
    finally:
        restore()
    assert len(serial) == len(par) == 4
    for s in syms:
        assert set(par[s.upper()]) == set(tfs), par[s]
    assert len(par["BTCUSDT"]["4h"]["candles"]) == 3
    assert t_par < t_serial, f"موازی سریع‌تر نبود: {t_par:.2f} vs {t_serial:.2f}"


def test_jobs_is_clamped_and_parallel_aborts_on_total_failure():
    def boom(*a, **kw):
        raise ValueError("unknown url type: '/v5/market/kline'")

    restore = _patch_autoscan(fetch=boom,
                              pick=lambda candidates=None, progress=True: "https://api.bybit.com")
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                dataset.download(["BTCUSDT"] * 4, ["1d"], 30, td, progress=False, jobs=99)
                raise AssertionError("باید RuntimeError می‌داد")
            except RuntimeError as e:
                assert "سه تلاش" in str(e)
    finally:
        restore()
