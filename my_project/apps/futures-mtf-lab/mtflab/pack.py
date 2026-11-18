"""بسته‌بندی پروژه در یک فایل ZIP — برای فرستادن/پشتیبان‌گیری از گوشی.

**چرا:** کاربر روی Termux می‌خواهد کل پروژه را در یک فایل داشته باشد و در پوشهٔ
Download گوشی پیدا کند. دو دام واقعی این‌جا هست:

۱. اگر `.git/` و `results/` و `data/` هم داخل بیایند، فایل چند صد مگابایت می‌شود
   و روی گوشی کپی‌کردنش وقت می‌گیرد — در حالی که برای «فرستادنِ کد» لازم نیستند.
۲. بدون `termux-setup-storage`، پوشهٔ Download در دسترس نیست؛ ابزار باید همان را
   بگوید، نه اینکه ساکت شکست بخورد.

پس: ZIP با `zipfile` کتابخانهٔ استاندارد (نیاز به `pkg install zip` ندارد)،
با فهرست صریحِ پوشه‌های سنگین/بازتولیدشدنی، و کپی به Download با هش sha256.

**چه نمی‌کند:** هیچ فایلی را تغییر نمی‌دهد، چیزی حذف نمی‌کند و به شبکه دست
نمی‌زند. `--full` (با `.git`) هم فقط نسخهٔ پشتیبان است، نه «پوش».
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
import zipfile
from typing import Dict, List, Optional, Tuple

VERSION = "1"

#: پوشه‌هایی که هیچ‌وقت داخل ZIP نمی‌روند (حجم بدون فایده برای «فرستادن کد»).
SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
             "node_modules", ".venv", "venv", "dist", "build", ".next", ".cache",
             "results", "data", "data_archive", "exports", "coverage", ".idea",
             ".vscode", ".turbo", ".arena"}
#: پسوندهای سنگین/موقت
SKIP_EXT = {".pyc", ".pyo", ".log", ".tmp", ".zip", ".tar", ".gz", ".csv", ".parquet"}
#: سقف حجم هر فایل (بیشتر از این، احتمالاً دادهٔ سنگین است نه کد)
MAX_FILE_BYTES = 8 * 1024 * 1024


def repo_root(start: str = ".") -> str:
    """ریشهٔ مخزن git؛ اگر نبود، همان پوشهٔ داده‌شده."""
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    cur = os.path.abspath(start)
    while cur != "/" and not os.path.exists(os.path.join(cur, ".git")):
        cur = os.path.dirname(cur)
    return cur if os.path.exists(os.path.join(cur, ".git")) else os.path.abspath(start)


def git_info(root: str) -> Dict[str, str]:
    info = {"branch": "", "commit": "", "dirty": ""}
    try:
        for key, args in (("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
                          ("commit", ["rev-parse", "--short", "HEAD"]),
                          ("dirty", ["status", "--porcelain"])):
            out = subprocess.run(["git", "-C", root] + args, capture_output=True,
                                 text=True, timeout=8)
            if out.returncode == 0:
                info[key] = out.stdout.strip() if key == "dirty" else out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def download_dir() -> str:
    """پوشهٔ Download گوشی اگر در دسترس باشد، وگرنه رشتهٔ خالی."""
    for cand in (os.path.expanduser("~/storage/downloads"), "/sdcard/Download",
                 os.path.expanduser("~/storage/shared/Download")):
        if os.path.isdir(cand):
            return cand
    return ""


def _skip(rel: str, size: int, with_data: bool, with_git: bool) -> bool:
    parts = rel.split(os.sep)
    for p in parts[:-1]:
        if p in SKIP_DIRS:
            if p == ".git" and with_git:
                continue
            if p in ("results", "data", "data_archive") and with_data:
                continue
            return True
    if rel.endswith(".gitkeep"):
        return False
    if os.path.splitext(rel)[1].lower() in SKIP_EXT:
        return True
    return size > MAX_FILE_BYTES


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def make_zip(root: str, out_dir: str = "", *, with_data: bool = False,
             with_git: bool = False, name: str = "") -> dict:
    """ZIP می‌سازد و مسیر/حجم/تعداد فایل/هش را برمی‌گرداند."""
    root = os.path.abspath(root)
    info = git_info(root)
    # نام شاخه می‌تواند `/` داشته باشد («arena/…») ⇒ نام فایل باید امن شود.
    def _safe(x: str) -> str:
        return "".join(ch if (ch.isalnum() or ch in "._-") else "-" for ch in str(x))

    parts = ["mtf-lab", _safe(info.get("branch") or "nogit"),
             _safe(info.get("commit") or "nocommit")]
    if with_data:
        parts.append("withdata")
    if with_git:
        parts.append("withgit")
    parts.append(_stamp())
    fname = _safe(name or "-".join(parts)) + ".zip"
    out_dir = out_dir or os.path.join(root, "..")
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(os.path.abspath(out_dir), fname)

    n_files = 0
    n_skip = 0
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            # هرسِ پوشه‌ها: سرعت و حجم
            keep = []
            for d in sorted(dirnames):
                full = os.path.join(dirpath, d)
                rel = d if rel_dir == "." else os.path.join(rel_dir, d)
                if d in SKIP_DIRS and not (with_git and d == ".git") \
                        and not (with_data and d in ("results", "data", "data_archive")):
                    n_skip += 1
                    continue
                if os.path.islink(full):
                    continue
                keep.append(d)
            dirnames[:] = keep
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = fn if rel_dir == "." else os.path.join(rel_dir, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                if os.path.islink(full) or _skip(rel, size, with_data, with_git):
                    n_skip += 1
                    continue
                try:
                    z.write(full, arcname=os.path.join("mtf-lab", rel))
                    n_files += 1
                except OSError:
                    n_skip += 1
        z.writestr("mtf-lab/PACK_INFO.txt",
                   (f"branch: {info.get('branch')}\ncommit: {info.get('commit')}\n"
                    f"dirty: {len(info.get('dirty') or '') > 0}\n"
                    f"files: {n_files}\npacked: {_stamp()}\n"
                    f"note: .git{'/results/data' if with_git else ''} "
                    f"{'included' if (with_git or with_data) else 'excluded'}\n"))
    return {"path": dest, "name": fname, "files": n_files, "skipped": n_skip,
            "bytes": os.path.getsize(dest), "sha256": sha256_of(dest),
            "branch": info.get("branch") or "", "commit": info.get("commit") or "",
            "dirty": bool(info.get("dirty"))}


def copy_to_download(src: str, dest_dir: str = "") -> str:
    """کپی به Download؛ مسیر مقصد یا رشتهٔ خالی (اگر دسترسی نبود)."""
    d = dest_dir or download_dir()
    if not d or not os.path.isdir(d):
        return ""
    dst = os.path.join(d, os.path.basename(src))
    try:
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            for chunk in iter(lambda: fi.read(1 << 20), b""):
                fo.write(chunk)
        if os.path.getsize(dst) != os.path.getsize(src):
            return ""
        return dst
    except OSError:
        return ""


def pack_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="mtflab pack",
                                description="ZIP از پروژه + کپی به Download گوشی")
    p.add_argument("--root", default="", help="ریشهٔ پروژه (پیش‌فرض: مخزن جاری)")
    p.add_argument("--out-dir", default="", help="پوشهٔ خروجی ZIP (پیش‌فرض: کنار مخزن)")
    p.add_argument("--with-data", action="store_true", help="شامل results/ و data/")
    p.add_argument("--full", action="store_true", help="پشتیبان کامل (با .git)")
    p.add_argument("--no-copy", action="store_true", help="به Download کپی نکن")
    a = p.parse_args(argv)

    root = a.root or repo_root(os.getcwd())
    info = git_info(root)
    print(f"📦 پروژه: {root}")
    if info.get("branch"):
        print(f"   شاخه: {info['branch']} · کد: {info.get('commit') or '?'}"
              + ("  ⚠️ تغییر ذخیره‌نشده دارد" if info.get("dirty") else ""))
    if info.get("branch") in ("main", "master"):
        print("   ⚠️ روی شاخهٔ اصلی هستی؛ کارهای این پروژه روی شاخهٔ "
              "arena/444f3300-trade-ai است.")

    rep = make_zip(root, a.out_dir or os.path.join(root, os.pardir),
                   with_data=a.with_data, with_git=a.full)
    mb = rep["bytes"] / 1048576
    print(f"✅ ZIP ساخته شد: {rep['path']}")
    print(f"   {rep['files']} فایل · {mb:.1f} مگابایت · {rep['skipped']} مورد رد شد")
    print(f"🔐 sha256 = {rep['sha256']}")
    if not a.full and not a.with_data:
        print("   (بدون .git و results/ و data/ — برای پشتیبان کامل: --full)")
    if not a.no_copy:
        dst = copy_to_download(rep["path"])
        if dst:
            print(f"📥 کپی شد در: {dst}")
        else:
            print("⚠️ پوشهٔ Download در دسترس نیست. یک‌بار در Termux بزن:")
            print("   termux-setup-storage")
            print(f"   یا خودت کپی کن: cp '{rep['path']}' ~/storage/downloads/")
    return 0
