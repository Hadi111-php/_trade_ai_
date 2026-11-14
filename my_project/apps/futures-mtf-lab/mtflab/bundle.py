"""بستهٔ مستقل اتوترید — «فقط الگوریتم‌ها» در یک پوشهٔ قابل‌حمل.

**چرا:** کاربر می‌خواهد همین الگوها و مکانیزم رصد را به یک داشبورد دیگر بدهد،
بدون این‌که کل کارگاه (داشبورد، ژورنال، مغز، اسکنر) را با خودش ببرد.

**چه می‌کند:** فهرست ثابتی از ماژول‌های «موتور» را کپی می‌کند در
`exports/autotrade_core/` و کنارشان یک `manifest.json` (هش sha256 هر فایل)،
یک `README_FA.md` و یک `demo.py` می‌گذارد. آن پوشه **بدون** این مخزن هم کار
می‌کند: فقط `python3` لازم است.

**چه نمی‌کند:** هیچ فایلی را بازنویسی/ویرایش نمی‌کند و هیچ کد تازه‌ای تولید
نمی‌کند — همان فایل‌های واقعیِ موتور کپی می‌شوند تا «نسخهٔ دوم» به‌وجود نیاید.
اگر یک روز فایل‌های مبدأ تغییر کنند، `--check` (و تست
`test_committed_bundle_is_in_sync`) می‌گوید بسته کهنه است.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from typing import Dict, List

#: ترتیب مهم نیست؛ فقط این‌ها لازم‌اند و هیچ‌کدام داشبورد/شبکه/ژورنال را نمی‌کشند.
CORE_FILES: List[str] = [
    "__init__.py",
    "config.py",
    "data.py",
    "indicators.py",
    "alignment.py",
    "fees.py",
    "signals.py",
    "logger.py",
    "engine.py",
    "knobs.py",
    "rules.py",
    "stats.py",
    "patterns.py",
    "autotrade_api.py",
]

BUNDLE_NAME = "autotrade_core"
DEFAULT_OUT = os.path.join("exports", BUNDLE_NAME)

README = """# autotrade_core — موتور اتوترید، مستقل

این پوشه یک **بستهٔ کامل** است: الگوها + موتور بک‌تست + آمار، بدون داشبورد،
بدون شبکه، بدون ژورنال. فقط کتابخانهٔ استاندارد پایتون (۳.۸+).

## نصب

پوشهٔ `{name}` را کنار پروژهٔ خودت بگذار و والدش را به مسیر پایتون اضافه کن:

```python
import sys; sys.path.insert(0, "/path/to")   # پوشه‌ای که {name} داخلش است
import {name}.autotrade_api as api
```

## سه تابعی که یک داشبورد لازم دارد

```python
api.schema()        # الگوها + ۲۷ کلید تنظیمات + پیش‌فرض هر الگو
api.run(data)       # بک‌تست: سنجه‌ها، OOS، به‌تفکیک قاعده/الگو/نماد + معاملات
api.signals_now(data)   # سیگنال روی کندل بستهٔ آخر (همان تصمیم موتور)
```

`data` یک دیکشنری است: `{{"BTCUSDT": [[ts, o, h, l, c, v], ...], ...}}`
(دیکشنری با کلیدهای `ts/open/high/low/close/volume` هم پذیرفته می‌شود).

## نمونهٔ کامل

```bash
python3 demo.py          # با کندل مصنوعی، فقط برای دیدن ساختار خروجی
```

## چه چیزی در خروجی `run` هست

| کلید | معنی |
|---|---|
| `metrics` | n، نرخ برد، expectancy (R)، سود، PF، حداکثر افت |
| `in_sample` / `out_of_sample` | همان سنجه‌ها برای ۳۰٪ اول و آخر بازهٔ زمانی |
| `by_rule` | هر قاعدهٔ بست: چند بار، چقدر، و آیا برای **کم‌کردن ضرر** بود |
| `by_pattern` | breakout / pullback |
| `by_symbol` | به تفکیک نماد |
| `trades` | هر معامله: زمان، الگو، قاعده، R، سود، تعداد کندل |
| `open_at_end` | پوزیشن‌هایی که آخر داده باز مانده‌اند (در سنجه‌ها نیستند) |

## مرزها (مهم)

- خروجی **توصیهٔ معامله نیست**. عدد بدون هزینه، بدون بیرون‌نمونه و بدون
  مقایسه با خط پایه معنا ندارد.
- `signals_now` پیش‌بینی نیست؛ تصمیم موتور روی کندل بستهٔ آخر است و با بسته
  شدن کندل بعدی می‌تواند عوض شود.
- هیچ سفارشی به صرافی فرستاده نمی‌شود؛ این بسته فقط محاسبه می‌کند.

_ساخته‌شده از مخزن `_trade_ai_` · نسخهٔ بسته: {version} · {stamp}_
"""

DEMO = '''"""نمونهٔ اجرای بستهٔ مستقل — بدون شبکه، با کندل مصنوعی."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from autotrade_core import autotrade_api as api          # noqa: E402
from autotrade_core.data import synthetic_candles        # noqa: E402


def main() -> int:
    print("api:", api.API_VERSION)
    sc = api.schema()
    print("variants:", [v["id"] for v in sc["variants"]])
    print("knobs:", len(sc["knobs"]))

    data = {"BTCUSDT": synthetic_candles("4h", 1200, seed=7),
            "ETHUSDT": synthetic_candles("4h", 1200, seed=9)}
    rep = api.run(data, variant="trend", overrides={"trail_atr_mult": 4.0})
    m = rep["metrics"]
    print(f"trades={m['n']} expectancy={m['expectancy_r']}R "
          f"oos_n={rep['out_of_sample']['n']} open_at_end={m['open_at_end']}")
    print("by_rule:", {k: v["n"] for k, v in rep["by_rule"].items()})
    print("signals_now:", [(s["symbol"], bool(s.get("signal")))
                           for s in api.signals_now(data)])
    print("json bytes:", len(api.to_json(rep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _src_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def build(out_dir: str = DEFAULT_OUT, clean: bool = True) -> Dict[str, object]:
    """بسته را می‌سازد (یا بازسازی می‌کند) و manifest برمی‌گرداند."""
    src = _src_dir()
    out_dir = os.path.abspath(out_dir)
    if clean and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    files: Dict[str, str] = {}
    for name in CORE_FILES:
        s = os.path.join(src, name)
        if not os.path.exists(s):
            raise FileNotFoundError(f"فایل موتور پیدا نشد: {s}")
        shutil.copyfile(s, os.path.join(out_dir, name))
        files[name] = _sha256(os.path.join(out_dir, name))

    version = "?"
    init = os.path.join(src, "__init__.py")
    if os.path.exists(init):
        for line in open(init, encoding="utf-8"):
            if line.startswith("__version__"):
                version = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

    manifest = {
        "name": BUNDLE_NAME,
        "version": version,
        "built_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "files": files,
        "api": "autotrade_api.API_VERSION",
        "note": "کپیِ عین فایل‌های موتور — بدون بازنویسی. با --check کهنه‌بودن معلوم می‌شود.",
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "README_FA.md"), "w", encoding="utf-8") as f:
        f.write(README.format(name=BUNDLE_NAME, version=version,
                              stamp=manifest["built_utc"]))
    with open(os.path.join(out_dir, "demo.py"), "w", encoding="utf-8") as f:
        f.write(DEMO)
    return manifest


def check(out_dir: str = DEFAULT_OUT) -> Dict[str, object]:
    """آیا بستهٔ موجود با فایل‌های فعلی موتور یکی است؟"""
    src = _src_dir()
    out_dir = os.path.abspath(out_dir)
    mp = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(mp):
        return {"ok": False, "reason": f"manifest نیست: {mp}", "stale": [], "missing": []}
    with open(mp, encoding="utf-8") as f:
        man = json.load(f)
    stale, missing, tampered = [], [], []
    for name in CORE_FILES:
        s, d = os.path.join(src, name), os.path.join(out_dir, name)
        if not os.path.exists(d):
            missing.append(name)
            continue
        want = man.get("files", {}).get(name)
        src_h, out_h = _sha256(s), _sha256(d)
        if out_h != src_h:
            stale.append(name)           # بسته همان کد فعلی نیست (کهنه یا ویرایش‌شده)
        elif out_h != want:
            tampered.append(name)        # فایل درست است ولی manifest با آن نمی‌خواند
    return {"ok": not stale and not missing and not tampered,
            "stale": stale, "missing": missing, "tampered": tampered,
            "built_utc": man.get("built_utc"), "out_dir": out_dir}


def bundle_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab bundle",
        description="ساخت بستهٔ مستقل موتور اتوترید (برای داشبوردهای دیگر)")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help=f"پوشهٔ خروجی (پیش‌فرض: {DEFAULT_OUT})")
    p.add_argument("--check", action="store_true",
                   help="فقط بررسی کن که بستهٔ موجود با کد فعلی یکی است یا نه")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)

    if a.check:
        rep = check(a.out)
        if rep["ok"]:
            print(("✅ بسته به‌روز است: " if a.lang == "fa" else "✅ bundle up to date: ")
                  + str(rep["out_dir"]))
            return 0
        print(("❌ بسته کهنه است. بساز: python3 -m mtflab bundle"
               if a.lang == "fa" else "❌ bundle is stale. rebuild it:"))
        for n in rep.get("stale", []):
            print(f"   • کهنه: {n}")
        for n in rep.get("missing", []):
            print(f"   • نیست: {n}")
        for n in rep.get("tampered", []):
            print(f"   • دست‌کاری‌شده: {n}")
        return 1

    man = build(a.out, clean=True)
    out = os.path.abspath(a.out)
    print(("✅ بستهٔ مستقل ساخته شد: " if a.lang == "fa" else "✅ bundle built: ") + out)
    print(f"   {len(man['files'])} فایل · نسخهٔ {man['version']} · {man['built_utc']}")
    print("   README_FA.md و demo.py کنارش هستند.")
    print(("   اجرا: " if a.lang == "fa" else "   try: ") + f"python3 {os.path.join(out, 'demo.py')}")
    return 0
