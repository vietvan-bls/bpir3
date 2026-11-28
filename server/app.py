#!/usr/bin/env python3
"""Web server chạy trên BPI-R3 (OpenWrt), cổng 8080.

Quyền truy cập:
  - Trong mạng nội bộ (192.168.x.x, 10.x, 172.16-31.x): dùng mọi chức năng, không cần mật khẩu.
  - Qua link Cloudflare công khai: phải đăng nhập (POST /api/login) rồi mới dùng được mọi chức năng.
    Chưa đăng nhập chỉ mở được trang web (hiện màn hình đăng nhập) và /api/whoami.
    Mật khẩu băm PBKDF2 trong /etc/bpi-web-auth.json; sai 5 lần liên tiếp -> khóa IP đó 5 phút.

  POST /api/login        {"password"} -> đặt cookie phiên 7 ngày
  POST /api/logout
  POST /api/password     {"new", "current"?}  đặt/đổi mật khẩu (qua Internet phải có "current")
  GET  /api/whoami       local / authed / admin / password_set
  GET  /camera.mjpg      camera giả lập: stream MJPEG (phát lặp video mẫu, không giới hạn người xem)
  GET  /camera.jpg       ảnh chụp khung hình hiện tại
  GET  /api/vision/stream  SSE: mỗi khung 1 sự kiện {people:[{id,box,trail}], count, total, ms} (vision.py)
  GET  /api/vision       kết quả nhận dạng của khung hiện tại
  GET  /api/status       nhiệt độ, tải CPU, RAM, uptime, số máy Wi-Fi
  GET  /api/public-url   link công khai hiện tại
  POST /api/echo         trả lại JSON đã gửi
  GET  /api/clients      danh sách máy đang bắt Wi-Fi của board
  GET  /api/log?src=server|tunnel|system
  POST /api/led          {"mode": "on"|"off"|"blink"|"heartbeat"}
  POST /api/new-link     tạo link Cloudflare mới
  POST /api/restart      khởi động lại server
  POST /api/reboot       khởi động lại cả board
  GET  /api/wifi/scan    quét các mạng Wi-Fi xung quanh (2.4 + 5 GHz)
  GET  /api/wifi/status  mạng Wi-Fi board đang bắt để lấy Internet + tiến trình kết nối
  POST /api/wifi/connect {"ssid", "key", "band": "2g"|"5g", "encryption"?}
                         bắt mạng mới (chạy nền, tự quay về mạng cũ nếu thất bại)
  GET  /api/lan          IP LAN của board, dải mạng, dải DHCP + tiến trình đổi
  POST /api/lan          {"ip", "prefix", "dhcp_start", "dhcp_limit"} đổi IP LAN; phải gọi
                         /api/lan/confirm từ IP mới trong thời hạn, nếu không sẽ tự quay về IP cũ
  GET  /api/lan/confirm?token=...
  GET  /api/music        danh sách bài hát trong /mnt/data/music (music.py)
  GET  /music/file?id=   phát nhạc (có Range để tua);  GET /music/cover?id=  ảnh bìa
  POST /api/music/upload?name=<file>  thân request = nội dung file;  POST /api/music/delete {"id"}
  GET  /api/speaker      trạng thái phát ra loa USB của board (speaker.py)
  POST /api/speaker      {"action": play{ids,index}|toggle|pause|resume|stop|next|prev|seek{pos}|
                          volume{volume}|shuffle{on}|repeat{on}}
  GET  /api/traffic?day=YYYY-MM-DD   máy nào vào trang nào trong ngày (log DNS, traffic.py) + dung lượng (nlbwmon)
  GET  /api/traffic/recent?mac=&since=  các tên miền vừa truy cập
  GET  /api/vpn/status?check=1   VPN cho mạng WiFi: bật/tắt, đã kết nối, IP + nước ra Internet
  GET  /api/vpn/vpngate          danh sách nước / máy chủ VPN Gate (miễn phí)
  POST /api/vpn/vpngate {cc, host?}   dùng VPN Gate nước đó
  POST /api/vpn/upload?name=     thân = file WireGuard .conf / OpenVPN .ovpn (header X-VPN-User / X-VPN-Pass nếu cần)
  POST /api/vpn/enable {on}      bật / tắt VPN cho mạng WiFi

IoT (iot.py, trang /iot): mật khẩu riêng, khác mật khẩu quản trị. Quản trị viên (trong mạng nội bộ hoặc đã
đăng nhập) cũng vào được; người chỉ có mật khẩu IoT thì chỉ vào được /iot và /api/iot/*.
  GET  /iot                      trang IoT
  GET  /api/iot/whoami           {iot, admin, password_set}
  POST /api/iot/login {"password"} / POST /api/iot/logout
  POST /api/iot/password {"new"}  đặt mật khẩu IoT (chỉ quản trị viên; "new" rỗng = xóa mật khẩu)
  GET  /api/iot/devices          thiết bị + giá trị mới nhất + trạng thái broker
  GET  /api/iot/history?topic=&range=1h|6h|24h|7d|30d
  GET  /api/iot/controls         POST /api/iot/controls {"items": [...]}  lưu danh sách nút điều khiển
  POST /api/iot/control {"id", "value"?}    bấm nút điều khiển
  POST /api/iot/publish {"topic", "payload", "retain"?}   gửi tin MQTT (topic iot/...)
  POST /api/iot/delete-device {"id"}        xóa dữ liệu của một thiết bị
  GET  /api/iot/accounts         tài khoản MQTT của thiết bị (mỗi tài khoản <tên> chỉ dùng iot/<tên>/#)
  POST /api/iot/accounts {"action": "create"|"reset"|"delete", "name", "note"?}  tạo / đổi mật khẩu / xóa

Kho linh kiện (kho.py, trang /kho), cần quyền quản trị:
  GET  /api/kho/meta                         tổng số, sắp hết, danh sách loại / vị trí
  GET  /api/kho/parts?q=&category=&location=&low=1&sort=&limit=&offset=
  GET  /api/kho/part?id=                     chi tiết + mã nhà cung cấp + lịch sử + BOM dùng nó
  POST /api/kho/part {id?, mpn, name, qty, min_qty, ..., suppliers: [{supplier, sku, url, price}]}
  POST /api/kho/part/delete {id}
  POST /api/kho/stock {id, delta | set, reason?, ref?}       nhập / xuất / kiểm kê
  POST /api/kho/preview?name=<file>&kind=bom|stock   thân = nội dung file CSV/XLSX -> {token, headers, mapping}
  POST /api/kho/import {token, mapping, mode: add|set, supplier?, location?, category?}   nhập đơn hàng
  POST /api/kho/bom/create {token, mapping, name?, boards?}
  GET  /api/kho/boms        GET /api/kho/bom?id=&boards=
  POST /api/kho/bom/update {id, name?, boards?}    POST /api/kho/bom/line {line_id, part_id?, qty?, dnp?}
  POST /api/kho/bom/rematch {id}   POST /api/kho/bom/add-missing {id}   POST /api/kho/bom/consume {id, boards}
  POST /api/kho/bom/delete {id}
  GET  /api/kho/bom/shortage.csv?id=&boards=&supplier=lcsc|all    GET /api/kho/export.csv
  POST /api/kho/scan {code}      đọc mã quét (QR nhãn LCSC, DataMatrix Digi-Key, mã C…, chữ) -> linh kiện khớp,
                                 nhãn đã nhập chưa, thông tin LCSC gợi ý
  POST /api/kho/scan/apply {code, action: add|create, qty?, part_id?, fields?}   nhập số lượng của nhãn
  GET  /api/kho/lcsc?code=C123   thông tin sản phẩm từ LCSC (lưu đệm)
  Nhiều người dùng: mỗi linh kiện / BOM có chủ sở hữu (owner_id: 0 = của mình, N = khách N).
  Quản lý (quản trị board) xem mọi thứ, lọc bằng ?owner=all|0|N, tạo mới với "owner_id".
  Khách đăng nhập bằng tài khoản kho (cookie bpi_kho): chỉ thấy hàng + BOM của mình, chỉ xem / kiểm tra BOM.
  GET  /api/kho/whoami           {role: admin|customer|null, customer?, customers?}
  POST /api/kho/login {username, password}   POST /api/kho/logout
  GET  /api/kho/customers        POST /api/kho/customers {action: save|delete, id?, name, phone?, note?}
  POST /api/kho/users {action: save|delete, customer_id, username, password?}   (mật khẩu trống = tự tạo)
  POST /api/kho/part/lcsc-fill {id, overwrite?}   điền thông tin còn trống từ LCSC

Mọi POST bắt buộc có header "X-BPI: 1". Trình duyệt không cho trang web lạ tự gắn header này
khi gửi sang board (CORS), và cookie phiên là SameSite=Strict, nên trang độc hại không bấm hộ được.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import threading
import time
import http.client
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8080"))
HERE = os.path.dirname(os.path.abspath(__file__))
LED = "/sys/class/leds/blue:status"
TUNNEL_LOG = "/tmp/cftunnel.log"
SSH_TUNNEL_LOG = "/tmp/sshtunnel.log"
LOCAL_NETS = [ipaddress.ip_network(n) for n in ("192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12")]
# Chế độ máy tính (desktop.py, chạy trên Windows/Linux/Pi): chỉ kho + IoT, tắt các tab của router.
# Chỉ chính máy đó (127.0.0.1) được coi là "nội bộ"; máy khác trong mạng phải đăng nhập bằng mật khẩu.
DESKTOP = os.environ.get("BPI_DESKTOP") == "1"
if DESKTOP:
    LOCAL_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128")]


# ---------------------------------------------------------------- helpers
def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def write(path, value):
    with open(path, "w", encoding="utf-8") as f:
        f.write(value)


def run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return f"[lỗi] {e}"


def detach(shell_cmd):
    """Chạy lệnh tách hẳn khỏi server (để server trả lời xong rồi mới restart/reboot)."""
    subprocess.Popen(["start-stop-daemon", "-S", "-b", "-x", "/bin/sh", "--", "-c", shell_cmd])


def ap_interfaces():
    return sorted(i for i in os.listdir("/sys/class/net") if "-ap" in i)


def band_of(iface):
    out = run(["iw", "dev", iface, "info"])
    m = re.search(r"channel \d+ \((\d+) MHz", out)
    if not m:
        return "?"
    return "5 GHz" if int(m.group(1)) > 4000 else "2.4 GHz"


def stations():
    """{mac: {iface, band, signal, connected_s}} cho mọi máy đang bắt Wi-Fi."""
    result = {}
    for iface in ap_interfaces():
        band = band_of(iface)
        mac = None
        for line in run(["iw", "dev", iface, "station", "dump"]).splitlines():
            line = line.strip()
            if line.startswith("Station "):
                mac = line.split()[1].lower()
                result[mac] = {"iface": iface, "band": band}
            elif mac and line.startswith("signal:"):
                result[mac]["signal"] = int(line.split()[1])
            elif mac and line.startswith("connected time:"):
                result[mac]["connected_s"] = int(line.split()[2])
    return result


def temps():
    out = {}
    base = "/sys/class/hwmon"
    for h in sorted(os.listdir(base)):
        name = read(f"{base}/{h}/name")
        t = read(f"{base}/{h}/temp1_input")
        if t.lstrip("-").isdigit():
            out[{"cpu_thermal": "CPU", "mt7915_phy0": "Wi-Fi 2.4G",
                 "mt7915_phy1": "Wi-Fi 5G"}.get(name, name)] = round(int(t) / 1000, 1)
    return out


def led_mode():
    trig = re.search(r"\[([^\]]+)\]", read(f"{LED}/trigger"))
    trig = trig.group(1) if trig else "none"
    if trig == "timer":
        return "blink"
    if trig == "heartbeat":
        return "heartbeat"
    return "on" if read(f"{LED}/brightness", "0") != "0" else "off"


def public_url(log=TUNNEL_LOG):
    m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", read(log))
    return m[-1] if m else None


def ssh_host():
    """Hostname SSH từ xa (dịch vụ sshtunnel), hoặc None nếu chưa bật."""
    u = public_url(SSH_TUNNEL_LOG)
    return u[len("https://"):] if u else None


# ---------------------------------------------------------------- data
def status():
    mem = {}
    for line in read("/proc/meminfo").splitlines():
        key, _, val = line.partition(":")
        mem[key] = int(val.split()[0]) // 1024  # MB
    t = temps()
    return {
        "hostname": read("/proc/sys/kernel/hostname"),
        "uptime_s": int(float(read("/proc/uptime", "0").split()[0])),
        "load": read("/proc/loadavg").split()[:3],
        "mem_total_mb": mem.get("MemTotal"),
        "mem_free_mb": mem.get("MemAvailable"),
        "cpu_temp_c": t.get("CPU"),
        "temps": t,
        "wifi_clients": len(stations()),
        "led": led_mode(),
        "camera": {"on": CAMERA is not None, "viewers": CAMERA.viewers if CAMERA else 0,
                   "fps": CAMERA_FPS, "live": isinstance(CAMERA, LiveCamera),
                   "size": CAMERA_SIZE if isinstance(CAMERA, LiveCamera) else "768x576",
                   "error": getattr(CAMERA, "error", "")},
        "epoch": int(time.time()),
    }


def clients():
    leases = {}
    for line in read("/tmp/dhcp.leases").splitlines():
        p = line.split()
        if len(p) >= 4:
            leases[p[1].lower()] = {"ip": p[2], "name": p[3] if p[3] != "*" else ""}
    out = []
    for mac, st in stations().items():
        info = leases.get(mac, {})
        out.append({"mac": mac, "ip": info.get("ip", ""), "name": info.get("name", ""), **st})
    return sorted(out, key=lambda c: c.get("signal", -100), reverse=True)


def get_log(src):
    if src == "tunnel":
        lines = []
        for raw in read(TUNNEL_LOG).splitlines()[-200:]:
            try:
                j = json.loads(raw)
                lines.append(f'{j.get("time", "")} {j.get("level", "")}: {j.get("message", "")}')
            except ValueError:
                lines.append(raw)
        return "\n".join(lines[-60:])
    if src == "system":
        return "\n".join(run(["logread"]).splitlines()[-60:])
    return "\n".join(run(["logread", "-e", "python3"]).splitlines()[-60:])


def set_led(mode):
    if mode == "blink":
        write(f"{LED}/trigger", "timer")
        write(f"{LED}/delay_on", "300")
        write(f"{LED}/delay_off", "300")
    elif mode == "heartbeat":
        write(f"{LED}/trigger", "heartbeat")
    elif mode in ("on", "off"):
        write(f"{LED}/trigger", "none")
        write(f"{LED}/brightness", "1" if mode == "on" else "0")
    else:
        raise ValueError("mode phải là on, off, blink hoặc heartbeat")
    return led_mode()


def new_link():
    old = public_url()
    subprocess.run(["/etc/init.d/cftunnel", "restart"], capture_output=True, timeout=20)
    for _ in range(30):
        time.sleep(1)
        url = public_url()
        if url and url != old:
            return url
    return public_url()


# ---------------------------------------------------------------- Wi-Fi WAN (scan + connect)
AP_CHANNEL = {"2g": "auto", "5g": "36"}  # kênh phát của board khi radio không dùng để bắt mạng
WIFI_JOB = {"state": "idle", "msg": "", "ssid": ""}  # idle | running | ok | failed
WIFI_LOCK = threading.Lock()


def ubus(obj, method, args=None, timeout=30):
    out = run(["ubus", "call", obj, method, json.dumps(args or {})], timeout)
    try:
        return json.loads(out)
    except ValueError:
        return {}


def uci_get(key):
    out = run(["uci", "-q", "get", key]).strip()
    return "" if out.startswith("[lỗi]") else out


def uci(*args):
    subprocess.run(["uci", *args], capture_output=True, timeout=10)


def radios():
    """{"2g": "radio0", "5g": "radio1"}"""
    out = {}
    for line in run(["uci", "show", "wireless"]).splitlines():
        m = re.match(r"wireless\.(\w+)\.band='?(\w+)'?", line)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def wifi_ifaces():
    """{"phy0": ["phy0-ap0", "phy0-sta0"], ...}"""
    out = {}
    for d in ubus("iwinfo", "devices").get("devices", []):
        out.setdefault(d.split("-")[0], []).append(d)
    return out


def sta_iface():
    for devs in wifi_ifaces().values():
        for d in devs:
            if "-sta" in d:
                return d
    return None


def encryption_of(e):
    if not e or not e.get("enabled"):
        return "none"
    auth, wpa = e.get("authentication", []), e.get("wpa", [])
    if "802.1x" in auth:
        return "enterprise"
    if "sae" in auth:
        return "sae-mixed" if "psk" in auth else "sae"
    if "psk" in auth:
        return "psk-mixed" if 1 in wpa else "psk2"
    return "wep" if e.get("wep") else "unknown"


ENC_TEXT = {"none": "Mở (không mật khẩu)", "psk2": "WPA2", "psk-mixed": "WPA/WPA2", "sae": "WPA3",
            "sae-mixed": "WPA2/WPA3", "enterprise": "Doanh nghiệp (không hỗ trợ)",
            "wep": "WEP (không hỗ trợ)", "unknown": "Không rõ"}


def wifi_scan():
    best = {}
    for devs in wifi_ifaces().values():
        for r in ubus("iwinfo", "scan", {"device": devs[0]}, timeout=40).get("results", []):
            ssid = r.get("ssid")
            band = {2: "2g", 5: "5g"}.get(r.get("band"))
            if not ssid or not band:
                continue
            enc = encryption_of(r.get("encryption"))
            item = {"ssid": ssid, "band": band, "channel": r.get("channel"), "signal": r.get("signal"),
                    "quality": round(100 * r.get("quality", 0) / max(r.get("quality_max", 70), 1)),
                    "encryption": enc, "enc_text": ENC_TEXT.get(enc, enc),
                    "supported": enc not in ("enterprise", "wep", "unknown")}
            key = (ssid, band)
            if key not in best or (item["signal"] or -999) > (best[key]["signal"] or -999):
                best[key] = item
    cur = uci_get("wireless.wwan.ssid")
    cur_band = next((b for b, r in radios().items() if r == uci_get("wireless.wwan.device")), "")
    for it in best.values():
        it["current"] = it["ssid"] == cur and it["band"] == cur_band
    return sorted(best.values(), key=lambda x: (not x["current"], -(x["signal"] or -999)))


def wan_ip():
    st = ubus("network.interface.wwan", "status")
    addrs = st.get("ipv4-address") or []
    return addrs[0]["address"] if st.get("up") and addrs else None


def wifi_status():
    sta = sta_iface()
    info = ubus("iwinfo", "info", {"device": sta}) if sta else {}
    connected = info.get("mode") == "Client" and bool(info.get("ssid"))
    band = next((b for b, r in radios().items() if r == uci_get("wireless.wwan.device")), "")
    return {
        "ssid": uci_get("wireless.wwan.ssid"),
        "band": band,
        "connected": connected,
        "signal": info.get("signal") if connected else None,
        "channel": info.get("channel") if connected else None,
        "bitrate_mbps": round(info.get("bitrate", 0) / 1000) if connected else None,
        "ip": wan_ip(),
        "job": dict(WIFI_JOB),
    }


def apply_wwan(radio, ssid, key, enc):
    for band, r in radios().items():
        uci("set", f"wireless.{r}.channel={'auto' if r == radio else AP_CHANNEL.get(band, 'auto')}")
    uci("set", f"wireless.wwan.device={radio}")
    uci("set", f"wireless.wwan.ssid={ssid}")
    uci("set", f"wireless.wwan.encryption={enc}")
    if enc == "none" or not key:
        uci("-q", "delete", "wireless.wwan.key")
    else:
        uci("set", f"wireless.wwan.key={key}")
    uci("-q", "delete", "wireless.wwan.disabled")
    uci("commit", "wireless")
    subprocess.run(["wifi", "reload"], capture_output=True, timeout=30)


def wait_connected(ssid, timeout=40):
    time.sleep(5)  # chờ wifi reload xong, tránh đọc nhầm IP của mạng cũ
    end = time.time() + timeout
    while time.time() < end:
        sta = sta_iface()
        info = ubus("iwinfo", "info", {"device": sta}) if sta else {}
        ip = wan_ip()
        if info.get("ssid") == ssid and ip:
            return ip
        time.sleep(2)
    return None


def connect_job(ssid, key, enc, band):
    prev = {k: uci_get(f"wireless.wwan.{k}") for k in ("device", "ssid", "key", "encryption")}
    radio = radios().get(band)
    try:
        apply_wwan(radio, ssid, key, enc)
        ip = wait_connected(ssid)
        if ip and ipaddress.ip_address(ip) in lan_network():
            reason = (f"Mạng '{ssid}' cấp IP {ip}, trùng dải {lan_network()} của board. "
                      "Đổi dải mạng LAN của board trước rồi thử lại. Đã quay về mạng cũ.")
        elif ip:
            LAST_WAN_NETS.clear()  # mạng mới -> quên dải của mạng cũ
            wan_networks()
            WIFI_JOB.update(state="ok", msg=f"Đã kết nối '{ssid}', IP {ip}.")
            return
        else:
            reason = f"Không kết nối được '{ssid}' (sai mật khẩu hoặc sóng yếu). Đã quay về mạng cũ."
        if prev["ssid"]:
            prev_band = next((b for b, r in radios().items() if r == prev["device"]), band)
            apply_wwan(prev["device"] or radio, prev["ssid"], prev["key"], prev["encryption"] or "psk2")
            wait_connected(prev["ssid"])
            reason += f" (đang dùng lại '{prev['ssid']}' {('5 GHz' if prev_band == '5g' else '2.4 GHz')})"
        WIFI_JOB.update(state="failed", msg=reason)
    except Exception as e:  # noqa: BLE001 - báo mọi lỗi lên giao diện
        WIFI_JOB.update(state="failed", msg=f"Lỗi: {e}")
    finally:
        WIFI_LOCK.release()


def wifi_connect(body):
    ssid = str(body.get("ssid", "")).strip()
    key = str(body.get("key", ""))
    band = body.get("band", "2g")
    enc = body.get("encryption") or ("psk2" if key else "none")
    if not 1 <= len(ssid.encode()) <= 32:
        raise ValueError("Tên Wi-Fi (SSID) không hợp lệ")
    if band not in radios():
        raise ValueError("Băng tần phải là 2g hoặc 5g")
    if enc not in ("none", "psk2", "psk-mixed", "sae", "sae-mixed"):
        raise ValueError("Board chưa hỗ trợ kiểu bảo mật này")
    if enc != "none" and not 8 <= len(key) <= 63:
        raise ValueError("Mật khẩu Wi-Fi phải dài 8–63 ký tự")
    if not WIFI_LOCK.acquire(blocking=False):
        raise ValueError("Đang kết nối một mạng khác, chờ chút")
    WIFI_JOB.update(state="running", msg=f"Đang kết nối '{ssid}'…", ssid=ssid)
    threading.Thread(target=connect_job, args=(ssid, key, enc, band), daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------- LAN (IP của board + DHCP)
LAN_JOB = {"state": "idle", "msg": "", "new_ip": "", "token": "", "deadline": 0}
LAN_LOCK = threading.Lock()
LAN_CONFIRMED = threading.Event()


def lan_config():
    raw = uci_get("network.lan.ipaddr") or "192.168.1.1"
    if "/" not in raw:
        raw += "/" + (uci_get("network.lan.netmask") or "255.255.255.0")
    iface = ipaddress.ip_interface(raw)
    start = int(uci_get("dhcp.lan.start") or 100)
    limit = int(uci_get("dhcp.lan.limit") or 150)
    net = iface.network
    return {"ip": str(iface.ip), "prefix": net.prefixlen, "netmask": str(net.netmask), "network": str(net),
            "dhcp_start": start, "dhcp_limit": limit,
            "dhcp_from": str(net.network_address + start), "dhcp_to": str(net.network_address + start + limit - 1)}


def lan_network():
    c = lan_config()
    return ipaddress.ip_interface(f"{c['ip']}/{c['prefix']}").network


LAST_WAN_NETS = set()


def wan_networks():
    """Dải mạng phía Internet. Nhớ cả dải đã thấy trước đó, vì lúc Wi-Fi đang kết nối lại
    interface chưa có IP và nếu chỉ đọc trạng thái hiện tại sẽ bỏ sót trùng dải."""
    for iface in ("wan", "wwan"):
        for a in ubus(f"network.interface.{iface}", "status").get("ipv4-address") or []:
            LAST_WAN_NETS.add(ipaddress.ip_interface(f"{a['address']}/{a['mask']}").network)
    return sorted(LAST_WAN_NETS)


def apply_lan(ip, prefix, start, limit):
    uci("set", f"network.lan.ipaddr={ip}/{prefix}")
    uci("-q", "delete", "network.lan.netmask")
    uci("set", f"dhcp.lan.start={start}")
    uci("set", f"dhcp.lan.limit={limit}")
    uci("commit", "network")
    uci("commit", "dhcp")
    # restart (không phải reload) để cổng mạng và Wi-Fi rớt một nhịp, các máy tự xin IP mới.
    subprocess.run(["/etc/init.d/network", "restart"], capture_output=True, timeout=60)
    subprocess.run(["/etc/init.d/dnsmasq", "restart"], capture_output=True, timeout=30)


def lan_job(new, old, wait_s):
    try:
        time.sleep(1)  # để kịp trả lời request trước khi mạng khởi động lại
        apply_lan(*new)
        if LAN_CONFIRMED.wait(wait_s):
            LAN_JOB.update(state="ok", msg=f"Đã đổi IP board sang {new[0]}.")
        else:
            apply_lan(*old)
            LAN_JOB.update(state="failed",
                           msg=f"Không có ai xác nhận IP mới {new[0]} trong {wait_s} giây, đã quay về {old[0]}.")
    except Exception as e:  # noqa: BLE001
        LAN_JOB.update(state="failed", msg=f"Lỗi: {e}")
    finally:
        LAN_JOB["token"] = ""
        LAN_LOCK.release()


def lan_change(body):
    try:
        ip = ipaddress.ip_address(str(body.get("ip", "")).strip())
        prefix = int(body.get("prefix", 24))
        start = int(body.get("dhcp_start", 100))
        limit = int(body.get("dhcp_limit", 150))
    except (ValueError, TypeError):
        raise ValueError("IP hoặc số không hợp lệ")
    wait_s = max(60, min(int(body.get("wait_s", 180)), 600))
    if ip.version != 4 or not ip.is_private:
        raise ValueError("IP phải là địa chỉ IPv4 nội bộ (192.168.x.x, 10.x.x.x, 172.16–31.x.x)")
    if not 16 <= prefix <= 28:
        raise ValueError("Dải mạng phải từ /16 đến /28")
    net = ipaddress.ip_interface(f"{ip}/{prefix}").network
    if ip in (net.network_address, net.broadcast_address):
        raise ValueError(f"{ip} là địa chỉ mạng hoặc broadcast của {net}, chọn IP khác (thường là .1)")
    for w in wan_networks():
        if net.overlaps(w):
            raise ValueError(f"Dải {net} trùng với mạng Internet board đang bắt ({w}). Chọn dải khác.")
    if start < 1 or limit < 1 or start + limit >= net.num_addresses - 1:
        raise ValueError(f"Dải DHCP vượt quá {net} (tối đa {net.num_addresses - 2} địa chỉ)")
    cur = lan_config()
    if (str(ip), prefix, start, limit) == (cur["ip"], cur["prefix"], cur["dhcp_start"], cur["dhcp_limit"]):
        raise ValueError("Không có gì thay đổi")
    if not LAN_LOCK.acquire(blocking=False):
        raise ValueError("Đang đổi mạng LAN, chờ chút")
    token = os.urandom(8).hex()
    LAN_CONFIRMED.clear()
    LAN_JOB.update(state="running", new_ip=str(ip), token=token, deadline=int(time.time()) + wait_s,
                   msg=f"Đang đổi IP board sang {ip}…")
    old = (cur["ip"], cur["prefix"], cur["dhcp_start"], cur["dhcp_limit"])
    threading.Thread(target=lan_job, args=((str(ip), prefix, start, limit), old, wait_s), daemon=True).start()
    return {"token": token, "new_ip": str(ip), "wait_s": wait_s}


def lan_status():
    job = {k: v for k, v in LAN_JOB.items() if k != "token"}
    return {**lan_config(), "job": job}


# ---------------------------------------------------------------- Camera (USB thật, hoặc video mẫu nếu không có)
CAMERA_FILE = os.environ.get("CAMERA_FILE", "/mnt/data/camera/vtest.mjpeg")
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "10"))
CAMERA_DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")       # webcam UVC (kmod-video-uvc)
CAMERA_SIZE = os.environ.get("CAMERA_SIZE", "1280x720")              # camera xuất MJPEG sẵn ở độ phân giải này
GRAY_W, GRAY_H = 192, 144                                            # ảnh xám nhỏ để nhận dạng chuyển động


class Camera:
    """Phát lặp các khung JPEG của một file .mjpeg với tốc độ cố định, như một camera IP.
    Một luồng nền đẩy khung mới; mỗi người xem chờ khung kế tiếp qua Condition."""

    def __init__(self, path, fps, vision=None):
        data = open(path, "rb").read()
        starts = [m.start() for m in re.finditer(b"\xff\xd8\xff", data)]
        self.frames = [data[a:b] for a, b in zip(starts, starts[1:] + [len(data)])]
        if not self.frames:
            raise ValueError(f"{path} không có khung JPEG nào")
        self.fps = fps
        self.vision = vision          # bộ nhận dạng người (vision.Vision) hoặc None
        self.detections = None        # kết quả nhận dạng của khung hiện tại
        self.frame, self.seq, self.viewers = self.frames[0], 0, 0
        self.cond = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        i, nxt = 0, time.monotonic()
        while True:
            det = None
            if self.vision:
                try:
                    det = self.vision.process(i)   # ~11 ms/khung trên BPI-R3, khung cách nhau 100 ms
                except Exception as e:  # noqa: BLE001 - lỗi nhận dạng không được làm dừng camera
                    print(f"Lỗi nhận dạng: {e}", flush=True)
            with self.cond:
                self.frame, self.seq, self.detections = self.frames[i], self.seq + 1, det
                self.cond.notify_all()
            i = (i + 1) % len(self.frames)
            nxt += 1 / self.fps
            time.sleep(max(0, nxt - time.monotonic()))

    def next_detection(self, last_seq, timeout=5):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.detections, self.seq

    def next_frame(self, last_seq, timeout=5):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.frame, self.seq


class LiveCamera:
    """Webcam USB qua ffmpeg. Một tiến trình ffmpeg xuất 2 luồng cùng lúc:
      - stdout: MJPEG gốc của camera (chép thẳng, không nén lại -> rất nhẹ CPU) cho người xem;
      - fd 3:   ảnh xám 192x144 (rawvideo) cho nhận dạng chuyển động.
    Rút camera / ffmpeg chết -> tự thử lại. Cùng giao diện với Camera (frame, seq, detections, next_*)."""

    def __init__(self, device, size, fps, vision=None):
        self.device, self.size, self.fps, self.vision = device, size, fps, vision
        self.frame, self.seq, self.viewers, self.detections = b"", 0, 0, None
        self.error = ""
        self.cond = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def _gray_reader(self, fd):
        n = GRAY_W * GRAY_H
        with os.fdopen(fd, "rb", buffering=0) as f:
            buf = b""
            while True:
                chunk = f.read(n - len(buf))
                if not chunk:
                    return
                buf += chunk
                if len(buf) < n:
                    continue
                g, buf = buf, b""
                if not self.vision:
                    continue
                try:
                    det = self.vision.process_gray(_vision.np.frombuffer(g, _vision.np.uint8).reshape(GRAY_H, GRAY_W))
                except Exception as e:  # noqa: BLE001 - lỗi nhận dạng không được làm dừng camera
                    print(f"Lỗi nhận dạng: {e}", flush=True)
                    continue
                with self.cond:
                    self.detections = det

    def _run(self):
        while True:
            if not os.path.exists(self.device):
                self.error = f"Không thấy {self.device} (camera chưa cắm?)"
                time.sleep(3)
                continue
            r, w = os.pipe()
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
                   "-f", "v4l2", "-input_format", "mjpeg", "-framerate", str(self.fps), "-video_size", self.size,
                   "-i", self.device,
                   "-map", "0:v", "-c:v", "copy", "-f", "mjpeg", "pipe:1",
                   "-map", "0:v", "-vf", f"scale={GRAY_W}:{GRAY_H},format=gray", "-f", "rawvideo", f"pipe:{w}"]
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(w,))
            except OSError as e:
                os.close(r); os.close(w)
                self.error = f"Không chạy được ffmpeg: {e}"
                time.sleep(5)
                continue
            os.close(w)
            threading.Thread(target=self._gray_reader, args=(r,), daemon=True).start()
            self.error = ""
            buf = b""
            try:
                while True:
                    chunk = p.stdout.read1(65536)
                    if not chunk:
                        break
                    buf += chunk
                    while True:   # tách từng ảnh JPEG: FFD8 ... FFD9
                        a = buf.find(b"\xff\xd8")
                        if a < 0:
                            buf = b""
                            break
                        b = buf.find(b"\xff\xd9", a + 2)
                        if b < 0:
                            buf = buf[a:]
                            if len(buf) > 4 << 20:   # dữ liệu hỏng
                                buf = b""
                            break
                        frame, buf = buf[a:b + 2], buf[b + 2:]
                        with self.cond:
                            self.frame, self.seq = frame, self.seq + 1
                            self.cond.notify_all()
            finally:
                p.kill()
                err = p.stderr.read().decode(errors="replace").strip()
                p.wait()
                self.error = err.splitlines()[-1] if err else "ffmpeg dừng"
                print(f"Camera: {self.error}, thử lại sau 3 giây", flush=True)
                time.sleep(3)

    def next_detection(self, last_seq, timeout=5):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.detections, self.seq

    def next_frame(self, last_seq, timeout=5):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq and self.frame, timeout)
            return self.frame, self.seq


TUNNEL_MIN_EVENT = 4096  # byte tối thiểu mỗi sự kiện SSE khi đi qua Cloudflare tunnel (xem stream_vision)
CAMERA_GRAY = os.environ.get("CAMERA_GRAY", "/mnt/data/camera/vtest_192x144.gray")  # ảnh xám nhỏ để phân tích

USE_LIVE = os.path.exists(CAMERA_DEVICE) and os.environ.get("CAMERA_MODE", "auto") != "file"
try:
    if DESKTOP:
        raise RuntimeError("chế độ máy tính")
    import vision as _vision
    if USE_LIVE:
        _w, _h = (int(v) for v in CAMERA_SIZE.split("x"))
        VISION = _vision.LiveVision(_w, _h)
    else:
        VISION = _vision.Vision(CAMERA_GRAY, 768, 576)
except Exception as e:  # noqa: BLE001 - thiếu numpy / thiếu file thì camera vẫn chạy, chỉ tắt nhận dạng
    print(f"Nhận dạng người tắt: {e}", flush=True)
    VISION = None

try:
    if DESKTOP:
        raise OSError("chế độ máy tính")
    if USE_LIVE:
        CAMERA = LiveCamera(CAMERA_DEVICE, CAMERA_SIZE, CAMERA_FPS, VISION)
        print(f"Camera thật: {CAMERA_DEVICE} {CAMERA_SIZE} {CAMERA_FPS} fps", flush=True)
    else:
        CAMERA = Camera(CAMERA_FILE, CAMERA_FPS, VISION)
except (OSError, ValueError) as e:
    print(f"Camera tắt: {e}", flush=True)
    CAMERA = None


# ---------------------------------------------------------------- Nhạc (music.py)
try:
    if DESKTOP:
        raise RuntimeError("chế độ máy tính")
    import music as _music
    MUSIC = _music.Library()
except Exception as e:  # noqa: BLE001
    print(f"Thư viện nhạc tắt: {e}", flush=True)
    MUSIC = None

try:
    import speaker as _speaker
    SPEAKER = _speaker.Speaker(MUSIC) if MUSIC else None
except Exception as e:  # noqa: BLE001
    print(f"Phát ra loa tắt: {e}", flush=True)
    SPEAKER = None


# ---------------------------------------------------------------- Thống kê truy cập web (traffic.py)
try:
    if DESKTOP:
        raise RuntimeError("chế độ máy tính")
    import traffic as _traffic
    TRAFFIC = _traffic.Traffic(lan_ips=[lan_config()["ip"]])
except Exception as e:  # noqa: BLE001
    print(f"Thống kê truy cập tắt: {e}", flush=True)
    TRAFFIC = None


# ---------------------------------------------------------------- VPN cho mạng WiFi (vpn.py)
try:
    if DESKTOP:
        raise RuntimeError("chế độ máy tính")
    import vpn as _vpn
except Exception as e:  # noqa: BLE001
    print(f"VPN tắt: {e}", flush=True)
    _vpn = None


# ---------------------------------------------------------------- Kho linh kiện (kho.py)
try:
    import kho as _kho
    KHO = _kho.Kho()
except Exception as e:  # noqa: BLE001
    print(f"Kho linh kiện tắt: {e}", flush=True)
    KHO = None


# ---------------------------------------------------------------- IoT / MQTT (iot.py)
import iot as _iot
IOT_AUTH = _iot.Auth()
IOT_ACCOUNTS = _iot.DeviceAccounts()
try:
    IOT = _iot.IoT()
except Exception as e:  # noqa: BLE001
    print(f"IoT tắt: {e}", flush=True)
    IOT = None


# ---------------------------------------------------------------- Đăng nhập (truy cập từ Internet)
AUTH_FILE = os.environ.get("BPI_AUTH_FILE", "/etc/bpi-web-auth.json")   # nằm trong overlay, giữ qua khởi động lại
SESSION_DAYS = 7
PBKDF2_ITER = 200_000
MAX_FAILS, LOCK_SECONDS = 5, 300
COOKIE = "bpi_session"
AUTH_LOCK = threading.Lock()
FAILS = {}  # ip -> [số lần sai, khóa tới thời điểm]


def load_auth():
    try:
        with open(AUTH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_auth(data):
    tmp = AUTH_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, AUTH_FILE)


def _pw_hash(pw, salt, it):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), it).hex()


def password_is_set():
    return bool(load_auth().get("password"))


def check_password(pw):
    p = load_auth().get("password")
    return bool(p) and hmac.compare_digest(_pw_hash(pw, p["salt"], p["it"]), p["hash"])


def _token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()  # file chỉ lưu băm của token


def new_session():
    token = secrets.token_urlsafe(32)
    with AUTH_LOCK:
        a = load_auth()
        now = time.time()
        sess = {k: v for k, v in a.get("sessions", {}).items() if v > now}
        sess[_token_key(token)] = now + SESSION_DAYS * 86400
        a["sessions"] = sess
        save_auth(a)
    return token


def session_valid(token):
    if not token:
        return False
    exp = load_auth().get("sessions", {}).get(_token_key(token))
    return bool(exp) and exp > time.time()


def end_session(token):
    with AUTH_LOCK:
        a = load_auth()
        if a.get("sessions", {}).pop(_token_key(token or ""), None) is not None:
            save_auth(a)


def set_password(new):
    if len(new) < 8:
        raise ValueError("Mật khẩu phải dài ít nhất 8 ký tự")
    salt = secrets.token_hex(16)
    with AUTH_LOCK:
        a = load_auth()
        a["password"] = {"salt": salt, "it": PBKDF2_ITER, "hash": _pw_hash(new, salt, PBKDF2_ITER)}
        a["sessions"] = {}  # đổi mật khẩu -> đăng xuất mọi phiên cũ
        save_auth(a)


def try_login(ip, pw):
    """Trả về token nếu đúng. Sai MAX_FAILS lần liên tiếp từ cùng IP -> khóa LOCK_SECONDS giây."""
    now = time.time()
    with AUTH_LOCK:
        cnt, until = FAILS.get(ip, [0, 0])
        if until > now:
            raise PermissionError(f"Sai quá nhiều lần, thử lại sau {int(until - now)} giây")
    if not password_is_set():
        raise ValueError("Chủ board chưa đặt mật khẩu truy cập từ xa (tab Hệ thống, khi ở mạng nội bộ)")
    if check_password(pw):
        with AUTH_LOCK:
            FAILS.pop(ip, None)
        return new_session()
    time.sleep(1)  # làm chậm việc dò mật khẩu
    with AUTH_LOCK:
        cnt += 1
        FAILS[ip] = [0, now + LOCK_SECONDS] if cnt >= MAX_FAILS else [cnt, 0]
        left = MAX_FAILS - cnt
    raise PermissionError("Sai mật khẩu" + (f", còn {left} lần thử" if left > 0 else
                                            f", bị khóa {LOCK_SECONDS // 60} phút"))


# ---------------------------------------------------------------- HTTP
DESKTOP_API = ("/api/kho/", "/api/iot/", "/api/login", "/api/logout", "/api/whoami", "/api/password")


def desktop_blocked(path):
    """Chế độ máy tính: API của router (Wi-Fi, LAN, VPN, LED, camera, nhạc…) không có."""
    return DESKTOP and (path.startswith(LUCI_PREFIXES) or (path.startswith("/api/") and not path.startswith(DESKTOP_API))
                        or path.startswith(("/camera", "/music/")))


PUBLIC_PATHS = {"/", "/index.html", "/api/whoami", "/api/login"}

# LuCI (uhttpd cổng 80) đi chung link công khai: các đường dẫn này được chuyển tiếp sang LuCI,
# nhưng chỉ sau khi đã đăng nhập web panel (trong mạng nội bộ thì như cũ). LuCI vẫn hỏi mật khẩu root riêng.
LUCI_PREFIXES = ("/cgi-bin/", "/luci-static/", "/ubus")
LUCI_MAX_BODY = 100 * 1024 * 1024   # đủ cho file firmware; Cloudflare cũng giới hạn ~100 MB
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
               "transfer-encoding", "upgrade", "host", "content-length"}


class Handler(BaseHTTPRequestHandler):
    def is_local(self):
        # Request qua Cloudflare Tunnel đến từ chính board (127.0.0.1) kèm header Cf-Connecting-IP,
        # nên chỉ coi là "nội bộ" khi đến thẳng từ một IP mạng LAN.
        if self.headers.get("Cf-Connecting-IP"):
            return False
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(ip in n for n in LOCAL_NETS)

    def via_proxy(self):
        """Request đi qua Cloudflare Tunnel hoặc Tailscale Funnel (cả hai đều tới từ 127.0.0.1, là HTTPS)."""
        return bool(self.headers.get("Cf-Connecting-IP")) or (
            self.client_address[0] in ("127.0.0.1", "::1") and bool(self.headers.get("X-Forwarded-For")))

    def client_ip(self):
        # IP thật của người dùng (để khóa đúng người khi sai mật khẩu nhiều lần).
        if self.headers.get("Cf-Connecting-IP"):
            return self.headers["Cf-Connecting-IP"]
        if self.via_proxy():
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return self.client_address[0]

    def session_token(self, name=COOKIE):
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return ""
        return c[name].value if name in c else ""

    def is_iot(self):
        """Vào được trang IoT: quản trị viên, hoặc đã đăng nhập bằng mật khẩu IoT."""
        return self.is_admin() or IOT_AUTH.valid(self.session_token(IOT_AUTH.COOKIE))

    def is_authed(self):
        return session_valid(self.session_token())

    def is_admin(self):
        """Trong mạng nội bộ: luôn có quyền. Qua Internet: phải đăng nhập."""
        return self.is_local() or self.is_authed()

    def cookie_header(self, token, max_age, name=COOKIE):
        secure = "; Secure" if self.via_proxy() else ""  # qua tunnel/Funnel là HTTPS
        return f"{name}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

    def _send(self, code, body, ctype="application/json", headers=None):
        if not isinstance(body, (str, bytes)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        text = ctype.startswith("text/") or ctype == "application/json"
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if text and "charset" not in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def stream_camera(self):
        if CAMERA is None:
            return self._send(503, {"error": "Camera chưa sẵn sàng (thiếu file video)"})
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store, no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.connection.settimeout(15)  # người xem treo mạng thì thả luồng ra
        with CAMERA.cond:
            CAMERA.viewers += 1
        try:
            seq = -1
            while True:
                frame, seq = CAMERA.next_frame(seq)
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                self.wfile.flush()
        except OSError:  # người xem đóng trang / mất mạng
            pass
        finally:
            with CAMERA.cond:
                CAMERA.viewers -= 1

    def serve_file(self, path, ctype):
        """Gửi file có hỗ trợ Range (206): trình phát nhạc cần để tua, Safari/iPhone bắt buộc có."""
        size = os.path.getsize(path)
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:                                   # bytes=-N: N byte cuối
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if m and (m.group(1) or m.group(2)) else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if m and (m.group(1) or m.group(2)):
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        if self.command == "HEAD":
            return
        self.connection.settimeout(30)
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left:
                    chunk = f.read(min(left, 128 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except OSError:   # người nghe tua / chuyển bài -> trình duyệt đóng kết nối cũ
            pass

    def proxy_luci(self, length=0):
        """Chuyển tiếp request sang LuCI (127.0.0.1:80) và trả nguyên kết quả về."""
        if not self.is_admin():
            self.close_connection = True
            if self.command == "GET" and "text/html" in self.headers.get("Accept", ""):
                return self._send(302, "", "text/plain", headers={"Location": "/"})   # về trang đăng nhập
            return self.need_login()
        if length > LUCI_MAX_BODY:
            self.close_connection = True
            return self._send(413, {"error": "quá lớn"})
        body = self.rfile.read(length) if length else None
        hdrs = {k: v for k, v in self.headers.items()
                if k.lower() not in HOP_HEADERS and not k.lower().startswith("cf-")}
        # Không gửi cookie phiên của web panel sang LuCI.
        if "Cookie" in hdrs:
            hdrs["Cookie"] = "; ".join(c for c in hdrs["Cookie"].split("; ")
                                       if not c.startswith((COOKIE + "=", IOT_AUTH.COOKIE + "=", "bpi_kho=")))
        hdrs["Host"] = "127.0.0.1"
        hdrs["X-Forwarded-For"] = self.client_ip()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", 80, timeout=120)
            conn.request(self.command, self.path, body, hdrs)
            r = conn.getresponse()
        except OSError as e:
            return self._send(502, {"error": f"LuCI không phản hồi: {e}"})
        self.send_response(r.status, r.reason)
        for k, v in r.getheaders():
            if k.lower() not in HOP_HEADERS:
                self.send_header(k, v)
        # Server này trả lời HTTP/1.0: không biết trước độ dài thì gửi tới hết rồi đóng kết nối.
        clen = r.getheader("Content-Length")
        if clen is not None:
            self.send_header("Content-Length", clen)
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            if self.command != "HEAD":
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except OSError:
            pass
        finally:
            conn.close()

    def music_upload(self, url, length):
        """POST /api/music/upload?name=<tên file>, thân request là nội dung file (không multipart,
        để ghi thẳng xuống thẻ nhớ từng phần mà không giữ cả file trong RAM)."""
        def reject(code, msg):
            self.close_connection = True   # chưa đọc hết thân request -> đóng kết nối
            return self._send(code, {"error": msg})
        if self.headers.get("X-BPI") != "1":
            return reject(400, "thiếu header X-BPI")
        if not self.is_admin():
            self.close_connection = True
            return self.need_login()
        if MUSIC is None:
            return reject(503, "Thư viện nhạc chưa bật")
        try:
            rel = MUSIC.save_upload(parse_qs(url.query).get("name", [""])[0], length, self.rfile)
        except ValueError as e:
            return reject(400, str(e))
        except OSError as e:
            return reject(500, str(e))
        self._send(200, {"ok": True, "id": rel})

    def do_HEAD(self):
        if urlparse(self.path).path.startswith(LUCI_PREFIXES):
            return self.proxy_luci()
        if urlparse(self.path).path == "/music/file":
            return self.do_GET()
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def stream_vision(self):
        """Server-Sent Events: mỗi khung camera gửi 1 sự kiện JSON (khung người, ID, vệt đi, số người).

        Qua Cloudflare quick tunnel, gói nhỏ bị gom lại và không tới trình duyệt (đo thực tế: sự kiện
        ~1.5 KB thì 15 giây không nhận được byte nào; đủ ~4 KB thì tới ngay). Vì vậy khi xem qua tunnel,
        mỗi sự kiện được đệm thêm một dòng chú thích SSE (":" + khoảng trắng, trình duyệt bỏ qua) cho đủ
        TUNNEL_MIN_EVENT byte. Trong mạng nội bộ không đệm.
        """
        if CAMERA is None or CAMERA.vision is None:
            return self._send(503, {"error": "Nhận dạng người chưa bật (thiếu numpy hoặc file ảnh xám)"})
        target = TUNNEL_MIN_EVENT if self.headers.get("Cf-Connecting-IP") else 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store, no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.connection.settimeout(15)
        try:
            seq = -1
            while True:
                det, seq = CAMERA.next_detection(seq)
                if det is None:
                    continue
                ev = b"data: " + json.dumps(det, separators=(",", ":")).encode() + b"\n"
                pad = target - len(ev) - 3
                self.wfile.write(ev + (b":" + b" " * pad + b"\n" if pad > 0 else b"") + b"\n")
                self.wfile.flush()
        except OSError:
            pass

    def need_login(self):
        self._send(401, {"error": "Cần đăng nhập", "login": True})

    # ------------------------------------------------------------ kho: quyền
    def kho_ctx(self):
        """Quản lý (quản trị board): mọi chủ sở hữu. Khách (tài khoản kho): chỉ hàng của mình, chỉ xem + BOM."""
        if self.is_admin():
            return {"role": "admin", "scope": None}
        if KHO is not None:
            u = KHO.session_user(self.session_token(_kho.KHO_COOKIE))
            if u:
                return {"role": "customer", "scope": u["customer_id"], "user": u}
        return None

    @staticmethod
    def kho_owner_param(v):
        """owner trong query của quản lý: '' / 'all' = mọi chủ sở hữu, 0 = của mình, N = khách N."""
        v = str(v or "").strip()
        return None if v in ("", "all") else int(v)

    def kho_get(self, path, q, ctx):
        if KHO is None:
            return self._send(503, {"error": "Kho chưa bật (xem log server)"})
        g = lambda k, d="": q.get(k, [d])[0]  # noqa: E731
        admin = ctx["role"] == "admin"
        # phạm vi đọc: khách luôn bị giới hạn vào hàng của mình, quản lý chọn bằng ?owner=
        scope = self.kho_owner_param(g("owner")) if admin else ctx["scope"]
        mine = None if admin else ctx["scope"]
        if path == "/api/kho/meta":
            return self._send(200, KHO.meta(scope))
        if path == "/api/kho/parts":
            return self._send(200, KHO.list_parts(g("q"), g("category"), g("location"), g("low") == "1",
                                                  int(g("limit", "200") or 200), int(g("offset", "0") or 0),
                                                  g("sort", "updated"), owner=scope))
        if path == "/api/kho/part":
            return self._send(200, KHO.get_part(int(g("id", "0") or 0), mine))
        if path == "/api/kho/boms":
            return self._send(200, KHO.boms(scope))
        if path == "/api/kho/bom":
            return self._send(200, KHO.bom(int(g("id", "0") or 0), g("boards") or None, mine))
        if path == "/api/kho/bom/shortage.csv":
            bid = int(g("id", "0") or 0)
            csv_text = KHO.bom_shortage_csv(bid, g("boards") or None, g("supplier", "lcsc"), mine)
            return self._send(200, "\ufeff" + csv_text, "text/csv", headers={
                "Content-Disposition": f'attachment; filename="thieu-bom-{bid}.csv"'})
        if path == "/api/kho/export.csv":
            return self._send(200, KHO.export_csv(scope), "text/csv", headers={
                "Content-Disposition": f'attachment; filename="kho-{time.strftime("%Y%m%d")}.csv"'})
        if not admin:
            raise PermissionError("Tài khoản khách chỉ được xem")
        if path == "/api/kho/lcsc":
            return self._send(200, KHO.lcsc_info(g("code")))
        if path == "/api/kho/customers":
            return self._send(200, KHO.customers())
        return self._send(404, {"error": "not found"})

    # khách được dùng các thao tác này (chỉ trên BOM của mình)
    KHO_CUSTOMER_POST = {"/api/kho/bom/create", "/api/kho/bom/update", "/api/kho/bom/line", "/api/kho/bom/rematch",
                         "/api/kho/bom/delete"}

    def kho_post(self, path, body, ctx):
        if KHO is None:
            raise OSError("Kho chưa bật (xem log server)")
        i = lambda k: int(body.get(k) or 0)  # noqa: E731
        admin = ctx["role"] == "admin"
        if not admin and path not in self.KHO_CUSTOMER_POST:
            raise PermissionError("Tài khoản khách chỉ được xem và kiểm tra BOM")
        own = None if admin else ctx["scope"]                              # kiểm tra quyền trên BOM
        new_owner = body.get("owner_id", 0) if admin else ctx["scope"]     # chủ sở hữu của dữ liệu tạo mới
        # ---- BOM (quản lý + khách)
        if path == "/api/kho/bom/create":
            return self._send(200, KHO.bom_create(body.get("token", ""), body.get("mapping"), body.get("name", ""),
                                                  body.get("boards", 1), owner=new_owner))
        if path == "/api/kho/bom/update":
            return self._send(200, KHO.bom_update(i("id"), body.get("name"), body.get("boards"), body.get("notes"), own))
        if path == "/api/kho/bom/line":
            return self._send(200, KHO.bom_set_line(i("line_id"), body.get("part_id"), body.get("qty"),
                                                    body.get("dnp"), own))
        if path == "/api/kho/bom/rematch":
            return self._send(200, KHO.bom_rematch(i("id"), own))
        if path == "/api/kho/bom/delete":
            KHO.bom_delete(i("id"), own)
            return self._send(200, {"ok": True})
        # ---- chỉ quản lý
        if path == "/api/kho/part":
            return self._send(200, KHO.save_part(body))
        if path == "/api/kho/scan":
            return self._send(200, KHO.scan(body.get("code", ""), owner=new_owner))
        if path == "/api/kho/scan/apply":
            return self._send(200, KHO.scan_apply(body.get("code", ""), body.get("action", "add"), body.get("qty"),
                                                  body.get("part_id"), body.get("fields"), owner=new_owner))
        if path == "/api/kho/part/lcsc-fill":
            return self._send(200, KHO.fill_from_lcsc(i("id"), bool(body.get("overwrite"))))
        if path == "/api/kho/part/delete":
            KHO.delete_part(i("id"))
            return self._send(200, {"ok": True})
        if path == "/api/kho/stock":
            return self._send(200, KHO.adjust(i("id"), body.get("delta"), body.get("set"),
                                              body.get("reason", ""), body.get("ref", "")))
        if path == "/api/kho/import":
            return self._send(200, KHO.import_stock(body.get("token", ""), body.get("mapping"), body.get("mode", "add"),
                                                    body.get("supplier", ""), body.get("location", ""),
                                                    body.get("category", ""), body.get("ref", ""), owner=new_owner))
        if path == "/api/kho/bom/add-missing":
            return self._send(200, KHO.bom_add_missing(i("id")))
        if path == "/api/kho/bom/consume":
            return self._send(200, KHO.bom_consume(i("id"), body.get("boards")))
        if path == "/api/kho/customers":          # {action: save|delete, id?, name, phone, note}
            if body.get("action") == "delete":
                KHO.delete_customer(i("id"))
                return self._send(200, {"ok": True})
            return self._send(200, KHO.save_customer(body))
        if path == "/api/kho/users":              # {action: save|delete, customer_id, username, password?}
            if body.get("action") == "delete":
                KHO.delete_user(body.get("username", ""))
                return self._send(200, {"ok": True})
            return self._send(200, KHO.save_user(body.get("customer_id"), body.get("username"), body.get("password", "")))
        return self._send(404, {"error": "not found"})

    def kho_public(self, path, body):
        """Đăng nhập / đăng xuất tài khoản khách của kho, và cho trang biết mình là ai."""
        if path == "/api/kho/whoami":
            ctx = self.kho_ctx()
            if not ctx:
                return self._send(200, {"role": None})
            out = {"role": ctx["role"]}
            if ctx["role"] == "customer":
                out.update(username=ctx["user"]["username"],
                           customer={"id": ctx["scope"], "name": ctx["user"]["customer_name"]})
            elif KHO is not None:
                out["customers"] = [{"id": c["id"], "name": c["name"]} for c in KHO.customers()]
            return self._send(200, out)
        if KHO is None:
            raise OSError("Kho chưa bật")
        if path == "/api/kho/login":
            token = KHO.login(self.client_ip(), body.get("username", ""), body.get("password", ""))
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": self.cookie_header(token, _kho.SESSION_DAYS * 86400, _kho.KHO_COOKIE)})
        if path == "/api/kho/logout":
            KHO.logout(self.session_token(_kho.KHO_COOKIE))
            return self._send(200, {"ok": True}, headers={"Set-Cookie": self.cookie_header("", 0, _kho.KHO_COOKIE)})
        return self._send(404, {"error": "not found"})

    def vpn_upload(self, url, length):
        """POST /api/vpn/upload?name=: thân = file cấu hình; tài khoản (nếu cần) qua header, không qua URL / log."""
        if self.headers.get("X-BPI") != "1" or not self.is_admin():
            self.close_connection = True
            return self.need_login() if self.headers.get("X-BPI") == "1" else self._send(400, {"error": "thiếu header X-BPI"})
        if _vpn is None or length > 200_000:
            self.close_connection = True
            return self._send(413, {"error": "File quá lớn"})
        data = self.rfile.read(length) if length else b""
        q = parse_qs(url.query)
        dec = lambda h: base64.b64decode(self.headers.get(h, "")).decode("utf-8", "replace") if self.headers.get(h) else ""  # noqa: E731
        try:
            return self._send(200, _vpn.use_upload(q.get("name", ["vpn"])[0][:60], data, dec("X-VPN-User"), dec("X-VPN-Pass")))
        except (ValueError, OSError) as e:
            return self._send(400, {"error": str(e)})

    def kho_upload(self, url, length):
        """POST /api/kho/preview?name=&kind=: thân request là file CSV/XLSX (không multipart)."""
        if self.headers.get("X-BPI") != "1":
            self.close_connection = True
            return self._send(400, {"error": "thiếu header X-BPI"})
        ctx = self.kho_ctx()
        q = parse_qs(url.query)
        kind = q.get("kind", ["stock"])[0]
        if not ctx or (ctx["role"] != "admin" and kind != "bom"):
            self.close_connection = True
            return self.need_login() if not ctx else self._send(403, {"error": "Tài khoản khách chỉ được tải BOM"})
        if KHO is None or length > _kho.MAX_UPLOAD:
            self.close_connection = True
            return self._send(413 if KHO else 503, {"error": "File quá lớn (tối đa 5 MB)" if KHO else "Kho chưa bật"})
        data = self.rfile.read(length) if length else b""
        try:
            return self._send(200, KHO.preview(q.get("name", ["file.csv"])[0], data, kind))
        except ValueError as e:
            return self._send(400, {"error": str(e)})

    def iot_get(self, path, q):
        if path == "/api/iot/whoami":
            return self._send(200, {"iot": self.is_iot(), "admin": self.is_admin(), "local": self.is_local(),
                                    "password_set": IOT_AUTH.is_set()})
        if not self.is_iot():
            return self.need_login()
        if IOT is None:
            return self._send(503, {"error": "IoT chưa bật (xem log server)"})
        if path == "/api/iot/devices":
            return self._send(200, IOT.devices())
        if path == "/api/iot/history":
            return self._send(200, IOT.history(q.get("topic", [""])[0], q.get("range", ["24h"])[0]))
        if path == "/api/iot/controls":
            return self._send(200, IOT.controls())
        if path == "/api/iot/accounts":
            return self._send(200, {"accounts": IOT_ACCOUNTS.list(), "lan_host": lan_config()["ip"],
                                    "public_host": _iot.public_mqtt_host()})
        return self._send(404, {"error": "not found"})

    def iot_post(self, path, body):
        if path == "/api/iot/login":
            token = IOT_AUTH.login(self.client_ip(), str(body.get("password", "")))
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": self.cookie_header(token, IOT_AUTH.SESSION_DAYS * 86400, IOT_AUTH.COOKIE)})
        if path == "/api/iot/logout":
            IOT_AUTH.logout(self.session_token(IOT_AUTH.COOKIE))
            return self._send(200, {"ok": True}, headers={"Set-Cookie": self.cookie_header("", 0, IOT_AUTH.COOKIE)})
        if path == "/api/iot/password":
            if not self.is_admin():
                raise PermissionError("Chỉ quản trị viên mới đổi được mật khẩu IoT")
            new = str(body.get("new", ""))
            IOT_AUTH.set_password(new) if new else IOT_AUTH.clear_password()
            return self._send(200, {"ok": True, "password_set": IOT_AUTH.is_set()})
        if not self.is_iot():
            return self.need_login()
        if IOT is None:
            raise OSError("IoT chưa bật (xem log server)")
        if path == "/api/iot/controls":
            return self._send(200, IOT.save_controls(body.get("items")))
        if path == "/api/iot/control":
            return self._send(200, IOT.run_control(str(body.get("id", "")), body.get("value")))
        if path == "/api/iot/publish":
            IOT.publish(body.get("topic", ""), body.get("payload", ""), body.get("retain"))
            return self._send(200, {"ok": True})
        if path == "/api/iot/delete-device":
            IOT.delete_device(str(body.get("id", "")))
            return self._send(200, {"ok": True})
        if path == "/api/iot/accounts":
            act = body.get("action")
            if act in ("create", "reset"):
                r = IOT_ACCOUNTS.create(body.get("name"), body.get("note", ""), reset=act == "reset")
                return self._send(200, {**r, "lan_host": lan_config()["ip"], "public_host": _iot.public_mqtt_host()})
            if act == "delete":
                IOT_ACCOUNTS.delete(body.get("name"))
                return self._send(200, {"ok": True})
            raise ValueError("action phải là create / reset / delete")
        return self._send(404, {"error": "not found"})

    def do_GET(self):
        url = urlparse(self.path)
        path, q = url.path, parse_qs(url.query)
        if desktop_blocked(path):
            return self._send(404, {"error": "Không có trên bản chạy máy tính (chỉ kho + IoT)"})
        if path.startswith(LUCI_PREFIXES):
            return self.proxy_luci()
        if path in ("/kho", "/kho.html"):   # trang tự hiện màn hình đăng nhập (quản lý hoặc tài khoản khách)
            with open(os.path.join(HERE, "kho.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if path.startswith("/api/vpn/"):
            if not self.is_admin():
                return self.need_login()
            if _vpn is None:
                return self._send(503, {"error": "VPN chưa bật"})
            try:
                if path == "/api/vpn/status":
                    return self._send(200, _vpn.status(q.get("check", [""])[0] == "1"))
                if path == "/api/vpn/vpngate":
                    return self._send(200, _vpn.vpngate_list())
            except (OSError, ValueError) as e:
                return self._send(502, {"error": str(e)})
            return self._send(404, {"error": "not found"})
        if path.startswith("/api/kho/"):
            try:
                if path == "/api/kho/whoami":
                    return self.kho_public(path, {})
                ctx = self.kho_ctx()
                if not ctx:
                    return self.need_login()
                return self.kho_get(path, q, ctx)
            except PermissionError as e:
                return self._send(403, {"error": str(e)})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except OSError as e:
                return self._send(502, {"error": f"Lỗi mạng: {e}"})
        if path in ("/iot", "/iot.html"):
            with open(os.path.join(HERE, "iot.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if path.startswith("/api/iot/"):
            try:
                return self.iot_get(path, q)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if path not in PUBLIC_PATHS and not self.is_admin():
            return self.need_login()
        if DESKTOP and path in ("/", "/index.html"):   # máy tính: không có bảng điều khiển router
            return self._send(302, b"", "text/plain", {"Location": "/kho"})
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if path == "/api/whoami":
            local, authed = self.is_local(), self.is_authed()
            return self._send(200, {"local": local, "authed": authed, "admin": local or authed,
                                    "password_set": password_is_set(), "ip": self.client_ip()})
        if path == "/camera.mjpg":
            return self.stream_camera()
        if path == "/api/vision/stream":
            return self.stream_vision()
        if path == "/api/vision":
            return self._send(200, (CAMERA and CAMERA.detections) or {"error": "chưa có"})
        if path == "/camera.jpg":
            if CAMERA is None:
                return self._send(503, {"error": "Camera chưa sẵn sàng"})
            return self._send(200, CAMERA.frame, "image/jpeg")
        if path == "/api/status":
            return self._send(200, status())
        if path == "/api/public-url":
            return self._send(200, {"url": public_url(), "ssh": ssh_host()})
        if path == "/api/lan":
            return self._send(200, lan_status())
        if path == "/api/lan/confirm":
            # Trang cũ gọi sang IP mới (khác origin) bằng fetch no-cors; tới được đây nghĩa là IP mới dùng được.
            tok = q.get("token", [""])[0]
            ok = bool(tok) and tok == LAN_JOB.get("token") and LAN_JOB["state"] == "running"
            if ok:
                LAN_CONFIRMED.set()
            return self._send(200 if ok else 400, {"confirmed": ok})
        if path == "/api/clients":
            return self._send(200, clients())
        if path == "/api/wifi/scan":
            return self._send(200, wifi_scan())
        if path == "/api/wifi/status":
            return self._send(200, wifi_status())
        if path == "/api/log":
            return self._send(200, {"log": get_log(q.get("src", ["server"])[0])})
        if path == "/api/speaker":
            if SPEAKER is None:
                return self._send(503, {"error": "Phát ra loa chưa bật"})
            return self._send(200, SPEAKER.status())
        if path in ("/api/music", "/music/file", "/music/cover"):
            if MUSIC is None:
                return self._send(503, {"error": "Thư viện nhạc chưa bật"})
            try:
                if path == "/api/music":
                    return self._send(200, MUSIC.tracks())
                tid = q.get("id", [""])[0]
                if path == "/music/cover":
                    return self._send(200, MUSIC.cover(tid), "image/jpeg",
                                      headers={"Cache-Control": "private, max-age=86400"})
                full = MUSIC.path_of(tid)
                return self.serve_file(full, _music.TYPES[os.path.splitext(full)[1].lower()])
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except FileNotFoundError as e:
                return self._send(404, {"error": str(e)})
        if path in ("/api/traffic", "/api/traffic/recent"):
            if TRAFFIC is None:
                return self._send(503, {"error": "Thống kê truy cập chưa bật"})
            if path == "/api/traffic/recent":
                return self._send(200, TRAFFIC.recent_events(q.get("mac", [""])[0],
                                                             int(q.get("since", ["0"])[0] or 0)))
            try:
                return self._send(200, TRAFFIC.report(q.get("day", [""])[0] or None))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        url = urlparse(self.path)
        if desktop_blocked(url.path):
            return self._send(404, {"error": "Không có trên bản chạy máy tính (chỉ kho + IoT)"})
        if url.path == "/api/music/upload":
            return self.music_upload(url, length)
        if url.path == "/api/kho/preview":
            return self.kho_upload(url, length)
        if url.path == "/api/vpn/upload":
            return self.vpn_upload(url, length)
        if url.path.startswith(LUCI_PREFIXES):   # form của LuCI không có X-BPI; LuCI tự chống CSRF bằng token
            return self.proxy_luci(length)
        if length > 65536:
            return self._send(413, {"error": "quá lớn"})
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "JSON không hợp lệ"})
        # Mọi POST phải có header X-BPI: trang lạ không gắn được header này khi gửi sang board (CORS).
        if self.headers.get("X-BPI") != "1":
            return self._send(400, {"error": "thiếu header X-BPI"})

        try:
            if url.path.startswith("/api/iot/"):
                return self.iot_post(url.path, body)
            if url.path in ("/api/kho/login", "/api/kho/logout"):
                return self.kho_public(url.path, body)
            if url.path.startswith("/api/kho/"):
                ctx = self.kho_ctx()
                if not ctx:
                    return self.need_login()
                return self.kho_post(url.path, body, ctx)
            if self.path == "/api/login":
                token = try_login(self.client_ip(), str(body.get("password", "")))
                return self._send(200, {"ok": True},
                                  headers={"Set-Cookie": self.cookie_header(token, SESSION_DAYS * 86400)})
            if not self.is_admin():
                return self.need_login()
            if url.path.startswith("/api/vpn/"):
                if _vpn is None:
                    raise OSError("VPN chưa bật")
                if url.path == "/api/vpn/vpngate":
                    return self._send(200, _vpn.use_vpngate(str(body.get("cc", "")), str(body.get("host", ""))))
                if url.path == "/api/vpn/enable":
                    return self._send(200, _vpn.set_enabled(bool(body.get("on"))))
                return self._send(404, {"error": "not found"})
            if self.path == "/api/logout":
                end_session(self.session_token())
                return self._send(200, {"ok": True}, headers={"Set-Cookie": self.cookie_header("", 0)})
            if self.path == "/api/password":
                # Qua Internet phải nhập đúng mật khẩu hiện tại mới đổi được.
                if not self.is_local() and password_is_set() and not check_password(str(body.get("current", ""))):
                    raise PermissionError("Mật khẩu hiện tại không đúng")
                set_password(str(body.get("new", "")))
                hdr = {}
                if not self.is_local():  # đổi xong mọi phiên bị hủy -> cấp lại phiên cho chính người đổi
                    hdr["Set-Cookie"] = self.cookie_header(new_session(), SESSION_DAYS * 86400)
                return self._send(200, {"ok": True}, headers=hdr)
            if self.path == "/api/speaker":
                if SPEAKER is None:
                    raise ValueError("Phát ra loa chưa bật")
                return self._send(200, SPEAKER.command(body))
            if self.path == "/api/music/delete":
                if MUSIC is None:
                    raise ValueError("Thư viện nhạc chưa bật")
                MUSIC.delete(str(body.get("id", "")))
                return self._send(200, {"ok": True})
            if self.path == "/api/echo":
                return self._send(200, {"you_sent": body})
            if self.path == "/api/led":
                return self._send(200, {"led": set_led(body.get("mode", ""))})
            if self.path == "/api/lan":
                return self._send(200, lan_change(body))
            if self.path == "/api/wifi/connect":
                return self._send(200, wifi_connect(body))
            if self.path == "/api/new-link":
                return self._send(200, {"url": new_link()})
            if self.path == "/api/restart":
                self._send(200, {"ok": True, "msg": "Server đang khởi động lại..."})
                return detach("sleep 1; /etc/init.d/myserver restart")
            if self.path == "/api/reboot":
                self._send(200, {"ok": True, "msg": "Board đang khởi động lại, chờ khoảng 1 phút."})
                return detach("sleep 1; reboot")
            return self._send(404, {"error": "not found"})
        except PermissionError as e:
            return self._send(403, {"error": str(e)})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except (OSError, subprocess.SubprocessError) as e:
            return self._send(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        # Bỏ log các lần trang tự cập nhật trạng thái để log dễ đọc.
        if any(p in (str(args[0]) if args else "") for p in ("/api/status", "/camera.jpg", "/api/traffic/recent", "/luci-static/",
                                                                   "GET /api/speaker", "GET /api/iot/devices",
                                                                   "GET /api/kho/meta", "GET /api/vpn/status")):
            return
        super().log_message(fmt, *args)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    # python3-light trên OpenWrt thiếu codec "idna" mà getfqdn() trong
    # HTTPServer.server_bind cần, nên bind socket trực tiếp và bỏ qua bước đó.
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "bpi-r3", self.server_address[1]


if __name__ == "__main__":
    def _stop(*_):
        # procd dừng dịch vụ bằng SIGTERM: lưu thống kê truy cập trước khi thoát.
        try:
            if TRAFFIC:
                TRAFFIC.flush()
            if SPEAKER:
                SPEAKER.shutdown()
            if IOT:
                IOT.flush()
        finally:
            os._exit(0)
    signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, "SIGBREAK"):          # Windows: đóng cửa sổ / Ctrl-Break
        signal.signal(signal.SIGBREAK, _stop)
    bind = os.environ.get("BIND", "0.0.0.0")
    print(f"Server listening on {bind}:{PORT}", flush=True)
    try:
        Server((bind, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        _stop()
