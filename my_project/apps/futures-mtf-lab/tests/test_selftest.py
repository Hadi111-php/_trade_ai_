"""تست‌های خودآزمایی (selftest): شناسنامهٔ نسخه + حالت سریع + به‌روزرسانی.

چرا این تست‌ها: روی گوشی، کاربر فقط یک اسکرین‌شات می‌فرستد. اگر خروجی
«کدام نسخه» را نگوید، ممکن است نسخهٔ قدیمی را ارزیابی کنیم و نفهمیم.
همچنین خودآزماییِ ساکت (بی‌خروجی برای چند دقیقه) شبیه «ماندن» است.
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import selftest                                      # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_env_line_has_version_commit_and_python():
    line = selftest.env_line()
    assert "نسخه:" in line
    assert "کد:" in line
    assert "پایتون" in line
    assert ("Termux" in line) or ("PC" in line)
    # نسخه باید عددی/تاریخی باشد، نه خالی
    assert any(ch.isdigit() for ch in line.split("نسخه:")[1].split("·")[0])


def test_quick_mode_skips_unit_tests_but_runs_four_checks():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = selftest.run_selftest(quick=True)
    out = buf.getvalue()
    assert rc == 0, out
    assert "حالت سریع" in out
    assert "4/4" in out
    for name in ("علی‌بودن موتور", "حسابرسی نشتی", "فیلتر هزینه", "سخت‌گیری"):
        assert name in out, name
    # هشدار «چند دقیقه» فقط در حالت کامل است
    assert "چند دقیقه طول می‌کشد" not in out


def test_unit_runner_streams_progress_instead_of_going_silent():
    """کد باید خروجی فرزند را جریانی بخواند و هر چند ثانیه پیشرفت چاپ کند."""
    src = open(os.path.join(ROOT, "mtflab", "selftest.py"), encoding="utf-8").read()
    assert "subprocess.Popen" in src            # نه run(capture_output=True)
    assert "خط خروجی" in src                     # نشانگر پیشرفت
    assert '"-u"' in src                         # بدون بافر
    assert "flush=True" in src


def test_main_passes_quick_flag():
    src = open(os.path.join(ROOT, "mtflab", "__main__.py"), encoding="utf-8").read()
    assert "run_selftest(quick=" in src
    assert "--quick" in src


def test_run_auto_update_exists_with_dirty_guard():
    sh = open(os.path.join(ROOT, "run-auto.sh"), encoding="utf-8").read()
    assert "--update|--upgrade)" in sh
    assert "reset --hard FETCH_HEAD" in sh
    # محافظ: با تغییر ذخیره‌نشده، بدون --force نباید اجرا شود
    assert "status --porcelain" in sh
    assert "--force" in sh
    assert "exit 3" in sh
