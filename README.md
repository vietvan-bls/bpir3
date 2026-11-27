# bpir3

Dự án liên quan đến Banana Pi BPI-R3 (MediaTek MT7986 / Filogic 830) chạy OpenWrt.

Thư mục trong repo:

| Thư mục | Nội dung |
|---|---|
| `server/` | Web server chạy trên board (cổng 8080) + dịch vụ procd + công cụ Windows |
| `tools/` | Script tiện ích chạy trên board (mở rộng thẻ nhớ, đo tốc độ nhận dạng) |
| `app/` | App điện thoại Flutter (Android + iOS) điều khiển web server |
| `build.sh`, `mksdimg.sh`, `openwrt.sh` | Build U-Boot/TF-A, tạo image SD, build OpenWrt bằng ImageBuilder |
| `out/` | Bootloader đã build sẵn + APK Android |

## Board

- Firmware: OpenWrt SNAPSHOT, ghi image `openwrt-mediatek-filogic-bananapi_bpi-r3-sdcard.img.gz`
  (tải ở [firmware-selector](https://firmware-selector.openwrt.org/?version=SNAPSHOT&target=mediatek%2Ffilogic&id=bananapi_bpi-r3))
  vào thẻ microSD bằng balenaEtcher hoặc Rufus.
- Boot từ thẻ SD: gạt công tắc boot **A, B, D = High**, rồi rút điện cắm lại.
- LAN của board: `192.168.2.1` (đã đổi khỏi `192.168.1.1` để không trùng với router nhà).
- Internet: board bắt Wi-Fi nhà làm WAN (interface `wwan`) và phát Wi-Fi riêng `BPI-R3` / `BPI-R3-5G`.
- Giao diện web LuCI: <http://192.168.2.1> (đã cài thêm bằng `apk add luci`). Từ xa: `<link công khai>/cgi-bin/luci/`
  (xem phần Truy cập từ Internet).
- Root có mật khẩu; máy tính vào SSH bằng khóa `~/.ssh/id_ed25519` (thêm vào `/etc/dropbear/authorized_keys`).
  `deploy.ps1` và `bpir3.bat` cần khóa này. Xem phần [Khóa SSH](#khóa-ssh).
- Múi giờ: `Asia/Ho_Chi_Minh` (`<+07>-7`).
- Loa: card âm thanh USB cắm cổng USB của board (xem phần Phát ra loa USB). Board không có Bluetooth sẵn.

### Những gì đã cài / cấu hình trên board

| Thành phần | Ghi chú |
|---|---|
| Gói | `luci python3-light python3-urllib python3-logging python3-numpy python3-openssl ffmpeg cloudflared nlbwmon minidlna kmod-usb-audio alsa-utils` + gói mở rộng thẻ nhớ |
| Dịch vụ tự chạy | `myserver` (web 8080), `cftunnel` (link web công khai), `sshtunnel` (SSH từ xa), `mosquitto` (MQTT 1883), `minidlna`, `nlbwmon` |
| `/mnt/data` | phân vùng p8 ~57 GB: `camera/`, `music/`, `traffic/`, `nlbwmon/` |
| dropbear | `main`: cổng 22, mọi interface, cho mật khẩu + khóa; `remote`: `127.0.0.1:2222`, chỉ khóa (cho SSH từ xa) |
| dnsmasq | ghi log truy vấn vào `/tmp/dnsmasq.log` (thống kê truy cập) |
| firewall | rule `Allow-MyServer-8080` cho dải `192.168.1.0/24` (mạng nhà) vào cổng 8080 |
| web panel | mật khẩu truy cập từ xa trong `/etc/bpi-web-auth.json` |

Chưa làm (cần đồng ý vì là rule firewall): ép mọi DNS cổng 53 về board và chặn DNS-over-TLS cổng 853, để thống kê
truy cập khó bị lọt hơn.

## Mở rộng thẻ nhớ (`/mnt/data`)

Image sdcard chỉ dùng ~512 MB đầu thẻ. Phần còn lại được tạo thành phân vùng `p8` "data" (ext4, ~57 GB),
tự mount ở `/mnt/data` khi khởi động (uci `fstab.data`, theo UUID).

- [tools/gpt_add_data.py](tools/gpt_add_data.py) thêm phân vùng vào GPT **mà không đụng MBR hybrid**
  và các phân vùng cũ (sgdisk báo lỗi với GPT của image này). Chạy thử trước, thêm `--write` để ghi.
- Cần gói: `sgdisk e2fsprogs kmod-fs-ext4 block-mount partx-utils`.
- Bản sao lưu GPT trước khi sửa nằm ở `backup/` (không đưa lên git).
- Ghi lại image mới vào thẻ sẽ xóa phân vùng này, cần chạy lại script.

## Web server mẫu (`server/`)

Server Python (thư viện chuẩn + numpy), chạy cổng **8080**, giao diện một trang nhiều tab:
📊 Tổng quan · 📷 Camera · 📶 Wi-Fi Internet · 🖧 Mạng LAN · 🎵 Nhạc · 🌐 Truy cập · 💡 Điều khiển · 📜 Log · ⚙️ Hệ thống.
Danh sách đầy đủ các API nằm ở đầu [server/app.py](server/app.py).

| File | Chức năng |
|---|---|
| [server/app.py](server/app.py) | HTTP server, đăng nhập, Wi-Fi, LAN, camera, chuyển tiếp LuCI |
| [server/index.html](server/index.html) | Giao diện web |
| [server/vision.py](server/vision.py) | Nhận dạng + tracking người trên camera |
| [server/music.py](server/music.py) / [server/speaker.py](server/speaker.py) | Thư viện nhạc / phát ra loa USB |
| [server/traffic.py](server/traffic.py) | Thống kê truy cập web theo máy |
| `myserver.init`, `cftunnel.init`, `sshtunnel.init` | Dịch vụ procd trên board |
| `deploy.ps1`, `bpir3.bat`, `find-board.ps1`, `ssh-remote.ps1` | Công cụ trên Windows |

Cài lần đầu trên board:

```sh
apk add python3-light python3-urllib python3-logging python3-numpy python3-openssl ffmpeg cloudflared
```

**Cách nhanh nhất:** bấm đúp [server/bpir3.bat](server/bpir3.bat). File này tự tìm board
(192.168.2.1 hoặc 192.168.1.24) và có menu: deploy code, xem/mở link công khai, mở trang web,
xem log, khởi động lại server, tạo link mới, SSH vào board. Có thể chạy thẳng một lệnh:
`bpir3.bat deploy|link|web|public|log|restart|newlink|ssh`.

Hoặc đẩy code từ máy tính lên board (tự cài dịch vụ `myserver` để chạy khi khởi động):

```powershell
cd server
.\deploy.ps1                       # máy tính đang ở mạng của board (192.168.2.x)
.\deploy.ps1 -Board 192.168.1.24   # máy tính đang ở mạng nhà
```

Truy cập:

- Từ mạng của board: <http://192.168.2.1:8080>
- Từ mạng nhà: `http://<IP wwan của board>:8080`. Firewall có rule `Allow-MyServer-8080`,
  chỉ cho phép dải `192.168.1.0/24`.

Quản lý dịch vụ trên board: `service myserver start|stop|restart`, xem log: `logread -e python3`.

### Camera USB thật (`/camera.mjpg`)

Webcam UVC cắm vào board (đang dùng: `0c45:636b USB Camera`, Sonix, qua hub USB). Cần driver: `apk add kmod-video-uvc`
(tạo `/dev/video0`). Camera xuất MJPEG sẵn tới 1920×1080, nên server **chép thẳng** khung JPEG cho người xem (không nén lại).

- Một tiến trình `ffmpeg` đọc camera và xuất song song 2 luồng: MJPEG gốc (stdout) cho người xem, ảnh xám 192×144
  (pipe riêng) cho nhận dạng chuyển động. Đo trên board: ffmpeg ~4% CPU, server ~2%, nhận dạng ~7 ms/khung.
- Cấu hình bằng biến môi trường trong `myserver.init`: `CAMERA_DEVICE` (mặc định `/dev/video0`), `CAMERA_SIZE`
  (`1280x720`), `CAMERA_FPS` (`10`), `CAMERA_MODE=file` để ép dùng video mẫu.
- Không có `/dev/video0` lúc server khởi động → dùng video mẫu như cũ. Rút camera giữa chừng → tự thử lại mỗi 3 giây.
- Nền ảnh để trừ nền lấy từ khung đầu và cập nhật dần; bật/tắt đèn (cả cảnh đổi) thì dựng lại nền ngay.
- ~2 Mbps mỗi người xem ở 1280×720. Camera không có hồng ngoại: phòng tối thì hình gần như đen.
- `/api/status` → `camera`: `live`, `size`, `error`.

### Camera giả lập (video mẫu, khi không có camera USB)

Phát lặp video mẫu `vtest.avi` của OpenCV (người đi bộ, 768×576, 10 fps) như một camera IP, dạng MJPEG.
Xem được cả qua link công khai (tab **📷 Camera**, hoặc mở thẳng `<link>/camera.mjpg` bằng trình duyệt/VLC).

```sh
apk add ffmpeg
mkdir -p /mnt/data/camera && cd /mnt/data/camera
wget -O vtest.avi https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi
ffmpeg -i vtest.avi -q:v 6 -f mjpeg vtest.mjpeg   # 795 khung, ~38 MB, nạp vào RAM khi server chạy
```

- `GET /camera.jpg`: ảnh khung hiện tại. Không giới hạn người xem (~3,8 Mbps mỗi người).

#### Nhận dạng + tracking người ([server/vision.py](server/vision.py))

OpenWrt không có OpenCV, nên dùng `numpy` (`apk add python3-numpy`): trừ nền (nền = trung vị ~60 khung,
cập nhật chậm) → lọc nhiễu hình thái học → gom vùng liền nhau → bỏ vùng nhỏ → tracker ghép theo khoảng cách tâm,
người mới phải xuất hiện ≥3 khung mới được đếm. Chạy ~11 ms/khung trên BPI-R3, server ~2% CPU.

```sh
# ảnh xám 192x144 khớp từng khung với vtest.mjpeg, dùng để phân tích
ffmpeg -i vtest.avi -vf scale=192:144,format=gray -f rawvideo /mnt/data/camera/vtest_192x144.gray
```

- `GET /api/vision/stream` (SSE): mỗi khung 1 sự kiện `{people:[{id, box, trail}], count, total, ms}`;
  trang web vẽ khung, ID, vệt đường đi lên canvas phủ trên video. `GET /api/vision`: kết quả khung hiện tại.
- Qua Cloudflare quick tunnel, sự kiện SSE nhỏ (~1,5 KB) bị giữ lại hoàn toàn; mỗi sự kiện được đệm
  (dòng chú thích SSE) cho đủ 4 KB khi đi qua tunnel thì tới ngay (~6–7 sự kiện/giây). Trong LAN không đệm.
- Hạn chế: người đi sát nhau bị gộp một khung; vật chuyển động khác cũng bị tính. Muốn chuẩn hơn cần mô hình AI.
- [tools/bench_vision.py](tools/bench_vision.py): đo tốc độ / kết quả trên toàn bộ video ngay trên board.
- Đổi video: chuyển video khác thành `.mjpeg` rồi đặt biến môi trường `CAMERA_FILE` trong `myserver.init`.

### Máy chủ nhạc ([server/music.py](server/music.py), tab **🎵 Nhạc**)

Board không có cổng âm thanh, nên nhạc **lưu trên board** (`/mnt/data/music`, kể cả thư mục con) và
**điện thoại/máy tính phát qua Wi-Fi**:

- **Trình duyệt**: tab Nhạc có tìm kiếm, tải lên (nhiều file, kéo thả), xóa, thanh phát ở cuối trang
  (trước/sau, tua, trộn bài, lặp). Chuyển tab vẫn nghe tiếp; điều khiển được từ màn hình khóa điện thoại
  (Media Session). Nghe được cả qua link công khai sau khi đăng nhập (Cloudflare giới hạn mỗi file tải lên ~100 MB).
- **App DLNA/UPnP** (VLC, BubbleUPnP, foobar2000, Windows Media Player…): `minidlna` chia sẻ cùng thư mục
  với tên **BPI-R3 Music** trong mạng của board. Trang trạng thái: <http://192.168.2.1:8200>.
- Tên bài / ca sĩ / album / thời lượng / ảnh bìa đọc bằng `ffmpeg -i` (không có ffprobe), lưu đệm trong
  `.index.json` và `.covers/`. File không có thẻ tên kiểu `Ca sĩ - Tên bài.mp3` được tách theo tên file.
- Nhận: mp3, m4a, aac, flac, ogg, opus, wav, webm. Phát nhạc hỗ trợ Range (tua được, Safari cần).
- Chép nhạc số lượng lớn: `scp -r "D:\Nhac" root@192.168.2.1:/mnt/data/music/` rồi bấm ↻.
- 2 bài "Bài thử 440Hz" và "Nốt Đô 523Hz" là tiếng bíp để thử, xóa được.

```sh
apk add minidlna
uci set minidlna.config.enabled=1
uci set minidlna.config.friendly_name="BPI-R3 Music"
uci delete minidlna.config.media_dir; uci add_list minidlna.config.media_dir="A,/mnt/data/music"
uci set minidlna.config.root_container=B
uci commit minidlna && service minidlna enable && service minidlna restart
```

#### Phát ra loa USB cắm vào board ([server/speaker.py](server/speaker.py))

Trong tab Nhạc chọn **🔊 Loa board**: bấm bài nào thì loa của board phát bài đó, trang web (điện thoại, máy tính,
cả qua link công khai) chỉ làm remote: dừng/phát, trước/sau, tua, trộn, lặp, âm lượng. Tắt màn hình điện thoại
nhạc vẫn chạy. Nhiều máy cùng điều khiển được, tất cả thấy chung một trạng thái.

```sh
apk add kmod-usb-audio alsa-utils     # driver card âm thanh USB + aplay/amixer
cat /proc/asound/cards                # kiểm tra board đã nhận card
```

- Phát bằng `ffmpeg` (giải mã) → `aplay` (ALSA, 48 kHz stereo), card đầu tiên có đường phát.
- Tạm dừng = dừng tiến trình và nhớ vị trí, phát tiếp bằng `ffmpeg -ss`.
- Card USB rút ra cắm lại giữa chừng → tự chờ và phát tiếp chỗ cũ (thử 5 lần). Âm lượng đặt lại trước mỗi lần phát
  vì card cắm lại sẽ về 100%.
- Âm lượng 0–200%: tới 100% dùng mixer của card; trên 100% tăng thêm bằng phần mềm (tới +12 dB, `alimiter`
  chống vỡ tiếng). Đổi mức tăng phần mềm khi đang phát sẽ khựng ~0,3 giây.
- API: `GET /api/speaker`, `POST /api/speaker {"action": "play", "ids": [...], "index": 0}` (và `toggle`, `next`,
  `prev`, `seek`, `volume`, `shuffle`, `repeat`, `stop`).
- Card hiện tại ("Viet audio", USB Audio Class, 44,1/48 kHz stereo) hay tự rút ra cắm lại; driver báo dải âm lượng
  0–4096 bất thường (vô hại).

### Thống kê truy cập web ([server/traffic.py](server/traffic.py), tab **🌐 Truy cập**)

Board là DNS của mọi máy trong mạng nên biết máy nào hỏi tên miền nào. Chỉ biết **tên trang**
(YouTube, Facebook, `vnexpress.net`…), không biết xem video/bài nào vì HTTPS đã mã hóa.

```sh
uci set dhcp.@dnsmasq[0].logqueries=1
uci set dhcp.@dnsmasq[0].logfacility=/tmp/dnsmasq.log   # server tự cắt file khi > 4 MB
uci commit dhcp && service dnsmasq restart
apk add nlbwmon                                         # dung lượng mỗi máy
uci set nlbwmon.@nlbwmon[0].database_directory=/mnt/data/nlbwmon
uci set nlbwmon.@nlbwmon[0].database_interval=2026-11-17/1   # mỗi ngày một chu kỳ
uci set nlbwmon.@nlbwmon[0].database_generations=30
uci set nlbwmon.@nlbwmon[0].commit_interval=1h
uci commit nlbwmon && service nlbwmon restart
```

- Tên miền phụ được gộp theo dịch vụ (`googlevideo.com` → YouTube, `fbcdn.net` → Facebook…), còn lại gộp theo
  tên miền chính. Dịch vụ nền (cập nhật hệ điều hành, quảng cáo, CDN) có thể ẩn.
- "Thời gian dùng" = số phút có ít nhất một lần truy cập (ước lượng; app chạy nền cũng tính).
- IP (cả IPv6) được đổi ra MAC qua `ip neigh`, tên máy lấy từ DHCP. Lưu theo ngày ở `/mnt/data/traffic/`, giữ 30 ngày.
- `GET /api/traffic?day=YYYY-MM-DD`, `GET /api/traffic/recent?mac=`.
- Không ghi được: máy dùng VPN, iCloud Private Relay, hoặc DNS mã hóa riêng (DoH/DoT). Máy có tra tên các
  dịch vụ DoH (`dns.google`, `cloudflare-dns.com`…) sẽ có dấu ⚠️.
- Múi giờ board: `Asia/Ho_Chi_Minh` (để chia ngày đúng).

### Đăng nhập khi truy cập qua link công khai

- Trong mạng nội bộ: dùng mọi chức năng, không cần mật khẩu.
- Qua link công khai: hiện màn hình đăng nhập; đăng nhập xong có **toàn quyền** (kể cả camera).
  Chưa đăng nhập thì mọi API (kể cả `/camera.mjpg`) trả về 401.
- Đặt/đổi mật khẩu ở tab **⚙️ Hệ thống**. Lưu dạng băm PBKDF2-SHA256 trong `/etc/bpi-web-auth.json` (quyền 600).
  Phiên đăng nhập 7 ngày (cookie HttpOnly, Secure, SameSite=Strict). Sai 5 lần liên tiếp → khóa IP 5 phút.
- Quên mật khẩu: `ssh root@192.168.2.1 "rm /etc/bpi-web-auth.json"` rồi đặt lại trong mạng nội bộ.
- Cần gói `python3-openssl` (cho `hashlib.pbkdf2_hmac`).

### Bảng điều khiển trên web

Mở `http://192.168.2.1:8080` từ mạng của board (hoặc qua link công khai sau khi đăng nhập).

- **Wi-Fi Internet**: quét mạng 2.4 + 5 GHz, bấm vào mạng → nhập mật khẩu để board bắt mạng đó làm WAN
  (interface `wwan`). Hỗ trợ mạng ẩn. Kết nối chạy nền; nếu sai mật khẩu, mất sóng, hoặc mạng mới cấp IP
  trùng dải `192.168.2.x`, board **tự quay về mạng cũ** (~1 phút). Bắt mạng 5 GHz thì Wi-Fi `BPI-R3-5G`
  sẽ đổi theo kênh của mạng đó.
- **Mạng LAN của board**: đổi IP board, dải mạng (/16–/28) và dải DHCP. Phải mở trang bằng IP LAN của board.
  Sau khi đổi, trang tự gọi sang IP mới để xác nhận; nếu 3 phút không xác nhận được, board **tự quay về IP cũ**.
  Từ chối dải trùng với mạng Internet board đang bắt. `bpir3.bat` tự tìm board theo gateway nên vẫn chạy sau khi đổi IP.
- Bắt mạng 5 GHz ở kênh DFS (52–144) sẽ làm Wi-Fi `BPI-R3-5G` tắt (không dò radar được khi radio đang bắt mạng),
  nên ưu tiên bắt mạng 2.4 GHz.
- Đèn LED, danh sách máy đang bắt Wi-Fi, log, tạo link công khai mới, khởi động lại server/board.

## Kho linh kiện (`/kho`, [server/kho.py](server/kho.py), [server/kho.html](server/kho.html))

Quản lý linh kiện mua từ LCSC, Digi-Key, Mouser, Taobao… Cần quyền quản trị (trong mạng, hoặc đã đăng nhập).
Mở: `http://192.168.2.1:8080/kho` / `https://bpi-r3.tail24dd60.ts.net/kho`, hoặc tab **Kho** trong app Android.

- **📦 Kho**: tìm theo MPN, giá trị, package, mã LCSC/Digi-Key/Mouser, vị trí; lọc theo loại / vị trí. Mỗi linh kiện có
  số lượng, mức cảnh báo, vị trí, giá, datasheet, nhiều mã / link nhà cung cấp, lịch sử nhập–xuất. Nút ±1, ±10, kiểm kê.
- **📋 BOM**: thả file BOM (CSV/XLSX từ KiCad, EasyEDA/JLCPCB, Altium…), tự nhận cột và khớp với kho theo
  mã LCSC → Digi-Key → Mouser → MPN → giá trị + package. Nhập số bo → xem từng dòng **cần / có / thiếu**, số bo làm được
  tối đa, tiền mua thêm; tải **CSV cần mua** (dạng LCSC: mã + số lượng, dán vào BOM Tool), **Lắp bo** để trừ kho.
  Dòng sai thì chọn lại linh kiện, đánh dấu DNP; “Thêm dòng thiếu vào kho” tạo sẵn linh kiện SL 0 để theo dõi.
- **📥 Nhập hàng**: thả file đơn hàng LCSC / Digi-Key / Mouser (CSV/XLSX) hoặc bảng tự làm (Taobao):
  linh kiện đã có thì cộng số lượng + thêm mã nhà cung cấp (gộp đúng cùng 1 linh kiện mua ở nhiều nơi), chưa có thì tạo.
  Chế độ “đặt đúng số lượng” dùng cho file kiểm kê. File `.xls` (Excel cũ) phải lưu lại thành `.xlsx` / `.csv`.
- **📷 Quét nhãn**: app (nút **Quét**, dùng camera) hoặc ô “Quét / dán mã” trên web (đầu đọc mã vạch USB 2D gõ như bàn phím).
  Đọc QR trên túi LCSC `{pbn:…,on:WM…,pc:C52711259,pm:CGA0603X7R104M500JT,qty:1500,…}`, DataMatrix Digi-Key
  (chuẩn ANSI MH10.8.2), mã `C…` hoặc link sản phẩm LCSC; chữ khác thì tìm trong kho. Đã có → cộng số lượng của nhãn;
  chưa có → tạo mới, **tự điền từ LCSC** (mô tả, giá trị, package, hãng, loại, datasheet, ảnh, giá). Mỗi nhãn chỉ cộng
  một lần (nhớ theo mã đơn + mã pick), quét lại sẽ cảnh báo. Quét liên tục được, vị trí nhớ từ lần trước.
- **🔤 Chụp nhãn (không có QR)**: app chụp / chọn ảnh nhãn, đọc chữ ngay trên máy (Google ML Kit, không cần mạng),
  tách mã LCSC (sửa lỗi O→0, I→1, C đọc thành 6…), MPN, số lượng, mã đơn, mã Digi-Key; sửa / chạm chọn cụm chữ rồi
  đi tiếp như quét QR. Server khớp MPN gần đúng (O=0, S=5, I=1…) để MPN đọc sai vẫn ra đúng linh kiện.
  Chỉ có MPN (không mã LCSC) thì không tra được thông số: API tìm kiếm của LCSC chặn truy cập tự động.
  Thông tin LCSC lấy từ API của trang lcsc.com (không chính thức, có thể đổi), lưu đệm 30 ngày; nút “Điền từ LCSC”
  ở chi tiết linh kiện để cập nhật.
- **⚠️ Sắp hết**: linh kiện có “Cảnh báo khi ≤” > 0 và số lượng ≤ mức đó; hiện số đếm ở đầu trang và trong app.
- **👥 Nhiều người dùng / cất hàng cho khách**: mỗi linh kiện và BOM có chủ sở hữu (“Của tôi” hoặc một khách);
  cùng MPN của bạn và của khách là 2 dòng riêng. Quản lý (đăng nhập quản trị board) chọn **“Kho của”** ở đầu trang
  (Tất cả / Của tôi / từng khách); thêm linh kiện, nhập đơn, quét nhãn, thêm BOM đều vào kho đang chọn (đổi được trong hộp thoại).
  Tab **👥 Khách**: thêm / sửa / xóa khách (không xóa được khi còn hàng), tạo tài khoản cho khách (mật khẩu tự tạo hoặc
  tự đặt, hiện 1 lần), đặt lại mật khẩu (đăng xuất máy cũ), xóa tài khoản.
  **Khách** đăng nhập tại `/kho` bằng tài khoản được cấp (cookie `bpi_kho`, phiên 30 ngày, sai 5 lần khóa 5 phút):
  chỉ thấy linh kiện, lịch sử, BOM của mình; tự tải BOM để xem thiếu gì (chỉ khớp với hàng của họ); không sửa số lượng,
  không nhập hàng, không vào được trang quản trị board / IoT / LuCI.
  **App Android**: quản lý có ô “Kho của” ở màn Kho (nhãn tên khách trên từng linh kiện khi xem “Tất cả”; quét, nhập mã LCSC,
  chụp nhãn, thêm, nhập đơn, thêm BOM đều vào kho đang chọn). Khách chọn **“Khách kho”** ở màn đăng nhập của app, dùng tài
  khoản kho được cấp → chỉ có màn Kho ở chế độ chỉ xem (không quét / sửa / lắp bo), vẫn tải BOM để kiểm tra.
- Dữ liệu: SQLite `/mnt/data/kho/kho.db`, tự sao lưu mỗi ngày vào `/mnt/data/kho/backup/` (giữ 14 bản).
  Xuất toàn bộ kho ra CSV (mở bằng Excel): `/api/kho/export.csv`.
- Chỉ dùng thư viện chuẩn của Python (đọc `.xlsx` bằng `zipfile` + XML), không cần cài thêm gói.
- API: xem đầu [server/app.py](server/app.py) (`/api/kho/*`).

## MQTT broker (IoT)

Mosquitto chạy trên board, cổng **1883**, chỉ vào được từ mạng của board (Wi-Fi `BPI-R3`, `192.168.2.x`);
firewall chặn từ WAN/Internet. Cài / cài lại: chép `server/` lên board rồi `sh mqtt-setup.sh`.

| Tài khoản | Dùng cho | Quyền |
|---|---|---|
| `iot` | Thiết bị (ESP32, cảm biến…) | đọc/ghi `iot/#` |
| `server` | Backend trên board | mọi topic; mật khẩu trong `/etc/bpi-mqtt.json` |

- Cấu hình: [server/mosquitto/mosquitto.conf](server/mosquitto/mosquitto.conf), quyền: [server/mosquitto/acl](server/mosquitto/acl).
- Mật khẩu `iot` được in ra lúc cài; đổi: `mosquitto_passwd -b /etc/mosquitto/passwd iot <mk_mới> && service mosquitto restart`.
  Tạo lại cả hai: `sh mqtt-setup.sh --reset`.
- Trạng thái (tin giữ lại, phiên) lưu ở `/mnt/data/mosquitto/`. Log: `logread -e mosquitto`.

### Trang IoT (`/iot`, [server/iot.py](server/iot.py), [server/iot.html](server/iot.html))

Trang riêng cho IoT, **mật khẩu riêng** (khác mật khẩu quản trị): người có mật khẩu IoT chỉ xem dữ liệu và bấm
điều khiển, không vào được phần quản trị board / LuCI. Quản trị viên (trong mạng hoặc đã đăng nhập) vào được cả hai,
và là người duy nhất đặt/đổi mật khẩu IoT (tab ⚙️ Cài đặt của trang IoT).

- Mở: `http://192.168.2.1:8080/iot` hoặc `<link công khai>/iot` (nút **📡 IoT** trên trang chính).
- **📊 Thiết bị**: gom topic theo `iot/<thiết bị>/…`, giá trị mới nhất, online/offline, bấm vào giá trị để xem
  biểu đồ 1 giờ → 30 ngày (trung bình + dải thấp/cao nhất).
- **🎛 Điều khiển**: tự tạo công tắc / nút bấm / thanh trượt; mỗi nút gửi payload vào topic lệnh
  (vd `iot/den/set` → `on`), trạng thái lấy từ topic trạng thái nếu có. Có ô gửi tin thủ công.
- Backend đăng ký `iot/#` bằng tài khoản `server` (`/etc/bpi-mqtt.json`), lưu SQLite `/mnt/data/iot/iot.db`
  (ghi gộp mỗi 5 giây cho đỡ hao thẻ nhớ, giữ 30 ngày). Danh sách nút: `/mnt/data/iot/controls.json`.
- Payload nhận: số, `on/off/true/false`, chữ, hoặc JSON (tách thành từng giá trị, vd `iot/vuon` →
  `{"do_am_dat": 41, "pin": {"v": 3.7}}` thành `iot/vuon/do_am_dat`, `iot/vuon/pin/v`). Tin `…/set` không bị lưu.
- Mật khẩu IoT: băm PBKDF2 trong `/etc/bpi-iot-auth.json`, phiên 30 ngày (cookie `bpi_iot`), sai 5 lần → khóa 5 phút.
- API: xem đầu [server/app.py](server/app.py) (`/api/iot/*`).

```sh
# thử từ một máy trong mạng 192.168.2.x
mosquitto_sub -h 192.168.2.1 -u iot -P <mật_khẩu> -t 'iot/#' -v
mosquitto_pub -h 192.168.2.1 -u iot -P <mật_khẩu> -t iot/phong-khach/nhiet-do -m 25.5
```

## Tên cố định qua Tailscale Funnel (`bpi-r3.tail24dd60.ts.net`)

Funnel (miễn phí) cho board một tên cố định có HTTPS, không cần tên miền, không mở cổng router.
Cài: [server/tailscale-funnel.sh](server/tailscale-funnel.sh) (lần đầu in link đăng nhập Tailscale và link bật Funnel).

| Địa chỉ | Tới |
|---|---|
| `https://bpi-r3.tail24dd60.ts.net` | web server 8080 (trang quản trị, `/iot`, LuCI) |
| `bpi-r3.tail24dd60.ts.net:8443` (TLS) | MQTT 1883, cho thiết bị ở xa |

- Tailscale chạy với `--accept-dns=false --netfilter-mode=off`: không đổi DNS/firewall của board.
- Server lấy IP thật của người dùng từ `X-Forwarded-For` (để khóa đúng người khi sai mật khẩu).
- Tắt: `tailscale funnel --https=443 off`, `tailscale funnel --tls-terminated-tcp=8443 off`; gỡ hẳn: `apk del tailscale`.
- **Đang có lỗi phía Tailscale (2026-11-18)**: tên miền trỏ tới 2 IP; IP qua máy chủ ingress thế hệ mới
  (`fd7a:115c:a1e0:ab12:…`) bị bộ lọc gói của Tailscale trên board chặn ("no rules matched"), nên khoảng một nửa số
  kết nối bị ngắt lúc bắt tay TLS. ESP32 mẫu tự thử lại nên vẫn kết nối được sau vài lần.

### Thiết bị ở xa (ESP32) qua MQTT/TLS

- Mỗi thiết bị một tài khoản, tạo ngay trên trang **`/iot` → ⚙️ Cài đặt → Tài khoản thiết bị** (hiện mật khẩu một lần
  kèm sẵn `secrets.h`; đổi mật khẩu / xóa cũng ở đó), hoặc bằng lệnh `sh /root/server/mqtt-add-device.sh <tên>`. Chỉ dùng được
  `iot/<tên>/#` (quy tắc `pattern` trong [server/mosquitto/acl](server/mosquitto/acl)). Xóa: `... <tên> --delete`.
  Lưu ý: `mqtt-setup.sh --reset` tạo lại file mật khẩu nên xóa luôn các tài khoản này.
- Code mẫu: [firmware/esp32-mqtt/esp32-mqtt.ino](firmware/esp32-mqtt/esp32-mqtt.ino) (PubSubClient + WiFiClientSecure,
  có sẵn ISRG Root X1/X2, LWT online/offline, nhận lệnh `iot/<tên>/set` bật tắt LED, gửi JSON mỗi 10 giây).
  Chép `secrets.example.h` thành `secrets.h` rồi điền Wi-Fi và tài khoản.

## Debug STM32 từ xa (ST-Link cắm vào board)

ST-Link cắm USB board → OpenOCD trên board làm GDB server → máy tính debug qua **Tailscale** (mạng riêng của bạn).

```
STM32 ──SWD── ST-Link ──USB── BPI-R3 (OpenOCD 127.0.0.1:3333) ══ tailscale serve (chỉ tailnet) ══ PC: IDE / GDB
```

- Đang dùng: ST-Link V2 (V2J46S7) + STM32F1 medium-density (64 KB flash, 20 KB RAM, Cortex-M3).
- Cài: `apk add openocd stlink-st-info stlink-st-flash stlink-st-util`, cấu hình [server/openocd/stm32.cfg](server/openocd/stm32.cfg)
  → `/etc/openocd/stm32.cfg`, dịch vụ [server/openocd.init](server/openocd.init) → `/etc/init.d/openocd-stm32`
  (tự chạy khi khởi động, rút / cắm lại ST-Link thì tự kết nối lại sau ~5 giây).
- Ra mạng: `tailscale serve --bg --tcp 3333 tcp://127.0.0.1:3333` (GDB) và `--tcp 4444` (telnet OpenOCD).
  **Chỉ máy trong tailnet** vào được; không qua Funnel, không mở firewall (cổng GDB không có mật khẩu).
- GDB ngắt kết nối (kể cả IDE tắt ngang) → chip tự chạy tiếp (`gdb-detach` → `resume`).
- Đổi chip: sửa dòng `source [find target/stm32f1x.cfg]` (stm32f4x, stm32g0x, stm32h7x, stm32l4x…) rồi
  `service openocd-stm32 restart`. Xem chip: `service openocd-stm32 stop; st-info --probe; service openocd-stm32 start`.

**Máy tính**: cài Tailscale, đăng nhập cùng tài khoản → board là `100.121.201.107` (hoặc `bpi-r3`).
Cần toolchain ARM (`arm-none-eabi-gdb` hoặc `gdb-multiarch`). Mỗi lúc một phiên GDB.

```sh
# dòng lệnh: nạp + chạy tới main
arm-none-eabi-gdb build/app.elf -ex "target extended-remote 100.121.201.107:3333" \
  -ex "monitor reset halt" -ex "load" -ex "break main" -ex "continue"
```

VS Code + Cortex-Debug (`.vscode/launch.json`):

```json
{ "type": "cortex-debug", "request": "launch", "name": "STM32 qua BPI-R3",
  "servertype": "external", "gdbTarget": "100.121.201.107:3333",
  "executable": "build/app.elf", "runToEntryPoint": "main",
  "overrideLaunchCommands": ["monitor reset halt", "load", "monitor reset halt"] }
```

STM32CubeIDE: *Debug Configurations → STM32 C/C++ Application → tab Debugger*: Debug probe **ST-LINK (OpenOCD)**,
bỏ chọn *Autostart local GDB server* / chọn **Connect to remote GDB server**, Host `100.121.201.107`, Port `3333`.
Keil / CubeProgrammer cần ST-Link “thật” trên máy → dùng USB/IP (chưa cài).

Telnet OpenOCD (`telnet 100.121.201.107 4444`): `reset halt`, `reset run`, `flash info 0`, `mdw 0x08000000 4`…

## Truy cập từ Internet (Cloudflare quick tunnel)

Dịch vụ `cftunnel` ([server/cftunnel.init](server/cftunnel.init)) chạy `cloudflared` để đưa cổng 8080
ra Internet qua link `https://xxx.trycloudflare.com`, không cần mở cổng trên router và không cần tài khoản.

```sh
apk add cloudflared          # cài lần đầu (deploy.ps1 sẽ cài dịch vụ cftunnel)
service cftunnel url         # in ra link công khai hiện tại
service cftunnel restart     # tạo link mới
service cftunnel stop        # ngừng chia sẻ ra Internet (disable để không tự bật khi khởi động)
```

Lưu ý:

- Link **đổi mỗi lần** tunnel hoặc board khởi động lại. Muốn tên miền cố định thì cần tài khoản
  Cloudflare + tên miền và chuyển sang named tunnel.
- Qua link công khai phải đăng nhập (xem phần Đăng nhập ở trên).
- Gói `cloudflared` có sẵn dịch vụ `/etc/init.d/cloudflared` (dùng token tài khoản), đã được disable.

### LuCI từ xa

Server cổng 8080 chuyển tiếp `/cgi-bin/`, `/luci-static/`, `/ubus` sang LuCI (uhttpd cổng 80), nên LuCI đi chung
link công khai: `<link>/cgi-bin/luci/` (nút **⚙️ LuCI** trên trang). Qua Internet phải đăng nhập web panel trước
(chưa đăng nhập: trang HTML chuyển về `/`, còn lại 401), sau đó LuCI hỏi mật khẩu root. Cookie phiên của web panel
không được gửi sang LuCI. Tải lên tối đa 100 MB mỗi lần (đủ cho file firmware).

### SSH từ xa

`.\deploy.ps1 -SshTunnel` (đã bật trên board) cài [server/sshtunnel.init](server/sshtunnel.init)
(quick tunnel `ssh://127.0.0.1:2222`) và một dropbear thứ hai chỉ nghe loopback, **chỉ cho đăng nhập bằng khóa**.
Hostname hiện trên trang Tổng quan (`service sshtunnel url`), đổi mỗi lần board khởi động lại.

```sh
# máy SSH cần cloudflared (Windows: winget install --id Cloudflare.cloudflared) và khóa đã thêm vào board
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" root@<hostname>.trycloudflare.com
```

- Trên Windows: [server/ssh-remote.ps1](server/ssh-remote.ps1) (ở nhà tự lấy hostname từ board).
- Điện thoại Android: Termux (`pkg install openssh cloudflared`).
- Thử thực tế: có khóa thì vào được qua Cloudflare; không có khóa thì bị từ chối (`No auth methods could be used`).
- Không chạy `service dropbear restart` thẳng trong phiên SSH: dropbear dừng sẽ cắt phiên, bước bật lại không chạy
  và board mất SSH (khi đó khởi động lại board bằng nút trên web, hoặc LuCI → System → Startup → dropbear → Start).
  `deploy.ps1` cho lệnh này chạy nền.

### Khóa SSH

Các khóa được phép vào board nằm ở `/etc/dropbear/authorized_keys` (dùng cho cả cổng 22 và SSH từ xa):

| Tên (comment) | Máy |
|---|---|
| `bpir3-pc` | Máy tính Windows (`C:\Users\Admin\.ssh\id_ed25519`, không đặt passphrase để script tự chạy) |
| `claude-bpir3` | Khóa thêm theo yêu cầu ngày 2026-11-17 |

```sh
# thêm khóa (trong mạng, hoặc từ một máy đã có khóa)
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@192.168.2.1 "cat >> /etc/dropbear/authorized_keys"
# gỡ khóa theo tên
ssh root@192.168.2.1 "sed -i '/ claude-bpir3$/d' /etc/dropbear/authorized_keys"
```

## Build từ source (bootloader, OpenWrt, app)

Các script dưới đây chạy trên máy Linux (Ubuntu/Debian), không chạy trên board.
### 1. Cài công cụ (Ubuntu/Debian)

```bash
sudo apt-get install -y gcc-aarch64-linux-gnu make git flex bison bc device-tree-compiler swig libssl-dev libgnutls28-dev uuid-dev gdisk dosfstools mtools e2fsprogs
```

### 2. Build bootloader

```bash
./build.sh
```

- Mặc định build cho boot từ **SD**. Build cho eMMC: `DEV=emmc ./build.sh`
- Đổi version U-Boot: `UBOOT_TAG=v2025.10 ./build.sh`
- Source được clone vào `work/`, kết quả nằm trong `out/`:

| File | Mô tả |
|---|---|
| `out/bl2.img` | TF-A BL2 (định dạng BootROM MediaTek, khởi tạo DDR4) |
| `out/fip.bin` | FIP = BL31 (TF-A) + BL33 (U-Boot) |
| `out/u-boot.bin` | U-Boot gốc (đã nằm trong fip.bin) |

Lệnh tương đương build tay:

```bash
export CROSS_COMPILE=aarch64-linux-gnu-
git clone --depth 1 -b v2025.10 https://github.com/u-boot/u-boot.git
git clone --depth 1 -b mtksoc https://github.com/mtk-openwrt/arm-trusted-firmware.git atf
make -C u-boot mt7986a_bpir3_sd_defconfig
make -C u-boot -j$(nproc)
make -C atf -j$(nproc) PLAT=mt7986 BOOT_DEVICE=sdmmc DRAM_USE_DDR4=1 USE_MKIMAGE=1 MKIMAGE=$PWD/u-boot/tools/mkimage BL33=$PWD/u-boot/u-boot.bin all fip
```

### 3. Tạo image thẻ SD

```bash
./mksdimg.sh bpir3-sdcard.img
```

Tuỳ chọn (biến môi trường):

- `SIZE_MB=2048` – kích thước image (mặc định 1024)
- `BOOT_MB=256` – kích thước phân vùng boot FAT32
- `BOOT_DIR=path/` – copy nội dung vào phân vùng boot (kernel `Image`, `*.dtb`, `extlinux/extlinux.conf`)
- `ROOTFS_DIR=path/` – copy rootfs vào phân vùng ext4

Layout GPT (sector 512 byte), giống image OpenWrt/frank-w:

| # | Tên | Sector | Offset | Nội dung |
|---|---|---|---|---|
| 1 | bl2 | 34 – 8191 | 17 KiB | `bl2.img` (BootROM đọc tại đây) |
| 2 | u-boot-env | 8192 – 9215 | 4 MiB | biến môi trường U-Boot |
| 3 | factory | 9216 – 13311 | 4.5 MiB | dữ liệu calib WiFi |
| 4 | fip | 13312 – 17407 | 6.5 MiB | `fip.bin` (BL2 tìm theo tên phân vùng `fip`) |
| 5 | boot | 18432 – … | 9 MiB | FAT32 |
| 6 | rootfs | còn lại | | ext4 |

### 4. Ghi ra thẻ SD

**Cẩn thận chọn đúng thiết bị** (`lsblk` để xem), lệnh dưới xoá toàn bộ thẻ:

```bash
sudo dd if=bpir3-sdcard.img of=/dev/sdX bs=4M conv=fsync status=progress
```

Hoặc chỉ ghi bootloader lên thẻ đã có bảng GPT như trên:

```bash
sudo dd if=out/bl2.img of=/dev/sdX bs=512 seek=34 conv=notrunc,fsync
```

```bash
sudo dd if=out/fip.bin of=/dev/sdX bs=512 seek=13312 conv=notrunc,fsync
```

### 5. Boot

1. Gạt switch boot (SW1) sang chế độ **SD** (theo bảng boot-select trên wiki BPI-R3).
2. Cắm UART debug (115200 8N1, 3.3V) để xem log BL2 → BL31 → U-Boot.
3. U-Boot dùng bootstd/distro boot: đặt `extlinux/extlinux.conf` + kernel + dtb (`mt7986a-bananapi-bpi-r3.dtb`) vào phân vùng boot để tự boot Linux.

### 6. Build OpenWrt

Dùng ImageBuilder chính thức (ghép package có sẵn, mất vài phút, không cần build từ source):

```bash
sudo apt-get install -y build-essential libncurses-dev zlib1g-dev gawk gettext libssl-dev xsltproc rsync wget unzip python3 zstd file
```

```bash
./openwrt.sh
```

- Đổi phiên bản: `OWRT_VER=25.12.6 ./openwrt.sh`
- Thêm/bớt package (`-pkg` để bỏ): `PACKAGES="luci luci-ssl wireguard-tools -ppp" ./openwrt.sh`
- Đưa sẵn cấu hình vào rootfs: `FILES_DIR=files ./openwrt.sh` (ví dụ `files/etc/config/network`)

Kết quả trong `out/openwrt/` (không commit, file lớn):

| File | Dùng cho |
|---|---|
| `*-bpi-r3-sdcard.img.gz` | ghi thẳng ra thẻ SD |
| `*-bpi-r3-squashfs-sysupgrade.itb` | nâng cấp từ OpenWrt đang chạy (`sysupgrade`) |
| `*-bpi-r3-{emmc,snand,nor}-preloader.bin` / `*-bl31-uboot.fip` | bootloader để cài lên eMMC/NAND/NOR |

Ghi thẻ SD:

```bash
gunzip -c out/openwrt/openwrt-*-bananapi_bpi-r3-sdcard.img.gz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
```

Gạt switch boot sang SD, cắm mạng vào cổng LAN, truy cập `http://192.168.1.1` (LuCI, user `root`, chưa có mật khẩu).
Từ image SD, U-Boot của OpenWrt có menu để cài OpenWrt sang NAND/eMMC.

### 7. App điện thoại (Android + iOS)

App Flutter trong `app/`, điều khiển "BPI-R3 Server" (tổng quan, camera, Wi-Fi, LAN, nhạc, truy cập web, LED, log, hệ thống).

- **Android**: cài `out/app/bpir3-arm64.apk` (bật "Cài ứng dụng không rõ nguồn gốc").
- Mở app → nhập **link công khai** (trycloudflare) và/hoặc **địa chỉ trong mạng** (vd `192.168.2.1:8080`).
  Ở nhà app dùng địa chỉ trong mạng trước (không cần mật khẩu); ra ngoài dùng link công khai + mật khẩu.
  App tự nhớ link công khai mới nhất mỗi lần kết nối được.

Build lại (cần Flutter ≥ 3.50, Android SDK):

```bash
cd app && flutter build apk --release --split-per-abi --target-platform android-arm64
```

**iOS** (cần máy Mac có Xcode, tài khoản Apple để cài lên iPhone):

```bash
cd app && flutter build ios --release
```

Hoặc mở `app/ios/Runner.xcworkspace` bằng Xcode, chọn Team ký app rồi bấm Run với iPhone đang cắm.
