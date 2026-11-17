#!/bin/sh
# Cài Mosquitto (MQTT broker) trên board. Chạy trên board: sh mqtt-setup.sh
# - Cổng 1883, bắt buộc đăng nhập, chỉ mở trong vùng LAN (firewall mặc định chặn WAN).
# - Tài khoản: "iot" (thiết bị, chỉ topic iot/#) và "server" (backend, mọi topic).
# - Mật khẩu của backend lưu ở /etc/bpi-mqtt.json (600). Chạy lại với --reset để đổi mật khẩu.
set -e
cd "$(dirname "$0")"
apk add mosquitto-ssl mosquitto-client-ssl python3-paho-mqtt
mkdir -p /mnt/data/mosquitto && chown mosquitto:mosquitto /mnt/data/mosquitto
cp mosquitto/mosquitto.conf /etc/mosquitto/mosquitto.conf
cp mosquitto/acl /etc/mosquitto/acl
if [ ! -f /etc/bpi-mqtt.json ] || [ "$1" = "--reset" ]; then
	gen() { python3 -c "import secrets;print(secrets.token_urlsafe(15))"; }
	P_IOT=$(gen); P_SRV=$(gen)
	[ ${#P_IOT} -ge 16 ] && [ ${#P_SRV} -ge 16 ] || { echo "Không tạo được mật khẩu"; exit 1; }
	rm -f /etc/mosquitto/passwd; touch /etc/mosquitto/passwd; chmod 600 /etc/mosquitto/passwd
	mosquitto_passwd -b /etc/mosquitto/passwd iot "$P_IOT"
	mosquitto_passwd -b /etc/mosquitto/passwd server "$P_SRV"
	printf '{"host": "127.0.0.1", "port": 1883, "user": "server", "password": "%s"}\n' "$P_SRV" > /etc/bpi-mqtt.json
	chmod 600 /etc/bpi-mqtt.json
	echo "Mật khẩu thiết bị (user iot): $P_IOT"
fi
chown mosquitto:mosquitto /etc/mosquitto/passwd /etc/mosquitto/acl
chmod 600 /etc/mosquitto/passwd /etc/mosquitto/acl
service mosquitto enable
service mosquitto restart
