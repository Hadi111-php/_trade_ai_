"""تست‌های `--lang` سراسری.

**باگ واقعی روی گوشی:** `run-auto.sh` روی Termux خودش `--lang en` را به همهٔ
دستورها اضافه می‌کند. `health`/`control` را قبلاً درست کردم، ولی `pack` و `gate`
و `ops` هنوز نمی‌شناختند و کاربر موقع `bash run-auto.sh --zip` این را دید:
`mtflab pack: error: unrecognized arguments: --lang en`.

حالا در `__main__` یک فیلتر سراسری هست: دستورهایی که خودشان `--lang` دارند
دست‌نخورده می‌مانند، بقیه پرچم را دور می‌ریزند.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab.__main__ import main, strip_lang_args                  # noqa: E402


def test_strip_removes_both_forms():
    assert strip_lang_args("pack", ["--lang", "en", "--no-copy"]) == ["--no-copy"]
    assert strip_lang_args("gate", ["--lang=en", "x.json"]) == ["x.json"]
    assert strip_lang_args("ops", ["--status", "--lang", "fa"]) == ["--status"]
    # مقدار بعد از --lang نباید بماند
    assert strip_lang_args("pack", ["a", "--lang", "en", "b"]) == ["a", "b"]


def test_commands_that_know_lang_are_untouched():
    assert strip_lang_args("autoscan", ["--lang", "en"]) == ["--lang", "en"]
    assert strip_lang_args("control", ["--lang=en"]) == ["--lang=en"]
    assert strip_lang_args("health", ["--lang", "fa"]) == ["--lang", "fa"]


def test_pack_runs_with_lang_flag():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with tempfile.TemporaryDirectory() as td:
        assert main(["pack", "--root", root, "--out-dir", td,
                     "--no-copy", "--lang", "en"]) == 0
        assert any(n.endswith(".zip") for n in os.listdir(td))


def test_ops_status_runs_with_lang_flag():
    with tempfile.TemporaryDirectory() as td:
        assert main(["ops", "--data-dir", td, "--status", "--lang", "en"]) == 0


def test_gate_runs_with_lang_flag():
    rep = {"gate": {"min_symbols": 8, "min_profitable_symbols_pct": 60.0,
                    "min_positive_years_pct": 60.0, "min_median_pf": 1.05,
                    "min_sign_test_p": 0.1, "min_trades": 100},
           "settings": {"symbols": ["A"], "days": 365},
           "aggregate": {"trend": {"n_symbols": 1, "total_trades": 10, "median_pf": 1.2,
                                   "median_expectancy": 1.0, "profitable_symbols_pct": 100.0,
                                   "positive_years_pct": 100.0, "sign_vs_base": None,
                                   "checks": {"symbols": False, "trades": False,
                                              "profitable_symbols": True,
                                              "positive_years": True, "median_pf": True,
                                              "significance": False},
                                   "survived": False}}}
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "auto_scan_x.json")
        json.dump(rep, open(p, "w", encoding="utf-8"))
        rc = main(["gate", "--lang", "en", p])
        assert rc == 1                    # FAIL واقعی، نه «گزارش پیدا نشد» (۲)
