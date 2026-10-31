"""بایگانی داده: از ۹۰ مگابایت کندل، یک «شناسنامه»ٔ کوچک و قابل‌اتکا.

مسئله: دادهٔ ۱۵ دقیقه‌ای ۲۰ نماد × ۲ سال ≈ ۹۰ مگابایت است. این حجم نه در گیت
جا می‌شود، نه در چت فرستادنی است. ولی **اثباتِ این‌که چه داده‌ای داشتیم** فقط
چند صد کیلوبایت است.

این ماژول سه لایه بایگانی می‌سازد:

| لایه | کجا | حجم | چه دارد |
|---|---|---|---|
| ۱ | گیت‌هاب | ~۳۰۰ KB | شناسنامه: هش فایل، هش محتوا، بازهٔ UTC، کندل ماهانه، بستهٔ روزانه، نمونهٔ کندل خام |
| ۲ | گوشی | ~۹۰ MB | خود بسته‌های JSON در `data/json/` |
| ۳ | اختیاری | فایل فشرده | آرشیو کامل برای GitHub Release |

چرا لایهٔ ۱ کافی است؟ چون هر کندل خام از مسیر «هش محتوا» قابل تأیید است: اگر
فردا همان بازه دوباره دانلود شود و هش یکی نباشد، یعنی داده عوض شده — و همان
لحظه می‌فهمیم، بدون این‌که ۹۰ مگابایت را جابه‌جا کرده باشیم.

هیچ‌جا شبکه صدا زده نمی‌شود.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, List, Optional, Sequence

from .store import content_sha256, read_index, sha256_file, verify

DIGEST_VERSION = 1


# ---------------------------------------------------------------------------
# تبدیل کندل → شناسنامه
# ---------------------------------------------------------------------------
def _month_key(ts_ms: int) -> str:
    t = time.gmtime(ts_ms / 1000)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def _day_ms(ts_ms: int) -> int:
    return (ts_ms // 86_400_000) * 86_400_000


def monthly_bars(candles: Sequence) -> List[List[float]]:
    """کندل ماهانه بر پایهٔ UTC: [start_ms, open, high, low, close, volume]."""
    buckets: Dict[str, List] = {}
    for c in candles:
        k = _month_key(c.open_time_ms)
        b = buckets.get(k)
        if b is None:
            buckets[k] = [c.open_time_ms, c.open, c.high, c.low, c.close, c.volume]
        else:
            b[2] = max(b[2], c.high)
            b[3] = min(b[3], c.low)
            b[4] = c.close
            b[5] += c.volume
    out: List[List[float]] = []
    for k in sorted(buckets):
        row = buckets[k]        # مرز ماه = open_time خود اولین کندل (UTC، بدون اتکا به ساعت محلی)
        out.append([float(row[0]), round(row[1], 8), round(row[2], 8),
                    round(row[3], 8), round(row[4], 8), round(row[5], 4)])
    return out


def daily_closes(candles: Sequence, limit: int = 1200) -> List[List[float]]:
    """آخرین بستهٔ هر روز UTC: [day_start_ms, close] — سبک و برای تحلیل خام کافی."""
    last: Dict[int, float] = {}
    for c in candles:
        last[_day_ms(c.open_time_ms)] = c.close
    keys = sorted(last)[-limit:]
    return [[float(k), round(last[k], 8)] for k in keys]


def digest_for_dataset(entry: dict, candles: Sequence, sample_bars: int = 3) -> dict:
    n = len(candles)
    head = candles[:sample_bars]
    tail = candles[-sample_bars:] if n > sample_bars else []
    return {
        "symbol": entry.get("symbol"),
        "tf": entry.get("tf"),
        "file": entry.get("file"),
        "n": n,
        "days_requested": entry.get("days_requested"),
        "first_ms": candles[0].open_time_ms if n else None,
        "last_ms": candles[-1].open_time_ms if n else None,
        "first_utc": entry.get("first_utc"),
        "last_utc": entry.get("last_utc"),
        "sha256": entry.get("sha256"),
        "content_sha256": entry.get("content_sha256"),
        "integrity_ok": entry.get("integrity_ok"),
        "monthly": monthly_bars(candles),
        "daily": daily_closes(candles),
        "samples": {
            "head": [[c.open_time_ms, c.open, c.high, c.low, c.close, c.volume]
                     for c in head],
            "tail": [[c.open_time_ms, c.open, c.high, c.low, c.close, c.volume]
                     for c in tail],
        },
    }


# ---------------------------------------------------------------------------
# ساخت شناسنامه
# ---------------------------------------------------------------------------
def build_digest(data_dir: str, tag: str = "", sample_bars: int = 3) -> dict:
    """شناسنامهٔ همهٔ بسته‌های موجود را می‌سازد (بدون شبکه، فقط خواندن فایل)."""
    from .autoscan import candles_from_json

    rows = verify(data_dir)
    if not rows:
        from .store import reindex
        reindex(data_dir)
        rows = verify(data_dir)

    idx = read_index(data_dir)
    datasets: Dict[str, dict] = {}
    problems: List[str] = []
    for r in rows:
        key = r["key"]
        entry = idx.get("datasets", {}).get(key) or {}
        path = os.path.join(data_dir, "json",
                            entry.get("file") or f"{key.lower()}.json")
        if not os.path.exists(path):
            problems.append(f"{key}: فایل نیست")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                cs = candles_from_json(json.load(f))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            problems.append(f"{key}: {e}")
            continue
        if not cs:
            problems.append(f"{key}: خالی")
            continue
        # هش‌ها همین‌جا از خود فایل بازمحاسبه می‌شوند (نه از فهرست قبلی)
        entry = dict(entry, symbol=entry.get("symbol") or key.split("_")[0],
                     tf=entry.get("tf") or key.split("_")[-1],
                     file=os.path.basename(path))
        d = digest_for_dataset(entry, cs, sample_bars)
        d["sha256"] = sha256_file(path)
        d["content_sha256"] = content_sha256(cs)
        d["bytes"] = os.path.getsize(path)
        datasets[key] = d

    return {
        "digest_version": DIGEST_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "tag": tag,
        "timezone": "UTC (epoch milliseconds; daily buckets at 00:00 UTC)",
        "n_datasets": len(datasets),
        "n_candles": sum(int(d["n"]) for d in datasets.values()),
        "problems": problems,
        "datasets": datasets,
    }


def digest_sha256(digest: dict) -> str:
    """هش کل شناسنامه — برای مقایسهٔ دو فایل شناسنامه."""
    blob = json.dumps(digest, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# نمایش
# ---------------------------------------------------------------------------
def render_manifest(digest: dict, lang: str = "fa") -> str:
    ds = digest["datasets"]
    out: List[str] = []
    if lang == "en":
        out.append("# Data archive manifest\n")
        out.append(f"created: {digest['created_at']} · tag: `{digest['tag'] or '—'}` · "
                   f"timezone: **UTC**\n")
        out.append(f"**{digest['n_datasets']} datasets** · "
                   f"{digest['n_candles']:,} candles · "
                   f"digest sha256 `{digest_sha256(digest)[:16]}`\n")
        out.append("| dataset | bars | from (UTC) | to (UTC) | file sha256 | content sha256 |")
        out.append("|---|---:|---|---|---|---|")
        for k in sorted(ds):
            d = ds[k]
            out.append(f"| `{k}` | {d['n']} | {d['first_utc']} | {d['last_utc']} | "
                       f"`{(d.get('sha256') or '')[:16]}` | "
                       f"`{(d.get('content_sha256') or '')[:16]}` |")
        if digest["problems"]:
            out.append("\n**Problems:** " + "; ".join(digest["problems"]))
        out.append("\n> Any future re-download can be compared field-by-field against "
                   "`content_sha256`. If it differs, the source data changed.")
        return "\n".join(out) + "\n"

    out.append("# شناسنامهٔ بایگانی داده\n")
    out.append(f"ساخته‌شده: {digest['created_at']} · برچسب: `{digest['tag'] or '—'}` · "
               f"منطقهٔ زمانی: **UTC**\n")
    out.append(f"**{digest['n_datasets']} بسته** · {digest['n_candles']:,} کندل · "
               f"هش شناسنامه `{digest_sha256(digest)[:16]}`\n")
    out.append("| بسته | کندل | از (UTC) | تا (UTC) | هش فایل | هش محتوا |")
    out.append("|---|---:|---|---|---|---|")
    for k in sorted(ds):
        d = ds[k]
        out.append(f"| `{k}` | {d['n']} | {d['first_utc']} | {d['last_utc']} | "
                   f"`{(d.get('sha256') or '')[:16]}` | "
                   f"`{(d.get('content_sha256') or '')[:16]}` |")
    if digest["problems"]:
        out.append("\n**مشکل‌ها:** " + "؛ ".join(digest["problems"]))
    out.append("\n> هر دانلود آینده را می‌شود ستون‌به‌ستون با `content_sha256` "
               "مقایسه کرد. اگر یکی نبود، یعنی دادهٔ منبع عوض شده — و همان‌جا "
               "می‌فهمیم، بدون جابه‌جایی ۹۰ مگابایت.")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# نوشتن روی دیسک
# ---------------------------------------------------------------------------
def write_archive(data_dir: str, out_dir: str, tag: str = "") -> Dict[str, str]:
    tag = tag or time.strftime("%Y%m%d-%H%M", time.gmtime())
    digest = build_digest(data_dir, tag=tag)
    os.makedirs(out_dir, exist_ok=True)
    js = os.path.join(out_dir, f"data_digest_{tag}.json")
    md = os.path.join(out_dir, f"data_digest_{tag}.md")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, separators=(",", ":"))
    with open(md, "w", encoding="utf-8") as f:
        f.write(render_manifest(digest, lang="fa"))
    return {"json": js, "md": md, "tag": tag,
            "bytes": str(os.path.getsize(js)),
            "sha256": sha256_file(js), "datasets": str(digest["n_datasets"]),
            "candles": f"{digest['n_candles']:,}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def archive_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab archive",
        description="ساخت شناسنامهٔ کوچک از دادهٔ ذخیره‌شده (بدون شبکه)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="data_archive")
    p.add_argument("--tag", default="",
                   help="برچسب فایل‌ها (پیش‌فرض: زمان UTC)")
    a = p.parse_args(argv)
    try:
        rep = write_archive(a.data_dir, a.out_dir, a.tag)
    except Exception as e:                                  # noqa: BLE001
        print(f"❌ ساخت شناسنامه ناموفق: {e}")
        return 2
    if rep["datasets"] == "0":
        print("⚠️ هیچ بستهٔ داده‌ای پیدا نشد. اول یک‌بار اسکنر را اجرا کنید.")
        return 2
    print("✅ شناسنامهٔ داده ساخته شد")
    print(f"   بسته‌ها : {rep['datasets']} · کندل: {rep['candles']}")
    print(f"   JSON    : {rep['json']}  ({int(rep['bytes']) / 1024:.0f} KB)")
    print(f"   خلاصه   : {rep['md']}")
    print(f"   sha256  : {rep['sha256']}")
    print("")
    print("   👉 همین فایل JSON را برای بایگانی در گیت‌هاب بفرستید.")
    print("   (دادهٔ کامل روی گوشی می‌ماند؛ این فقط شناسنامه است.)")
    return 0
