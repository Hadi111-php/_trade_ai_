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
#   bash run-auto.sh --archive        # شناسنامهٔ داده (بدون شبکه)
#   bash run-auto.sh --data-index     # فهرست داده‌ها (بدون شبکه)
#   bash run-auto.sh --sweep --tf 4h  # حساسیت به هزینه/اجرا (بدون شبکه)
#   bash run-auto.sh --exec-scan      # مدیریت خروج ۱۵دقیقه‌ای (بدون شبکه)
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

# ── زبان: روی Termux خط فارسی در ترمینال برعکس و جدا نمایش داده می‌شود ───────
LANG_EN=0
[ "${TERMUX_VERSION:-}" != "" ] && LANG_EN=1
_prev=""
for a in "$@"; do
  case "$a" in
    --lang=en*|--lang=EN*) LANG_EN=1 ;;
    --lang=fa*) LANG_EN=0 ;;
  esac
  # حالت «--lang fa» (دو آرگومان جدا)
  if [ "$_prev" = "--lang" ]; then
    case "$a" in en*) LANG_EN=1 ;; fa*) LANG_EN=0 ;; esac
  fi
  _prev="$a"
done
# fa→en پیام دوزبانه: msg "فارسی" "English"
msg() { if [ "$LANG_EN" = "1" ]; then printf '%s' "${2:-}"; else printf '%s' "${1:-}"; fi; }
has_lang_flag=0
for a in "$@"; do case "$a" in --lang|--lang=*) has_lang_flag=1;; esac; done
if [ "$LANG_EN" = "1" ] && [ "$has_lang_flag" = "0" ]; then set -- "$@" --lang en; fi
ok()   { say "$G" "✅ $*"; }
warn() { say "$Y" "⚠️  $*"; }
err()  { say "$R" "❌ $*"; }

# ── ابزارهای جانبی که «اسکن» نیستند ────────────────────────────────────────
# چرا اینجا هم هست: اگر کاربر از پوشهٔ اپ اجرا کند (نه ریشهٔ مخزن)، باید همان
# رفتار را بگیرد. قبلاً --archive بی‌صدا به یک اسکن کامل ۴ ساعته تبدیل می‌شد.
for a in "$@"; do
  case "$a" in
    --archive)
      _TAG=""; _prev=""
      for b in "$@"; do
        [ "$_prev" = "--tag" ] && _TAG="$b"
        case "$b" in --tag=*) _TAG="${b#--tag=}";; esac
        _prev="$b"
      done
      if [ -n "$_TAG" ]; then
        python3 -m mtflab archive --out-dir data_archive --tag "$_TAG"
      else
        python3 -m mtflab archive --out-dir data_archive
      fi
      _RC=$?
      # خروجی مستقیم چاپ شد؛ اگر خطا داد، همان‌جا بمانِ (بدون کپی الکی)
      [ "$_RC" -ne 0 ] && exit "$_RC"
      # کپی به پوشهٔ Download گوشی (مثل بقیهٔ خروجی‌ها) تا پیدا کردنش ساده باشد
      _DEST=""
      for cand in "$HOME/storage/downloads" "/sdcard/Download"; do
        [ -d "$cand" ] && _DEST="$cand" && break
      done
      if [ -n "$_DEST" ]; then
        for f in data_archive/data_digest_*.json data_archive/data_digest_*.md; do
          [ -f "$f" ] && cp -f "$f" "$_DEST/" 2>/dev/null
        done
        echo ""
        echo "✅ copied to the phone Download folder: $_DEST"
        echo "   pick it in your file manager / chat app"
      else
        echo ""
        echo "⚠️  storage access not set up. run once:  termux-setup-storage"
        echo "   or copy manually from: $(pwd)/data_archive/"
      fi
      exit 0
      ;;
    --data-index)
      _L="--lang en"; _D=""
      for b in "$@"; do
        case "$b" in --lang=fa|--fa) _L="--lang fa";; --deep) _D="--deep";; esac
      done
      exec python3 -m mtflab data-index --reindex $_L $_D
      ;;
    --exec-scan)
      _EX=()
      for b in "$@"; do
        [ "$b" = "--exec-scan" ] && continue
        _EX+=("$b")
      done
      _HAS_LANG=0
      for b in "${_EX[@]+"${_EX[@]}"}"; do case "$b" in --lang*) _HAS_LANG=1;; esac; done
      if [ "$_HAS_LANG" = "0" ]; then
        if [ "$LANG_EN" = "1" ]; then _EX+=("--lang" "en"); else _EX+=("--lang" "fa"); fi
      fi
      _HAS_OUT=0
      for b in "${_EX[@]+"${_EX[@]}"}"; do case "$b" in --out-dir*) _HAS_OUT=1;; esac; done
      if [ "$_HAS_OUT" = "0" ]; then
        python3 -m mtflab exec-scan --out-dir results "${_EX[@]+"${_EX[@]}"}"
      else
        python3 -m mtflab exec-scan "${_EX[@]+"${_EX[@]}"}"
      fi
      exit $?
      ;;
    --sweep)
      # تحلیل هزینه روی دادهٔ ذخیره‌شده — بدون شبکه.
      # کپی به Download **داخل خودِ پایتون** انجام می‌شود (mtflab.sweep.deliver)،
      # چون آنجا مسیر واقعی فایل‌ها معلوم است. اینجا فقط اجرا می‌کنیم.
      _SW=()
      for b in "$@"; do
        [ "$b" = "--sweep" ] && continue
        _SW+=("$b")
      done
      _HAS_LANG=0
      for b in "${_SW[@]+"${_SW[@]}"}"; do case "$b" in --lang*) _HAS_LANG=1;; esac; done
      if [ "$_HAS_LANG" = "0" ]; then
        if [ "$LANG_EN" = "1" ]; then _SW+=("--lang" "en"); else _SW+=("--lang" "fa"); fi
      fi
      _HAS_OUT=0
      for b in "${_SW[@]+"${_SW[@]}"}"; do case "$b" in --out-dir*) _HAS_OUT=1;; esac; done
      if [ "$_HAS_OUT" = "0" ]; then
        python3 -m mtflab sweep --out-dir results "${_SW[@]+"${_SW[@]}"}"
      else
        python3 -m mtflab sweep "${_SW[@]+"${_SW[@]}"}"
      fi
      exit $?
      ;;
  esac
done

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

# ── --files: خروجی‌های آخر را نشان بده و (روی گوشی) کپی کن ──────────────────
for a in "$@"; do
  if [ "$a" = "--files" ]; then
    LATEST_MD=$(ls -1t results/auto_scan_*.md 2>/dev/null | head -1)
    if [ -z "$LATEST_MD" ]; then
      err "$(msg "هنوز هیچ خروجی‌ای ساخته نشده." "no output yet.")"
      say "" "    bash run-auto.sh --offline"
      exit 1
    fi
    TAGF=$(basename "$LATEST_MD" .md | sed 's/^auto_scan_//')
    F1="results/auto_scan_${TAGF}.md"
    F2="results/auto_scan_${TAGF}.json"
    say "" "$(msg "📂 مسیر کامل :" "📂 full path :") $(pwd)/results"
    for f in "$F1" "$F2" "results/auto_scan_${TAGF}.zip"; do
      [ -f "$f" ] && say "" "   • $(pwd)/$f"
    done
    for cand in "$HOME/storage/downloads" "/sdcard/Download"; do
      if [ -d "$cand" ]; then
        for f in "$F1" "$F2" "results/auto_scan_${TAGF}.zip"; do
          [ -f "$f" ] && cp -f "$f" "$cand/" 2>/dev/null
        done
        ok "$(msg "کپی شد به: $cand/" "copied to: $cand/")"
        break
      fi
    done
    if [ -n "${PREFIX:-}" ] && [ ! -d "$HOME/storage/downloads" ] && [ ! -d /sdcard/Download ]; then
      warn "$(msg "دسترسی به حافظه نبود. یک‌بار بزنید:" "no storage access. run once:") termux-setup-storage"
    fi
    exit 0
  fi
done

say "$B" "════════════════════════════════════════════════════════════"
say "$B" "  $(msg "Futures MTF Lab — اسکن خودکار چندنمادی" "Futures MTF Lab — multi-symbol autoscan")"
# نسخهٔ کد روی صفحه: اگر کلون عقب باشد، همین‌جا دیده می‌شود (نه بعد از ۴ ساعت)
_VER="$(git -C "$HERE" log --oneline -1 2>/dev/null | cut -c1-7)"
[ -n "$_VER" ] && say "$B" "  code: $_VER"
say "$B" "════════════════════════════════════════════════════════════"

# ── ۰) پیش‌نیازها ────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  err "$(msg "python3 نصب نیست." "python3 is not installed.")"
  say "" "$(msg "روی Termux اجرا کنید:" "On Termux run:")"
  say "" "    pkg update && pkg install python -y"
  exit 1
fi
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "?")
ok "$(msg "python3 پیدا شد (نسخه $PYV) — هیچ بستهٔ بیرونی لازم نیست" "python3 $PYV found — no external packages needed")"

# جلوگیری از خواب گوشی در طول دانلود (اگر Termux:API نصب باشد)
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock 2>/dev/null && ok "$(msg "قفل بیداری فعال شد (گوشی نمی‌خوابد)" "wake-lock on (phone will not sleep)")"
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
say "" "$(msg "📦 منبع داده: $SRC" "📦 data source: $SRC")"

if [ "$SRC" = "bybit" ]; then
  say "" "$(msg "🌐 بررسی دسترسی به Bybit …" "🌐 checking Bybit access ...")"
  PROBE_LANG=""
  [ "$LANG_EN" = "1" ] && PROBE_LANG="--lang en"
  if ! python3 -m mtflab autoscan --probe-only $PROBE_LANG; then
    err "$(msg "به Bybit دسترسی نیست (فیلتر شبکه یا قطعی اینترنت)." "Bybit is not reachable (network filter or offline).")"
    say "" "$(msg "  گزینه‌ها:" "  options:")"
    say "" "$(msg "   ۰) اجرای آفلاین روی دادهٔ همراه پروژه (۲ نماد، ۵ سال):" "   0) run offline on bundled data (2 symbols, 5 years):")"
    say "" "        bash run-auto.sh --offline"
    say "" "$(msg "   ۱) VPN/پروکسی را روشن کنید و دوباره اجرا کنید" "   1) turn on VPN/proxy and retry")"
    say "" "$(msg "   ۲) اگر قبلاً داده گرفته‌اید:  bash run-auto.sh --source json" "   2) if you already have cached data:  bash run-auto.sh --source json")"
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
say "" "$(msg "▶️  شروع اسکن — گزارش زنده در: $LOG" "▶️  scanning — live log: $LOG")"
say "" ""

set -o pipefail 2>/dev/null || true
python3 -m mtflab autoscan --tag "$TAG" "$@" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]:-0}

say ""
if [ "$STATUS" -ne 0 ]; then
  err "$(msg "اجرا با خطا تمام شد (کد $STATUS). لاگ: $LOG" "run failed (code $STATUS). log: $LOG")"
  say "" "$(msg "  اگر وسط کار قطع شد، دوباره همین دستور را بزنید:" "  if it was interrupted, just run the same command again:")"
  say "" "$(msg "  داده‌های دانلودشده ذخیره شده‌اند و ادامه می‌دهد." "  downloaded data is cached and it will resume.")"
  exit "$STATUS"
fi

# ── ۳) فایل‌های خروجی ───────────────────────────────────────────────────────
MD="results/auto_scan_${TAG}.md"
JS="results/auto_scan_${TAG}.json"

say "$G" "════════════════════════════════════════════════════════════"
ok "$(msg "تمام شد" "DONE")"
say "$G" "════════════════════════════════════════════════════════════"
echo
say "" "$(msg "📄 گزارش خوانا : $MD" "📄 report   : $MD")"
say "" "$(msg "🗂 بستهٔ داده  : $JS" "🗂 data pack: $JS")"
say "" "$(msg "📜 لاگ اجرا    : $LOG" "📜 log      : $LOG")"
echo
if [ "$SRC" != "csv" ]; then
  NJ=$(ls -1 data/json/*.json 2>/dev/null | wc -l | tr -d ' ')
  say "" "$(msg "💾 فایل‌های دادهٔ ذخیره‌شده: $NJ فایل در data/json/" "💾 cached data files: $NJ in data/json/")"
  DU=$(du -sh data/json 2>/dev/null | cut -f1)
  [ -n "${DU:-}" ] && say "" "$(msg "   حجم: $DU" "   size: $DU")"
fi

# ── ۴) بسته‌بندی برای ارسال ─────────────────────────────────────────────────
ZIP="results/auto_scan_${TAG}.zip"
if [ -f "$MD" ] && [ -f "$JS" ]; then
  if command -v zip >/dev/null 2>&1; then
    zip -q -j "$ZIP" "$MD" "$JS" && ok "$(msg "بستهٔ فشرده ساخته شد: $ZIP" "zip created: $ZIP")"
  else
    warn "$(msg "zip نصب نیست (اختیاری): pkg install zip" "zip not installed (optional): pkg install zip")"
  fi
else
  err "$(msg "فایل خروجی پیدا نشد — لاگ را ببینید: $LOG" "output file missing — see log: $LOG")"
fi

echo
# ── ۴.۵) بیرون آوردن فایل از گوشی ────────────────────────────────────────────
ABS_DIR="$(pwd)/results"
say "" "$(msg "📂 مسیر کامل خروجی‌ها:" "📂 full output path:")"
say "" "   $ABS_DIR"
COPIED=""
if [ -n "${PREFIX:-}" ] || [ -d "$HOME/storage/downloads" ] || [ -d /sdcard/Download ]; then
  DEST=""
  for cand in "$HOME/storage/downloads" "/sdcard/Download"; do
    [ -d "$cand" ] && { DEST="$cand"; break; }
  done
  if [ -n "$DEST" ]; then
    COPIED=1
    for f in "$MD" "$JS"; do
      [ -f "$f" ] && cp -f "$f" "$DEST/" 2>/dev/null
    done
    [ -f "$ZIP" ] && cp -f "$ZIP" "$DEST/" 2>/dev/null
    say "$G" "$(msg "✅ کپی شد به پوشهٔ Download گوشی:" "✅ copied to the phone Download folder:")"
    say "$G" "   $DEST/"
    say "" "$(msg "   از همان‌جا در فایل‌منیجر یا چت انتخاب و ارسال کنید." "   pick them there in your file manager / chat app.")"
  fi
fi
if [ -z "$COPIED" ] && [ -n "${PREFIX:-}" ]; then
  warn "$(msg "دسترسی به حافظهٔ مشترک نبود. یک‌بار این را بزنید و دوباره اجرا کنید:" "shared storage not accessible. run this once, then retry:")"
  say "" "    termux-setup-storage"
fi

echo
say "$Y" "$(msg "👉 مرحلهٔ بعد: فایل گزارش (md) و بستهٔ داده (json) را بفرستید." "👉 NEXT: send back the report (md) and the data pack (json).")"
say "$Y" "$(msg "   همین دو فایل برای بازبینی کامل کافی است." "   these two files are all that is needed.")"
echo
say "" "$(msg "برای تحلیل مجدد بدون دانلود دوباره:" "re-analyse without downloading again:")"
say "" "    bash run-auto.sh --source json --tag rerun"

if command -v termux-wake-unlock >/dev/null 2>&1; then
  termux-wake-unlock 2>/dev/null
fi
