"""CLI: python -m scalplab [run] … | python -m scalplab selftest"""
from __future__ import annotations

import json
import sys

from .config import load_config
from .runner import run_lab


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "selftest":
        from .selftest import run_selftest
        return run_selftest()
    if argv and argv[0] == "auto":
        argv = argv[1:]
        from .auto import run_auto
        cfg = load_config(argv)
        return run_auto(cfg)
    if argv and argv[0] == "sweep":
        argv = argv[1:]
        from .sweep import run_sweep
        cfg = load_config(argv)
        run_sweep(cfg)
        return 0

    if argv and argv[0] == "trader":
        argv = argv[1:]
        from .trader_brain import load_trader_config, run_trader
        cfg = load_trader_config(argv)
        return run_trader(cfg)

    if argv and argv[0] == "dashboard":
        argv = argv[1:]
        from .dashboard import main as dash_main
        return dash_main(argv)

    cfg = load_config(argv)
    report = run_lab(cfg)

    print(f"\nrun_id={report['run_id']}  data={report['data_mode']}  "
          f"signals={report['total_signals']}")
    print(f"label: {report['label']}")
    print("ranking:", " > ".join(report["ranking_by_net_expectancy"]) or "—")
    for mid, m in report["pooled_metrics"].items():
        if m.get("n"):
            print(f"  {mid:18s} n={m['n']:4d} hit_net={m['hit_net']:.3f} "
                  f"net_bps={m['avg_net_bps']:+.2f} ci={m['hit_net_ci95']}")
    print("report:", report["files"]["signals"].replace("signals_", "report_")
          .replace(".jsonl", ".md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
