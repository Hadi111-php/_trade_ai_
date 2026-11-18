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
