"""انبار داده: فهرستِ یک‌جا (`data/json/_index.json`) برای همهٔ بسته‌های ذخیره‌شده.

چرا این ماژول هست؟

۱. **بدون دانلود دوباره.** هر بستهٔ JSON که یک‌بار گرفته شده، در فهرست ثبت
   می‌شود؛ ابزارهای دیگر (`autoscan --source json`، `comove`، تست‌های بعدی)
   همان فایل را می‌خوانند و هیچ درخواست شبکه‌ای نمی‌زنند.
۲. **قابل تأیید بودن.** برای هر بسته سه اثر انگشت نگه می‌داریم:
   `sha256` فایل، هش محتوای کندل‌ها (هر شش ستون)، و بازهٔ زمانی.
   پس بعداً می‌شود گفت «این نتیجه روی *همین* داده ساخته شده» یا نه.
۳. **بی‌صدا خراب نشدن.** اگر فایلی پاک/دست‌کاری شده باشد، `verify` می‌گوید.

این ماژول فقط فایل می‌خواند و می‌نویسد؛ هیچ وابستگی بیرونی ندارد و هیچ‌جا
شبکه صدا نمی‌زند. عمداً به `autoscan` وابسته نیست تا حلقهٔ import نسازد.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, List, Optional, Sequence

INDEX_NAME = "_index.json"
INDEX_VERSION = 1


# ---------------------------------------------------------------------------
# مسیرها
# ---------------------------------------------------------------------------
def index_path(data_dir: str) -> str:
    return os.path.join(data_dir, "json", INDEX_NAME)


def dataset_key(symbol: str, tf: str) -> str:
    return f"{str(symbol).upper()}_{tf}"


# ---------------------------------------------------------------------------
# هش‌ها
# ---------------------------------------------------------------------------
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_sha256(candles: Sequence) -> str:
    """هش محتوای کندل‌ها روی **هر شش** ستون (open/high/low/close/volume/time).

    `data_fingerprint` در autoscan فقط open/close/volume را می‌بیند و برای
    «همان داده است؟» کافی نیست؛ این یکی برای تأیید صحت است.
    """
    h = hashlib.sha256()
    for c in candles:
        h.update(f"{c.open_time_ms}|{c.open:.10f}|{c.high:.10f}|{c.low:.10f}"
                 f"|{c.close:.10f}|{c.volume:.10f};".encode("ascii"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# خواندن/نوشتن فهرست (نوشتن اتمیک: tmp + replace تا فایل نصفه نماند)
# ---------------------------------------------------------------------------
def read_index(data_dir: str) -> dict:
    path = index_path(data_dir)
    if not os.path.exists(path):
        return {"version": INDEX_VERSION, "updated_at": None, "datasets": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"version": INDEX_VERSION, "updated_at": None, "datasets": {},
                "corrupt": True}
    if not isinstance(data.get("datasets"), dict):
        data["datasets"] = {}
    data.setdefault("version", INDEX_VERSION)
    return data


def write_index(data_dir: str, data: dict) -> None:
    path = index_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["version"] = INDEX_VERSION
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def upsert(data_dir: str, entry: dict) -> dict:
    """یک بسته را در فهرست ثبت/به‌روزرسانی می‌کند و فهرست را برمی‌گرداند."""
    data = read_index(data_dir)
    data["datasets"][dataset_key(entry["symbol"], entry["tf"])] = entry
    write_index(data_dir, data)
    return data


# ---------------------------------------------------------------------------
# ساخت مدخل
# ---------------------------------------------------------------------------
def build_entry(symbol: str, tf: str, path: str, meta: dict,
                candles: Sequence, integrity: Optional[dict] = None) -> dict:
    """مدخل فهرست برای یک بستهٔ JSON تازه نوشته‌شده."""
    step_ms = None
    try:
        from .data import tf_to_minutes
        step_ms = tf_to_minutes(tf) * 60_000
    except (KeyError, ValueError):
        pass
    first = candles[0].open_time_ms if candles else None
    last = candles[-1].open_time_ms if candles else None
    return {
        "symbol": str(symbol).upper(),
        "tf": tf,
        "file": os.path.basename(path),
        "bytes": os.path.getsize(path) if os.path.exists(path) else None,
        "n": len(candles),
        "days_requested": meta.get("days"),
        "first_ms": first,
        "last_ms": last,
        "first_utc": (time.strftime("%Y-%m-%d %H:%M", time.gmtime(first / 1000))
                      if first else None),
        "last_utc": (time.strftime("%Y-%m-%d %H:%M", time.gmtime(last / 1000))
                     if last else None),
        "step_ms": step_ms,
        "sha256": sha256_file(path) if os.path.exists(path) else None,
        "content_sha256": content_sha256(candles) if candles else None,
        "source": meta.get("base_url") or "bybit",
        "downloaded_at": meta.get("downloaded_at"),
        "integrity_ok": (integrity or {}).get("ok"),
        "integrity": integrity or {},
    }


# ---------------------------------------------------------------------------
# بازبینی
# ---------------------------------------------------------------------------
def verify(data_dir: str, deep: bool = False) -> List[dict]:
    """وضعیت هر مدخل را بررسی می‌کند: فایل هست؟ هش می‌خورد؟ بازه درست است؟

    :param deep: اگر True، فایل دوباره خوانده و هش محتوا هم مقایسه می‌شود
        (کندتر، ولی «همان کندل‌ها؟» را اثبات می‌کند).
    """
    from .autoscan import candles_from_json

    data = read_index(data_dir)
    rows: List[dict] = []
    for key, e in sorted(data.get("datasets", {}).items()):
        path = os.path.join(data_dir, "json", e.get("file") or f"{key.lower()}.json")
        row = {"key": key, "symbol": e.get("symbol"), "tf": e.get("tf"),
               "n": e.get("n"), "file": e.get("file"),
               "first_utc": e.get("first_utc"), "last_utc": e.get("last_utc"),
               "status": "ok", "detail": ""}
        if not os.path.exists(path):
            row.update(status="missing", detail="فایل نیست")
            rows.append(row)
            continue
        size = os.path.getsize(path)
        if e.get("bytes") and size != e["bytes"]:
            row.update(status="changed",
                       detail=f"اندازه عوض شده ({e['bytes']} → {size})")
        if deep:
            try:
                with open(path, encoding="utf-8") as f:
                    cs = candles_from_json(json.load(f))
                got = content_sha256(cs)
                if e.get("content_sha256") and got != e["content_sha256"]:
                    row.update(status="changed", detail="هش محتوا نمی‌خورد")
                elif len(cs) != e.get("n"):
                    row.update(status="changed",
                               detail=f"تعداد کندل عوض شده ({e.get('n')} → {len(cs)})")
            except (OSError, ValueError, json.JSONDecodeError) as ex:
                row.update(status="corrupt", detail=str(ex)[:60])
        rows.append(row)
    return rows


def reindex(data_dir: str, days_default: Optional[int] = None) -> dict:
    """همهٔ فایل‌های `data/json/*.json` را می‌خواند و در فهرست ثبت می‌کند.

    چرا لازم است: اگر بسته‌ها با اجرای قدیمی یا با `--source json` آمده باشند،
    مدخلی در فهرست ندارند. این تابع یک‌بار همه را اسکن می‌کند تا فهرست
    **کامل** شود و بعد از آن هیچ ابزاری نیاز به دانلود دوباره نداشته باشد.
    """
    from .autoscan import candles_from_json, data_integrity

    folder = os.path.join(data_dir, "json")
    if not os.path.isdir(folder):
        return {"added": 0, "skipped": 0, "errors": []}
    added = skipped = 0
    errors: List[str] = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name == INDEX_NAME:
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            cs = candles_from_json(payload)
            meta = dict(payload.get("meta") or {})
        except (OSError, ValueError, json.JSONDecodeError) as e:
            errors.append(f"{name}: {e}")
            continue
        if not cs:
            skipped += 1
            continue
        sym = (meta.get("symbol") or name.split("_")[0]).upper()
        tf = meta.get("tf") or (name[:-5].split("_")[-1])
        days = int(meta.get("days") or days_default or 0)
        meta.setdefault("days", days)
        integ = data_integrity(cs, tf, days or 30)
        upsert(data_dir, build_entry(sym, tf, path, meta, cs, integ))
        added += 1
    return {"added": added, "skipped": skipped, "errors": errors}


def _json_files(data_dir: str) -> List[str]:
    folder = os.path.join(data_dir, "json")
    if not os.path.isdir(folder):
        return []
    return [n for n in sorted(os.listdir(folder))
            if n.endswith(".json") and n != INDEX_NAME]


def totals(rows: Sequence[dict]) -> Dict[str, float]:
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    candles = sum(int(r.get("n") or 0) for r in rows)
    return {"datasets": n, "ok": ok, "bad": n - ok, "candles": candles}


# ---------------------------------------------------------------------------
# نمایش
# ---------------------------------------------------------------------------
def render_index(data_dir: str, lang: str = "fa", deep: bool = False) -> str:
    rows = verify(data_dir, deep=deep)
    data = read_index(data_dir)
    t = totals(rows)
    out: List[str] = []
    if lang == "en":
        out.append("# Local data store\n")
        out.append(f"index: `{index_path(data_dir)}` · updated "
                   f"{data.get('updated_at') or '—'}\n")
        out.append(f"**{t['datasets']} datasets** · ok {t['ok']} · problems "
                   f"{t['bad']} · {t['candles']:,} candles\n")
        if not rows:
            files = _json_files(data_dir)
            if files:
                out.append(f"_{len(files)} data file(s) on disk but not indexed — "
                           f"run `data-index --reindex` once_")
            else:
                out.append("_(empty — run the scanner once to download)_")
            return "\n".join(out) + "\n"
        out.append("| key | n | from (UTC) | to (UTC) | status | note |")
        out.append("|---|---:|---|---|---|---|")
        for r in rows:
            out.append(f"| `{r['key']}` | {r['n']} | {r['first_utc']} | "
                       f"{r['last_utc']} | {r['status']} | {r['detail']} |")
        out.append("\n> All timestamps are UTC epoch milliseconds. "
                   "Re-running any tool with `--source json` reuses these files "
                   "and downloads nothing.")
        return "\n".join(out) + "\n"

    out.append("# انبار دادهٔ محلی\n")
    out.append(f"فهرست: `{index_path(data_dir)}` · آخرین به‌روزرسانی "
               f"{data.get('updated_at') or '—'}\n")
    out.append(f"**{t['datasets']} بسته** · سالم {t['ok']} · مشکل‌دار {t['bad']} · "
               f"{t['candles']:,} کندل\n")
    if not rows:
        files = _json_files(data_dir)
        if files:
            out.append(f"_{len(files)} فایل داده روی دیسک هست ولی در فهرست ثبت "
                       f"نشده — یک‌بار بزنید: `data-index --reindex`_")
        else:
            out.append("_(خالی — یک‌بار اسکنر را اجرا کنید تا داده گرفته شود)_")
        return "\n".join(out) + "\n"
    out.append("| کلید | کندل | از (UTC) | تا (UTC) | وضعیت | توضیح |")
    out.append("|---|---:|---|---|---|---|")
    for r in rows:
        out.append(f"| `{r['key']}` | {r['n']} | {r['first_utc']} | "
                   f"{r['last_utc']} | {r['status']} | {r['detail']} |")
    out.append("\n> همهٔ زمان‌ها یونیکس میلی‌ثانیه و **UTC** هستند. اجرای دوبارهٔ "
               "هر ابزار با `--source json` همین فایل‌ها را می‌خواند و هیچ "
               "دانلودی نمی‌کند.")
    return "\n".join(out) + "\n"
