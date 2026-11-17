"""گزارش کنترل — یک دستور، یک فایل، برای «بفرست ببینم سیستم سالم است یا نه».

**چرا:** کاربر از گوشی/کامپیوتر اجرا می‌کند و می‌خواهد نتیجه را برای بازبینی
بفرستد. تا حالا باید چند خروجی مختلف را کپی می‌کرد (سلامت، وضعیت داده، ژورنال).
این ماژول همان عددهای موجود را **جمع** می‌کند و در یک فایل مارک‌داون +
یک فایل JSON می‌نویسد، همراه با هش sha256 تا معلوم باشد دستکاری نشده است.

**چه چیزی تازه محاسبه می‌کند؟** هیچ فرمول تازه‌ای ندارد:
- اعداد سلامت/کندل/گرم‌شدن از `health.system_health`
- فهرست کش و گزارش‌ها از `ops.status`
- خلاصهٔ کد از git و محیط از `sys`/`platform`
فقط این‌ها را به یک چک‌لیست قابل‌داوری تبدیل می‌کند (✅/⚠️/❌ + راه‌حل).

**چه چیزی نمی‌کند:** در ژورنال، `state.json`، سرمایه یا آمار اعتبارسنجی
**هیچ** نوشتنی ندارد؛ فقط `results/control/` را می‌سازد. هیچ چیز هم جعل نمی‌کند:
اگر داده نبود، «داده نیست» می‌نویسد، نه صفرِ بی‌معنا.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from typing import Dict, List, Optional, Sequence

VERSION = "1"

#: همهٔ خروجی‌ها این‌جا می‌روند (مستقل از ژورنال).
CONTROL_DIR = os.path.join("results", "control")


# ── کمکی‌ها ────────────────────────────────────────────────────────────────
def _utc(ms: Optional[int] = None) -> str:
    sec = (ms if ms is not None else int(time.time() * 1000)) / 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sec))


def _stamp(ms: Optional[int] = None) -> str:
    """مُهر زمانی امن برای نام فایل: `20261117T080000Z`."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(
        (ms if ms is not None else int(time.time() * 1000)) / 1000.0))


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(root: str = ".") -> str:
    """کوتاه‌شدهٔ HEAD؛ اگر git نبود یا مخزن نبود، رشتهٔ خالی (بدون خطا)."""
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _mark(ok) -> str:
    """True → ✅، False → ❌، None → ⚠️ (هشدار، اجرا را نمی‌بندد)."""
    return "✅" if ok is True else ("❌" if ok is False else "⚠️")


# ── چک‌لیست ────────────────────────────────────────────────────────────────
def checks(health: dict, data: dict) -> List[dict]:
    """چک‌لیست قابل‌داوری. `ok=None` یعنی هشدار (مثلاً ژورنالِ خالی در روز اول)."""
    rows = health.get("rows") or []
    clock = health.get("clock") or {}
    warm = health.get("warmup") or {}
    jr = health.get("journal") or {}
    hb = health.get("heartbeat") or {}
    verdict = health.get("verdict") or {}
    out: List[dict] = []

    # ۱) اصلاً داده‌ای هست؟
    files = int(data.get("files") or 0)
    out.append({
        "name": "داده در کش",
        "ok": files > 0 if files or rows else False,
        "detail": (f"{files} فایل · تایم‌فریم‌ها: "
                   + (", ".join(f"{k}×{v}" for k, v in sorted((data.get("by_tf") or {}).items())) or "—")),
        "fix": "bash run-auto.sh --ops --download --days 365",
    })

    # ۲) تازگی: هیچ نمادی عقب نباشد
    behind = [r.get("behind_bars", 0) for r in rows]
    worst_behind = max(behind) if behind else None
    out.append({
        "name": "تازگی داده",
        "ok": (all(r.get("fresh") for r in rows) if rows else False),
        "detail": (f"بیشترین عقب‌ماندگی: {worst_behind} کندل" if rows else "نمادی خوانده نشد"),
        "fix": "bash run-auto.sh --ops --sync",
    })

    # ۳) گرم‌شدن لایه‌ها
    wrows = warm.get("rows") or []
    out.append({
        "name": "گرم‌شدن لایه‌ها",
        "ok": bool(warm.get("ok")) if rows else None,
        "detail": ("، ".join(f"{w.get('layer')} {w.get('have')}/{w.get('need')}" for w in wrows[:4])
                   or "بدون دادهٔ کافی برای سنجش"),
        "fix": "نماد/تاریخ بیشتری بگیر: bash run-auto.sh --days 730",
    })

    # ۴) موتور تا آخرین کندلِ بسته پردازش کرده؟
    last_closed = clock.get("last_closed_open_ms")
    lp = (hb.get("last_processed") or {})
    if lp and last_closed:
        todo = [s for s, ms in lp.items() if ms is not None and ms < last_closed]
        out.append({
            "name": "پردازش تا آخرین کندل",
            "ok": not todo,
            "detail": (f"{len(lp) - len(todo)}/{len(lp)} نماد هم‌گام"
                       + (f" · عقب: {', '.join(todo)}" if todo else "")),
            "fix": "bash run-auto.sh --live --backfill 400",
        })
    else:
        out.append({"name": "پردازش تا آخرین کندل", "ok": None,
                    "detail": "state.json هنوز ساخته نشده",
                    "fix": "bash run-auto.sh --live --backfill 400"})

    # ۵) ژورنال
    opens, closes = int(jr.get("opens") or 0), int(jr.get("closes") or 0)
    out.append({
        "name": "ژورنال",
        "ok": True if closes > 0 else (None if opens else None),
        "detail": f"{opens} باز · {closes} بسته · {jr.get('records', 0)} رکورد",
        "fix": "با سیگنال تازه خودش پر می‌شود؛ برای بک‌فیل: --live --backfill 400",
    })

    # ۶) حساب مجازی
    eq = hb.get("equity")
    out.append({
        "name": "حساب مجازی",
        "ok": (isinstance(eq, (int, float)) and eq > 0) if eq is not None else None,
        "detail": (f"equity = {eq:.2f}" if isinstance(eq, (int, float)) else "ساخته نشده"),
        "fix": "bash run-auto.sh --live",
    })

    # ۷) حکم نهایی
    code = verdict.get("code") or "?"
    out.append({
        "name": "حکم",
        "ok": code not in ("no_data", "stale", "error"),
        "detail": f"{code} — {verdict.get('label') or ''}",
        "fix": ("bash run-auto.sh --ops --sync" if code == "stale"
                else "bash run-auto.sh --ops --download --days 365" if code == "no_data" else ""),
    })
    return out


# ── جمع‌آوری ────────────────────────────────────────────────────────────────
def collect(universe: Dict[str, Sequence], cfg, *, data_dir: str = "data",
            state_path: str = "results/live/state.json",
            journal_path: str = "results/live/journal.jsonl",
            out_dir: str = CONTROL_DIR, now_ms: Optional[int] = None,
            write: bool = True, root: str = ".") -> dict:
    """ساخت گزارش کنترل. `write=False` فقط برمی‌گرداند (برای تست/داشبورد)."""
    from .health import system_health
    from .ops import status as ops_status

    h = system_health(universe or {}, cfg, state_path=state_path,
                      journal_path=journal_path, now_ms=now_ms)
    st = ops_status(data_dir)
    data = st.get("data") or {}
    rep = {
        "version": VERSION,
        "created_utc": _utc(now_ms),
        "commit": _git_commit(root),
        "env": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "termux": bool(os.environ.get("TERMUX_VERSION")),
            "cwd": os.getcwd(),
            "data_dir": data_dir,
        },
        "health": h,
        "data": data,
        "jobs": [{k: j.get(k) for k in ("id", "kind", "status", "started_utc")}
                 for j in (st.get("jobs") or [])[:10]],
        "reports": (st.get("reports") or [])[:10],
        "checks": checks(h, data),
        "note": ("این فایل هیچ چیزی را در ژورنال/سرمایه تغییر نداده است؛ "
                 "فقط خوانده و جمع کرده. اعداد از health/ops آمده‌اند."),
    }
    rep["ok"] = all(c["ok"] is not False for c in rep["checks"])
    if write:
        paths = write_files(rep, out_dir=out_dir)
        rep["paths"] = paths
    return rep


def write_files(rep: dict, out_dir: str = CONTROL_DIR) -> dict:
    """نوشتن `.md` و `.json` با مُهر زمانی + هش. مسیرها را برمی‌گرداند."""
    os.makedirs(out_dir, exist_ok=True)
    stem = f"control_{_stamp(int(rep['health']['clock']['now_ms']))}"
    mdp = os.path.join(out_dir, stem + ".md")
    jsp = os.path.join(out_dir, stem + ".json")
    with open(mdp, "w", encoding="utf-8") as f:
        f.write(render_md(rep))
    payload = dict(rep)
    payload.pop("paths", None)
    with open(jsp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"md": mdp, "json": jsp, "stem": stem,
            "sha256": {"md": sha256_of(mdp), "json": sha256_of(jsp)}}


# ── نمایش ──────────────────────────────────────────────────────────────────
def render_md(rep: dict) -> str:
    h = rep["health"]
    c = h.get("clock") or {}
    v = h.get("verdict") or {}
    jr = h.get("journal") or {}
    L: List[str] = []
    L.append(f"# گزارش کنترل — {rep['created_utc']}")
    L.append("")
    L.append(f"**حکم:** {v.get('label') or '—'} (`{v.get('code')}`)  ")
    L.append(f"**کد:** `{rep.get('commit') or '?'}` · پایتون {rep['env']['python']} · "
             f"{'Termux' if rep['env']['termux'] else 'PC/لینوکس'}")
    L.append("")
    L.append("## ۱) چک‌لیست")
    L.append("")
    L.append("| بررسی | نتیجه | جزئیات | اگر خراب بود |")
    L.append("|---|---|---|---|")
    for ck in rep["checks"]:
        L.append(f"| {ck['name']} | {_mark(ck['ok'])} | {ck['detail']} | {ck['fix'] or '—'} |")
    L.append("")
    L.append("## ۲) ساعت و کندل")
    L.append("")
    L.append(f"- تایم‌فریم تریگر: **{h.get('tf', {}).get('trigger')}** "
             f"(گام {c.get('step_minutes')} دقیقه)")
    L.append(f"- آخرین کندل بسته: `{c.get('last_closed_utc')}`")
    L.append(f"- بستهٔ بعدی: `{c.get('next_close_utc')}` — "
             f"{int(c.get('seconds_to_next') or 0)} ثانیهٔ دیگر")
    L.append("")
    L.append("## ۳) نمادها")
    L.append("")
    L.append("| نماد | کندل | آخرین کندل | عقب | تازه | گرم | دروازه‌های بسته |")
    L.append("|---|---|---|---|---|---|---|")
    for r in h.get("rows") or []:
        blocked = [g.get("label") or g.get("id") for g in (r.get("gates") or [])
                   if not g.get("ok")]
        L.append(f"| {r.get('symbol')} | {r.get('bars')} | {r.get('last_candle_utc')} | "
                 f"{r.get('behind_bars')} | {'✅' if r.get('fresh') else '❌'} | "
                 f"{'✅' if r.get('warmup_ok') else '❌'} | "
                 f"{'، '.join(str(b) for b in blocked) or '—'} |")
    if not (h.get("rows") or []):
        L.append("| — | — | — | — | — | — | — |")
    L.append("")
    wrows = (h.get("warmup") or {}).get("rows") or []
    L.append("## ۴) گرم‌شدن لایه‌ها")
    L.append("")
    if wrows:
        L.append("| لایه | دارم | لازم | آماده |")
        L.append("|---|---|---|---|")
        for w in wrows:
            L.append(f"| {w.get('layer')} | {w.get('have')} | {w.get('need')} | "
                     f"{'✅' if w.get('ready') else '❌'} |")
    else:
        L.append("_دادهٔ کافی برای سنجش لایه‌ها نیست._")
    L.append("")
    d = rep.get("data") or {}
    L.append("## ۵) داده و ژورنال")
    L.append("")
    L.append(f"- فایل کش: **{d.get('files', 0)}** · حجم: "
             f"{round((d.get('bytes') or 0) / 1048576, 2)} مگابایت")
    L.append(f"- بازه: `{d.get('oldest') or '—'}` تا `{d.get('newest') or '—'}`")
    L.append(f"- ژورنال: {jr.get('opens', 0)} باز · {jr.get('closes', 0)} بسته · "
             f"{jr.get('records', 0)} رکورد")
    eq = h.get("heartbeat", {}).get("equity")
    L.append(f"- سرمایهٔ مجازی: {round(eq, 2) if isinstance(eq, (int, float)) else '—'}")
    L.append("")
    L.append("## ۶) آخرین کارهای پس‌زمینه")
    L.append("")
    if rep.get("jobs"):
        L.append("| شناسه | نوع | وضعیت |")
        L.append("|---|---|---|")
        for j in rep["jobs"]:
            L.append(f"| `{j.get('id')}` | {j.get('kind')} | {j.get('status')} |")
    else:
        L.append("_کاری ثبت نشده (یا هنوز از داشبورد اجرا نشده)._")
    L.append("")
    L.append("## ۷) این فایل را همین‌طور بفرست")
    L.append("")
    L.append("کل همین متن (یا فایل `.md`) کافی است؛ اعداد از `health` و `ops` "
             "آمده‌اند و هش در فایل `.json` هست.")
    L.append("")
    L.append(f"وضعیت کلی: **{'سالم' if rep.get('ok') else 'نیاز به رسیدگی'}**")
    L.append("")
    L.append("_این گزارش هیچ چیزی را در ژورنال، سرمایه یا آمار اعتبارسنجی تغییر نداده است._")
    L.append("")
    return "\n".join(L)


def summary_line(rep: dict) -> str:
    """یک خط برای ترمینال/داشبورد."""
    v = (rep.get("health") or {}).get("verdict") or {}
    bad = [c["name"] for c in rep.get("checks") or [] if c["ok"] is False]
    return (f"{_mark(rep.get('ok'))} {v.get('label') or '—'}"
            + (f" · ایراد: {', '.join(bad)}" if bad else " · هیچ ایرادی پیدا نشد"))


# ── CLI ────────────────────────────────────────────────────────────────────
def control_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from dataclasses import replace

    from .config import load_config
    from .desk import load_universe

    p = argparse.ArgumentParser(prog="mtflab control",
                                description="گزارش کنترل: یک فایل برای بازبینی")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--symbols", default="")
    p.add_argument("--state", default="results/live/state.json")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--out", default=CONTROL_DIR)
    p.add_argument("--json", action="store_true", help="چاپ JSON به‌جای خلاصه")
    p.add_argument("--lang", choices=["fa", "en"], default="fa",
                   help="پذیرفته می‌شود تا run-auto --lang رد نشود؛ خروجی فارسی می‌ماند")
    p.add_argument("--stdout", action="store_true", help="فایل ننویس، فقط چاپ کن")
    a = p.parse_args(argv)

    cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=a.tf, tf_filter=a.tf_filter, tf_bias=a.tf_bias,
                  verbose=False, forensics=False, run_id="", symbol="")
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or None
    uni = load_universe(a.data_dir, a.tf, syms)
    rep = collect(uni, cfg, data_dir=a.data_dir, state_path=a.state,
                  journal_path=a.journal, out_dir=a.out, write=not a.stdout)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    elif a.stdout:
        print(render_md(rep))
    else:
        print(render_md(rep))
        p_ = rep["paths"]
        print(f"📄 {p_['md']}")
        print(f"🧾 {p_['json']}")
        print(f"🔐 sha256(md) = {p_['sha256']['md']}")
    return 0 if rep.get("ok") else 1
