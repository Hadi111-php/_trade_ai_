"""مجموعه‌دادهٔ یک‌جا (`dataset`) — دانلودِ چندساله در **یک فایل**، و برگرداندنش.

**چرا:** کاربر می‌خواهد یک‌بار دادهٔ چندساله را از Bybit بگیرد، در یک فایل JSON
داشته باشد و بفرستد؛ بعد همهٔ آزمون‌ها روی همان اجرا شود. دو دام واقعی این‌جا هست:

۱. سه تایم‌فریم × ۲۰ نماد × ۴ سال، اگر جدا-جدا فرستاده شوند، ۶۰+ فایل می‌شود و
   گم/ناقص می‌شوند ⇒ یک فایل با `meta` خودتوصیف + `sha256`.
۲. «۴ سال» نباید با ۱۵ دقیقه گرفته شود: ۲۰ نماد × ۴ سال × 15m ≈ ۲٫۸ میلیون کندل
   (صدها مگابایت). برای یک سیستم ۴ ساعته، `1h/4h/1d` کافی است (کمتر از ۵۰ مگابایت).

**چه می‌کند:** `export` (از کش → یک فایل)، `import` (فایل → کش `data/json/…` تا
همهٔ ابزارهای موجود بدون تغییر کار کنند)، و `--download` که همان دانلودِ
ادامه‌پذیرِ `autoscan.fetch_or_load` را برای هر نماد/تایم‌فریم صدا می‌زند.

**چه نمی‌کند:** هیچ عددی نمی‌سازد، هیچ کندلی را «پر» نمی‌کند و دادهٔ مصنوعی
جای دادهٔ واقعی نمی‌گذارد. اگر شبکه نبود، صریح خطا می‌دهد و فایل نیمه‌کاره را
با هش علامت می‌زند.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Dict, List, Optional, Sequence

VERSION = "1"
SCHEMA = "mtflab.dataset.v1"

#: تایم‌فریم‌های پیش‌فرض برای یک سیستم ۴ ساعته (۱۵m لازم نیست).
DEFAULT_TFS = ("1d", "4h", "1h")
#: پیش‌فرض ۲۰ نماد نقدشوندهٔ پروژه.
DEFAULT_DAYS = 1460          # ۴ سال ≈ دو رژیم کامل


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def cache_path(data_dir: str, symbol: str, tf: str) -> str:
    return os.path.join(data_dir, "json", f"{symbol.lower()}_{tf}.json")


def load_from_cache(data_dir: str, symbols: Sequence[str],
                    tfs: Sequence[str]) -> Dict[str, Dict[str, dict]]:
    """خواندن کش موجود؛ فقط فایل‌های سالم. خروجی: {sym: {tf: payload}}."""
    out: Dict[str, Dict[str, dict]] = {}
    for sym in symbols:
        for tf in tfs:
            p = cache_path(data_dir, sym, tf)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, ValueError):
                continue
            if payload.get("candles"):
                out.setdefault(sym.upper(), {})[tf] = payload
    return out


def build(data: Dict[str, Dict[str, dict]], days: int = DEFAULT_DAYS,
          tfs: Sequence[str] = DEFAULT_TFS, source: str = "bybit") -> dict:
    """بستهٔ یک‌فایلی از داده‌های کش‌شده (بدون تغییر در کندل‌ها)."""
    counts = {tf: 0 for tf in tfs}
    symbols: List[str] = []
    for sym in sorted(data):
        per = data[sym]
        if not per:
            continue
        symbols.append(sym)
        for tf, payload in per.items():
            counts[tf] = counts.get(tf, 0) + int(payload.get("meta", {}).get("n")
                                                or len(payload.get("candles") or []))
    total = sum(counts.values())
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_utc": _now(),
        "source": source,
        "days": int(days),
        "tfs": list(tfs),
        "symbols": symbols,
        "counts": counts,
        "n_candles": total,
        "note": ("کندل‌ها همان‌طور که از Bybit (عمومی، فقط بسته) آمده‌اند؛ "
                 "هیچ پرکردن یا ساختگی‌ای انجام نشده."),
        "data": {sym: {tf: data[sym][tf] for tf in data[sym]} for sym in symbols},
    }


def write_dataset(payload: dict, path: str) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    sha = _sha256(path)
    return {"path": path, "bytes": os.path.getsize(path), "sha256": sha,
            "symbols": len(payload.get("symbols") or []),
            "n_candles": payload.get("n_candles", 0),
            "counts": payload.get("counts", {})}


def import_dataset(path: str, data_dir: str) -> dict:
    """برگرداندن فایل به `data/json/<sym>_<tf>.json` (ادغام با موجود، بدون حذف)."""
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"این فایل مجموعه‌دادهٔ {SCHEMA} نیست "
                         f"(schema={payload.get('schema')!r})")
    written, skipped = [], []
    for sym, per_tf in (payload.get("data") or {}).items():
        for tf, candles_payload in (per_tf or {}).items():
            p = cache_path(data_dir, sym, tf)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.isfile(p):
                skipped.append(f"{sym}_{tf}")
                # ادغام: اگر فایل موجود کندل بیشتری دارد، آن را نگه می‌داریم
                try:
                    with open(p, encoding="utf-8") as f:
                        old = json.load(f)
                    if len(old.get("candles") or []) >= len(candles_payload.get("candles") or []):
                        continue
                except (OSError, ValueError):
                    pass
            with open(p, "w", encoding="utf-8") as f:
                json.dump(candles_payload, f, ensure_ascii=False, separators=(",", ":"))
            written.append(f"{sym}_{tf}")
    return {"written": len(written), "kept_existing": len(skipped),
            "files": written[:200], "symbols": sorted(
                {s.split("_")[0] for s in written})}


def resolve_base_url(base_url: str = "", progress: bool = True) -> str:
    """آدرس پایهٔ Bybit را قطعی می‌کند.

    باگ واقعی روی گوشی: `--base-url` خالی به `fetch_klines_range` می‌رسید و
    `urlopen("/v5/market/kline?...")` با `unknown url type` می‌شکست؛ نتیجه‌اش
    یک «مجموعه‌دادهٔ صفر-کندلی» بود که هش هم داشت و شبیه موفقیت به‌نظر می‌رسید.
    پس آدرس **هرگز** خالی یا بی‌scheme رد نمی‌شود.
    """
    b = (base_url or "").strip().rstrip("/")
    if not b:
        from .autoscan import pick_base_url
        return pick_base_url(progress=progress).rstrip("/")
    if not b.startswith(("http://", "https://")):
        raise ValueError(
            f"آدرس نامعتبر: {base_url!r} — باید با https:// شروع شود "
            "(مثال: https://api.bybit.com)")
    return b


def _download_one(symbol: str, tf: str, days: int, data_dir: str,
                  refresh: bool, base_url: str, progress: bool):
    """یک (نماد×تایم‌فریم) را می‌گیرد و payload کش را برمی‌گرداند (یا None)."""
    from .autoscan import fetch_or_load
    cs, _meta = fetch_or_load(symbol, tf, days, data_dir, base_url=base_url,
                              refresh=refresh, progress=progress)
    if not cs:
        return None
    path = cache_path(data_dir, symbol, tf)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def download(symbols: Sequence[str], tfs: Sequence[str], days: int,
             data_dir: str, refresh: bool = False,
             base_url: str = "", progress: bool = True,
             jobs: int = 3) -> Dict[str, Dict[str, dict]]:
    """دانلود ادامه‌پذیر با همان مسیر موجود (`fetch_or_load`).

    :param jobs: تعداد دانلود هم‌زمان. روی گوشی هر درخواست ~۰٫۵–۱ ثانیه است و
        ۴ سال × ۳ تایم‌فریم × ۲۰ نماد ≈ ۲۱۰۰ درخواست می‌شود؛ سریال یعنی ~۳۰
        دقیقه، با `jobs=3` یعنی ~۱۰ دقیقه. سقف ۶ است تا سقف نرخ Bybit نخورد.
    """
    from .autoscan import fetch_or_load                      # noqa: F401
    base_url = resolve_base_url(base_url, progress=progress)
    pairs = [(s, t) for s in symbols for t in tfs]
    jobs = max(1, min(int(jobs or 1), 6))
    if progress:
        print(f"🌐 منبع: {base_url} · هم‌زمانی: {jobs}")
        if jobs > 1:
            print(f"   ({len(pairs)} فایل؛ سریال ~۳۰ دقیقه، با {jobs} جریان "
                  f"~{max(1, 30 // jobs)} دقیقه)")

    out: Dict[str, Dict[str, dict]] = {}
    errors: List[str] = []
    lock = threading.Lock()
    quiet = jobs > 1                     # در حالت موازی، خط‌ها قفل می‌شوند

    def _record(sym: str, tf: str, payload, err: str = "") -> None:
        with lock:
            if err:
                errors.append(err)
                if progress:
                    print(f"⚠️ {sym} {tf}: {err}")
            elif payload:
                out.setdefault(sym.upper(), {})[tf] = payload
                if progress and quiet:
                    n = len(payload.get("candles") or [])
                    print(f"   ✅ {sym} {tf}: {n} کندل")

    def _abort_hint() -> RuntimeError:
        return RuntimeError(
            "سه تلاش اول شکست خورد و هیچ داده‌ای نیامد؛ ادامه بی‌فایده است. "
            f"آخرین خطا: {errors[-1] if errors else 'نامعلوم'}")

    if jobs == 1:
        for sym, tf in pairs:
            try:
                payload = _download_one(sym, tf, days, data_dir, refresh, base_url, progress)
            except Exception as e:                              # noqa: BLE001
                _record(sym, tf, None, f"{type(e).__name__}: {str(e)[:90]}")
                if len(errors) >= 3 and not out:
                    raise _abort_hint()
                continue
            _record(sym, tf, payload)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = {pool.submit(_download_one, s, t, days, data_dir, refresh,
                                base_url, False): (s, t) for s, t in pairs}
            for fut in as_completed(futs):
                sym, tf = futs[fut]
                try:
                    payload = fut.result()
                except Exception as e:                          # noqa: BLE001
                    _record(sym, tf, None, f"{type(e).__name__}: {str(e)[:90]}")
                else:
                    _record(sym, tf, payload)
                if len(errors) >= 3 and not out:
                    for f in futs:
                        f.cancel()
                    raise _abort_hint()

    if progress:
        files = sum(len(v) for v in out.values())
        line = f"📊 داده: {files} فایل (نماد×تایم‌فریم)"
        if errors:
            line += f" · شکست: {len(errors)}"
        print(line)
    return out


def dataset_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .autoscan import DEFAULT_SYMBOLS

    p = argparse.ArgumentParser(
        prog="mtflab dataset",
        description="دادهٔ چندساله در یک فایل JSON (صادرات/ورود/دانلود)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--symbols", default="", help="با کاما؛ پیش‌فرض ۲۰ نماد پروژه")
    p.add_argument("--tfs", default=",".join(DEFAULT_TFS))
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--download", action="store_true", help="از Bybit دانلود کن (ادامه‌پذیر)")
    p.add_argument("--refresh", action="store_true", help="کش را نادیده بگیر")
    p.add_argument("--base-url", default="")
    p.add_argument("--jobs", type=int, default=3,
                   help="دانلود هم‌زمان (۱=سریال، سقف ۶)؛ پیش‌فرض ۳")
    p.add_argument("--export", default="", help="مسیر فایل خروجی .json")
    p.add_argument("--import", dest="import_path", default="",
                   help="فایل .json را به کش برگردان")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] \
        or list(DEFAULT_SYMBOLS)

    if a.import_path:
        try:
            rep = import_dataset(a.import_path, a.data_dir)
        except (OSError, ValueError) as e:
            print(f"❌ {e}")
            return 2
        print(f"✅ {rep['written']} فایل نوشته شد · {rep['kept_existing']} فایل موجود "
              f"دست‌نخورده ماند · نماد: {len(rep['symbols'])}")
        print(f"   کش: {os.path.join(a.data_dir, 'json')}")
        return 0

    if a.download:
        print(f"⬇️ دانلود {a.days} روز · {len(symbols)} نماد · {'/'.join(tfs)} …")
        try:
            data = download(symbols, tfs, a.days, a.data_dir, refresh=a.refresh,
                            base_url=a.base_url, jobs=a.jobs)
        except (ValueError, RuntimeError) as e:
            print(f"❌ {e}")
            print("   تشخیص: python3 -m mtflab autoscan --probe-only")
            print("   یا آدرس دستی: --base-url https://api.bybit.com")
            return 2
    else:
        data = load_from_cache(a.data_dir, symbols, tfs)
        if not data:
            print("❌ هیچ کشی نبود. با --download اجرا کن.")
            return 2

    payload = build(data, days=a.days, tfs=tfs)
    if not payload.get("n_candles"):
        # فایل صفر-کندلی با هش معتبر، بدترین خروجی ممکن است: کاربر فکر می‌کند
        # داده گرفته. پس نوشته نمی‌شود و کد خروج غیرصفر است.
        print("❌ هیچ کندلی جمع نشد — فایل خالی نوشته نشد.")
        if a.download:
            print("   خطاهای دانلود بالا را ببین؛ معمولاً فیلتر شبکه/VPN است.")
        return 2
    out = a.export or os.path.join(
        "exports", f"dataset_{a.days}d_{time.strftime('%Y%m%d', time.gmtime())}.json")
    rep = write_dataset(payload, out)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"📦 {rep['path']}")
        print(f"   نماد: {rep['symbols']} · کندل: {rep['n_candles']} · "
              f"{rep['bytes'] / 1048576:.1f} مگابایت")
        print(f"   تفکیک: " + " · ".join(f"{k}={v}" for k, v in sorted(rep["counts"].items())))
        print(f"🔐 sha256 = {rep['sha256']}")
        print("   همین فایل را بفرست (یا با `--import` برگردان).")
    return 0
