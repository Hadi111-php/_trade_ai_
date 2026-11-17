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
#   bash run-auto.sh --trade-lab      # آزمون قله/دره + استراحت بعد از سود
#   bash run-auto.sh --live           # اتوترید مجازی: رصد سیگنال‌ها روی کندل تازه
#   bash run-auto.sh --live --status  # فقط گزارش وضعیت (بدون گرفتن داده)
#   bash run-auto.sh --dash           # داشبورد کارگاه (وب) روی همین گوشی
#   bash run-auto.sh --doctor         # معاینهٔ نصب: پورت/داده/پوشه‌ها (بدون شبکه)
#   bash run-auto.sh --audit          # بازبینی سلامت معاملات (هر ضرر ≈۱R؟)
#   bash run-auto.sh --bundle         # ساخت بستهٔ مستقل موتور برای داشبورد دیگر
#   bash run-auto.sh --pump --download --days 365   # پامپ و دامپ: دانلود ۱۵m + اندازه‌گیری
#   bash run-auto.sh --pump                        # همان، روی دادهٔ کش‌شده (بدون شبکه)
#   bash run-auto.sh --hunt                        # چشم شکارچی: زمینهٔ سیگنال‌ها در برد/باخت
#   bash run-auto.sh --watch                       # شکار زنده: یک‌بار همهٔ نمادها (+بوق/اعلان)
#   bash run-auto.sh --watch-loop                  # همان، هر ۵ دقیقه تا Ctrl+C
#   bash run-auto.sh --exits                       # حسابرسی خروج: چقدر سود روی میز ماند
#   bash run-auto.sh --v10 --download --days 180   # V10 Pro (BB+RSI+حجم) روی دادهٔ واقعی
#   bash run-auto.sh --v10 --compare               # مقایسهٔ V10 با الگوهای MTF
#   bash run-auto.sh --patterns                    # کارنامهٔ الگوها: کدام سیگنال بابت کدام الگو
#   bash run-auto.sh --algorithms                  # کاتالوگ الگوریتم‌ها با فرمول و مقدار فعلی
#   bash run-auto.sh --health                      # سلامت سیستم: چرا سیگنالی نیست؟
#   bash run-auto.sh --control                     # گزارش کنترل: یک فایل برای فرستادن (چک‌لیست + هش)
#   bash run-auto.sh --evaluate                    # همهٔ گام‌ها با هم: پروب → سینک → بک‌فیل → سلامت → گزارش
#   bash run-auto.sh --update                      # به‌روزرسانی کد (بدون کلون تازه) + نمایش کد قبلی/جدید
#   bash run-auto.sh --evaluate --offline          # همان، بدون شبکه (روی کش موجود)
#   bash run-auto.sh --evaluate --days 400         # همان، ولی اول ۴۰۰ روز دادهٔ واقعی را دانلود کن
#   bash run-auto.sh --ops                         # مدیریت کلان: وضعیت داده/گزارش‌ها
#   bash run-auto.sh --ops --sync                  # به‌روزرسانی دادهٔ واقعی (ادغام با کش)
#   bash run-auto.sh --ops --download --days 365   # دانلود یک‌ساله از Bybit
#   bash run-auto.sh --ops --exitstyles            # آزمایش خروج از همین‌جا (گزارش مستقل)
#   bash run-auto.sh --exit-styles                 # همان آزمایش، خروجی مستقیم روی ترمینال
#   bash run-auto.sh --shadow                      # دفتر خبر: کارنامهٔ اعتبار منبع (بی‌اثر روی سیستم)
#   bash run-auto.sh --shadow --open BTCUSDT --side LONG --note "خبر"   # ثبت سیگنال خبری
#   bash run-auto.sh --brain          # آزمون «مغز دوم» روی دادهٔ ذخیره‌شده
#   bash run-auto.sh --brain-view     # ساخت/دیدن «چشم مغز» (دیدگاه هر نماد)
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
    --trade-lab)
      _TL=()
      for b in "$@"; do
        [ "$b" = "--trade-lab" ] && continue
        _TL+=("$b")
      done
      _HAS_LANG=0
      for b in "${_TL[@]+"${_TL[@]}"}"; do case "$b" in --lang*) _HAS_LANG=1;; esac; done
      if [ "$_HAS_LANG" = "0" ]; then
        if [ "$LANG_EN" = "1" ]; then _TL+=("--lang" "en"); else _TL+=("--lang" "fa"); fi
      fi
      _HAS_OUT=0
      for b in "${_TL[@]+"${_TL[@]}"}"; do case "$b" in --out-dir*) _HAS_OUT=1;; esac; done
      if [ "$_HAS_OUT" = "0" ]; then
        python3 -m mtflab trade-lab --out-dir results "${_TL[@]+"${_TL[@]}"}"
      else
        python3 -m mtflab trade-lab "${_TL[@]+"${_TL[@]}"}"
      fi
      exit $?
      ;;
    --brain-view|--view)
      _BV=()
      for b in "$@"; do
        case "$b" in --brain-view|--view) continue;; esac
        _BV+=("$b")
      done
      _HAS_LANG=0
      for b in "${_BV[@]+"${_BV[@]}"}"; do case "$b" in --lang*) _HAS_LANG=1;; esac; done
      if [ "$_HAS_LANG" = "0" ]; then
        if [ "$LANG_EN" = "1" ]; then _BV+=("--lang" "en"); else _BV+=("--lang" "fa"); fi
      fi
      _HAS_OUT=0
      for b in "${_BV[@]+"${_BV[@]}"}"; do case "$b" in --out-dir*) _HAS_OUT=1;; esac; done
      if [ "$_HAS_OUT" = "0" ]; then
        python3 -m mtflab view --out-dir results "${_BV[@]+"${_BV[@]}"}"
      else
        python3 -m mtflab view "${_BV[@]+"${_BV[@]}"}"
      fi
      exit $?
      ;;
    --brain|--model)
      _BR=()
      for b in "$@"; do
        case "$b" in --brain|--model) continue;; esac
        _BR+=("$b")
      done
      _HAS_LANG=0
      for b in "${_BR[@]+"${_BR[@]}"}"; do case "$b" in --lang*) _HAS_LANG=1;; esac; done
      if [ "$_HAS_LANG" = "0" ]; then
        if [ "$LANG_EN" = "1" ]; then _BR+=("--lang" "en"); else _BR+=("--lang" "fa"); fi
      fi
      _HAS_OUT=0
      for b in "${_BR[@]+"${_BR[@]}"}"; do case "$b" in --out-dir*) _HAS_OUT=1;; esac; done
      if [ "$_HAS_OUT" = "0" ]; then
        python3 -m mtflab brain --out-dir results "${_BR[@]+"${_BR[@]}"}"
      else
        python3 -m mtflab brain "${_BR[@]+"${_BR[@]}"}"
      fi
      exit $?
      ;;
    --watch|--radar)
      _WA=()
      for b in "$@"; do
        case "$b" in --watch|--radar) continue;; esac
        _WA+=("$b")
      done
      _OUT=0
      for b in "${_WA[@]+"${_WA[@]}"}"; do case "$b" in --out-dir*) _OUT=1;; esac; done
      if [ "$_OUT" = "0" ]; then _WA=(--out-dir results "${_WA[@]+"${_WA[@]}"}"); fi
      python3 -m mtflab watch --once --out-dir results "${_WA[@]+"${_WA[@]}"}"
      exit $?
      ;;
    --watch-loop)
      _WL=()
      for b in "$@"; do case "$b" in --watch-loop) continue;; esac; _WL+=("$b"); done
      python3 -m mtflab watch --out-dir results "${_WL[@]+"${_WL[@]}"}"
      exit $?
      ;;
    --v10|--v10pro)
      _V=()
      for b in "$@"; do
        case "$b" in --v10|--v10pro) continue;; esac
        _V+=("$b")
      done
      _OUT=0
      for b in "${_V[@]+"${_V[@]}"}"; do case "$b" in --out-dir*) _OUT=1;; esac; done
      if [ "$_OUT" = "0" ]; then _V=(--out-dir results "${_V[@]+"${_V[@]}"}"); fi
      python3 -m mtflab v10 "${_V[@]+"${_V[@]}"}"
      exit $?
      ;;
    --algorithms|--algos|--catalog)
      _A=()
      for b in "$@"; do
        case "$b" in --algorithms|--algos|--catalog) continue;; esac
        _A+=("$b")
      done
      _OUT=0
      for b in "${_A[@]+"${_A[@]}"}"; do case "$b" in --out-dir*) _OUT=1;; esac; done
      if [ "$_OUT" = "0" ]; then _A=(--out-dir results "${_A[@]+"${_A[@]}"}"); fi
      python3 -m mtflab algorithms "${_A[@]+"${_A[@]}"}"
      exit $?
      ;;
    --update|--upgrade)
      # به‌روزرسانی بدون کلون تازه: حلِ خطای «destination path 'lab' already exists»
      _REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
      if [ -z "$_REPO" ]; then
        echo "❌ این پوشه داخل یک مخزن git نیست."
        echo "   اگر با ZIP دانلود کرده‌اید، یک‌بار درست کلون کنید (راهنما: بخش ۴۰)."
        exit 2
      fi
      _FORCE=0
      for b in "$@"; do [ "$b" = "--force" ] && _FORCE=1; done
      _DIRTY="$(git -C "$_REPO" status --porcelain 2>/dev/null)"
      if [ -n "$_DIRTY" ] && [ "$_FORCE" = "0" ]; then
        echo "⚠️  فایل‌های ذخیره‌نشده دارند (به‌روزرسانی آن‌ها را پاک می‌کند):"
        printf '%s\n' "$_DIRTY" | head -5
        echo "   اگر خودت دستی عوض کرده‌ای: اول commit کن، یا با --force نادیده بگیر."
        exit 3
      fi
      _BR="$(git -C "$_REPO" rev-parse --abbrev-ref HEAD)"
      _OLD="$(git -C "$_REPO" rev-parse --short HEAD)"
      echo "شاخه: $_BR  ·  کد فعلی: $_OLD"
      echo "در حال گرفتن آخرین نسخه از GitHub…"
      if ! git -C "$_REPO" fetch origin "$_BR" --depth 1; then
        echo "❌ دریافت نشد (شبکه/VPN). چیزی عوض نشد."
        exit 1
      fi
      git -C "$_REPO" reset --hard FETCH_HEAD || exit 1
      _NEW="$(git -C "$_REPO" rev-parse --short HEAD)"
      echo "✅ کد: $_OLD → $_NEW"
      echo "   داده و ژورنال دست‌نخورده ماند (results/ و data/ در git نیستند)."
      echo "   بعدی: python3 -m mtflab selftest --quick   یا   bash run-auto.sh --evaluate"
      exit 0
      ;;
    --evaluate|--eval)
      # یک دستور برای «ارزیابی کامل + فایل گزارش»: پروب → سینک → بک‌فیل → سلامت → کنترل
      _DATA="data"; _TF="4h"; _OFF="0"; _SYMS=""; _DAYS=""
      _prev=""
      for b in "$@"; do
        case "$_prev" in
          --data-dir) _DATA="$b" ;;
          --tf) _TF="$b" ;;
          --symbols) _SYMS="$b" ;;
          --days) _DAYS="$b" ;;
        esac
        case "$b" in
          --offline) _OFF="1" ;;
          --days=*) _DAYS="${b#--days=}" ;;
        esac
        _prev="$b"
      done
      _S=()
      [ -n "$_SYMS" ] && _S=(--symbols "$_SYMS")
      echo "════════ ارزیابی کامل — داده: $_DATA · تایم‌فریم: $_TF ════════"
      if [ "$_OFF" = "1" ]; then
        echo "۱/۵ دسترسی به داده — رد شد (--offline)"
        echo "۲/۵ به‌روزرسانی داده — رد شد (--offline)"
      else
        echo "۱/۵ بررسی دسترسی به دادهٔ Bybit…"
        python3 -m mtflab ops --probe --data-dir "$_DATA" \
          || echo "⚠️ گام ۱ موفق نبود (شبکه/فیلتر IP) — ادامه می‌دهم با کش موجود"
        if [ -n "$_DAYS" ]; then
          echo "۲/۵ دانلود $_DAYS روز دادهٔ واقعی (اولین بار چند دقیقه طول می‌کشد)…"
          python3 -m mtflab ops --download --days "$_DAYS" --data-dir "$_DATA" "${_S[@]+"${_S[@]}"}" \
            || echo "⚠️ گام ۲ موفق نبود — ادامه می‌دهم با کش موجود"
        else
          echo "۲/۵ به‌روزرسانی داده (۳۰ روز، با ادغام)…"
          python3 -m mtflab ops --sync --sync-days 30 --data-dir "$_DATA" "${_S[@]+"${_S[@]}"}" \
            || echo "⚠️ گام ۲ موفق نبود — ادامه می‌دهم با کش موجود"
        fi
      fi
      echo "۳/۵ اتوترید مجازی تا آخرین کندل بسته (بک‌فیل ۴۰۰)…"
      if [ "$_OFF" = "1" ]; then
        python3 -m mtflab live --offline --backfill 400 --no-brain --data-dir "$_DATA" \
          --tf "$_TF" --lang en "${_S[@]+"${_S[@]}"}" || echo "⚠️ گام ۳ با خطا تمام شد"
      else
        python3 -m mtflab live --backfill 400 --no-brain --data-dir "$_DATA" \
          --tf "$_TF" --lang en "${_S[@]+"${_S[@]}"}" || echo "⚠️ گام ۳ با خطا تمام شد"
      fi
      echo "۴/۵ سلامت سیستم…"
      python3 -m mtflab health --data-dir "$_DATA" --tf "$_TF" --lang en
      echo "۵/۵ گزارش کنترل…"
      python3 -m mtflab control --data-dir "$_DATA" --tf "$_TF" "${_S[@]+"${_S[@]}"}"
      _RC=$?
      echo "════════ تمام شد — فایل گزارش را همان‌طور که هست بفرست ════════"
      exit $_RC
      ;;
    --control|--report)
      _C=()
      for b in "$@"; do
        case "$b" in --control|--report) continue;; esac
        _C+=("$b")
      done
      python3 -m mtflab control "${_C[@]+"${_C[@]}"}"
      exit $?
      ;;
    --health|--status)
      _H=()
      for b in "$@"; do
        case "$b" in --health|--status) continue;; esac
        _H+=("$b")
      done
      python3 -m mtflab health "${_H[@]+"${_H[@]}"}"
      exit $?
      ;;
    --ops|--manage)
      _O=()
      for b in "$@"; do
        case "$b" in --ops|--manage) continue;; esac
        _O+=("$b")
      done
      python3 -m mtflab ops "${_O[@]+"${_O[@]}"}"
      exit $?
      ;;
    --exit-styles|--stops)
      _E=()
      for b in "$@"; do
        case "$b" in --exit-styles|--exitstyles|--stops) continue;; esac
        _E+=("$b")
      done
      python3 -m mtflab exitstyles "${_E[@]+"${_E[@]}"}"
      exit $?
      ;;
    --shadow|--news)
      _S=()
      for b in "$@"; do
        case "$b" in --shadow|--news) continue;; esac
        _S+=("$b")
      done
      python3 -m mtflab shadow "${_S[@]+"${_S[@]}"}"
      exit $?
      ;;
    --patterns|--scorecard|--attribution)
      _P=()
      for b in "$@"; do
        case "$b" in --patterns|--scorecard|--attribution) continue;; esac
        _P+=("$b")
      done
      _OUT=0
      for b in "${_P[@]+"${_P[@]}"}"; do case "$b" in --out-dir*) _OUT=1;; esac; done
      if [ "$_OUT" = "0" ]; then _P=(--out-dir results "${_P[@]+"${_P[@]}"}"); fi
      python3 -m mtflab patterns "${_P[@]+"${_P[@]}"}"
      exit $?
      ;;
    --exits|--exit-audit)
      _EX=()
      for b in "$@"; do case "$b" in --exits|--exit-audit) continue;; esac; _EX+=("$b"); done
      python3 -m mtflab exits --journal results/live/journal.jsonl --out results/exits_fa.md "${_EX[@]+"${_EX[@]}"}"
      exit $?
      ;;
    --hunt|--hunter)
      _HU=()
      for b in "$@"; do
        case "$b" in --hunt|--hunter) continue;; esac
        _HU+=("$b")
      done
      python3 -m mtflab hunter --journal results/live/journal.jsonl --out results/hunter_fa.md "${_HU[@]+"${_HU[@]}"}"
      exit $?
      ;;
    --pump|--pumpdump|--dump)
      _PM=()
      for b in "$@"; do
        case "$b" in --pump|--pumpdump|--dump) continue;; esac
        _PM+=("$b")
      done
      _OUT=0
      for b in "${_PM[@]+"${_PM[@]}"}"; do case "$b" in --out-dir*) _OUT=1;; esac; done
      if [ "$_OUT" = "0" ]; then
        python3 -m mtflab pumpdump --out-dir results "${_PM[@]+"${_PM[@]}"}"
      else
        python3 -m mtflab pumpdump "${_PM[@]+"${_PM[@]}"}"
      fi
      exit $?
      ;;
    --audit)
      _AU=()
      for b in "$@"; do
        case "$b" in --audit) continue;; esac
        _AU+=("$b")
      done
      python3 -m mtflab audit --journal results/live/journal.jsonl "${_AU[@]+"${_AU[@]}"}"
      exit $?
      ;;
    --bundle)
      python3 -m mtflab bundle
      exit $?
      ;;
    --doctor|--check)
      _DR=()
      for b in "$@"; do
        case "$b" in --doctor|--check) continue;; esac
        _DR+=("$b")
      done
      python3 -m mtflab doctor "${_DR[@]+"${_DR[@]}"}"
      exit $?
      ;;
    --dash|--desk)
      _D=()
      for b in "$@"; do
        case "$b" in --dash|--desk) continue;; esac
        _D+=("$b")
      done
      python3 -m mtflab live --serve "${_D[@]+"${_D[@]}"}"
      exit $?
      ;;
    --live)
      _LV=()
      for b in "$@"; do
        [ "$b" = "--live" ] && continue
        _LV+=("$b")
      done
      _HAS_LANG=0
      for b in "${_LV[@]+"${_LV[@]}"}"; do case "$b" in --lang*) _HAS_LANG=1;; esac; done
      if [ "$_HAS_LANG" = "0" ]; then
        if [ "$LANG_EN" = "1" ]; then _LV+=("--lang" "en"); else _LV+=("--lang" "fa"); fi
      fi
      _HAS_OUT=0
      for b in "${_LV[@]+"${_LV[@]}"}"; do case "$b" in --out-dir*) _HAS_OUT=1;; esac; done
      if [ "$_HAS_OUT" = "0" ]; then
        python3 -m mtflab live --out-dir results "${_LV[@]+"${_LV[@]}"}"
      else
        python3 -m mtflab live "${_LV[@]+"${_LV[@]}"}"
      fi
      exit $?
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
