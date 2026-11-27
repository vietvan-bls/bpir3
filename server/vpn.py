"""VPN cho mạng WiFi của board: máy bắt WiFi BPI-R3 ra Internet qua VPN (đổi nước), board vẫn đi mạng thường.

Nguồn VPN:
  - VPN Gate (miễn phí, không tài khoản, đề án ĐH Tsukuba): tải danh sách máy chủ, chọn nước -> OpenVPN.
  - Tải file cấu hình lên: WireGuard .conf (Proton VPN Free, Mullvad, Surfshark…) hoặc OpenVPN .ovpn (+ user/pass).

Định tuyến (chỉ áp dụng cho nguồn là mạng LAN của board):
  ưu tiên 9000: from <LAN> lookup main suppress_prefixlength 0  -> đích trong mạng (LAN, mạng nhà…) đi thẳng
  ưu tiên 9001: from <LAN> lookup 100                           -> còn lại (Internet) qua VPN
  ưu tiên 9003: oif <thiết bị VPN> lookup 100                   -> socket gắn vào VPN (DNS, kiểm tra IP)
  bảng 100: default dev <VPN>  +  unreachable default (metric cao) = kill-switch khi VPN rớt.
Firewall: zone "bpivpn" (masquerade) + forwarding lan -> bpivpn; chặn IPv6 lan -> wan khi bật.
DNS: dnsmasq hỏi DNS qua VPN (server=IP@thiết bị), strict-order, sau cùng mới tới DNS thường (để board vẫn chạy khi VPN rớt).

Chạy nền: dịch vụ procd /etc/init.d/bpi-vpn gọi `python3 vpn.py run` (theo /etc/bpi-vpn/state.json).
"""
import base64
import csv
import io
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request

CONF_DIR = "/etc/bpi-vpn"
STATE = os.path.join(CONF_DIR, "state.json")
OVPN = os.path.join(CONF_DIR, "client.ovpn")
AUTH = os.path.join(CONF_DIR, "auth.txt")
WGCONF = os.path.join(CONF_DIR, "wg.conf")
LOG = "/tmp/bpi-vpn.log"
TABLE = 100
DEV_OVPN, DEV_WG = "tunvpn", "wgvpn"
VPNGATE_API = "http://www.vpngate.net/api/iphone/"
DEFAULT_DNS = ["1.1.1.1", "8.8.8.8"]
# chỉ thị OpenVPN có thể chạy lệnh / nạp plugin trên board: bỏ khi nhận file từ ngoài
OVPN_UNSAFE = {"up", "down", "script-security", "plugin", "route-up", "route-pre-down", "ipchange", "tls-verify",
               "client-connect", "client-disconnect", "learn-address", "auth-user-pass-verify", "management",
               "daemon", "log", "log-append", "writepid", "cd", "chroot", "setenv", "setenv-safe", "dev", "dev-type",
               "redirect-gateway", "route", "route-ipv6", "dhcp-option", "status"}
_cache = {"vpngate": (0, None), "ip": (0, None)}


def sh(*cmd, check=False, timeout=20):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise OSError((r.stderr or r.stdout).strip() or f"{cmd[0]} lỗi")
    return r


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"enabled": False}


def save_state(st):
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    tmp = STATE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def write_secret(path, text):
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def lan_net():
    ip = sh("uci", "-q", "get", "network.lan.ipaddr").stdout.strip() or "192.168.1.1"
    if "/" not in ip:
        ip += "/" + (sh("uci", "-q", "get", "network.lan.netmask").stdout.strip() or "255.255.255.0")
    return str(ipaddress.ip_interface(ip).network)


def dev_of(st):
    return DEV_WG if st.get("kind") == "wireguard" else DEV_OVPN


# ------------------------------------------------------------------ VPN Gate
def vpngate_servers(force=False):
    ts, data = _cache["vpngate"]
    if data and not force and time.time() - ts < 600:
        return data
    req = urllib.request.Request(VPNGATE_API, headers={"User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    out = []
    for r in csv.reader(io.StringIO(text)):
        if len(r) < 15 or r[0].startswith(("*", "#")) or not r[14]:
            continue
        try:
            out.append({"host": r[0], "ip": r[1], "score": int(r[2]), "ping": int(r[3] or 0),
                        "mbps": round(int(r[4] or 0) / 1e6), "country": r[5], "cc": r[6],
                        "sessions": int(r[7] or 0), "config": r[14]})
        except ValueError:
            continue
    out.sort(key=lambda s: -s["score"])
    _cache["vpngate"] = (time.time(), out)
    return out


def vpngate_list():
    """Danh sách nước + vài máy chủ tốt nhất mỗi nước (không kèm cấu hình)."""
    by = {}
    for s in vpngate_servers():
        by.setdefault(s["cc"], {"cc": s["cc"], "country": s["country"], "servers": []})["servers"].append(
            {k: s[k] for k in ("host", "ip", "ping", "mbps", "sessions", "score")})
    countries = sorted(by.values(), key=lambda c: -len(c["servers"]))
    for c in countries:
        c["count"] = len(c["servers"])
        c["servers"] = c["servers"][:8]
    return countries


def sanitize_ovpn(text, has_auth):
    lines = []
    for ln in text.replace("\r", "").split("\n"):
        word = ln.strip().split()[0].lower() if ln.strip() and not ln.strip().startswith(("#", ";")) else ""
        if word in OVPN_UNSAFE:
            continue
        if word == "auth-user-pass":
            if has_auth:
                lines.append(f"auth-user-pass {AUTH}")
            continue
        lines.append(ln)
    if not has_auth and any(l.strip().lower().startswith("auth-user-pass") for l in text.splitlines()):
        raise ValueError("File .ovpn này cần tên đăng nhập + mật khẩu của VPN")
    return "\n".join(lines) + "\n"


def use_vpngate(cc, host=""):
    servers = [s for s in vpngate_servers(force=True) if s["cc"] == cc.upper() and (not host or s["host"] == host)]
    if not servers:
        raise ValueError("Không có máy chủ VPN Gate cho nước này (danh sách thay đổi liên tục, thử lại sau)")
    s = servers[0]
    cfg = base64.b64decode(s["config"]).decode("utf-8", "replace")
    write_secret(OVPN, sanitize_ovpn(cfg, has_auth=False))
    st = {"enabled": True, "kind": "openvpn", "source": "vpngate", "name": f"VPN Gate · {s['country']} · {s['host']}",
          "country": s["country"], "cc": s["cc"], "server": s["ip"], "dns": DEFAULT_DNS, "compat": True,
          "since": time.time()}
    save_state(st)
    restart()
    return status()


# ------------------------------------------------------------------ cấu hình tải lên
def parse_wg(text):
    sec, iface, peers = None, {}, []
    for ln in text.replace("\r", "").split("\n"):
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        m = re.fullmatch(r"\[(\w+)\]", ln)
        if m:
            sec = m.group(1).lower()
            if sec == "peer":
                peers.append({})
            continue
        if "=" not in ln:
            continue
        k, v = (x.strip() for x in ln.split("=", 1))
        (iface if sec == "interface" else peers[-1] if peers else {})[k.lower()] = v
    if not iface.get("privatekey") or not peers or not peers[0].get("publickey") or not peers[0].get("endpoint"):
        raise ValueError("File WireGuard thiếu PrivateKey / [Peer] PublicKey / Endpoint")
    addrs = [a.strip() for a in iface.get("address", "").split(",") if a.strip()]
    v4 = [a for a in addrs if ":" not in a]
    if not v4:
        raise ValueError("File WireGuard không có địa chỉ IPv4 (Address)")
    dns = [d.strip() for d in iface.get("dns", "").split(",") if re.fullmatch(r"[\d.]+", d.strip())]
    return iface, peers, v4[0], dns


def use_upload(name, data, username="", password=""):
    text = data.decode("utf-8", "replace")
    if len(data) > 200_000:
        raise ValueError("File quá lớn")
    if "[Interface]" in text and "[Peer]" in text:
        iface, peers, addr, dns = parse_wg(text)
        write_secret(WGCONF, text)
        ep = peers[0]["endpoint"]
        st = {"enabled": True, "kind": "wireguard", "source": "upload", "name": f"WireGuard · {name}",
              "server": ep.rsplit(":", 1)[0], "address": addr, "dns": dns or DEFAULT_DNS, "since": time.time()}
    elif re.search(r"^\s*(client|remote)\b", text, re.M):
        has_auth = bool(username)
        if has_auth:
            write_secret(AUTH, f"{username}\n{password}\n")
        write_secret(OVPN, sanitize_ovpn(text, has_auth))
        remote = re.search(r"^\s*remote\s+(\S+)", text, re.M)
        st = {"enabled": True, "kind": "openvpn", "source": "upload", "name": f"OpenVPN · {name}",
              "server": remote.group(1) if remote else "", "dns": DEFAULT_DNS, "compat": True, "since": time.time()}
    else:
        raise ValueError("Không nhận ra file: cần WireGuard .conf ([Interface]/[Peer]) hoặc OpenVPN .ovpn")
    save_state(st)
    restart()
    return status()


# ------------------------------------------------------------------ bật / tắt
def set_enabled(on):
    st = load_state()
    if on and not st.get("kind"):
        raise ValueError("Chưa chọn VPN: chọn nước VPN Gate hoặc tải file cấu hình lên trước")
    st["enabled"] = bool(on)
    save_state(st)
    if on:
        restart()
    else:
        sh("/etc/init.d/bpi-vpn", "stop", timeout=30)
        teardown()
    _cache["ip"] = (0, None)
    return status()


def restart():
    _cache["ip"] = (0, None)
    sh("/etc/init.d/bpi-vpn", "enable")
    sh("/etc/init.d/bpi-vpn", "restart", timeout=30)


# ------------------------------------------------------------------ định tuyến / firewall / DNS
def ensure_firewall(block_v6):
    changed = False
    if sh("uci", "-q", "get", "firewall.bpivpn").returncode != 0:
        for args in (("set", "firewall.bpivpn=zone"), ("set", "firewall.bpivpn.name=bpivpn"),
                     ("add_list", f"firewall.bpivpn.device={DEV_OVPN}"), ("add_list", f"firewall.bpivpn.device={DEV_WG}"),
                     ("set", "firewall.bpivpn.input=REJECT"), ("set", "firewall.bpivpn.output=ACCEPT"),
                     ("set", "firewall.bpivpn.forward=REJECT"), ("set", "firewall.bpivpn.masq=1"),
                     ("set", "firewall.bpivpn.mtu_fix=1"),
                     ("set", "firewall.bpivpn_fwd=forwarding"), ("set", "firewall.bpivpn_fwd.src=lan"),
                     ("set", "firewall.bpivpn_fwd.dest=bpivpn"),
                     ("set", "firewall.bpivpn_v6=rule"), ("set", "firewall.bpivpn_v6.name=BPI-VPN-block-IPv6"),
                     ("set", "firewall.bpivpn_v6.src=lan"), ("set", "firewall.bpivpn_v6.dest=*"),
                     ("set", "firewall.bpivpn_v6.family=ipv6"), ("set", "firewall.bpivpn_v6.proto=all"),
                     ("set", "firewall.bpivpn_v6.target=REJECT")):
            sh("uci", *args)
        changed = True
    want = "1" if block_v6 else "0"
    if sh("uci", "-q", "get", "firewall.bpivpn_v6.enabled").stdout.strip() != want:
        sh("uci", "set", f"firewall.bpivpn_v6.enabled={want}")
        changed = True
    if changed:
        sh("uci", "commit", "firewall")
        sh("/etc/init.d/firewall", "reload", timeout=30)


def wan_dns():
    servers = []
    for path in ("/tmp/resolv.conf.d/resolv.conf.auto", "/tmp/resolv.conf.auto"):
        try:
            for ln in open(path):
                m = re.match(r"\s*nameserver\s+([\d.]+)", ln)
                if m and m.group(1) not in servers and not m.group(1).startswith("127."):
                    servers.append(m.group(1))
        except OSError:
            continue
    return servers or ["8.8.8.8"]


def set_dns(st, on):
    """Khi bật: DNS qua VPN trước (server=IP@thiết bị), DNS thường sau cùng (strict-order)."""
    key = "dhcp.@dnsmasq[0]"
    if on:
        dev = dev_of(st)
        servers = [f"{d}@{dev}" for d in st.get("dns") or DEFAULT_DNS] + wan_dns()
        sh("uci", "-q", "delete", f"{key}.server")
        for s in servers:
            sh("uci", "add_list", f"{key}.server={s}")
        sh("uci", "set", f"{key}.noresolv=1")
        sh("uci", "set", f"{key}.strictorder=1")
    else:
        sh("uci", "-q", "delete", f"{key}.server")
        sh("uci", "-q", "delete", f"{key}.noresolv")
        sh("uci", "-q", "delete", f"{key}.strictorder")
    sh("uci", "commit", "dhcp")
    sh("/etc/init.d/dnsmasq", "restart", timeout=30)


def rules_up(dev):
    lan = lan_net()
    teardown_rules()
    sh("ip", "rule", "add", "from", lan, "lookup", "main", "suppress_prefixlength", "0", "priority", "9000")
    sh("ip", "rule", "add", "from", lan, "lookup", str(TABLE), "priority", "9001")
    for d in (DEV_OVPN, DEV_WG):
        sh("ip", "rule", "add", "oif", d, "lookup", str(TABLE), "priority", "9003")
    sh("ip", "route", "replace", "unreachable", "default", "metric", "9999", "table", str(TABLE))   # kill-switch
    sh("ip", "-6", "route", "replace", "unreachable", "default", "metric", "9999", "table", str(TABLE))


def route_vpn(dev):
    sh("ip", "route", "replace", "default", "dev", dev, "metric", "0", "table", str(TABLE))


def teardown_rules():
    for _ in range(6):
        for pref in ("9000", "9001", "9003"):
            sh("ip", "rule", "del", "priority", pref)
    sh("ip", "route", "flush", "table", str(TABLE))
    sh("ip", "-6", "route", "flush", "table", str(TABLE))


def teardown():
    """Tắt hẳn VPN: gỡ định tuyến, DNS về như cũ, bỏ chặn IPv6, xóa thiết bị."""
    teardown_rules()
    sh("ip", "link", "del", DEV_WG)
    sh("ip", "link", "del", DEV_OVPN)
    set_dns({}, False)
    if sh("uci", "-q", "get", "firewall.bpivpn").returncode == 0:
        ensure_firewall(False)


# ------------------------------------------------------------------ trạng thái
def dev_up(dev):
    return os.path.exists(f"/sys/class/net/{dev}")


def wg_handshake():
    r = sh("wg", "show", DEV_WG, "latest-handshakes")
    try:
        return max(int(x.split()[1]) for x in r.stdout.strip().splitlines() if x.split())
    except ValueError:
        return 0


def exit_ip(dev, force=False):
    ts, data = _cache["ip"]
    if data and not force and time.time() - ts < 60:
        return data
    try:
        s = socket.socket()
        s.settimeout(10)
        s.setsockopt(socket.SOL_SOCKET, 25, dev.encode())   # SO_BINDTODEVICE: đi đúng đường VPN
        s.connect(("ip-api.com", 80))
        s.sendall(b"GET /json/?fields=query,country,countryCode,city,isp HTTP/1.0\r\nHost: ip-api.com\r\n\r\n")
        d = b""
        while True:
            c = s.recv(4096)
            if not c:
                break
            d += c
        s.close()
        data = json.loads(d.split(b"\r\n\r\n", 1)[1])
    except (OSError, ValueError, IndexError) as e:
        data = {"error": str(e)[:100]}
    _cache["ip"] = (time.time() if "error" not in data else 0, data)   # lỗi thì lần sau hỏi lại
    return data


def status(check_ip=False):
    st = load_state()
    dev = dev_of(st)
    out = {k: st.get(k) for k in ("enabled", "kind", "source", "name", "country", "cc", "server", "since")}
    up = dev_up(dev)
    if st.get("kind") == "wireguard":
        hs = wg_handshake() if up else 0
        connected = up and hs > 0 and time.time() - hs < 180
    else:
        connected = up and "Initialization Sequence Completed" in (open(LOG).read()[-20000:] if os.path.exists(LOG) else "")
    out.update(connected=bool(st.get("enabled") and connected), lan=lan_net())
    if up:
        try:
            out["rx"] = int(open(f"/sys/class/net/{dev}/statistics/rx_bytes").read())
            out["tx"] = int(open(f"/sys/class/net/{dev}/statistics/tx_bytes").read())
        except OSError:
            pass
    if out["connected"]:
        out["exit"] = exit_ip(dev, force=check_ip)
    try:
        out["log"] = open(LOG).read()[-1500:]
    except OSError:
        out["log"] = ""
    return out


# ------------------------------------------------------------------ chạy nền (procd)
def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def run():
    st = load_state()
    if not st.get("enabled") or not st.get("kind"):
        teardown()
        return
    open(LOG, "w").close()
    dev = dev_of(st)
    ensure_firewall(True)
    rules_up(dev)
    if st["kind"] == "wireguard":
        iface, peers, addr, _ = parse_wg(open(WGCONF).read())
        sh("ip", "link", "del", DEV_WG)
        sh("ip", "link", "add", DEV_WG, "type", "wireguard", check=True)
        wg_lines = ["[Interface]", f"PrivateKey = {iface['privatekey']}"]
        for p in peers:
            wg_lines.append("[Peer]")
            for k in ("publickey", "presharedkey", "endpoint", "allowedips", "persistentkeepalive"):
                if p.get(k):
                    wg_lines.append(f"{k} = {p[k]}")
        tmp = os.path.join(CONF_DIR, ".wg-set")
        write_secret(tmp, "\n".join(wg_lines) + "\n")
        try:
            sh("wg", "setconf", DEV_WG, tmp, check=True)
        finally:
            os.remove(tmp)
        sh("ip", "addr", "add", addr, "dev", DEV_WG, check=True)
        sh("ip", "link", "set", DEV_WG, "mtu", iface.get("mtu", "1420"), "up", check=True)
        route_vpn(DEV_WG)
        set_dns(st, True)
        log(f"WireGuard lên: {st.get('name')}")
        while True:   # procd giữ tiến trình; báo rớt / có lại để xem log
            time.sleep(60)
            hs = wg_handshake()
            if hs and time.time() - hs > 180:
                log("WireGuard: lâu không có handshake (máy chủ không trả lời?)")
    else:
        args = ["openvpn", "--config", OVPN, "--dev", DEV_OVPN, "--dev-type", "tun", "--route-nopull",
                "--pull-filter", "ignore", "redirect-gateway", "--pull-filter", "ignore", "dhcp-option", "--verb", "3", "--connect-retry-max", "3",
                "--ping", "10", "--ping-exit", "60"]
        if st.get("compat"):   # máy chủ cũ (VPN Gate): AES-128-CBC / SHA1 / chứng chỉ yếu
            args += ["--data-ciphers", "AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305:AES-128-CBC",
                     "--tls-cipher", "DEFAULT:@SECLEVEL=0"]
        dns_set = False
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        def _stop(*_):   # procd dừng / khởi động lại dịch vụ: tắt luôn OpenVPN (không để chạy mồ côi)
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
            sys.exit(0)
        signal.signal(signal.SIGTERM, _stop)
        for line in p.stdout:
            with open(LOG, "a") as f:
                f.write(line)
            if "Initialization Sequence Completed" in line:
                route_vpn(DEV_OVPN)
                if not dns_set:
                    set_dns(st, True)
                    dns_set = True
        p.wait()
        log(f"OpenVPN thoát (mã {p.returncode}); kill-switch giữ máy trong mạng không ra Internet. procd sẽ chạy lại.")
        time.sleep(5)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run()
    elif len(sys.argv) > 1 and sys.argv[1] == "stop":
        teardown()
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
