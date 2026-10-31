#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# لانچر ریشهٔ پروژه — از هر جای مخزن اجرا می‌شود
# =============================================================================
#   bash run-auto.sh                       → اسکن ۲۰ نمادی (نیاز به اینترنت)
#   bash run-auto.sh --offline             → اجرا روی دادهٔ همراه پروژه (آفلاین)
#   bash run-auto.sh --probe-only          → فقط تشخیص شبکه
#   bash run-auto.sh --data-index          → فهرست دادهٔ ذخیره‌شده (بدون شبکه)
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
