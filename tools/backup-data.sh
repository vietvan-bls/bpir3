#!/bin/sh
# Sao lưu dữ liệu board (kho, IoT, cấu hình) → file MÃ HÓA trong data-backup/ (repo PUBLIC: không bao giờ commit bản thô).
#   Chạy trong container (cần SSH vào board, xem CLAUDE.md):  BPI_SSH=b tools/backup-data.sh
# Gồm: /mnt/data/kho (chụp SQLite nhất quán + backup hằng ngày), /mnt/data/iot (chụp SQLite + json),
#      cấu hình OpenWrt (sysupgrade -b: mạng, Wi-Fi, firewall, dropbear, tailscale…), /etc/bpi-*, /etc/mosquitto, /etc/openocd.
# Mã hóa: openssl AES-256-CBC + PBKDF2 (600k vòng). Mật khẩu nằm ở /root/.bpi-backup-pass trên board (chủ giữ thêm 1 bản).
# Giải mã:  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in FILE.enc -out data.tar.gz   (hỏi mật khẩu)
#           tar -xzf data.tar.gz   → kho/ iot/ etc/ config-sysupgrade.tar.gz (khôi phục: sysupgrade -r config-sysupgrade.tar.gz)
set -e
cd "$(dirname "$0")/.."
SSH=${BPI_SSH:-b}; OUT=data-backup; mkdir -p $OUT
F=$OUT/bpi-data-$(date +%Y%m%d-%H%M).tar.gz.enc
PASS=$($SSH 'cat /root/.bpi-backup-pass 2>/dev/null')
[ -n "$PASS" ] || { echo "Chưa có /root/.bpi-backup-pass trên board"; exit 1; }
$SSH 'set -e; T=$(mktemp -d); cd $T; mkdir -p kho iot etc
python3 - <<PY
import sqlite3
for src, dst in (("/mnt/data/kho/kho.db", "kho/kho.db"), ("/mnt/data/iot/iot.db", "iot/iot.db")):
    a = sqlite3.connect("file:" + src + "?mode=ro", uri=True); b = sqlite3.connect(dst); a.backup(b); b.close(); a.close()
PY
cp -r /mnt/data/kho/backup kho/ 2>/dev/null || true
cp /mnt/data/iot/*.json iot/ 2>/dev/null || true
cp -a /etc/bpi-* /etc/mosquitto /etc/openocd etc/ 2>/dev/null || true
sysupgrade -b config-sysupgrade.tar.gz >/dev/null 2>&1
tar -czf - kho iot etc config-sysupgrade.tar.gz; cd /; rm -rf $T' \
  | PASS="$PASS" openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass env:PASS -out "$F"
ls -la "$F"
# Kiểm tra giải mã được và đủ nội dung (không ghi bản thô ra đĩa)
PASS="$PASS" openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass env:PASS -in "$F" | tar -tzf - | sed 's#/.*##' | sort | uniq -c
