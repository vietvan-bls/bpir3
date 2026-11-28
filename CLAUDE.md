# CLAUDE.md — bàn giao cho phiên làm việc sau

Người dùng nói tiếng Việt, thích làm nhanh ("build đi", "push nhé"), làm việc qua điện thoại; trả lời bằng tiếng Việt.
Repo này là toàn bộ dự án BPI-R3: xem [README.md](README.md) cho hướng dẫn từng tính năng. File này là ghi chú *cách làm việc*.

**Repo đang PUBLIC** → không bao giờ commit mật khẩu, khóa, cookie, token, mật khẩu MQTT/khách. Chỉ ghi chỗ chúng nằm trên board.
Nhánh: toàn bộ công việc đã gộp vào `main` (fast-forward từ `claude/festive-brahmagupta-nrzyez`). Làm tiếp trên nhánh
mà phiên được giao; người dùng muốn thì gộp lại vào `main`.

## 1. Board và cách vào

| Thứ | Giá trị |
|---|---|
| Board | BPI-R3, OpenWrt SNAPSHOT (apk, musl, kernel 6.18), Python 3.14, hostname `OpenWrt` |
| LAN | `192.168.2.1/24` (Wi-Fi `BPI-R3`, `BPI-R3-5G`); WAN = Wi-Fi nhà `VQH` (wwan, 192.168.1.x DHCP) |
| Web server | `/root/server/app.py` cổng 8080, dịch vụ `myserver`; bản cũ sau mỗi deploy ở `/root/server-backup/` |
| Tên cố định | `https://bpi-r3.tail24dd60.ts.net` (Tailscale Funnel → :8080), MQTT TLS `:8443` (Funnel → :1883) |
| Tailnet (riêng chủ) | `100.121.201.107`: OpenOCD GDB `:3333`, telnet `:4444` (`tailscale serve`, không Funnel) |
| Link công khai phụ | Cloudflare quick tunnel (dịch vụ `cftunnel`), **đổi mỗi lần board khởi động lại** |
| SSH từ xa | quick tunnel `sshtunnel` → dropbear `127.0.0.1:2222`, **chỉ khóa**; hostname đổi mỗi lần khởi động |

**Quy trình vào board từ container mới** (container của phiên trước đã mất, kể cả khóa SSH):
1. Cài `cloudflared` (tải binary từ GitHub releases `cloudflared-linux-amd64` vào `/usr/local/bin`) và `openssh-client`.
2. Tạo khóa: `ssh-keygen -t ed25519 -N '' -C claude-bpir3 -f ~/.ssh/id_ed25519`. Nhờ người dùng thêm public key vào board:
   LuCI (`https://bpi-r3.tail24dd60.ts.net/cgi-bin/luci/` sau khi đăng nhập web panel) → System → Administration → SSH-Keys,
   và xóa khóa `claude-bpir3` cũ. Tuyệt đối không xin mật khẩu root qua chat nếu có cách khác.
3. Lấy hostname SSH hiện tại: đăng nhập web panel (`POST /api/login {"password"}`, header `X-BPI: 1`, cần mật khẩu quản trị —
   hỏi người dùng), rồi `GET /api/public-url` → trường `ssh`. Funnel đôi khi lỗi 1 trong 2 IP ingress → thử lại vài lần.
4. `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@<ssh>`
   Tiện: viết script `b` trong scratchpad bọc lệnh trên (`b 'lệnh'`), timeout 120 s.
5. Lưu ý: `pgrep -f`/`killall` theo chuỗi có trong chính câu lệnh SSH sẽ giết luôn phiên shell (đã gặp) → kill theo PID.

## 2. Dựng lại môi trường build trong container (Ubuntu 24.04)

```sh
apt-get install -y gcc-aarch64-linux-gnu flex bison bc device-tree-compiler swig libgnutls28-dev uuid-dev libssl-dev \
  gdisk dosfstools mtools e2fsprogs zstd gawk xsltproc rsync wget unzip file openjdk-17-jdk-headless \
  mosquitto mosquitto-clients gcc-arm-none-eabi libnewlib-arm-none-eabi gdb-multiarch ffmpeg psmisc
pip install paho-mqtt==2.1.0 openpyxl pysocks yowasp-yosys yowasp-nextpnr-himbaechel-gowin apycula   # 3 gói cuối: FPGA
```
- **Flutter** (stable, đã dùng 3.50 / Dart 3.14): tải archive theo `releases_linux.json` của `storage.googleapis.com/flutter_infra_release`,
  giải nén vào `/opt/flutter`, `git config --global --add safe.directory /opt/flutter`.
- **Android SDK**: cmdline-tools (`commandlinetools-linux-*_latest.zip`) → `/opt/android-sdk/cmdline-tools/latest`;
  `sdkmanager --licenses`; `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`.
- Env: `export ANDROID_HOME=/opt/android-sdk PATH=/opt/flutter/bin:$PATH`.
- Gradle hay lỗi 429 (Maven Central) lần đầu → thử lại sau 20–40 s.
- Bộ kiểm duyệt của phiên có thể chặn `curl … | sh` (vd cài arduino-cli) và thao tác “đi vòng proxy”; khi bị chặn thì dừng, giải thích, hỏi người dùng.

## 3. Build / test / deploy

**Server (Python, chỉ thư viện chuẩn + numpy/paho):** chạy thử trong container trước khi deploy:
```sh
cd server
python3 - <<'EOF'   # mật khẩu quản trị GIẢ cho container (xóa sau khi test)
import hashlib,secrets,json; s=secrets.token_hex(16)
json.dump({"password":{"salt":s,"it":1000,"hash":hashlib.pbkdf2_hmac("sha256",b"adminpass",bytes.fromhex(s),1000).hex()}},open("/etc/bpi-web-auth.json","w"))
EOF
KHO_DIR=/tmp/x/kho IOT_DIR=/tmp/x/iot IOT_AUTH_FILE=/tmp/x/iotauth.json IOT_MQTT_CONF=/nonexistent CAMERA_MODE=file PORT=18080 python3 app.py
```
- `127.0.0.1` **không** được coi là “trong mạng” → đăng nhập bằng `/api/login` (cookie) để có quyền quản trị.
- Mọi POST cần header `X-BPI: 1`. Tải file lên (kho, vpn, nhạc) là thân request thô (không multipart).
- Test giao diện web bằng Playwright (có sẵn, `devices['Pixel 7']`), chụp màn hình rồi xem bằng Read.
- Deploy: `tar -cf - app.py kho.py … | b 'cp … /root/server-backup/; tar -C /root/server -xf - && python3 -m py_compile … && service myserver restart'`.
  **Trước khi ghi đè, so md5 file trên board với repo** (người dùng có thể sửa trực tiếp trên board / máy Windows bằng `deploy.ps1`).
- Thêm module/file mới thì cập nhật danh sách trong `server/deploy.ps1`.

**App Flutter:**
```sh
cd app && flutter analyze && flutter test
flutter build apk --release --split-per-abi --target-platform android-arm64
cp build/app/outputs/flutter-apk/app-arm64-v8a-release.apk ../out/app/bpir3-arm64.apk   # rồi tăng version trong pubspec.yaml
```
- Xem giao diện app không cần điện thoại: `flutter create --platforms web . && flutter build web`, chép `build/web` ra scratchpad,
  **xóa `web/`, `build/web` và `git checkout -- .metadata analysis_options.yaml`** (flutter create sửa 2 file này). Chạy proxy Python
  phục vụ thư mục web và chuyển `/api/*`, `/music/*`, `/camera*` sang server (cùng origin để cookie chạy). Flutter web vẽ bằng canvas:
  Playwright bấm theo tọa độ (`page.mouse.click`) + `keyboard.type`, chụp màn hình để kiểm tra.
- Gửi APK cho người dùng bằng SendUserFile (`display: attach`).

**Board:** đổi cấu hình hệ thống (firewall, gói, dịch vụ) → nói rõ trước; người dùng đã đồng ý các thứ hiện có.

## 4. Lỗi / bẫy đã gặp

- Flutter ≥ 3.47: Material tách sang package `material_ui` → import `package:material_ui/material_ui.dart`.
- `file_picker` 13: `FilePicker.pickFiles(...)` là hàm static trả `List<PlatformFile>`, đọc bằng `f.xFile`.
- ML Kit text recognition: R8 báo thiếu lớp chữ Trung/Nhật/Hàn → đã có `android/app/proguard-rules.pro` (`-dontwarn …`).
- Tailscale Funnel: IP ingress `103.84.155.217` (ingress thế hệ mới `fd7a:…:ab12:…`) bị bộ lọc gói trên node chặn → ~½ kết nối lỗi;
  lỗi phía Tailscale, chưa khắc phục được (khởi động lại không hết). Client cần thử lại.
- Tailscale chạy `--accept-dns=false --netfilter-mode=off` (không đụng DNS/firewall của board).
- Container của Claude ra Internet qua proxy MITM: không chở được MQTT/TLS thô → test MQTT qua Funnel bằng cách chạy client trên chính board.
- OpenWrt BusyBox thiếu `base64`, `od` → sinh mật khẩu bằng `python3 -c "import secrets…"` (từng làm Mosquitto chạy mật khẩu rỗng vài phút).
- Mosquitto chạy dưới user `mosquitto`, đọc lại `passwd` khi SIGHUP → sau `mosquitto_passwd` phải `chown mosquitto`.
- OpenOCD: GDB detach không tự chạy chip → cấu hình đã có `gdb-detach { resume }`.
- VPN Gate cần `--data-ciphers …:AES-128-CBC` và `--tls-cipher DEFAULT:@SECLEVEL=0` (máy chủ cũ).
- SQLite tái sử dụng id linh kiện đã xóa → `save_part` dọn `stock_log`/`part_suppliers` sót khi tạo mới.
- API tìm kiếm của LCSC (`/ftps/wm/search/global`) trả 403 → không tra được MPN → mã LCSC; chỉ API chi tiết theo mã C… dùng được.
- GitHub chỉ cho clone repo công khai, **không tải được file Releases** của repo khác (oss-cad-suite) → FPGA dùng bản YoWASP từ PyPI;
  thư viện arm64 lấy `.deb` từ `ports.ubuntu.com`.
- Gowin EDA (bản Standard) không kiểm tra được license từ container: proxy chỉ chở HTTPS. Người dùng bảo **bỏ qua Gowin EDA**,
  chỉ dùng bộ mã nguồn mở. Tang Console 60K (GW5AT-60): nạp được, báo DONE, nhưng UART chưa thấy gì (Apicula chưa thử chip này trên phần cứng thật).
  nextpnr có GW5AT-60B phải build từ source (`-DHIMBAECHEL_GOWIN_DEVICES="GW5AT-60B;GW1NS-4"`, cài vào `/opt/nextpnr`) + `apycula>=0.36`.
- Tang Nano 4K: BL702 chỉ có JTAG, **không có UART** qua USB (đã dò cả 29 chân).
- `apk search` có thể rỗng nếu chỉ mục cũ → `apk update` trước.

## 5. Trạng thái hiện tại (cuối phiên trước)

- Đã chạy trên board: web server (mọi tab), kho (dữ liệu thật của chủ: 4 loại / ~3.5k con, chưa có khách), IoT + Mosquitto
  (tài khoản `iot`, `server`, `esp-xa`), Tailscale Funnel, OpenOCD + ST-Link (đích STM32F1, firmware gốc sao lưu ở
  `/mnt/data/stm32-backup/`), VPN (**người dùng đang bật VPN Gate Nhật**), webcam đã được hỗ trợ nhưng gần đây không thấy cắm.
- FPGA Tang Nano 4K cắm USB board, `openFPGALoader` ở `/mnt/data/fpga/` (README mục FPGA), đang nạp `hello.fs` (SRAM).
- USB-CAN candleLight → `can0` (driver gs_usb đã cài), công cụ `/usr/bin/can.py`; cổng để `down` khi không dùng.
- Sao lưu dữ liệu: `tools/backup-data.sh` → `data-backup/*.enc` (AES-256, mật khẩu ở `/root/.bpi-backup-pass` trên board).
  **Không bao giờ commit bản giải mã.** Bản đầu tiên: 2026-11-28.
- App Android 1.5.0 (`out/app/bpir3-arm64.apk`).
- Mật khẩu quản trị web panel đã từng lộ trong chat phiên trước → đã nhắc người dùng đổi (chưa rõ đã đổi chưa).

## 6. Việc dang dở / ý tưởng người dùng từng nhắc

- Thông báo đẩy (có máy mới bắt Wi-Fi, camera thấy chuyển động) — đã hỏi cách làm, chưa làm.
- Trợ lý giọng nói trên board (Whisper/Claude/edge-tts) — card âm thanh “Viet audio” không có tín hiệu mic; cần mic USB hoặc dùng mic điện thoại.
- USB/IP cho Keil / STM32CubeProgrammer — chưa cài.
- App: màn IoT chưa có; iOS chưa build (cần Mac); quét camera / OCR chưa thử trên máy thật.
- Nhãn Mouser chưa nhận riêng; sketch ESP32 chưa biên dịch thử.
- Cân nhắc đổi repo sang private.
