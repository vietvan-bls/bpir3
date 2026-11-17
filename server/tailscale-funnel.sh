#!/bin/sh
# Đưa board ra Internet với tên cố định https://bpi-r3.<tailnet>.ts.net (Tailscale Funnel, miễn phí).
#   443  -> web server 8080 (trang quản trị, /iot, LuCI)
#   8443 -> MQTT 1883 (Funnel giữ TLS, thiết bị ở xa dùng MQTT qua TLS)
# Lần đầu: tailscale up in ra link đăng nhập; funnel có thể in link để bật Funnel cho tailnet.
set -e
apk add tailscale
service tailscale enable
service tailscale start
sleep 3
# accept-dns=false: board vẫn là DNS cho mạng của nó; netfilter-mode=off: không đụng firewall
# (Funnel chuyển thẳng vào 127.0.0.1 nên không cần rule).
tailscale status >/dev/null 2>&1 || tailscale up --hostname=bpi-r3 --accept-dns=false --netfilter-mode=off
tailscale funnel --bg --https=443 http://127.0.0.1:8080
tailscale funnel --bg --tls-terminated-tcp=8443 tcp://127.0.0.1:1883
tailscale funnel status
