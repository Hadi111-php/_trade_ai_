#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# لانچر ریشهٔ پروژه — از هر جای مخزن اجرا می‌شود
# =============================================================================
#   bash run-auto.sh                       → اسکن ۲۰ نمادی (نیاز به اینترنت)
#   bash run-auto.sh --offline             → اجرا روی دادهٔ همراه پروژه (آفلاین)
#   bash run-auto.sh --probe-only          → فقط تشخیص شبکه
#   bash run-auto.sh --data-index          → فهرست دادهٔ ذخیره‌شده (بدون شبکه)
#   bash run-auto.sh --archive [--tag X]   → شناسنامهٔ داده برای بایگانی در گیت
#   bash run-auto.sh --verify-archive      → مقایسهٔ دادهٔ فعلی با شناسنامهٔ مرجع
#   bash run-auto.sh --sweep [--tf 4h]     → حساسیت به هزینه (بدون دانلود)
#   bash run-auto.sh --exec-scan           → مدیریت خروج ۱۵دقیقه‌ای (بدون دانلود)
#   bash run-auto.sh --source json         → تحلیل مجدد روی دادهٔ ذخیره‌شده
#
# چرا این فایل هست: ابزار در my_project/apps/futures-mtf-lab است و اگر از ریشهٔ
# مخزن اجرا شود، پایتون ماژول mtflab را پیدا نمی‌کند. این لانچر خودش مسیر درست را
# انتخاب می‌کند تا لازم نباشد مسیر را حفظ کنید.
# =============================================================================
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
APP="$HERE/my_project/apps/futures-mtf-lab"

if [ ! -d "$APP" ]; then
  echo "❌ پوشهٔ اپ پیدا نشد: $APP"
  echo "   احتمالاً این کلون از شاخهٔ main است و اپ جدید در آن نیست."
  echo "   راه‌حل:"
  echo "     git fetch origin arena/444f3300-trade-ai --depth 1"
  echo "     git checkout -B arena/444f3300-trade-ai FETCH_HEAD"
  exit 2
fi

cd "$APP" || exit 2

# ── --status: بگو الان کجای تاریخچه هستیم و کد به‌روز است یا نه ─────────────
for a in "$@"; do
  if [ "$a" = "--status" ]; then
    echo "📁 اپ     : $APP"
    echo -n "🔖 کامیت : "; git -C "$HERE" log --oneline -1 2>/dev/null || echo "(بدون گیت)"
    echo -n "🌿 شاخه  : "; git -C "$HERE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?"
    echo -n "🐍 پایتون: "; python3 -V 2>&1 || echo "نصب نیست"
    echo -n "🧪 mtflab: "; (cd "$APP" && python3 -c "import mtflab,mtflab.autoscan as a;print('ok · scanner v'+a.VERSION)" 2>&1) || true
    if grep -q "def diagnose_network" "$APP/mtflab/autoscan.py" 2>/dev/null; then
      echo "🩺 پروب  : نسخهٔ جدید (kline را هم تست می‌کند) ✅"
    else
      echo "🩺 پروب  : نسخهٔ قدیمی ❌ → این را بزنید:"
      echo "           git fetch origin arena/444f3300-trade-ai --depth 1"
      echo "           git checkout -B arena/444f3300-trade-ai FETCH_HEAD"
    fi
    # آیا کلون عقب است؟ (مهم‌ترین علت «دستور کار نکرد»)
    echo -n "🔄 به‌روز؟  : "
    if git -C "$HERE" fetch -q --depth 1 origin arena/444f3300-trade-ai 2>/dev/null; then
      _HEAD="$(git -C "$HERE" rev-parse HEAD 2>/dev/null)"
      _NEW="$(git -C "$HERE" rev-parse FETCH_HEAD 2>/dev/null)"
      if [ "$_HEAD" = "$_NEW" ]; then
        echo "بله ✅  (همان آخرین نسخه)"
      else
        echo "خیر ❌  کد جدیدتر موجود است:"
        git -C "$HERE" log --oneline HEAD..FETCH_HEAD 2>/dev/null | head -6 | sed 's/^/             /'
        echo "           برای به‌روزرسانی:"
        echo "             git checkout -B arena/444f3300-trade-ai FETCH_HEAD"
      fi
    else
      echo "(بدون شبکه — چک نشد)"
    fi
    exit 0
  fi
done

# روی Termux خط فارسی در ترمینال برعکس و جدا نمایش داده می‌شود،
# پس خروجی به‌صورت پیش‌فرض انگلیسی می‌شود (با --lang fa قابل تغییر است).
HAS_LANG=0
for a in "$@"; do case "$a" in --lang|--lang=*) HAS_LANG=1;; esac; done
if [ "${TERMUX_VERSION:-}" != "" ] && [ "$HAS_LANG" = "0" ]; then
  set -- "$@" --lang en
fi

# اگر --archive خواسته شد: شناسنامهٔ کوچک داده برای بایگانی در گیت (بدون شبکه)
for a in "$@"; do
  if [ "$a" = "--archive" ]; then
    TAG=""
    prev=""
    for b in "$@"; do
      [ "$prev" = "--tag" ] && TAG="$b"
      case "$b" in --tag=*) TAG="${b#--tag=}";; esac
      prev="$b"
    done
    # exec نمی‌کنیم تا مرحلهٔ «کپی به Download» هم اجرا شود
    if [ -n "$TAG" ]; then
      python3 -m mtflab archive --out-dir data_archive --tag "$TAG"
    else
      python3 -m mtflab archive --out-dir data_archive
    fi
    _RC=$?
    [ "$_RC" -ne 0 ] && exit "$_RC"
    _DEST=""
    for cand in "$HOME/storage/downloads" "/sdcard/Download"; do
      [ -d "$cand" ] && _DEST="$cand" && break
    done
    if [ -n "$_DEST" ]; then
      for f in "$APP"/data_archive/data_digest_*.json "$APP"/data_archive/data_digest_*.md; do
        [ -f "$f" ] && cp -f "$f" "$_DEST/" 2>/dev/null
      done
      echo ""
      echo "✅ copied to the phone Download folder: $_DEST"
      echo "   pick it in your file manager / chat app"
    fi
    exit 0
  fi
done

# اگر --sweep خواسته شد: کل کار را به لانچر خودِ اپ بسپار.
# چرا: یک‌بار اینجا مستقیم `python3 -m mtflab sweep` صدا زده شد و چون با `exec`
# بود، مرحلهٔ کپی به پوشهٔ Download گوشی اجرا نشد — فایل‌ها ساخته شدند ولی
# کاربر پیدایشان نکرد. کپی و پیام‌ها فقط در یک جا زندگی می‌کنند: لانچر اپ.
for a in "$@"; do
  if [ "$a" = "--sweep" ] || [ "$a" = "--exec-scan" ]; then
    exec bash "$APP/run-auto.sh" "$@"
  fi
done

# اگر --verify-archive خواسته شد: دادهٔ فعلی را با شناسنامهٔ مرجع مقایسه کن
for a in "$@"; do
  if [ "$a" = "--verify-archive" ]; then
    REF=""
    prev=""
    for b in "$@"; do
      [ "$prev" = "--against" ] && REF="$b"
      case "$b" in --against=*) REF="${b#--against=}";; esac
      prev="$b"
    done
    [ -z "$REF" ] && REF="$APP/results/data_digest_15m_20261031.json"
    exec python3 -m mtflab archive --out-dir data_archive --verify-against "$REF" --lang en
  fi
done

# اگر --data-index خواسته شد: فهرست بسته‌های دادهٔ ذخیره‌شده (بدون شبکه)
for a in "$@"; do
  if [ "$a" = "--data-index" ]; then
    LANG_ARG="--lang en"
    DEEP=""
    for b in "$@"; do
      case "$b" in
        --lang=fa|--fa) LANG_ARG="--lang fa" ;;
        --deep) DEEP="--deep" ;;
      esac
    done
    exec python3 -m mtflab data-index --reindex $LANG_ARG $DEEP
  fi
done

# اگر --probe-only خواسته شد، مستقیم به CLI پایتون بده (اسکریپت اصلی این را ندارد)
for a in "$@"; do
  if [ "$a" = "--probe-only" ]; then
    # همهٔ آرگومان‌ها پاس می‌شوند تا --lang هم از دست نرود
    exec python3 -m mtflab autoscan "$@"
  fi
done

exec bash "$APP/run-auto.sh" "$@"
