#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# تحلیل هم‌حرکتی ارزها — آیا رابطهٔ پنهان و پایدار بین ارزها وجود دارد؟
# =============================================================================
# این اسکریپت به اینترنت نیاز ندارد؛ روی همان داده‌ای کار می‌کند که
# run-auto.sh قبلاً دانلود کرده (data/json/*.json).
#
#   bash run-comove.sh              # ۳ گروه، ۱۰۰۰ جایگشت
#   bash run-comove.sh --k 4        # ۴ گروه
#   bash run-comove.sh --lang fa    # خروجی فارسی
# =============================================================================
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
APP="$HERE/my_project/apps/futures-mtf-lab"
[ -d "$APP" ] || APP="$HERE"
cd "$APP" || { echo "app dir not found"; exit 2; }

# روی Termux خط فارسی برعکس رندر می‌شود ⇒ انگلیسی
HAS_LANG=0
_prev=""
for a in "$@"; do
  case "$a" in --lang=*|--lang) HAS_LANG=1 ;; esac
  [ "$_prev" = "--lang" ] && HAS_LANG=1
  _prev="$a"
done
if [ "${TERMUX_VERSION:-}" != "" ] && [ "$HAS_LANG" = "0" ]; then
  set -- "$@" --lang en
fi

N=$(ls -1 data/json/*.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$N" -lt 3 ]; then
  echo "❌ Only $N symbol file(s) in data/json/ — need at least 3."
  echo "   Run this first:  bash run-auto.sh"
  exit 2
fi

echo "🧩 co-movement on $N cached symbol files"
python3 -m mtflab comove "$@"
STATUS=$?

MD=$(ls -1t results/comove*.md 2>/dev/null | head -1)
JS=$(ls -1t results/comove*.json 2>/dev/null | head -1)
echo
if [ -n "${MD:-}" ]; then echo "📄 full path: $(pwd)/$MD"; fi

# کپی به Download گوشی
for cand in "$HOME/storage/downloads" "/sdcard/Download"; do
  if [ -d "$cand" ]; then
    [ -n "${MD:-}" ] && cp -f "$MD" "$cand/" 2>/dev/null
    [ -n "${JS:-}" ] && cp -f "$JS" "$cand/" 2>/dev/null
    echo "✅ copied to: $cand/"
    break
  fi
done

exit $STATUS
