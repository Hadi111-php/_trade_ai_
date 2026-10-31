#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  Futures MTF Lab — اجرای سریع روی لینوکس / macOS / Termux  (PAPER فقط)
#  استفاده:  ./start-mtf.sh selftest | compare | serve | validate
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "❌ python3 پیدا نشد"; exit 1; }

case "${1:-help}" in
  selftest)  "$PY" -m mtflab selftest ;;
  compare)   "$PY" -m mtflab compare \
                --csv "../futures-scalp-lab/data/btcusdt_1h_lastyear.csv" \
                --out "results/dash_scenarios.html"
             echo; echo "✅ داشبورد: results/dash_scenarios.html" ;;
  serve)     "$PY" -m mtflab serve --dir results --port "${2:-8080}" ;;
  validate)  "$PY" -m mtflab validate --data bybit --symbol BTCUSDT \
                --tf-trigger 15m --tf-filter 1h --tf-bias 4h ;;
  *) cat <<'HELP'

 Futures MTF Lab — راهنما
 ────────────────────────────────────────────
  ./start-mtf.sh selftest    خودآزمایی (تست‌ها + ضد lookahead)
  ./start-mtf.sh compare     مقایسهٔ سناریوی قدیم و جدید + داشبورد
  ./start-mtf.sh serve [پورت]  سرو داشبورد (پیش‌فرض 8080)
  ./start-mtf.sh validate    اعتبارسنجی کامل روی دادهٔ 15m (نیاز به اینترنت)

  همهٔ گزینه‌ها:  python3 -m mtflab --help

HELP
  ;;
esac
