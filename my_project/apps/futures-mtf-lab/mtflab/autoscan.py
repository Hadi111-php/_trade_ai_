"""اسکن خودکار چندنمادی — یک دستور، از دانلود تا گزارش.

هدف: کاربر روی گوشی (Termux) یا هر ماشینی این را اجرا می‌کند و یک «بستهٔ
شواهد» می‌گیرد که برای بازبینی کافی است. هیچ وابستگی بیرونی لازم نیست
(فقط کتابخانهٔ استاندارد پایتون).

مراحل:
  ۱) دانلود دادهٔ تاریخی هر نماد از Bybit (عمومی، بدون کلید) + ذخیره در JSON
  ۲) اجرای مجموعه‌ای از «نسخه‌ها» روی همان داده (پایه / روندکاوی / …)
  ۳) سنجش هر نسخه: کل دوره + سال‌به‌سال + نماد‌به‌نماد
  ۴) دروازهٔ پذیرش از پیش تعیین‌شده (همان قاعدهٔ `robust`) + حکم نهایی
  ۵) تولید گزارش فارسی (MD) + بستهٔ JSON برای بازبینی

نکته‌های طراحی که عمدی‌اند:
  • فقط **یک تایم‌فریم** دانلود می‌شود و بقیه از آن ساخته می‌شود (سرعت روی موبایل).
  • همهٔ نسخه‌ها روی **همان** تایم‌فریم و همان نمادها اجرا می‌شوند تا مقایسه منصفانه باشد.
  • داده در JSON ذخیره می‌شود (خواستهٔ کاربر) با امکان ادامهٔ اجرا بعد از قطعی.
  • نمادهایی که تاریخ کوتاه دارند حذف نمی‌شوند، ولی «پوشش»شان ثبت می‌شود.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import PRESETS, MTFConfig
from .data import Candle, resample_up, tf_to_minutes
from .diagnose import _position_pnls
from .engine import run_backtest
from .robust import sign_test_p

VERSION = "1.0"

# ----------------------------------------------------------------------------
# نمادهای پیش‌فرض
# ----------------------------------------------------------------------------
# انتخاب: نقدشونده‌ترین USDT-Perpهای Bybit با تاریخ کافی + تنوع (L1، L2، DeFi، meme).
# ⚠️ محدودیت‌های صادقانه:
#   ۱) این فهرست «امروز» انتخاب شده ⇒ **survivorship bias** دارد (نمادهایی که
#      حذف شده‌اند اینجا نیستند و همهٔ آن‌ها بازنده بودند).
#   ۲) چون همه‌شان امروز زنده‌اند، نتیجه به نفع استراتژی بایاس دارد.
#   ۳) پوشش تاریخی هر نماد در گزارش ثبت می‌شود تا معلوم باشد روی چه بازه‌ای سنجیده شد.
DEFAULT_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
    "DOTUSDT", "TRXUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "SUIUSDT", "TONUSDT", "BCHUSDT",
)

#: آدرس‌های جایگزین — در برخی کشورها/شبکه‌ها api.bybit.com فیلتر است.
BASE_URLS: Tuple[str, ...] = (
    "https://api.bybit.com",
    "https://api.bytick.com",
)


# ----------------------------------------------------------------------------
# ذخیره/خواندن JSON
# ----------------------------------------------------------------------------
def candles_to_json(candles: Sequence[Candle], meta: Optional[dict] = None) -> dict:
    """بستهٔ کندل‌ها به‌صورت JSON خودتوصیف (قابل ارسال و بازبینی مستقل)."""
    m = dict(meta or {})
    m.setdefault("n", len(candles))
    m.setdefault("schema", "mtflab.candles.v1")
    m.setdefault("scanner_version", VERSION)
    m.setdefault("created_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if candles:
        m.setdefault("start", time.strftime("%Y-%m-%d", time.gmtime(candles[0].open_time_ms / 1000)))
        m.setdefault("end", time.strftime("%Y-%m-%d", time.gmtime(candles[-1].open_time_ms / 1000)))
    return {
        "meta": m,
        "columns": ["ts", "open", "high", "low", "close", "volume"],
        "candles": [[c.open_time_ms, c.open, c.high, c.low, c.close, round(c.volume, 6)]
                    for c in candles],
    }


def candles_from_json(payload: dict) -> List[Candle]:
    return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                   float(r[4]), float(r[5]) if len(r) > 5 else 0.0)
            for r in payload.get("candles", [])]


def _json_path(data_dir: str, symbol: str, tf: str) -> str:
    return os.path.join(data_dir, "json", f"{symbol.lower()}_{tf}.json")


# ----------------------------------------------------------------------------
# دانلود
# ----------------------------------------------------------------------------
def _probe(base_url: str, timeout: int = 10) -> bool:
    """آیا این آدرس در دسترس است؟ (سریع‌ترین راه برای انتخاب mirror)"""
    url = f"{base_url}/v5/market/time"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"mtf-autoscan/{VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return int(payload.get("retCode", 1)) == 0
    except (urllib.error.URLError, TimeoutError, OSError, ValueError,
            json.JSONDecodeError):
        return False


def pick_base_url(candidates: Sequence[str] = BASE_URLS, progress: bool = True) -> str:
    for url in candidates:
        if _probe(url):
            if progress:
                print(f"  🌐 آدرس در دسترس: {url}")
            return url
        if progress:
            print(f"  ⚠️ پاسخ نداد: {url}")
    raise RuntimeError("هیچ‌کدام از آدرس‌های Bybit در دسترس نیستند. "
                       "اتصال/فیلتر شبکه را بررسی کنید.")


def load_csv_symbol(symbol: str, path: str, native_tf: str, tf: str,
                    progress: bool = True) -> Tuple[List[Candle], dict]:
    """خواندن یک CSV محلی و ارتقای تایم‌فریم در صورت نیاز (حالت آفلاین)."""
    from .data import csv_candles
    if not os.path.exists(path):
        raise RuntimeError(f"CSV پیدا نشد: {path}")
    cs = csv_candles(path)
    if not cs:
        raise RuntimeError(f"CSV خالی است: {path}")
    from .data import align_timeframe
    _m: dict = {}
    cs = align_timeframe(cs, tf, "trigger", _m)
    if native_tf != tf and not _m.get("timeframe_fix"):
        if tf_to_minutes(tf) < tf_to_minutes(native_tf):
            raise RuntimeError(f"نمی‌شود از {native_tf} به {tf} رسید (ساخت پایین‌تر ممنوع)")
        cs = resample_up(cs, native_tf, tf)[0]
    meta = {"symbol": symbol, "tf": tf, "native_tf": native_tf, "path": path,
            "n": len(cs), "from_cache": True}
    if progress:
        print(f"    📂 CSV: {os.path.basename(path)} → {len(cs)} کندل {tf}")
    return cs, meta


def data_fingerprint(candles: Sequence[Candle]) -> str:
    """اثر انگشت داده — تا بتوان بعداً تأیید کرد همان داده تحلیل شده است.

    چرا: وقتی بستهٔ JSON از گوشی برمی‌گردد، باید بتوان بدون ابهام گفت «این خروجی
    روی همین داده ساخته شده». یک هش کوتاه کافی است.
    """
    import hashlib
    h = hashlib.sha256()
    for c in candles:
        h.update(f"{c.open_time_ms}|{c.open:.8f}|{c.close:.8f}|{c.volume:.6f};"
                 .encode("ascii"))
    return h.hexdigest()[:16]


def discover_cached_symbols(data_dir: str, tf: str) -> List[str]:
    """نمادهایی که فایل کش JSON برای همین تایم‌فریم دارند (مرتب، ثابت)."""
    import glob
    pat = os.path.join(data_dir, "json", f"*_{tf}.json")
    out = []
    for path in sorted(glob.glob(pat)):
        name = os.path.basename(path)[: -(len(tf) + 6)]   # حذف "_<tf>.json"
        if name:
            out.append(name.upper())
    return out


def fetch_or_load(symbol: str, tf: str, days: int, data_dir: str,
                  base_url: str, refresh: bool = False,
                  progress: bool = True) -> Tuple[List[Candle], dict]:
    """دادهٔ یک نماد را از JSON می‌خواند یا دانلود و ذخیره می‌کند (ادامه‌پذیر)."""
    path = _json_path(data_dir, symbol, tf)
    step = tf_to_minutes(tf) * 60_000

    if not refresh and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            cs = candles_from_json(payload)
            # کش فقط وقتی معتبر است که تا نزدیک «الان» داده داشته باشد
            if cs and cs[-1].open_time_ms + step >= int(time.time() * 1000) - 3 * 86_400_000:
                if progress:
                    print(f"    ↺ کش JSON: {os.path.basename(path)} ({len(cs)} کندل)")
                meta = dict(payload.get("meta") or {})
                meta["from_cache"] = True
                return cs, meta
        except (OSError, ValueError, json.JSONDecodeError) as e:
            if progress:
                print(f"    ⚠️ کش خراب ({e}) — دوباره دانلود می‌شود")

    from .bybit_public import fetch_klines_range
    cs = fetch_klines_range(symbol, tf, days, base_url=base_url,
                            cache_dir=os.path.join(data_dir, "csv"),
                            progress=False, rate_sleep=0.35)
    meta = {
        "symbol": symbol, "tf": tf, "days": days,
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "n": len(cs),
        "start": (time.strftime("%Y-%m-%d", time.gmtime(cs[0].open_time_ms / 1000))
                  if cs else None),
        "end": (time.strftime("%Y-%m-%d", time.gmtime(cs[-1].open_time_ms / 1000))
                if cs else None),
        "base_url": base_url,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(candles_to_json(cs, meta), f, ensure_ascii=False, separators=(",", ":"))
    if progress:
        print(f"    ✅ {len(cs)} کندل → {path}")
    return cs, meta


# ----------------------------------------------------------------------------
# ساخت لایه‌ها
# ----------------------------------------------------------------------------
def build_layers(trig: Sequence[Candle], tf_trigger: str, tf_filter: str,
                 tf_bias: str, bias_enabled: bool) -> Dict[str, List[Candle]]:
    layers = {"trigger": list(trig)}
    if tf_filter and tf_filter != tf_trigger:
        layers["filter"] = resample_up(trig, tf_trigger, tf_filter)[0]
    else:
        layers["filter"] = list(trig)
    if bias_enabled:
        layers["bias"] = (resample_up(trig, tf_trigger, tf_bias)[0]
                          if tf_bias and tf_bias != tf_trigger else list(trig))
    else:
        layers["bias"] = []
    return layers


# ----------------------------------------------------------------------------
# اجرای یک نسخه روی یک نماد
# ----------------------------------------------------------------------------
def _year_of(ts_ms: int) -> int:
    return time.gmtime(ts_ms / 1000).tm_year


def run_variant(cfg: MTFConfig, layers: Dict[str, List[Candle]],
                overrides: dict) -> dict:
    """یک نسخه را اجرا و معیارهای «هم‌سطح با بقیه» را برمی‌گرداند."""
    c = replace(cfg, verbose=False, forensics=False, run_id="", **overrides)
    res = run_backtest(c, layers)
    s = res["summary"]
    pnls = _position_pnls(res)

    per_year: Dict[int, dict] = {}
    for t in res["trades"]:
        y = _year_of(t["ts"])
        d = per_year.setdefault(y, {"pnl": 0.0, "n": 0, "wins": 0})
        d["pnl"] += t["pnl"]
        d["n"] += 1
        if t["pnl"] > 0:
            d["wins"] += 1
    years = {str(y): {"pnl": round(v["pnl"], 2), "n": v["n"],
                      "win_rate": round(v["wins"] / v["n"], 4) if v["n"] else 0.0}
             for y, v in sorted(per_year.items())}

    wins = [p for p in pnls if p > 0]
    gross_w, gross_l = sum(wins), -sum(p for p in pnls if p <= 0)
    return {
        "n": len(pnls),
        "n_legs": len(res["trades"]),
        "pnl": round(sum(pnls), 4),
        "expectancy": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": (round(gross_w / gross_l, 4) if gross_l > 0 else None),
        "return_pct": round(s.get("return_pct") or 0.0, 2),
        "max_drawdown_pct": round(s.get("max_drawdown_pct") or 0.0, 2),
        "total_fees": round(sum(t.get("fees", 0.0) for t in res["trades"]), 2),
        "per_year": years,
        "positive_years": sum(1 for y in years.values() if y["pnl"] > 0),
        "years_n": len(years),
        "veto_top": dict(sorted((s.get("veto_stats") or {}).items(),
                                key=lambda kv: -kv[1])[:5]),
    }


# ----------------------------------------------------------------------------
# نسخه‌های قابل مقایسه (همه روی یک تایم‌فریم)
# ----------------------------------------------------------------------------
def variants_for(tf_trigger: str, tf_filter: str, tf_bias: str) -> List[Tuple[str, str, dict]]:
    """نسخه‌ها: (شناسه، برچسب، overrides).

    همه روی **همان** تایم‌فریم اجرا می‌شوند تا اختلاف فقط از «منطق» بیاید، نه از
    تعداد معامله یا هزینه. این نکته‌ای است که در آزمون‌های قبلی رعایت نشده بود.
    """
    base_tf = {"tf_trigger": tf_trigger, "tf_filter": tf_filter, "tf_bias": tf_bias}
    preset_trend = dict(PRESETS["trend_4h"])
    # پریست trend_4h تایم‌فریم خودش را دارد؛ اینجا به تایم‌فریم اسکن تحمیل می‌شود
    preset_trend.pop("tf_trigger", None)
    preset_trend.pop("tf_filter", None)
    preset_trend.pop("tf_bias", None)

    return [
        ("base", "پایه (همان تایم‌فریم اسکن)", dict(base_tf)),
        ("trend", "روندکاوی: شکست + بدون TP + تریل باز",
         dict(base_tf, **preset_trend)),
        ("trend_tp", "روندکاوی + TP ثابت 6×ATR (برای سنجش اثر TP)",
         dict(base_tf, **dict(preset_trend, take_profit_atr_mult=6.0))),
        ("pullback", "فقط pullback (فرضیهٔ ۱ ساله — باید رد شود)",
         dict(base_tf, trigger_entry_modes=["pullback"])),
        ("climax", "ردِ کندل اوج (فرضیهٔ ۱ ساله — باید رد شود)",
         dict(base_tf, trigger_max_range_atr=1.0)),
    ]


# ----------------------------------------------------------------------------
# دروازهٔ پذیرش
# ----------------------------------------------------------------------------
GATE = {
    "min_symbols": 8,            # حداقل نماد با دادهٔ کافی
    "min_profitable_symbols_pct": 60.0,
    "min_positive_years_pct": 60.0,
    "min_median_pf": 1.05,
    "min_sign_test_p": 0.10,     # p باید ≤ این باشد (در برابر نسخهٔ پایه)
    "min_trades": 100,
}


def aggregate(per_symbol: Dict[str, Dict[str, dict]], variants: Sequence[str]) -> dict:
    out: Dict[str, dict] = {}
    for vid in variants:
        rows = [(sym, d[vid]) for sym, d in per_symbol.items()
                if vid in d and d[vid]["n"] > 0]
        if not rows:
            out[vid] = {"ok": False, "n_symbols": 0}
            continue
        pfs = sorted(r["profit_factor"] for _, r in rows if r["profit_factor"] is not None)
        exps = sorted(r["expectancy"] for _, r in rows)
        prof = sum(1 for x in pfs if x > 1.0)
        tot_years = sum(r["years_n"] for _, r in rows)
        pos_years = sum(r["positive_years"] for _, r in rows)
        total_n = sum(r["n"] for _, r in rows)
        total_pnl = sum(r["pnl"] for _, r in rows)

        # آزمون علامت: این نسخه در چند نماد از «پایه» بهتر بود؟
        sign = None
        if vid != "base":
            wins = n = 0
            for sym, d in per_symbol.items():
                if "base" not in d or vid not in d:
                    continue
                n += 1
                if d[vid]["expectancy"] > d["base"]["expectancy"]:
                    wins += 1
            sign = {"wins": wins, "of": n, "p_value": sign_test_p(wins, n)}

        checks = {
            "symbols": len(rows) >= GATE["min_symbols"],
            "trades": total_n >= GATE["min_trades"],
            "profitable_symbols": (100.0 * prof / max(1, len(pfs))
                                   >= GATE["min_profitable_symbols_pct"]),
            "positive_years": (100.0 * pos_years / max(1, tot_years)
                               >= GATE["min_positive_years_pct"]),
            "median_pf": (pfs[len(pfs) // 2] if pfs else 0.0) >= GATE["min_median_pf"],
            "significance": (vid == "base") or
                            (sign is not None and sign["p_value"] <= GATE["min_sign_test_p"]),
        }
        out[vid] = {
            "ok": True,
            "n_symbols": len(rows),
            "total_trades": total_n,
            "total_pnl": round(total_pnl, 2),
            "median_pf": round(pfs[len(pfs) // 2], 4) if pfs else None,
            "median_expectancy": round(exps[len(exps) // 2], 4) if exps else None,
            "profitable_symbols": prof,
            "profitable_symbols_pct": round(100.0 * prof / max(1, len(pfs)), 2),
            "positive_years": pos_years,
            "years_n": tot_years,
            "positive_years_pct": round(100.0 * pos_years / max(1, tot_years), 2),
            "sign_vs_base": sign,
            "checks": checks,
            "survived": bool(all(checks.values())),
        }
    return out


# ----------------------------------------------------------------------------
# اجرای کامل
# ----------------------------------------------------------------------------
def autoscan(cfg: MTFConfig, symbols: Sequence[str], days: int, tf: str,
             data_dir: str, refresh: bool = False,
             progress: bool = True, stop_on_network_error: bool = True,
             source: str = "bybit", csv_paths: Optional[Dict[str, str]] = None,
             csv_native_tf: str = "1h") -> dict:
    tf_filter, tf_bias = "1d", "1d"
    variants = variants_for(tf, tf_filter, tf_bias)
    vids = [v[0] for v in variants]

    base_url = ""
    if source == "bybit":
        base_url = pick_base_url(progress=progress)
        os.makedirs(os.path.join(data_dir, "json"), exist_ok=True)

    per_symbol: Dict[str, Dict[str, dict]] = {}
    coverage: Dict[str, dict] = {}
    errors: List[str] = []
    t0 = time.time()

    for i, sym in enumerate(symbols, 1):
        if progress:
            print(f"\n[{i}/{len(symbols)}] {sym}")
        try:
            if source == "csv":
                path = (csv_paths or {}).get(sym)
                if not path:
                    raise RuntimeError("مسیر CSV داده نشد")
                cs, meta = load_csv_symbol(sym, path, csv_native_tf, tf, progress=progress)
            elif source == "json":
                path = _json_path(data_dir, sym, tf)
                if not os.path.exists(path):
                    raise RuntimeError(f"JSON پیدا نشد: {path} (یک‌بار با --source bybit دانلود کنید)")
                with open(path, encoding="utf-8") as f:
                    payload = json.load(f)
                cs = candles_from_json(payload)
                meta = dict(payload.get("meta") or {}, from_cache=True)
                if progress:
                    print(f"    ↺ JSON: {os.path.basename(path)} ({len(cs)} کندل)")
            else:
                cs, meta = fetch_or_load(sym, tf, days, data_dir, base_url,
                                         refresh=refresh, progress=progress)
        except Exception as e:                                  # noqa: BLE001
            msg = f"{sym}: {e}"
            errors.append(msg)
            if progress:
                print(f"    ❌ {msg}")
            # خطای شبکه برای همه تکرار می‌شود ⇒ ادامه بی‌فایده است
            if stop_on_network_error and "شبکه" in str(e):
                errors.append("توقف: خطای شبکه")
                break
            continue

        if not cs:
            errors.append(f"{sym}: دادهٔ خالی")
            continue

        layers = build_layers(cs, tf, tf_filter, tf_bias, bias_enabled=True)
        coverage[sym] = {
            "n_trigger": len(cs),
            "years": round(len(cs) * tf_to_minutes(tf) / (365 * 1440), 2),
            "start": time.strftime("%Y-%m-%d", time.gmtime(cs[0].open_time_ms / 1000)),
            "end": time.strftime("%Y-%m-%d", time.gmtime(cs[-1].open_time_ms / 1000)),
            "from_cache": meta.get("from_cache", False),
            "fingerprint": data_fingerprint(cs),
            "source": ("CSV محلی" if source == "csv"
                       else "کش JSON" if meta.get("from_cache")
                       else "دانلود تازه"),
        }
        per_symbol[sym] = {}
        for vid, label, over in variants:
            try:
                m = run_variant(cfg, layers, over)
                m["label"] = label
                per_symbol[sym][vid] = m
                if progress:
                    print(f"    {vid:9s} n={m['n']:4d} PF={(m['profit_factor'] or 0):5.3f} "
                          f"exp={m['expectancy']:+7.2f}$ ret={m['return_pct']:+7.1f}%")
            except Exception as e:                              # noqa: BLE001
                errors.append(f"{sym}/{vid}: {e}")
                if progress:
                    print(f"    ❌ {vid}: {e}")

    agg = aggregate(per_symbol, vids)
    rankings = sorted([(v, a) for v, a in agg.items() if a.get("ok")],
                      key=lambda kv: -(kv[1]["median_expectancy"] or -1e9))
    winner = rankings[0][0] if rankings else None
    survived = [v for v, a in agg.items() if a.get("survived")]

    return {
        "version": VERSION,
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "settings": {
            "symbols": list(symbols), "days": days, "tf_trigger": tf,
            "tf_filter": tf_filter, "tf_bias": tf_bias,
            "fee_bps": cfg.fee_bps, "slippage_pct": cfg.slippage_pct,
            "risk_per_trade_pct": cfg.risk_per_trade_pct,
            "max_concurrent": cfg.max_concurrent,
            "initial_equity": cfg.initial_equity,
            "base_url": base_url, "source": source,
        },
        "gate": GATE,
        "coverage": coverage,
        "variants": [{"id": v, "label": l} for v, l, _ in variants],
        "per_symbol": per_symbol,
        "aggregate": agg,
        "rankings": [{"variant": v, "median_expectancy": a["median_expectancy"]}
                     for v, a in rankings],
        "winner": winner,
        "survived": survived,
        "errors": errors,
    }


# ----------------------------------------------------------------------------
# گزارش فارسی
# ----------------------------------------------------------------------------
def _f(x, d: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+,.{d}f}" if isinstance(x, float) else str(x)


def render_report(res: dict) -> str:
    L: List[str] = []
    w = L.append
    st = res["settings"]
    agg = res["aggregate"]
    cov = res["coverage"]

    w("# گزارش اسکن خودکار چندنمادی\n")
    w(f"*ساخته‌شده: {res['generated_at']} · نسخهٔ اسکنر {res['version']} · "
      f"زمان اجرا {res['elapsed_s']} ثانیه*\n")
    w(f"- نمادها: **{len(cov)}** · تایم‌فریم تریگر: `{st['tf_trigger']}` / "
      f"فیلتر: `{st['tf_filter']}` · بازه: {st['days']} روز")
    w(f"- هزینه: {st['fee_bps']} bps + {st['slippage_pct']}% اسلیپیج هر طرف · "
      f"ریسک {st['risk_per_trade_pct']}% · حداکثر {st['max_concurrent']} پوزیشن هم‌زمان\n")

    # ── ۱) حکم ────────────────────────────────────────────────────────────
    w("## ۱) حکم\n")
    if res["survived"]:
        w(f"✅ نسخه‌های زیر از دروازهٔ پذیرش عبور کردند: "
          f"**{', '.join(res['survived'])}**\n")
    else:
        w("❌ **هیچ نسخه‌ای از دروازهٔ پذیرش عبور نکرد.**\n")
    if res["winner"]:
        a = agg[res["winner"]]
        w(f"بهترین نسخه بر اساس میانهٔ expectancy: "
          f"**`{res['winner']}`** با "
          f"{_f(a['median_expectancy'])}$ (میانهٔ PF {a['median_pf']}) روی "
          f"{a['n_symbols']} نماد و {a['total_trades']} معامله.\n")
        w("قاعدهٔ پذیرش (از پیش تعیین‌شده): "
          f"حداقل {GATE['min_symbols']} نماد · "
          f"PF>1 در ≥{GATE['min_profitable_symbols_pct']}٪ نمادها · "
          f"سال مثبت در ≥{GATE['min_positive_years_pct']}٪ · "
          f"میانهٔ PF ≥ {GATE['min_median_pf']} · "
          f"p ≤ {GATE['min_sign_test_p']} در برابر پایه.\n")

    # ── ۲) جدول نسخه‌ها ───────────────────────────────────────────────────
    w("## ۲) مقایسهٔ نسخه‌ها (همه روی همان تایم‌فریم و همان نمادها)\n")
    w("| نسخه | نماد | معاملات | میانهٔ PF | میانهٔ expectancy | نماد PF>1 | سال مثبت | "
      "P در برابر پایه | حکم |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for v in res["variants"]:
        vid, label = v["id"], v["label"]
        a = agg.get(vid) or {}
        if not a.get("ok"):
            continue
        sgn = a.get("sign_vs_base")
        p_txt = "—" if not sgn else f"{sgn['p_value']} ({sgn['wins']}/{sgn['of']})"
        w(f"| `{vid}` | {a['n_symbols']} | {a['total_trades']} | {a['median_pf']} | "
          f"{_f(a['median_expectancy'])}$ | {a['profitable_symbols']}/"
          f"{a['profitable_symbols_pct']}٪ | {a['positive_years']}/"
          f"{a['years_n']} ({a['positive_years_pct']}٪) | {p_txt} | "
          f"{'✅' if a['survived'] else '❌'} |")
    w("")
    w("> «P در برابر پایه» = آزمون علامت: آیا این نسخه در اکثر نمادها از نسخهٔ پایه "
      "بهتر بود؟ عدد کوچک یعنی برتری سیستماتیک، نه شانسی.\n")

    # ── ۳) جدول نماد‌به‌نماد برای بهترین نسخه ─────────────────────────────
    vid = res["winner"]
    if vid:
        w(f"## ۳) جزئیات نماد‌به‌نماد — نسخهٔ `{vid}`\n")
        w("| نماد | پوشش | معاملات | PF | expectancy | بازده٪ | افت٪ | سال‌های مثبت |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|")
        for sym, d in res["per_symbol"].items():
            m = d.get(vid)
            if not m:
                continue
            c = cov.get(sym, {})
            w(f"| {sym} | {c.get('years', 0)} سال | {m['n']} | "
              f"{m['profit_factor'] if m['profit_factor'] is not None else '—'} | "
              f"{_f(m['expectancy'])}$ | {_f(m['return_pct'])}% | "
              f"{_f(m['max_drawdown_pct'])}% | {m['positive_years']}/{m['years_n']} |")
        w("")

        # ── ۴) سال‌به‌سال (مهم‌ترین نمودار برای تشخیص رژیم) ────────────────
        w(f"## ۴) سال‌به‌سال — نسخهٔ `{vid}` (PnL دلاری)\n")
        years = sorted({y for d in res["per_symbol"].values()
                        for y in (d.get(vid, {}).get("per_year") or {})})
        if years:
            w("| نماد | " + " | ".join(years) + " |")
            w("|---|" + "---:|" * len(years))
            for sym, d in res["per_symbol"].items():
                m = d.get(vid)
                if not m:
                    continue
                cells = [f"{_f((m['per_year'].get(y) or {}).get('pnl'))}" for y in years]
                w(f"| {sym} | " + " | ".join(cells) + " |")
            w("")
            w("> اگر یک نسخه فقط در سال‌های صعودی سود بدهد و در بقیه ضرر، این "
              "«استراتژی» نیست؛ «شرط‌گذاری روی رژیم» است.\n")

    # ── ۵) پوشش داده ─────────────────────────────────────────────────────
    w("## ۵) پوشش داده\n")
    w("| نماد | کندل | سال | از | تا | منبع |")
    w("|---|---:|---:|---|---|---|")
    for sym, c in cov.items():
        w(f"| {sym} | {c['n_trigger']} | {c['years']} | {c['start']} | {c['end']} | "
          f"{c.get('source', '—')} |")
    w("")

    # ── ۶) محدودیت‌ها ────────────────────────────────────────────────────
    w("## ۶) محدودیت‌ها (که خودمان اعلام می‌کنیم)\n")
    w("- **Survivorship bias**: فهرست نمادها از میان نمادهای *امروز زنده* انتخاب شده؛ "
      "نمادهایی که حذف شده‌اند (و بازنده بودند) در نمونه نیستند.")
    w(f"- همهٔ نمادها تاریخ یکسان ندارند؛ پوشش در جدول ۵ آمده است. نمادهای جوان‌تر "
      f"وزن کمتری دارند ولی در شمارش «سال مثبت» حضور دارند.")
    w("- فهرست نمادها ثابت است و با نتایج تغییر داده نشده — تغییری هم داده نشود، "
      "وگرنه دقیقاً همان انتخابی می‌شود که می‌خواستیم از آن پرهیز کنیم.")
    w("- این ابزار PAPER است: هیچ سفارشی به صرافی فرستاده نمی‌شود و اعداد سود واقعی نیستند.\n")
    w("---\n_آزمون دادهٔ تاریخی، توصیهٔ معاملاتی نیست._")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def autoscan_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .config import load_config

    p = argparse.ArgumentParser(
        prog="mtflab autoscan",
        description="اسکن خودکار چندنمادی: دانلود + تحلیل + گزارش")
    p.add_argument("--symbols", nargs="+", default=None,
                   help="نمادها (پیش‌فرض: ۲۰ نماد نقدشونده)")
    p.add_argument("--days", type=int, default=1460,
                   help="بازهٔ تاریخی به روز (پیش‌فرض ۱۴۶۰ ≈ ۴ سال)")
    p.add_argument("--tf", default="4h", help="تایم‌فریم تریگر (پیش‌فرض 4h)")
    p.add_argument("--data-dir", default="data", help="پوشهٔ داده")
    p.add_argument("--refresh", action="store_true", help="نادیده گرفتن کش")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--tag", default="", help="پسوند نام فایل‌ها")
    p.add_argument("--source", choices=["bybit", "json", "csv"], default="bybit",
                   help="bybit=دانلود | json=فقط کش JSON | csv=فایل‌های محلی")
    p.add_argument("--csv", action="append", default=[],
                   help="در حالت csv: --csv SYMBOL=path.csv (قابل تکرار)")
    p.add_argument("--csv-native-tf", default="1h",
                   help="تایم‌فریم فایل‌های CSV (پیش‌فرض 1h)")
    p.add_argument("--probe-only", action="store_true",
                   help="فقط بررسی دسترسی شبکه و خروج")
    known, rest = p.parse_known_args(argv if argv is not None else None)

    if known.probe_only:
        try:
            url = pick_base_url()
            print(f"✅ شبکه سالم است: {url}")
            return 0
        except RuntimeError as e:
            print(f"❌ {e}")
            return 1

    csv_paths: Dict[str, str] = {}
    for item in known.csv:
        if "=" not in item:
            print(f"❌ فرمت درست: --csv SYMBOL=path.csv (دریافت‌شده: {item})")
            return 2
        sym, path = item.split("=", 1)
        csv_paths[sym.strip().upper()] = path.strip()

    # کانفیگ فقط «حامل» هزینه/ریسک است؛ داده از منبع این دستور می‌آید.
    # برای عبور از اعتبارسنجی، یک --csv ساختگی می‌دهیم (هرگز خوانده نمی‌شود).
    fake_csv = next(iter(csv_paths.values()), "") or os.path.join(
        known.data_dir, "json", "_placeholder.json")
    cfg = load_config(list(rest) + ["--data", "csv", "--csv", fake_csv])
    cfg.verbose = False
    cfg.forensics = False
    if known.symbols:
        symbols = known.symbols
    elif csv_paths:
        symbols = list(csv_paths)
    elif known.source == "json":
        # حالت بازاجرا: هر نمادی که در کش موجود است به‌کار می‌رود
        symbols = discover_cached_symbols(known.data_dir, known.tf)
        if not symbols:
            print(f"❌ در {known.data_dir}/json هیچ کش {known.tf} پیدا نشد.")
            print("   یک‌بار با --source bybit دانلود کنید.")
            return 2
        print(f"📂 {len(symbols)} نماد از کش پیدا شد: {' '.join(symbols)}")
    else:
        symbols = list(DEFAULT_SYMBOLS)

    print("=" * 70)
    print(f"🔎 اسکن خودکار — {len(symbols)} نماد · تایم‌فریم {known.tf} · "
          f"{known.days} روز · منبع {known.source}")
    print("=" * 70)

    try:
        res = autoscan(cfg, symbols, known.days, known.tf, known.data_dir,
                       refresh=known.refresh, source=known.source,
                       csv_paths=csv_paths, csv_native_tf=known.csv_native_tf)
    except RuntimeError as e:
        print(f"\n❌ قطع شد: {e}")
        print("   راه‌حل: اتصال را عوض کنید (Wi-Fi/داده) یا از VPN استفاده کنید.")
        return 2

    os.makedirs(known.out_dir, exist_ok=True)
    tag = f"_{known.tag}" if known.tag else ""
    md_path = os.path.join(known.out_dir, f"auto_scan{tag}.md")
    json_path = os.path.join(known.out_dir, f"auto_scan{tag}.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_report(res))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)

    # ── خلاصهٔ روی صفحه ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊 خلاصه")
    for v in res["variants"]:
        a = res["aggregate"].get(v["id"]) or {}
        if not a.get("ok"):
            continue
        mark = "✅" if a["survived"] else "❌"
        print(f"  {mark} {v['id']:9s} نماد={a['n_symbols']:2d} "
              f"معامله={a['total_trades']:4d} میانهٔPF={a['median_pf']:<6} "
              f"میانهٔexp={a['median_expectancy']:+7.2f}$ "
              f"PF>1={a['profitable_symbols_pct']:5.1f}% "
              f"سال+={a['positive_years_pct']:5.1f}%")
    if res["errors"]:
        print(f"\n  ⚠️ {len(res['errors'])} خطا (جزئیات در گزارش)")
    print(f"\n📄 گزارش : {md_path}")
    print(f"🗂 بستهٔ داده: {json_path}")
    print("=" * 70)
    print("👉 همین دو فایل را برای بازبینی بفرستید.")
    return 0
