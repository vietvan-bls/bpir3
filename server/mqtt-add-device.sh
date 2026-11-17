#!/bin/sh
# Tạo tài khoản MQTT riêng cho một thiết bị (thường là thiết bị ở xa, vào qua Tailscale Funnel).
# Thiết bị chỉ được đọc/ghi topic iot/<tên>/# (quy tắc "pattern" trong /etc/mosquitto/acl).
# Chạy trên board:  sh mqtt-add-device.sh <tên>        tạo / đặt lại mật khẩu
#                   sh mqtt-add-device.sh <tên> --delete  xóa tài khoản
set -e
NAME="$1"
case "$NAME" in
	""|iot|server|*[!a-z0-9-]*) echo "Dùng: $0 <tên: chữ thường, số, dấu -> [--delete]"; exit 1 ;;
esac
if [ "$2" = "--delete" ]; then
	mosquitto_passwd -D /etc/mosquitto/passwd "$NAME"
	service mosquitto restart
	echo "Đã xóa tài khoản $NAME"
	exit 0
fi
P=$(python3 -c "import secrets;print(secrets.token_urlsafe(15))")
[ ${#P} -ge 16 ] || { echo "Không tạo được mật khẩu"; exit 1; }
mosquitto_passwd -b /etc/mosquitto/passwd "$NAME" "$P"
chmod 600 /etc/mosquitto/passwd
service mosquitto restart
HOST=$(tailscale status --json 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null || echo "<tên board>.ts.net")
cat <<EOT
Tài khoản MQTT cho thiết bị:
  Ở xa (Internet):   $HOST cổng 8443 (TLS)
  Trong mạng board:  192.168.2.1 cổng 1883
  User:     $NAME
  Mật khẩu: $P
  Topic:    iot/$NAME/...   (lệnh từ web: iot/$NAME/set)
EOT
