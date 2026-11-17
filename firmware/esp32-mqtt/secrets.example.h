// Chép file này thành secrets.h rồi điền thông tin (secrets.h không đưa lên git).
#pragma once

#define WIFI_SSID   "ten-wifi-noi-dat-esp32"
#define WIFI_PASS   "mat-khau-wifi"

// Tạo tài khoản trên board:  sh /root/server/mqtt-add-device.sh <tên>
// Tên tài khoản cũng là tên thiết bị: chỉ dùng được topic iot/<tên>/...
#define MQTT_USER   "esp-xa"
#define MQTT_PASS   "mat-khau-mqtt"

// Ở xa: tên Tailscale Funnel của board, cổng 8443 (TLS).
#define MQTT_HOST   "bpi-r3.tail24dd60.ts.net"
#define MQTT_PORT   8443
