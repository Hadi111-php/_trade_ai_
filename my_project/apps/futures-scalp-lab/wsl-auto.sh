#!/usr/bin/env bash
# wsl-auto.sh — دانلود/آپدیت خودکار + اجرای AUTO (PAPER) در WSL/لینوکس
# استفاده: bash wsl-auto.sh            (خودش کلون/آپدیت می‌کند و اجرا می‌کند)
#          bash wsl-auto.sh /path/to/Main_Arena_conn   (از مسیر موجود، بدون دانلود)
set -u
BR="arena/01a0255b-main-arena-conn"
URL="https://github.com/HaadiTaba111/Main_Arena_conn.git"
DEST="${1:-$HOME/Main_Arena_conn}"

echo "== Scalp Lab WSL bootstrap =="

# ۱) پایتون
if ! command -v python3 >/dev/null 2>&1; then
    echo "[i] python3 نیست؛ سعی در نصب..."
    if command -v sudo >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y python3 || true
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -y && apt-get install -y python3 || true
    fi
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 پیدا نشد. دستی نصب کن: sudo apt install python3"
    exit 1
fi
echo "[ok] python3: $(python3 --version 2>&1)"

# ۲) دانلود/آپدیت (اگر مسیر موجود داده نشد و پوشه نبود، کلون کن)
LAB="$DEST/apps/futures-scalp-lab"
if [ ! -d "$LAB" ]; then
    echo "[i] کلون ریپو (بار اول ممکن است اعتبار GitHub بخواهد)..."
    git clone --branch "$BR" "$URL" "$DEST" || {
        echo "[ERROR] کلون نشد. اگر ریپو private است یک‌بار دستی کلون کن یا مسیر ویندوز را بده:"
        echo "        bash wsl-auto.sh /mnt/c/.../Main_Arena_conn"
        exit 1
    }
else
    echo "[i] آپدیت از گیت‌هاب..."
    ( cd "$DEST" && git fetch origin "$BR" && git checkout "$BR" && \
      git pull --ff-only origin "$BR" ) || echo "[warn] آپدیت نشد؛ از نسخهٔ محلی استفاده می‌شود."
fi

# ۳) اجرا
cd "$LAB" || exit 1
echo "== اجرای AUTO (PAPER) — بدون سفارش واقعی =="
exec python3 -m scalplab auto --data binance --symbol BTCUSDT --tf 1m --interval 5 \
    --forever --trade --size 100 --leverage 3 --max-concurrent 4 --cb-losses 2 \
    --stop-pct 0.005 --trail-pct 0.003
