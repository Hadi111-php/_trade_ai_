"""نمونهٔ اجرای بستهٔ مستقل — بدون شبکه، با کندل مصنوعی."""
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
