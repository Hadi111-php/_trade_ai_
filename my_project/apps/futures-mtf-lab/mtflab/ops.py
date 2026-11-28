"""مرکز عملیات («مدیریت کلان»): دانلود دادهٔ واقعی، آزمون‌های مستقل، معاینهٔ نصب.

**چرا این ماژول:** تا امروز هر کار سنگین یک دستور جدا داشت (دانلود، آزمایش خروج،
معاینه) و کاربر باید ترمینال باز می‌کرد. این‌جا همان کارها به **کارهای پس‌زمینه**
تبدیل می‌شوند تا از داخل داشبورد اجرا شوند، بدون این‌که صفحه قفل شود.

سه قاعدهٔ طراحی:

  ۱) **هیچ‌وقت صفحه را قفل نکن.** سرور داشبورد تک‌رشته‌ای است؛ دانلود یک‌ساله
     اگر همگام اجرا شود، مرورگر تا دقیقه‌ها «در حال انتظار» می‌ماند. پس هر کار
     در یک `threading.Thread` می‌رود و UI فقط وضعیت را می‌پرسد.
  ۲) **گزارش مستقل.** هر اجرا فایل خودش را در `results/ops/` می‌نویسد. هیچ‌چیز
     در ژورنال معاملات، سرمایه، اعتبارسنجی یا کارنامهٔ الگوها نوشته نمی‌شود؛
     پس یک آزمون هرگز آمار سیستم را آلوده نمی‌کند.
  ۳) **دادهٔ واقعی، بدون ادعا.** اگر شبکه نبود، کار با خطای صریح تمام می‌شود و
     کش قبلی دست‌نخورده می‌ماند. هیچ داده‌ای جعل نمی‌شود.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from typing import Callable, Dict, List, Optional, Sequence

VERSION = 1
OPS_DIR = os.path.join("results", "ops")
MAX_LOG_LINES = 120
KEEP_JOBS = 40

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
DEFAULT_TFS = ["1h", "4h", "1d"]

_LOCK = threading.RLock()
_JOBS: Dict[str, dict] = {}            # id → job (زنده یا تمام‌شده)
_ORDER: List[str] = []                 # ترتیب شروع، تازه‌ها آخر


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ══════════════════════════════════════════════════════════════════════════
#  ۱) اجراکنندهٔ کارهای پس‌زمینه
# ══════════════════════════════════════════════════════════════════════════
def _log_of(job: dict, line: str) -> None:
    with _LOCK:
        job["log"].append(str(line)[:400])
        if len(job["log"]) > MAX_LOG_LINES:
            del job["log"][: len(job["log"]) - MAX_LOG_LINES]
        job["updated_utc"] = _now()


def _persist(job: dict) -> None:
    """ثبت مستقل هر کار در results/ops/<id>.json (برای بعد از ری‌استارت)."""
    try:
        os.makedirs(OPS_DIR, exist_ok=True)
        path = os.path.join(OPS_DIR, f"{job['id']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=1)
    except OSError:
        pass                     # ثبت گزارش هرگز نباید خود کار را بشکند


def start(kind: str, title: str, fn: Callable[[Callable[[str], None]], dict],
          params: Optional[dict] = None) -> dict:
    """یک کار پس‌زمینه شروع کن. `fn(log)` باید dict خلاصه برگرداند."""
    with _LOCK:
        if any(j["status"] == "running" and j["kind"] == kind for j in _JOBS.values()):
            raise RuntimeError("یک کار از همین نوع در حال اجراست")
        jid = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
        job = {"id": jid, "kind": kind, "title": title, "status": "running",
               "started_utc": _now(), "finished_utc": None, "duration_s": None,
               "params": params or {}, "log": [], "summary": {}, "error": "",
               "report": "", "version": VERSION, "persisted": False}
        _JOBS[jid] = job
        _ORDER.append(jid)
        while len(_ORDER) > KEEP_JOBS:
            old = _ORDER.pop(0)
            _JOBS.pop(old, None)

    def _run() -> None:
        t0 = time.time()
        log = lambda m: _log_of(job, m)                     # noqa: E731
        try:
            summary = fn(log) or {}
            with _LOCK:
                job.update({"status": "done", "summary": summary,
                            "finished_utc": _now(),
                            "duration_s": round(time.time() - t0, 1)})
        except Exception as e:                              # noqa: BLE001
            with _LOCK:
                job.update({"status": "error", "error": f"{type(e).__name__}: {e}",
                            "finished_utc": _now(),
                            "duration_s": round(time.time() - t0, 1)})
            _log_of(job, f"❌ {type(e).__name__}: {e}")
            _log_of(job, traceback.format_exc().strip().splitlines()[-1])
        _persist(job)
        with _LOCK:
            job["persisted"] = True      # حالا وضعیت و فایل هم‌خوان‌اند

    threading.Thread(target=_run, daemon=True, name=f"ops-{jid}").start()
    return dict(job)


def _load_persisted() -> List[dict]:
    out: List[dict] = []
    if not os.path.isdir(OPS_DIR):
        return out
    for name in sorted(os.listdir(OPS_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(OPS_DIR, name), encoding="utf-8") as f:
                rec = json.load(f)
            if isinstance(rec, dict) and rec.get("id"):
                out.append(rec)
        except (OSError, ValueError):
            continue
    return out


def jobs() -> List[dict]:
    """کارهای این نشست + کارهای ذخیره‌شدهٔ نشست‌های قبل (تازه‌تر اول)."""
    with _LOCK:
        live = [dict(j) for j in _JOBS.values()]
    seen = {j["id"] for j in live}
    merged = live + [j for j in _load_persisted() if j["id"] not in seen]
    merged.sort(key=lambda j: j.get("started_utc") or "", reverse=True)
    return merged[:30]


def running() -> List[dict]:
    with _LOCK:
        return [dict(j) for j in _JOBS.values() if j["status"] == "running"]


# ══════════════════════════════════════════════════════════════════════════
#  ۲) داده: دانلود کامل و به‌روزرسانی تدریجی (ادغام، بدون پاک‌کردن تاریخ)
# ══════════════════════════════════════════════════════════════════════════
def merge_candles(old: Sequence, new: Sequence) -> list:
    """ادغام کندل‌های قدیم و تازه بر اساس زمان باز شدن (تکراری‌ها حذف).

    چرا لازم است: دانلود «آخرین ۳۰ روز» نباید تاریخ یک‌ساله را پاک کند. بدون
    ادغام، فایل کش با ۳۰ روز بازنویسی می‌شد و آزمایش خروج روی دادهٔ کوتاه
    اجرا می‌شد — همان دامی که در پروژه یک‌بار گرفته شد.
    """
    by_ts = {}
    for c in list(old) + list(new):
        by_ts[int(c.open_time_ms)] = c
    return [by_ts[k] for k in sorted(by_ts)]


def _cache_path(data_dir: str, symbol: str, tf: str) -> str:
    return os.path.join(data_dir, "json", f"{symbol.lower()}_{tf}.json")


def _read_cache(path: str):
    from .autoscan import candles_from_json
    if not os.path.exists(path):
        return [], {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return candles_from_json(payload), dict(payload.get("meta") or {})


def _write_cache(data_dir: str, symbol: str, tf: str, cs, meta_extra: dict) -> str:
    from .autoscan import candles_to_json
    path = _cache_path(data_dir, symbol, tf)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta = {"symbol": symbol, "tf": tf, "n": len(cs),
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "start": (time.strftime("%Y-%m-%d", time.gmtime(cs[0].open_time_ms / 1000))
                      if cs else None),
            "end": (time.strftime("%Y-%m-%d", time.gmtime(cs[-1].open_time_ms / 1000))
                    if cs else None)}
    meta.update(meta_extra or {})
    if cs:
        meta["days"] = max(1, int((cs[-1].open_time_ms - cs[0].open_time_ms) / 86_400_000))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(candles_to_json(cs, meta), f, ensure_ascii=False,
                  separators=(",", ":"))
    return path


def data_status(data_dir: str = "data") -> dict:
    """خلاصهٔ کش فعلی: چه نماد/تایم‌فریمی داریم و تا کجا می‌رسد."""
    jdir = os.path.join(data_dir, "json")
    if not os.path.isdir(jdir):
        return {"files": 0, "symbols": [], "by_tf": {}, "bytes": 0,
                "newest": None, "oldest": None}
    files = [n for n in os.listdir(jdir) if n.endswith(".json")]
    by_tf: Dict[str, int] = {}
    syms = set()
    newest = oldest = None
    total = 0
    for name in files:
        base = name[:-5]
        if "_" not in base:
            continue
        sym, tf = base.rsplit("_", 1)
        syms.add(sym.upper())
        by_tf[tf] = by_tf.get(tf, 0) + 1
        path = os.path.join(jdir, name)
        try:
            total += os.path.getsize(path)
            _, meta = _read_cache(path)
            for k in ("start",):
                v = meta.get(k)
                if v and (oldest is None or v < oldest):
                    oldest = v
            v = meta.get("end")
            if v and (newest is None or v > newest):
                newest = v
        except (OSError, ValueError):
            continue
    return {"files": len(files), "symbols": sorted(syms), "by_tf": by_tf,
            "bytes": total, "oldest": oldest, "newest": newest}


def job_download(symbols: Sequence[str], tfs: Sequence[str], days: int,
                 data_dir: str = "data", base_url: str = "") -> Callable:
    """کار «دانلود یک‌ساله»: دادهٔ واقعی Bybit → `data/json/*.json`."""
    def _fn(log: Callable[[str], None]) -> dict:
        from .autoscan import fetch_or_load, pick_base_url
        url = base_url or pick_base_url(progress=False)
        if not url:
            raise RuntimeError("هیچ آدرس سالمی برای Bybit پیدا نشد — اینترنت/فیلتر؟")
        log(f"آدرس: {url} · بازه: {days} روز · {len(symbols)} نماد × {len(tfs)} تایم‌فریم")
        saved, total_bars = [], 0
        for sym in symbols:
            for tf in tfs:
                log(f"⏳ {sym} {tf} …")
                cs, meta = fetch_or_load(sym, tf, days, data_dir, url,
                                         refresh=False, progress=False)
                bars = len(cs)
                total_bars += bars
                saved.append({"symbol": sym, "tf": tf, "bars": bars,
                              "start": meta.get("start"), "end": meta.get("end"),
                              "from_cache": bool(meta.get("from_cache"))})
                log(f"   ✅ {sym} {tf}: {bars} کندل · {meta.get('start')} → {meta.get('end')}")
        if not saved:
            raise RuntimeError("هیچ داده‌ای ذخیره نشد")
        return {"saved": saved, "total_bars": total_bars, "days": days,
                "data": data_status(data_dir)}
    return _fn


def job_sync(symbols: Sequence[str], tfs: Sequence[str], days: int = 30,
             data_dir: str = "data", base_url: str = "") -> Callable:
    """کار «به‌روزرسانی»: فقط کندل‌های تازه را بگیر و با کش **ادغام** کن."""
    def _fn(log: Callable[[str], None]) -> dict:
        from .autoscan import pick_base_url
        from .bybit_public import fetch_klines_range
        url = base_url or pick_base_url(progress=False)
        if not url:
            raise RuntimeError("هیچ آدرس سالمی برای Bybit پیدا نشد — اینترنت/فیلتر؟")
        log(f"آدرس: {url} · پنجرهٔ تازه: {days} روز")
        out = []
        for sym in symbols:
            for tf in tfs:
                old, meta_old = _read_cache(_cache_path(data_dir, sym, tf))
                log(f"⏳ {sym} {tf}: دریافت {days} روز اخیر …")
                new = fetch_klines_range(sym, tf, days=days, base_url=url,
                                         progress=False, rate_sleep=0.35,
                                         save_csv=False)
                if not new:
                    log(f"   ⚠️ {sym} {tf}: دادهٔ تازه‌ای نیامد — کش دست‌نخورده")
                    continue
                merged = merge_candles(old, new)
                added = len(merged) - len(old)
                path = _write_cache(data_dir, sym, tf, merged,
                                    {"source": "sync", "base_url": url,
                                     "fetch_days": days, "added": added})
                out.append({"symbol": sym, "tf": tf, "added": added,
                            "bars": len(merged), "path": path})
                log(f"   ✅ {sym} {tf}: +{added} کندل (جمع {len(merged)})")
                try:
                    from .store import build_entry, upsert
                    from .data import find_gaps
                    integration = find_gaps(merged, tf, max_report=5)
                    upsert(data_dir, build_entry(sym, tf, path,
                                                 {"source": "sync", "n": len(merged)},
                                                 merged, integration))
                except Exception as e:                     # noqa: BLE001
                    log(f"   ⚠️ ثبت در فهرست داده انجام نشد ({type(e).__name__})")
        if not out:
            raise RuntimeError("هیچ نمادی به‌روزرسانی نشد (شبکه یا نماد نامعتبر)")
        return {"updated": out, "days": days, "data": data_status(data_dir)}
    return _fn


def job_probe(base_url: str = "") -> Callable:
    """تست واقعی دسترسی به دادهٔ بازار (نه فقط پینگ)."""
    def _fn(log: Callable[[str], None]) -> dict:
        from .autoscan import BASE_URLS, diagnose_network, pick_base_url
        cands = [base_url] if base_url else list(BASE_URLS)
        rep = diagnose_network(cands, timeout=8)
        ok_url = pick_base_url(cands, progress=False)
        for r in rep:
            log(f"{'✅' if r['ok'] else '❌'} {r['kind']:5s} {r['base']} → {r['status']} · {r['note']}")
        if not ok_url:
            raise RuntimeError("دادهٔ بازار در دسترس نیست (فیلتر/قطعی). "
                               "کش فعلی دست‌نخورده است.")
        log(f"✅ آدرس سالم: {ok_url}")
        return {"ok": True, "base_url": ok_url, "checks": rep}
    return _fn


# ══════════════════════════════════════════════════════════════════════════
#  ۳) آزمون‌های مستقل
# ══════════════════════════════════════════════════════════════════════════
def job_exitstyles(tf: str = "auto", variant: str = "base",
                   data_dir: str = "data") -> Callable:
    """آزمایش «حد ضرر ثابت در برابر شناور» — گزارش مستقل، بدون اثر روی سیستم."""
    def _fn(log: Callable[[str], None]) -> dict:
        from dataclasses import replace

        from .config import load_config
        from .exitstyles import (_detect_tf, _load_cache, _next_tf, compare,
                                 render_text)
        from .patterns import variants_for

        t = tf if tf and tf != "auto" else (_detect_tf(data_dir) or "1h")
        tfil, tbia = _next_tf(t) or t, _next_tf(_next_tf(t) or t) or t
        uni = _load_cache(data_dir, t)
        if not uni:
            raise RuntimeError(f"داده‌ای برای تایم‌فریم {t} در {data_dir}/json نیست — "
                               "اول «به‌روزرسانی داده» را بزن.")
        log(f"تایم‌فریم {t}/{tfil}/{tbia} · {len(uni)} نماد")
        cfg = load_config(["--data", "synthetic", "--quiet"])
        cfg = replace(cfg, tf_trigger=t, tf_filter=tfil, tf_bias=tbia,
                      verbose=False, forensics=False, run_id="", symbol="")
        for vid, _label, ov in variants_for(t, tfil, tbia):
            if vid == variant:
                cfg = replace(cfg, **{k: v for k, v in (ov or {}).items()
                                      if k in cfg.__dataclass_fields__})
                break
        res = compare(uni, cfg, verbose=False)
        res["variant"] = variant
        txt = render_text(res)
        os.makedirs(OPS_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        md = os.path.join(OPS_DIR, f"exit_styles_{t}_{stamp}.md")
        js = os.path.join(OPS_DIR, f"exit_styles_{t}_{stamp}.json")
        with open(md, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        with open(js, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        top = res["rows"][0] if res["rows"] else {}
        log(f"✅ {len(res['rows'])} سیاست · {res['entries']} ورود مشترک")
        if top:
            log(f"   صدر جدول: {top['policy']['label']} · "
                f"expectancy {top['all'].get('expectancy_r')} R · "
                f"n={top['all'].get('n')}")
        return {"tf": t, "entries": res["entries"], "policies": len(res["rows"]),
                "top": ({"id": top.get("policy", {}).get("id"),
                         "label": top.get("policy", {}).get("label"),
                         "expectancy_r": (top.get("all") or {}).get("expectancy_r"),
                         "n": (top.get("all") or {}).get("n")}) if top else None,
                "report_md": md, "report_json": js,
                "symbols": res.get("symbols"), "range": res.get("range")}
    return _fn


def job_doctor() -> Callable:
    """معاینهٔ نصب: پورت، داده، پوشه‌ها (بدون شبکه)."""
    def _fn(log: Callable[[str], None]) -> dict:
        from .doctor import render, run_checks
        rep = run_checks()
        txt = render(rep, "fa")
        os.makedirs(OPS_DIR, exist_ok=True)
        path = os.path.join(OPS_DIR, f"doctor_{time.strftime('%Y%m%d-%H%M%S')}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        for line in txt.splitlines()[:MAX_LOG_LINES]:
            log(line)
        return {"ok": bool(rep.get("ok")), "checks": len(rep.get("checks") or []),
                "report_md": path}
    return _fn


# ══════════════════════════════════════════════════════════════════════════
#  ۴) وضعیت کلی برای تب «مدیریت کلان»
# ══════════════════════════════════════════════════════════════════════════
def status(data_dir: str = "data") -> dict:
    js = jobs()
    last_done = next((j for j in js if j["status"] == "done"), None)
    reports = []
    if os.path.isdir(OPS_DIR):
        for name in sorted(os.listdir(OPS_DIR), reverse=True):
            if not name.endswith((".md", ".json")) or name.startswith("probe"):
                continue
            # فایل `<job-id>.json` خودِ رکورد کار است، نه گزارش محتوا
            if any(name == f"{j['id']}.json" for j in js):
                continue
            path = os.path.join(OPS_DIR, name)
            reports.append({"name": name, "bytes": os.path.getsize(path),
                            "kind": ("md" if name.endswith(".md") else "json"),
                            "id": name.rsplit(".", 1)[0]})
    return {
        "version": VERSION,
        "created_utc": _now(),
        "data": data_status(data_dir),
        "jobs": js,
        "running": [j["id"] for j in running()],
        "reports": reports[:25],
        "ops_dir": OPS_DIR,
        "network": (last_done.get("summary", {}).get("base_url")
                    if last_done and last_done.get("kind") in ("probe", "sync", "download")
                    else None),
        "note": ("هر اجرا گزارش مستقل خودش را در results/ops می‌نویسد؛ "
                 "هیچ‌چیز در ژورنال معاملات، سرمایه یا آمار اعتبارسنجی نوشته نمی‌شود."),
    }


def read_report(rid: str) -> dict:
    """خواندن یک گزارش مستقل برای نمایش در داشبورد (بدون path traversal)."""
    name = os.path.basename(str(rid or ""))
    if not name:
        raise KeyError("شناسهٔ گزارش خالی است")
    if not name.endswith((".md", ".json")):
        name += ".md"
    path = os.path.join(OPS_DIR, name)
    if not os.path.isfile(path):
        raise KeyError(f"گزارش {name} پیدا نشد")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return {"id": name.rsplit(".", 1)[0], "name": name, "text": text[:200_000],
            "bytes": os.path.getsize(path)}


# ══════════════════════════════════════════════════════════════════════════
#  ۵) CLI
# ══════════════════════════════════════════════════════════════════════════
def _wait(job_id: str, timeout: float = 1800.0, echo: bool = True) -> dict:
    seen = 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = next((x for x in jobs() if x["id"] == job_id), None)
        if j is None:
            raise RuntimeError("کار پیدا نشد")
        lines = j.get("log") or []
        if echo:
            for line in lines[seen:]:
                print(f"   {line}")
            seen = len(lines)
        if j["status"] != "running" and j.get("persisted", True):
            return j
        time.sleep(0.5)
    raise TimeoutError("کار در زمان مجاز تمام نشد")


def ops_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab ops",
        description="مدیریت کلان: دانلود دادهٔ واقعی، آزمون‌های مستقل، معاینهٔ نصب")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--tfs", default=",".join(DEFAULT_TFS))
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--sync-days", type=int, default=30)
    p.add_argument("--tf", default="auto")
    p.add_argument("--variant", default="base")
    p.add_argument("--status", action="store_true")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--download", action="store_true")
    p.add_argument("--sync", action="store_true")
    p.add_argument("--exitstyles", action="store_true")
    p.add_argument("--doctor", action="store_true")
    a = p.parse_args(argv)

    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    tfs = [s.strip() for s in a.tfs.split(",") if s.strip()]

    if a.status or not any((a.probe, a.download, a.sync, a.exitstyles, a.doctor)):
        st = status(a.data_dir)
        d = st["data"]
        print(f"داده: {d['files']} فایل · {len(d['symbols'])} نماد · "
              f"{d['oldest']} → {d['newest']} · {d['bytes'] // 1024} KB")
        print(f"گزارش‌ها: {len(st['reports'])} فایل در {st['ops_dir']}")
        for j in st["jobs"][:8]:
            print(f"  · [{j['status']}] {j['title']} — {j.get('started_utc') or ''}"
                  f"{(' · ' + str(j.get('duration_s')) + 's') if j.get('duration_s') else ''}")
            if j.get("error"):
                print(f"      ❌ {j['error']}")
        return 0

    if a.probe:
        j = start("probe", "بررسی دسترسی به دادهٔ بازار", job_probe())
        j = _wait(j["id"])
        return 0 if j["status"] == "done" else 1
    if a.download:
        j = start("download", f"دانلود {a.days} روز داده",
                  job_download(syms, tfs, a.days, a.data_dir),
                  {"symbols": syms, "tfs": tfs, "days": a.days})
        j = _wait(j["id"])
        return 0 if j["status"] == "done" else 1
    if a.sync:
        j = start("sync", f"به‌روزرسانی {a.sync_days} روز اخیر",
                  job_sync(syms, tfs, a.sync_days, a.data_dir),
                  {"symbols": syms, "tfs": tfs, "days": a.sync_days})
        j = _wait(j["id"])
        return 0 if j["status"] == "done" else 1
    if a.exitstyles:
        j = start("exitstyles", "آزمایش خروج: ثابت در برابر شناور",
                  job_exitstyles(a.tf, a.variant, a.data_dir),
                  {"tf": a.tf, "variant": a.variant})
        j = _wait(j["id"])
        if j["status"] == "done":
            md = (j.get("summary") or {}).get("report_md")
            if md:
                print(f"\n📄 {md}")
                try:
                    print(open(md, encoding="utf-8").read())
                except OSError:
                    pass
        return 0 if j["status"] == "done" else 1
    if a.doctor:
        j = start("doctor", "معاینهٔ نصب", job_doctor())
        j = _wait(j["id"])
        return 0 if j["status"] == "done" and (j.get("summary") or {}).get("ok") else 1
    return 0
