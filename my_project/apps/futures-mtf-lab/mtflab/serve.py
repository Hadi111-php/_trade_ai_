"""سرور سبک داشبورد (فقط کتابخانهٔ استاندارد — بدون Flask).

کاربرد:
    python3 -m mtflab serve --dir results --port 8080

- به `0.0.0.0` گوش می‌دهد تا در پیش‌نمایش/شبکهٔ محلی هم دیده شود.
- صفحهٔ اصلی، فهرست داشبوردها و گزارش‌های HTML/JSON/MD را نشان می‌دهد.
- فقط فایل‌های داخل پوشهٔ مجاز سرو می‌شوند (جلوگیری از path traversal).
- هیچ endpoint اجرای backtest ندارد؛ فقط نمایش (read-only) تا سرویس زنده
  هرگز در معرض اجرای کد از بیرون نباشد.
"""
from __future__ import annotations

import html
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Tuple


def _list_files(root: str) -> List[Tuple[str, int, float]]:
    out = []
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        p = os.path.join(root, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in (".html", ".json", ".md", ".csv", ".jsonl"):
            st = os.stat(p)
            out.append((name, st.st_size, st.st_mtime))
    out.sort(key=lambda x: -x[2])
    return out


INDEX_TMPL = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Futures MTF Lab — داشبوردها</title>
<style>
body{{margin:0;background:#0d1017;color:#e6edf3;font-family:Vazirmatn,-apple-system,Tahoma,sans-serif;padding:22px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8b98a9;font-size:12px;margin-bottom:18px}}
a{{color:#3ddc97;text-decoration:none}} a:hover{{text-decoration:underline}}
table{{border-collapse:collapse;width:100%;max-width:980px;background:#151a24;border:1px solid #26303f;border-radius:10px;overflow:hidden}}
th,td{{padding:9px 12px;border-bottom:1px solid #26303f;text-align:right;font-size:13px}}
th{{color:#8b98a9;background:#1b2230}} .dim{{color:#8b98a9;font-size:12px}}
.badge{{padding:2px 8px;border-radius:999px;font-size:11px;border:1px solid #26303f;color:#8b98a9}}
</style></head><body>
<h1>📊 Futures MTF Lab — داشبوردها</h1>
<div class="sub">پوشه: <span class="dim">{root}</span> · {count} فایل · PAPER فقط</div>
<table><thead><tr><th>فایل</th><th>نوع</th><th>حجم</th></tr></thead><tbody>{rows}</tbody></table>
<div class="sub" style="margin-top:16px">
  <a href="/">↩ بازگشت به داشبورد</a> &nbsp;·&nbsp;
  برای ساخت داشبورد مقایسه:
  <span class="dim">python3 -m mtflab compare --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv</span>
</div>
</body></html>"""


def make_handler(root: str):
    root_abs = os.path.abspath(root)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MTFLabDash/1.0"

        def log_message(self, fmt, *args):        # لاگ کوتاه، بدون نویز
            if os.environ.get("MTFLAB_SERVE_VERBOSE"):
                super().log_message(fmt, *args)

        def _safe_path(self, rel: str) -> str:
            rel = urllib.parse.unquote(rel).lstrip("/")
            p = os.path.abspath(os.path.join(root_abs, rel))
            if not p.startswith(root_abs + os.sep) and p != root_abs:
                raise PermissionError(p)
            return p

        def do_GET(self):                          # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    # صفحهٔ اصلی = داشبورد مقایسه (اگر ساخته شده باشد)
                    dash = os.path.join(root_abs, "dash_scenarios.html")
                    if os.path.isfile(dash):
                        self.send_response(302)
                        self.send_header("Location", "/dash_scenarios.html")
                        self.end_headers()
                        return
                    self._serve_index()
                    return
                if path in ("/files", "/files.html"):
                    self._serve_index()
                    return
                if path == "/healthz":
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                p = self._safe_path(path)
                if not os.path.isfile(p):
                    # اگر داشبورد مقایسه وجود دارد، به آن هدایت کن
                    dash = os.path.join(root_abs, "dash_scenarios.html")
                    if os.path.isfile(dash):
                        self.send_response(302)
                        self.send_header("Location", "/dash_scenarios.html")
                        self.end_headers()
                        return
                    self.send_error(404, "فایل پیدا نشد")
                    return
                self._serve_file(p)
            except PermissionError:
                self.send_error(403, "دسترسی مجاز نیست")
            except Exception as e:                 # noqa: BLE001
                self.send_error(500, f"خطای سرور: {e}")

        def _serve_file(self, p: str):
            ext = os.path.splitext(p)[1].lower()
            ctype = {".html": "text/html; charset=utf-8",
                     ".json": "application/json; charset=utf-8",
                     ".md": "text/plain; charset=utf-8",
                     ".csv": "text/csv; charset=utf-8",
                     ".jsonl": "application/x-ndjson; charset=utf-8"}.get(
                ext, "application/octet-stream")
            with open(p, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_index(self):
            files = _list_files(root_abs)
            rows = "".join(
                f'<tr><td><a href="/{urllib.parse.quote(n)}">{html.escape(n)}</a></td>'
                f'<td><span class="badge">{os.path.splitext(n)[1].lstrip(".")}</span></td>'
                f'<td class="dim">{_human(sz)}</td></tr>'
                for n, sz, _ in files)
            body = INDEX_TMPL.format(root=html.escape(root_abs), count=len(files),
                                     rows=rows or '<tr><td colspan="3" class="dim">فایلی نیست</td></tr>')
            b = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    return Handler


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def serve(root: str = "results", host: str = "0.0.0.0", port: int = 8080) -> None:
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    print(f"🌐 داشبورد در حال اجراست: http://{host}:{port}/  →  {root}")
    print("   (Ctrl-C برای توقف)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹ متوقف شد.")
    finally:
        httpd.server_close()
