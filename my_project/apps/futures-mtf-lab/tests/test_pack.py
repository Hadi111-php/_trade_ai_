"""تست‌های «بسته‌بندی پروژه در ZIP» برای Termux/PC.

سه چیز مهم است:
۱. فایل ZIP سبک باشد: `.git/`، `results/`، `data/` و `__pycache__` بیرون بمانند.
۲. نام فایل امن باشد — شاخهٔ `arena/444f3300-trade-ai` نباید `/` در نام بگذارد
   (این باگ واقعاً رخ داد و zipfile با FileNotFoundError افتاد).
۳. اگر پوشهٔ Download در دسترس نبود، ابزار باید راهنما بدهد نه اینکه ساکت بماند.
"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import pack                                            # noqa: E402


def _fake_repo(td: str) -> str:
    root = os.path.join(td, "repo")
    os.makedirs(os.path.join(root, ".git", "objects"))
    os.makedirs(os.path.join(root, "mtflab", "__pycache__"))
    os.makedirs(os.path.join(root, "results", "control"))
    os.makedirs(os.path.join(root, "data", "json"))
    os.makedirs(os.path.join(root, "docs"))
    open(os.path.join(root, "run-auto.sh"), "w").write("#!/bin/bash\n")
    open(os.path.join(root, "mtflab", "health.py"), "w").write("# health\n")
    open(os.path.join(root, "mtflab", "__pycache__", "x.pyc"), "w").write("junk")
    open(os.path.join(root, "docs", "SUMMARY.md"), "w").write("doc\n")
    open(os.path.join(root, ".git", "HEAD"), "w").write("ref: refs/heads/x\n")
    open(os.path.join(root, "results", "control", "c.md"), "w").write("x\n")
    open(os.path.join(root, "data", "json", "btc_4h.json"), "w").write("{}\n")
    open(os.path.join(root, "big.csv"), "w").write("a,b\n1,2\n")
    open(os.path.join(root, ".gitkeep"), "w").write("")
    return root


def test_zip_excludes_heavy_stuff_and_keeps_code():
    with tempfile.TemporaryDirectory() as td:
        root = _fake_repo(td)
        rep = pack.make_zip(root, td)
        names = zipfile.ZipFile(rep["path"]).namelist()
        assert any(n.endswith("mtflab/health.py") for n in names)
        assert any(n.endswith("run-auto.sh") for n in names)
        assert any(n.endswith("docs/SUMMARY.md") for n in names)
        assert any(n.endswith("PACK_INFO.txt") for n in names)
        assert not any("/.git/" in n for n in names)
        assert not any("/results/" in n for n in names)
        assert not any("/data/" in n for n in names)
        assert not any("__pycache__" in n for n in names)
        assert not any(n.endswith(".csv") for n in names)


def test_filename_is_safe_when_branch_has_slash():
    with tempfile.TemporaryDirectory() as td:
        root = _fake_repo(td)
        # نام شاخه از git خوانده می‌شود؛ این‌جا مستقیم نام را با «/» می‌سازیم
        rep = pack.make_zip(root, td, name="mtf-lab-arena/444f3300-trade-ai")
        base = os.path.basename(rep["path"])
        assert "/" not in base
        assert os.path.isfile(rep["path"])
        assert base.endswith(".zip")


def test_sha_and_size_reported():
    with tempfile.TemporaryDirectory() as td:
        rep = pack.make_zip(_fake_repo(td), td)
        assert rep["sha256"] == pack.sha256_of(rep["path"])
        assert rep["bytes"] == os.path.getsize(rep["path"])
        assert rep["files"] >= 4


def test_with_data_and_full_toggles():
    with tempfile.TemporaryDirectory() as td:
        root = _fake_repo(td)
        rep = pack.make_zip(root, td, with_data=True, name="withdata")
        names = zipfile.ZipFile(rep["path"]).namelist()
        assert any("/results/" in n for n in names)
        assert any("/data/" in n for n in names)
        rep2 = pack.make_zip(root, td, with_git=True, name="withgit")
        names2 = zipfile.ZipFile(rep2["path"]).namelist()
        assert any("/.git/" in n for n in names2)


def test_copy_to_download_and_fallback():
    with tempfile.TemporaryDirectory() as td:
        rep = pack.make_zip(_fake_repo(td), td)
        dest = os.path.join(td, "downloads")
        os.makedirs(dest)
        got = pack.copy_to_download(rep["path"], dest)
        assert got and os.path.isfile(got)
        assert pack.sha256_of(got) == rep["sha256"]
        # پوشهٔ ناموجود ⇒ رشتهٔ خالی (نه استثنا)
        assert pack.copy_to_download(rep["path"], os.path.join(td, "nope")) == ""


def test_cli_prints_path_and_hash():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        root = _fake_repo(td)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pack.pack_command(["--root", root, "--out-dir", td, "--no-copy"])
        out = buf.getvalue()
        assert rc == 0
        assert "ZIP ساخته شد" in out and "sha256" in out
        assert any(n.endswith(".zip") for n in os.listdir(td))


def test_download_hint_when_storage_missing():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        root = _fake_repo(td)
        old = os.environ.get("HOME")
        os.environ["HOME"] = td                    # ~/storage/downloads وجود ندارد
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pack.pack_command(["--root", root, "--out-dir", td])
            assert "termux-setup-storage" in buf.getvalue()
        finally:
            if old is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old


def test_run_auto_zip_and_main_dispatch():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sh = open(os.path.join(root, "run-auto.sh"), encoding="utf-8").read()
    assert "--zip|--pack)" in sh and "-m mtflab pack" in sh
    mn = open(os.path.join(root, "mtflab", "__main__.py"), encoding="utf-8").read()
    assert '"pack", "zip"' in mn and "pack_command" in mn
