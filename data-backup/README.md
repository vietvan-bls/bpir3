# Sao lưu dữ liệu board (đã MÃ HÓA)

Các file `bpi-data-YYYYMMDD-HHMM.tar.gz.enc` được mã hóa AES-256-CBC, khóa sinh từ mật khẩu bằng PBKDF2 (600 000 vòng).
Repo đang public nhưng không đọc được nếu không có mật khẩu. Mật khẩu **không nằm trong repo**: nó ở `/root/.bpi-backup-pass` trên board
(chỉ root đọc được). Chủ board nên chép thêm một bản ra trình quản lý mật khẩu.

Bên trong: `kho/` (kho.db + backup hằng ngày), `iot/` (iot.db + json), `etc/` (`/etc/bpi-*`, mosquitto, openocd),
`config-sysupgrade.tar.gz` (cấu hình OpenWrt: mạng, Wi-Fi, firewall, khóa SSH/dropbear, Tailscale…).

Tạo bản mới (trong container Claude, cần SSH vào board): `BPI_SSH=b tools/backup-data.sh` rồi commit file `.enc` mới.

Giải mã (Linux / macOS / Git Bash trên Windows):
```sh
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in bpi-data-….tar.gz.enc -out data.tar.gz   # nhập mật khẩu
tar -xzf data.tar.gz
```
Khôi phục: chép `kho/kho.db` → `/mnt/data/kho/`, `iot/*` → `/mnt/data/iot/` (dừng `myserver` trước), `etc/*` → `/etc/`,
cấu hình OpenWrt: `sysupgrade -r config-sysupgrade.tar.gz` rồi reboot.
