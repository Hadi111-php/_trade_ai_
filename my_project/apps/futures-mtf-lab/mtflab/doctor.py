"""معاینهٔ سریع نصب — «چرا داشبورد/اتوترید بالا نمی‌آید؟»

این ماژول هیچ معامله‌ای نمی‌کند و به شبکه هم دست نمی‌زند. فقط همان چیزهایی را
می‌سنجد که روی گوشی واقعاً می‌شکنند:

  • پورت اشغال (بیشترین علت: یک `--dash` قدیمی که بسته نشده)
  • نبودِ دادهٔ کش‌شده (داشبورد بالا می‌آید ولی خالی است)
  • پوشهٔ `results/` غیرقابل‌نوشتن
  • نبودِ `termux-api` (مرورگر خودکار باز نمی‌شود، ولی داشبورد سالم است)
  • فضای کم دیسک

هر بررسی `ok` دارد و یک `hint` که دقیقاً می‌گوید چه بزنی. خروجی صفر یعنی هیچ
مشکلِ **مانعِ اجرا** پیدا نشد؛ هشدارها اجرا را نمی‌بندند.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from typing import Dict, List

MIN_PY = (3, 8)


def _check(cid: str, fa: str, ok: bool, detail: str, hint: str = "",
           warn_only: bool = False) -> dict:
    return {"id": cid, "fa": fa, "ok": bool(ok), "detail": detail,
            "hint": hint, "warn_only": bool(warn_only)}


def port_free(port: int, host: str = "0.0.0.0") -> bool:
    """آیا می‌شود روی این پورت گوش داد؟ (سوکت فوراً بسته می‌شود.)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _data_summary(data_dir: str, tf: str) -> dict:
    jdir = os.path.join(data_dir, "json")
    files: List[str] = []
    if os.path.isdir(jdir):
        files = [n for n in os.listdir(jdir) if n.endswith(f"_{tf}.json")]
    newest = 0.0
    newest_name = ""
    for n in files:
        try:
            m = os.path.getmtime(os.path.join(jdir, n))
        except OSError:
            continue
        if m > newest:
            newest, newest_name = m, n
    return {"count": len(files), "dir": jdir, "newest": newest,
            "newest_name": newest_name}


def _journal_lines(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def run_checks(data_dir: str = "data", tf: str = "4h", port: int = 8770,
               state: str = "results/live/state.json",
               journal: str = "results/live/journal.jsonl",
               brain_model: str = "results/brain_model.json") -> Dict[str, object]:
    checks: List[dict] = []

    # ۱) پایتون
    v = sys.version_info
    checks.append(_check(
        "python", "نسخهٔ پایتون", v[:2] >= MIN_PY, f"{v.major}.{v.minor}.{v.micro}",
        f"حداقل {MIN_PY[0]}.{MIN_PY[1]} لازم است — pkg up && pkg install python"))

    # ۲) پورت
    free = port_free(port)
    checks.append(_check(
        "port", f"پورت {port} آزاد است", free,
        "آزاد" if free else "اشغال — احتمالاً یک داشبورد قدیمی باز مانده",
        f"pkill -f 'mtflab live --serve'   # یا: bash run-auto.sh --dash --port {port + 1}"))

    # ۳) نوشتن در پوشهٔ جاری و results
    for cid, fa, path in (("cwd", "نوشتن در پوشهٔ پروژه", "."),
                          ("results", "پوشهٔ results قابل نوشتن", "results")):
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".doctor_probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            checks.append(_check(cid, fa, True, os.path.abspath(path)))
        except OSError as e:
            checks.append(_check(cid, fa, False, str(e)[:70],
                                 "فضای دیسک یا مجوز پوشه را بررسی کن"))

    # ۴) دادهٔ کش‌شده
    ds = _data_summary(data_dir, tf)
    have = ds["count"] > 0
    when = ""
    if ds["newest"]:
        import time as _t
        when = " · تازه‌ترین: " + _t.strftime("%Y-%m-%d %H:%M",
                                             _t.localtime(ds["newest"]))
    # داشبورد با کش خالی هم بالا می‌آید (فقط جدول‌ها خالی‌اند) → هشدار، نه مانع.
    checks.append(_check(
        "data", f"دادهٔ {tf} در کش", have,
        f"{ds['count']} فایل{when}" if have else "0 فایل — داشبورد بالا می‌آید ولی خالی است",
        "bash run-auto.sh --live   # یا: bash run-auto.sh --dash (قدم پس‌زمینه)",
        warn_only=True))

    # ۵) وضعیت و ژورنال اتوترید
    st_ok = os.path.isfile(state)
    checks.append(_check(
        "state", "حساب مجازی ساخته شده", st_ok,
        state if st_ok else "هنوز نبود — اولین اجرای --live می‌سازد",
        "bash run-auto.sh --live", warn_only=True))
    n = _journal_lines(journal)
    checks.append(_check(
        "journal", "ژورنال سیگنال‌ها", n > 0, f"{n} رکورد",
        "bash run-auto.sh --live", warn_only=True))

    # ۶) مدل مغز
    has_model = os.path.isfile(brain_model)
    checks.append(_check(
        "brain", "مدل «چشم مغز»", has_model,
        brain_model if has_model else "نبود — اتوترید بدون نظاره‌گر اجرا می‌شود",
        "bash run-auto.sh --brain-view --train", warn_only=True))

    # ۷) termux-api (باز شدن خودکار مرورگر)
    opener = shutil.which("termux-open-url") or shutil.which("termux-open")
    checks.append(_check(
        "termux_api", "termux-api برای بازکردن مرورگر", bool(opener),
        opener or "نصب نیست — نشانی را دستی در مرورگر بزن",
        "pkg install termux-api  (و افزونهٔ Termux:API از F-Droid)",
        warn_only=True))

    # ۸) فضای دیسک
    try:
        du = shutil.disk_usage(".")
        free_mb = du.free // (1024 * 1024)
        checks.append(_check(
            "disk", "فضای دیسک", free_mb >= 100, f"{free_mb} MB آزاد",
            "فایل‌های results/ قدیمی را پاک کن", warn_only=True))
    except OSError:
        pass

    blocking = [c for c in checks if not c["ok"] and not c["warn_only"]]
    warnings = [c for c in checks if not c["ok"] and c["warn_only"]]
    return {"ok": not blocking, "checks": checks,
            "blocking": [c["id"] for c in blocking],
            "warnings": [c["id"] for c in warnings]}


def render(rep: Dict[str, object], lang: str = "fa") -> str:
    fa = lang != "en"
    out: List[str] = []
    out.append("🩺 معاینهٔ نصب\n" if fa else "🩺 install check\n")
    out.append("| بررسی | نتیجه | جزئیات |" if fa else "| check | result | detail |")
    out.append("|---|---|---|")
    for c in rep["checks"]:
        mark = "✅" if c["ok"] else ("⚠️" if c["warn_only"] else "❌")
        out.append(f"| {c['fa'] if fa else c['id']} | {mark} | {c['detail']} |")
    out.append("")
    bad = [c for c in rep["checks"] if not c["ok"] and not c["warn_only"]]
    warn = [c for c in rep["checks"] if not c["ok"] and c["warn_only"]]
    if bad:
        out.append("❌ مانعِ اجرا:" if fa else "❌ blocking:")
        for c in bad:
            out.append(f"   • {c['fa']}" + (f" — {c['hint']}" if c["hint"] else ""))
        out.append("")
    if warn:
        out.append("⚠️ هشدار (اجرا را نمی‌بندد):" if fa else "⚠️ warnings:")
        for c in warn:
            out.append(f"   • {c['fa']}" + (f" — {c['hint']}" if c["hint"] else ""))
        out.append("")
    if not bad:
        out.append("✅ هیچ مانعی پیدا نشد. داشبورد باید بالا بیاید:"
                   if fa else "✅ no blockers. the desk should start:")
        out.append("   bash run-auto.sh --dash")
    return "\n".join(out) + "\n"


def doctor_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="mtflab doctor",
                                description="معاینهٔ سریع نصب (بدون شبکه)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--state", default="results/live/state.json")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--brain-model", default="results/brain_model.json")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    p.add_argument("--json", action="store_true", help="خروجی JSON (برای اشتراک‌گذاری)")
    a = p.parse_args(argv)
    rep = run_checks(a.data_dir, a.tf, a.port, a.state, a.journal, a.brain_model)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render(rep, a.lang), end="")
    return 0 if rep["ok"] else 1
