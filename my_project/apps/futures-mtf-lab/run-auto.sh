#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# اسکن خودکار چندنمادی — اجرای یک‌مرحله‌ای روی Termux / هر لینوکس
# =============================================================================
# کاری که می‌کند:
#   ۱) دادهٔ تاریخی ~۲۰ نماد را از Bybit می‌گیرد (عمومی، بدون کلید)
#   ۲) در JSON ذخیره می‌کند (قابل ادامه بعد از قطعی)
#   ۳) پنج نسخهٔ استراتژی را روی همه اجرا می‌کند
#   ۴) گزارش فارسی + بستهٔ JSON می‌سازد
#
# استفاده:
#   bash run-auto.sh                 # پیش‌فرض: ۲۰ نماد، ۵ سال، 4h
#   bash run-auto.sh --days 730      # فقط ۲ سال (سریع‌تر)
#   bash run-auto.sh --symbols BTCUSDT ETHUSDT SOLUSDT
#   bash run-auto.sh --source json   # فقط تحلیل مجدد روی دادهٔ ذخیره‌شده
# =============================================================================
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$HERE" || exit 1

# ── رنگ‌ها (اگر پشتیبانی نشد، بی‌اثر) ────────────────────────────────────────
if [ -t 1 ]; then
  G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
else
  G=''; R=''; Y=''; B=''; N=''
fi
say()  { printf "%b%s%b\n" "${1:-}" "${2:-}" "$N"; }
ok()   { say "$G" "✅ $*"; }
warn() { say "$Y" "⚠️  $*"; }
err()  { say "$R" "❌ $*"; }

# ── --offline: اجرا روی دادهٔ همراهِ خود پروژه، بدون اینترنت ─────────────────
OFFLINE=0
_ARGS=()
for a in "$@"; do
  if [ "$a" = "--offline" ]; then OFFLINE=1; else _ARGS+=("$a"); fi
done
set -- ${_ARGS[@]+"${_ARGS[@]}"}
CSS_ARGS=()
if [ "$OFFLINE" = "1" ]; then
  BDATA="../futures-scalp-lab/data"
  for pair in "BTCUSDT:btcusdt_1h_bybit.csv" "ETHUSDT:ethusdt_1h_bybit.csv"; do
    sym="${pair%%:*}"; file="${pair#*:}"
    [ -f "$BDATA/$file" ] && CSS_ARGS+=(--csv "$sym=$BDATA/$file")
  done
  if [ ${#CSS_ARGS[@]} -eq 0 ]; then
    echo "❌ --offline: فایل دادهٔ همراه پروژه پیدا نشد ($BDATA)"
    exit 2
  fi
  set -- "$@" --source csv --csv-native-tf 1h "${CSS_ARGS[@]}"
fi

say "$B" "════════════════════════════════════════════════════════════"
say "$B" "  Futures MTF Lab — اسکن خودکار چندنمادی"
say "$B" "════════════════════════════════════════════════════════════"

# ── ۰) پیش‌نیازها ────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 نصب نیست."
  say "" "روی Termux اجرا کنید:"
  say "" "    pkg update && pkg install python -y"
  exit 1
fi
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "?")
ok "python3 پیدا شد (نسخه $PYV) — هیچ بستهٔ بیرونی لازم نیست"

# جلوگیری از خواب گوشی در طول دانلود (اگر Termux:API نصب باشد)
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock 2>/dev/null && ok "قفل بیداری فعال شد (گوشی نمی‌خوابد)"
fi

mkdir -p data/json results

# ── ۱) بررسی دسترسی شبکه ────────────────────────────────────────────────────
# منبع را از آرگومان‌ها بخوان (json/csv → بررسی شبکه لازم نیست)
SRC="bybit"
prev=""
for a in "$@"; do
  if [ "$prev" = "--source" ]; then SRC="$a"; fi
  case "$a" in
    --source=*) SRC="${a#--source=}" ;;
  esac
  prev="$a"
done
SRC="bybit"
prev=""
for a in "$@"; do
  [ "$prev" = "--source" ] && SRC="$a"
  case "$a" in --source=*) SRC="${a#--source=}";; esac
  prev="$a"
done
say "" "📦 منبع داده: $SRC"

if [ "$SRC" = "bybit" ]; then
  say "" "🌐 بررسی دسترسی به Bybit …"
  if ! python3 -m mtflab autoscan --probe-only; then
    err "به Bybit دسترسی نیست (فیلتر شبکه یا قطعی اینترنت)."
    say "" "  گزینه‌ها:"
    say "" "   ۰) اجرای آفلاین روی دادهٔ همراه پروژه (۲ نماد، ۵ سال):"
    say "" "        bash run-auto.sh --offline"
    say "" "   ۱) VPN/پروکسی را روشن کنید و دوباره اجرا کنید"
    say "" "   ۲) اگر قبلاً داده گرفته‌اید:  bash run-auto.sh --source json"
    exit 2
  fi
fi

# ── ۲) اجرا ─────────────────────────────────────────────────────────────────
STAMP=$(date +%Y%m%d-%H%M 2>/dev/null || echo manual)
# اگر کاربر خودش --tag داده، همان برنده است (وگرنه نام فایل‌ها ناهماهنگ می‌شود)
USER_TAG=""
prev=""
for a in "$@"; do
  [ "$prev" = "--tag" ] && USER_TAG="$a"
  case "$a" in --tag=*) USER_TAG="${a#--tag=}";; esac
  prev="$a"
done
TAG="${USER_TAG:-$STAMP}"
LOG="results/auto_scan_${TAG}.log"
say "" "▶️  شروع اسکن — گزارش زنده در: $LOG"
say "" ""

set -o pipefail 2>/dev/null || true
python3 -m mtflab autoscan --tag "$TAG" "$@" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]:-0}

say ""
if [ "$STATUS" -ne 0 ]; then
  err "اجرا با خطا تمام شد (کد $STATUS). لاگ: $LOG"
  say "" "  اگر وسط کار قطع شد، دوباره همین دستور را بزنید:"
  say "" "  داده‌های دانلودشده ذخیره شده‌اند و ادامه می‌دهد."
  exit "$STATUS"
fi

# ── ۳) فایل‌های خروجی ───────────────────────────────────────────────────────
MD="results/auto_scan_${TAG}.md"
JS="results/auto_scan_${TAG}.json"

say "$G" "════════════════════════════════════════════════════════════"
ok "تمام شد"
say "$G" "════════════════════════════════════════════════════════════"
echo
say "" "📄 گزارش خوانا : $MD"
say "" "🗂 بستهٔ داده  : $JS"
say "" "📜 لاگ اجرا    : $LOG"
echo
if [ "$SRC" != "csv" ]; then
  NJ=$(ls -1 data/json/*.json 2>/dev/null | wc -l | tr -d ' ')
  say "" "💾 فایل‌های دادهٔ ذخیره‌شده: $NJ فایل در data/json/"
  DU=$(du -sh data/json 2>/dev/null | cut -f1)
  [ -n "${DU:-}" ] && say "" "   حجم: $DU"
fi

# ── ۴) بسته‌بندی برای ارسال ─────────────────────────────────────────────────
ZIP="results/auto_scan_${TAG}.zip"
if [ -f "$MD" ] && [ -f "$JS" ]; then
  if command -v zip >/dev/null 2>&1; then
    zip -q -j "$ZIP" "$MD" "$JS" && ok "بستهٔ فشرده ساخته شد: $ZIP"
  else
    warn "zip نصب نیست (اختیاری): pkg install zip"
  fi
else
  err "فایل خروجی پیدا نشد — لاگ را ببینید: $LOG"
fi

echo
say "$Y" "👉 مرحلهٔ بعد: فایل گزارش (md) و بستهٔ داده (json) را بفرستید."
say "$Y" "   همین دو فایل برای بازبینی کامل کافی است."
echo
say "" "برای تحلیل مجدد بدون دانلود دوباره:"
say "" "    bash run-auto.sh --source json --tag rerun"

if command -v termux-wake-unlock >/dev/null 2>&1; then
  termux-wake-unlock 2>/dev/null
fi
