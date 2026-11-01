"""تست‌های بالا آمدن داشبورد و عیب‌یابی.

این‌ها از یک درد واقعی آمده‌اند: روی گوشی `bash run-auto.sh --dash` اجرا شد و
«داشبورد بالا نیامد». سه علت قابل بازتولید وجود دارد و هر سه این‌جا قفل می‌شوند:

  ۱. پورت ۸۷۷۰ را یک اجرای قدیمی گرفته بود → سرور با traceback می‌مرد.
  ۲. سرور فقط **بعد از** گرفتن کندل ۲۰ نماد بالا می‌آمد (چند دقیقه سکوت).
  ۳. خروجی بافر می‌شد و نشانی هیچ‌وقت چاپ نمی‌شد.
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.doctor import port_free, run_checks                        # noqa: E402
from mtflab.labweb import bind_server                                 # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Lab:
    """داشبورد واقعی لازم نیست؛ فقط چیزی که `make_handler` صدا می‌زند."""

    def __init__(self):
        self.demo = True
        self.report_dir = "results"
        self.lab_dir = tempfile.mkdtemp()
        self.journal_path = os.path.join(self.lab_dir, "j.jsonl")
        self.state_path = os.path.join(self.lab_dir, "s.json")

    def overview(self):
        return {"version": "test", "demo": True, "symbols_cached": [], "bars": {}}


def _busy_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s


# ═══════════════════════════════════════════════════════════════════════════
# ۱) پورت اشغال → پورت بعدی، نه مرگ
# ═══════════════════════════════════════════════════════════════════════════
def test_bind_server_moves_to_next_port_when_busy():
    s = _busy_socket()
    busy = s.getsockname()[1]
    try:
        srv = bind_server(_Lab(), "127.0.0.1", busy, tries=3)
        try:
            got = srv.server_address[1]
            assert got != busy, "باید پورت دیگری بردارد"
            assert got > busy, "پورت بعدی، نه تصادفی"
        finally:
            srv.server_close()
    finally:
        s.close()


def test_bind_server_uses_requested_port_when_free():
    s = _busy_socket()
    port = s.getsockname()[1]
    s.close()                       # آزادش می‌کنیم
    srv = bind_server(_Lab(), "127.0.0.1", port, tries=3)
    try:
        assert srv.server_address[1] == port
    finally:
        srv.server_close()


# ═══════════════════════════════════════════════════════════════════════════
# ۲) doctor — همان چیزی که کاربر روی گوشی می‌زند
# ═══════════════════════════════════════════════════════════════════════════
def test_doctor_flags_busy_port_as_blocking():
    s = _busy_socket()
    busy = s.getsockname()[1]
    try:
        rep = run_checks(port=busy)
        assert rep["ok"] is False
        assert "port" in rep["blocking"]
        row = [c for c in rep["checks"] if c["id"] == "port"][0]
        assert "--port" in row["hint"] or "pkill" in row["hint"]
    finally:
        s.close()


def test_doctor_does_not_treat_missing_data_as_blocking():
    """کش خالی یعنی داشبورد «خالی» است، نه اینکه بالا نیاید."""
    with tempfile.TemporaryDirectory() as td:
        rep = run_checks(data_dir=os.path.join(td, "nope"),
                         state=os.path.join(td, "s.json"),
                         journal=os.path.join(td, "j.jsonl"),
                         brain_model=os.path.join(td, "b.json"),
                         port=0)
        assert "data" in rep["warnings"], rep
        assert "data" not in rep["blocking"]
        row = [c for c in rep["checks"] if c["id"] == "data"][0]
        assert "خالی" in row["detail"]


def test_doctor_render_lists_every_check():
    from mtflab.doctor import render
    rep = run_checks(port=0)
    md = render(rep, "fa")
    for c in rep["checks"]:
        assert c["fa"] in md
    assert "معاینهٔ نصب" in md


def test_port_free_true_for_os_assigned_port():
    assert port_free(0) is True


# ═══════════════════════════════════════════════════════════════════════════
# ۳) داشبورد واقعاً و سریع بالا می‌آید (بدون شبکه)
# ═══════════════════════════════════════════════════════════════════════════
def _spawn_dash(extra=()):
    cmd = [sys.executable, "-u", "-m", "mtflab", "live", "--serve",
           "--demo", "--no-step", "--no-open", "--port", "0", *extra]
    return subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)


def test_dash_prints_url_within_seconds_and_serves_page():
    p = _spawn_dash()
    try:
        t0 = time.time()
        url, lines = None, []
        while time.time() - t0 < 25:
            line = p.stdout.readline()
            if not line:
                break
            lines.append(line)
            m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
            if m:
                url = f"http://127.0.0.1:{m.group(1)}/"
                break
        assert url, "نشانی چاپ نشد:\n" + "".join(lines)
        assert time.time() - t0 < 15, "باید در چند ثانیه بالا بیاید، نه چند دقیقه"
        with urllib.request.urlopen(url, timeout=10) as r:
            html = r.read().decode("utf-8")
        assert r.status == 200
        assert "کارگاه اتوترید مجازی" in html
        assert "brainViews" in html          # بلوک «چشم مغز» هم بالاست
    finally:
        p.terminate()
        try:
            out = p.communicate(timeout=10)[0] or ""
        except subprocess.TimeoutExpired:
            p.kill()
            out = ""
        assert "Traceback" not in out, out


def test_dash_survives_busy_port():
    """همان سناریوی گوشی: ۸۷۷۰ گرفته است، ولی داشبورد باید بالا بیاید."""
    s = _busy_socket()
    busy = s.getsockname()[1]
    try:
        p = _spawn_dash(("--port", str(busy)))
        try:
            t0 = time.time()
            url, lines = None, []
            while time.time() - t0 < 25:
                line = p.stdout.readline()
                if not line:
                    break
                lines.append(line)
                m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
                if m:
                    url = f"http://127.0.0.1:{m.group(1)}/"
                    break
            assert url, "".join(lines)
            assert str(busy) not in url, "باید پورت دیگری بردارد"
            assert "اشغال بود" in "".join(lines)
            with urllib.request.urlopen(url, timeout=10) as r:
                assert r.status == 200
        finally:
            p.terminate()
            try:
                p.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    finally:
        s.close()
