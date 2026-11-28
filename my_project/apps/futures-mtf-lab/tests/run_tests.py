#!/usr/bin/env python3
"""تست‌رانر بدون وابستگی (جایگزین pytest در محیط‌های سبک).

استفاده:
    python3 tests/run_tests.py            # همهٔ تست‌ها
    python3 tests/run_tests.py alignment  # فقط فایل‌های شامل این کلیدواژه

اگر pytest نصب باشد، همان تست‌ها با `pytest tests/` هم کار می‌کنند
(توابع ساده با assert هستند و هیچ fixture خاصی لازم ندارند).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _load_module(path: str):
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    files = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py")
                   and (not argv or any(a in f for a in argv)))
    total = passed = failed = 0
    failures = []
    t0 = time.time()
    for fn in files:
        mod = _load_module(os.path.join(HERE, fn))
        tests = [k for k in dir(mod) if k.startswith("test_") and callable(getattr(mod, k))]
        print(f"\n── {fn} ({len(tests)} تست)")
        for tname in sorted(tests):
            total += 1
            try:
                getattr(mod, tname)()
                passed += 1
                print(f"   ✅ {tname}")
            except Exception as e:                      # noqa: BLE001
                failed += 1
                failures.append((fn, tname, e, traceback.format_exc()))
                print(f"   ❌ {tname}: {e}")

    print("\n" + "=" * 66)
    print(f"نتیجه: {passed}/{total} پاس · {failed} شکست · {time.time()-t0:.1f}s")
    if failures:
        print("\nجزئیات شکست‌ها:")
        for fn, tname, e, tb in failures:
            print(f"\n--- {fn}::{tname}\n{tb}")
    print("=" * 66)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
