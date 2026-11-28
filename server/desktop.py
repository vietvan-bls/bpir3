#!/usr/bin/env python3
"""Chạy kho linh kiện + IoT trên máy tính (Windows 10/11, Linux, Raspberry Pi) — không cần board BPI-R3.

  python desktop.py                         chạy, mở trình duyệt http://127.0.0.1:8080/kho
  python desktop.py --restore FILE.enc      khôi phục dữ liệu từ bản sao lưu đã mã hóa (data-backup/*.enc), hỏi mật khẩu
  python desktop.py --set-password          đặt mật khẩu quản trị (để máy khác trong mạng vào được, kèm --lan)
  python desktop.py --lan                   cho máy khác trong mạng (điện thoại…) truy cập qua http://<IP máy>:8080/kho
  Tùy chọn: --data THƯ_MỤC (mặc định: thư mục "data" cạnh file này), --port 8080, --no-browser

Chỉ có các trang /kho và /iot. Các tab của router (Wi-Fi, LAN, VPN, LED, camera, nhạc) bị tắt.
Trên chính máy này (127.0.0.1) không cần mật khẩu. Máy khác phải đăng nhập bằng mật khẩu quản trị.
IoT: dữ liệu cũ xem được ngay; muốn nhận dữ liệu mới thì sửa data/mqtt.json trỏ tới broker MQTT (vd IP board).
"""
import argparse
import getpass
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
for _s in (sys.stdout, sys.stderr):          # console Windows mặc định cp1252 → in tiếng Việt bị lỗi
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def paths(data):
    return {
        "KHO_DIR": os.path.join(data, "kho"),
        "IOT_DIR": os.path.join(data, "iot"),
        "BPI_AUTH_FILE": os.path.join(data, "web-auth.json"),
        "IOT_AUTH_FILE": os.path.join(data, "iot-auth.json"),
        "IOT_MQTT_CONF": os.path.join(data, "mqtt.json"),
        "IOT_MOSQ_PASSWD": os.path.join(data, "mosquitto-passwd"),
    }


def decrypt(blob, password):
    """Giải mã file của tools/backup-data.sh: openssl enc -aes-256-cbc -pbkdf2 -iter 600000 (salt 8 byte)."""
    if blob[:8] != b"Salted__":
        raise ValueError("Không phải file mã hóa của openssl (thiếu 'Salted__')")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        sys.exit("Cần thư viện cryptography để giải mã:  python -m pip install cryptography")
    salt, body = blob[8:16], blob[16:]
    km = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, 48)
    d = Cipher(algorithms.AES(km[:32]), modes.CBC(km[32:])).decryptor()
    out = d.update(body) + d.finalize()
    pad = out[-1] if out else 0
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError("Sai mật khẩu (hoặc file hỏng)")
    return out[:-pad]


def restore(enc_file, data):
    pw = os.environ.get("BPI_BACKUP_PASS") or getpass.getpass("Mật khẩu sao lưu (/root/.bpi-backup-pass trên board): ")
    with open(enc_file, "rb") as f:
        raw = decrypt(f.read(), pw)
    p = paths(data)
    for k in ("KHO_DIR", "IOT_DIR"):
        if os.path.exists(os.path.join(p[k], k[:3].lower() + ".db")):
            bak = p[k] + time.strftime("-truoc-khoi-phuc-%Y%m%d-%H%M%S")
            shutil.move(p[k], bak)
            print("Dữ liệu cũ chuyển sang", bak)
    os.makedirs(data, exist_ok=True)
    remap = {"etc/bpi-web-auth.json": p["BPI_AUTH_FILE"], "etc/bpi-iot-auth.json": p["IOT_AUTH_FILE"],
             "etc/bpi-mqtt.json": p["IOT_MQTT_CONF"]}
    n = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
        for m in t.getmembers():
            name = m.name.lstrip("./")
            if not m.isfile() or ".." in name.split("/"):
                continue
            if name.startswith(("kho/", "iot/")):
                dst = os.path.join(data, *name.split("/"))
            elif name in remap:
                dst = remap[name]
            else:
                continue   # cấu hình OpenWrt, mosquitto, vpn… chỉ dùng cho board
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with t.extractfile(m) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
    print(f"Đã khôi phục {n} file vào {data}")
    print("Mật khẩu quản trị và mật khẩu trang IoT giống trên board.")
    try:
        with open(p["IOT_MQTT_CONF"], encoding="utf-8") as f:
            c = json.load(f)
        print(f"IoT: broker MQTT đang trỏ tới {c.get('host', '127.0.0.1')}:{c.get('port', 1883)} — sửa {p['IOT_MQTT_CONF']} nếu cần.")
    except (OSError, ValueError):
        pass


def main():
    ap = argparse.ArgumentParser(description="Kho linh kiện + IoT trên máy tính")
    ap.add_argument("--data", default=os.path.join(HERE, "data"))
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--lan", action="store_true", help="cho máy khác trong mạng truy cập")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--restore", metavar="FILE.enc")
    ap.add_argument("--set-password", action="store_true")
    a = ap.parse_args()
    data = os.path.abspath(a.data)

    if a.restore:
        return restore(a.restore, data)

    os.makedirs(data, exist_ok=True)
    env = paths(data)
    for d in (env["KHO_DIR"], env["IOT_DIR"]):
        os.makedirs(d, exist_ok=True)
    os.environ.update(env)
    os.environ.update({"BPI_DESKTOP": "1", "PORT": str(a.port), "BIND": "0.0.0.0" if a.lan else "127.0.0.1",
                       "CAMERA_MODE": "file"})
    sys.path.insert(0, HERE)
    os.chdir(HERE)

    if a.set_password:
        import app
        pw = getpass.getpass("Mật khẩu quản trị mới (≥ 8 ký tự): ")
        if pw != getpass.getpass("Nhập lại: "):
            sys.exit("Hai lần không khớp")
        app.set_password(pw)
        return print("Đã đặt mật khẩu.")

    url = f"http://127.0.0.1:{a.port}/kho"
    print("Dữ liệu:", data)
    print("Mở:", url, "(Ctrl+C hoặc đóng cửa sổ để dừng)")
    if a.lan:
        print(f"Máy khác trong mạng: http://<IP máy này>:{a.port}/kho — cần mật khẩu quản trị (--set-password),"
              " Windows có thể hỏi cho phép Python qua Firewall.")
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    import runpy
    runpy.run_path(os.path.join(HERE, "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
