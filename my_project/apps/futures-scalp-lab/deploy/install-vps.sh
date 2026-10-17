#!/usr/bin/env bash
# نصب یک‌خطی روی VPS (اوبونتو): کلون/آپدیت + systemd + اجرا.
# استفاده: bash install-vps.sh
set -u
BR="arena/01a0255b-main-arena-conn"
URL="https://github.com/HaadiTaba111/Main_Arena_conn.git"
DEST="/opt/Main_Arena_conn"

command -v python3 >/dev/null 2>&1 || { sudo apt-get update -y && sudo apt-get install -y python3 git; }

if [ -d "$DEST/.git" ]; then
    echo "[i] آپدیت..."
    ( cd "$DEST" && git fetch origin "$BR" && git checkout "$BR" && git pull --ff-only origin "$BR" ) \
      || echo "[warn] آپدیت نشد؛ نسخهٔ محلی."
else
    echo "[i] کلون (اگر private بود، اعتبار GitHub خودت را در ترمینال بزن)..."
    sudo git clone --branch "$BR" "$URL" "$DEST" || { echo "[ERROR] کلون نشد."; exit 1; }
fi

# واحد systemd (اگر نبود کپی کن)
if [ -f "$DEST/apps/futures-scalp-lab/deploy/scalplab.service" ]; then
    sudo cp "$DEST/apps/futures-scalp-lab/deploy/scalplab.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now scalplab
    echo "[ok] سرویس فعال شد. وضعیت: systemctl status scalplab | لاگ: journalctl -u scalplab -f"
else
    echo "[warn] فایل service پیدا نشد."
fi
