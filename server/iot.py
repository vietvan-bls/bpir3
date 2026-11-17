"""IoT: nhận dữ liệu từ MQTT broker (Mosquitto trên board), lưu SQLite, điều khiển thiết bị.

Quy ước topic (thiết bị dùng tài khoản MQTT "iot", chỉ được dùng iot/#):
  iot/<thiết bị>/<giá trị>   payload là số ("25.5"), on/off/true/false, hoặc chữ bất kỳ
  iot/<thiết bị>             payload JSON {"nhiet_do": 25.5, "do_am": 60} -> tách thành iot/<thiết bị>/nhiet_do ...
  iot/<thiết bị>/status      "online" / "offline" (nên đặt làm LWT của thiết bị)
Thiết bị không có status được coi là online nếu gửi dữ liệu trong ONLINE_SECONDS gần nhất.

Điều khiển: các "nút điều khiển" (công tắc / nút bấm / thanh trượt) do người dùng tạo trên trang /iot,
mỗi nút gửi payload vào một topic lệnh, ví dụ iot/den-phong/set -> "on". Lưu ở CONTROLS_FILE.

Trang /iot có mật khẩu riêng (khác mật khẩu quản trị): AUTH_FILE, cookie "bpi_iot".
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:  # chạy được phần web dù chưa cài python3-paho-mqtt
    mqtt = None

DATA_DIR = os.environ.get("IOT_DIR", "/mnt/data/iot")
DB_FILE = os.path.join(DATA_DIR, "iot.db")
CONTROLS_FILE = os.path.join(DATA_DIR, "controls.json")
MQTT_CONF = os.environ.get("IOT_MQTT_CONF", "/etc/bpi-mqtt.json")
AUTH_FILE = os.environ.get("IOT_AUTH_FILE", "/etc/bpi-iot-auth.json")
TOPIC_ROOT = "iot"
ONLINE_SECONDS = 300
KEEP_DAYS = 30
FLUSH_SECONDS = 5
MAX_PAYLOAD = 4096
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
TRUE_WORDS, FALSE_WORDS = {"on", "true", "1", "yes", "open"}, {"off", "false", "0", "no", "closed"}


def _to_number(v):
    """Số -> float; on/off/true/false -> 1/0; còn lại None."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    try:
        f = float(s)
        return f if f == f and abs(f) != float("inf") else None   # bỏ NaN / vô cực
    except ValueError:
        pass
    if s in TRUE_WORDS:
        return 1.0
    if s in FALSE_WORDS:
        return 0.0
    return None


def parse_message(topic, payload):
    """Trả về danh sách (topic, số|None, chữ) từ một tin MQTT."""
    text = payload.decode("utf-8", "replace").strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            out = []

            def walk(prefix, d, depth=0):
                for k, v in d.items():
                    k = str(k).strip().replace("/", "_")[:40] or "_"
                    t = f"{prefix}/{k}"
                    if isinstance(v, dict) and depth < 2:
                        walk(t, v, depth + 1)
                    else:
                        raw = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                        out.append((t, _to_number(v), raw[:200]))
            walk(topic, obj)
            return out[:50]
    return [(topic, _to_number(text), text[:200])]


class IoT:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS readings (topic TEXT NOT NULL, ts REAL NOT NULL, value REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS readings_topic_ts ON readings (topic, ts);
            CREATE TABLE IF NOT EXISTS latest (topic TEXT PRIMARY KEY, ts REAL, value REAL, raw TEXT);
        """)
        self.latest = {t: {"ts": ts, "value": v, "raw": raw}
                       for t, ts, v, raw in self.db.execute("SELECT topic, ts, value, raw FROM latest")}
        self.pending = []          # (topic, ts, value) chờ ghi xuống thẻ nhớ
        self.dirty = set()         # topic có giá trị mới nhất chưa ghi
        self.connected = False
        self.error = ""
        self.count = 0             # số tin đã nhận từ lúc chạy
        self.client = None
        self._last_prune = 0
        threading.Thread(target=self._flusher, daemon=True).start()
        self._start_mqtt()

    # ------------------------------------------------------------ MQTT
    def _start_mqtt(self):
        if mqtt is None:
            self.error = "Chưa cài python3-paho-mqtt"
            return
        try:
            with open(MQTT_CONF) as f:
                conf = json.load(f)
        except (OSError, ValueError) as e:
            self.error = f"Không đọc được {MQTT_CONF}: {e}"
            return
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bpi-server-{secrets.token_hex(3)}")
        c.username_pw_set(conf.get("user"), conf.get("password"))
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        c.reconnect_delay_set(1, 30)
        c.connect_async(conf.get("host", "127.0.0.1"), int(conf.get("port", 1883)), keepalive=30)
        c.loop_start()
        self.client = c

    def _on_connect(self, client, userdata, flags, reason, props=None):
        if reason.is_failure:
            self.connected, self.error = False, f"Broker từ chối: {reason}"
            return
        self.connected, self.error = True, ""
        client.subscribe(f"{TOPIC_ROOT}/#", qos=0)

    def _on_disconnect(self, client, userdata, flags, reason, props=None):
        self.connected = False
        if reason.is_failure:
            self.error = f"Mất kết nối broker: {reason}"

    def _on_message(self, client, userdata, msg):
        if len(msg.payload) > MAX_PAYLOAD or msg.topic.endswith("/set"):
            return   # bỏ tin quá lớn và tin lệnh (do chính trang /iot gửi)
        now = time.time()
        with self.lock:
            self.count += 1
            for topic, value, raw in parse_message(msg.topic, msg.payload):
                self.latest[topic] = {"ts": now, "value": value, "raw": raw}
                self.dirty.add(topic)
                if value is not None:
                    self.pending.append((topic, now, value))

    # ------------------------------------------------------------ lưu trữ
    def flush(self):
        with self.lock:
            rows, self.pending = self.pending, []
            dirty, self.dirty = self.dirty, set()
            lat = [(t, self.latest[t]["ts"], self.latest[t]["value"], self.latest[t]["raw"]) for t in dirty]
            if not rows and not lat:
                return
            self.db.executemany("INSERT INTO readings VALUES (?, ?, ?)", rows)
            self.db.executemany("INSERT OR REPLACE INTO latest VALUES (?, ?, ?, ?)", lat)
            self.db.commit()

    def _flusher(self):
        while True:
            time.sleep(FLUSH_SECONDS)
            try:
                self.flush()
                if time.time() - self._last_prune > 3600:
                    self._last_prune = time.time()
                    with self.lock:
                        self.db.execute("DELETE FROM readings WHERE ts < ?", (time.time() - KEEP_DAYS * 86400,))
                        self.db.commit()
            except sqlite3.Error as e:
                self.error = f"Lỗi ghi dữ liệu: {e}"

    # ------------------------------------------------------------ API đọc
    def status(self):
        return {"connected": self.connected, "error": self.error, "received": self.count,
                "topics": len(self.latest)}

    def devices(self):
        """Gom các topic theo thiết bị: iot/<thiết bị>/<giá trị>."""
        now = time.time()
        with self.lock:
            items = sorted(self.latest.items())
        devs = {}
        for topic, d in items:
            parts = topic.split("/")
            if len(parts) < 2:
                continue
            dev = devs.setdefault(parts[1], {"id": parts[1], "last": 0, "status": None, "metrics": []})
            name = "/".join(parts[2:]) or "(giá trị)"
            if name == "status":
                dev["status"] = d["raw"]
                continue
            dev["last"] = max(dev["last"], d["ts"])
            dev["metrics"].append({"topic": topic, "name": name, "value": d["value"], "raw": d["raw"], "ts": d["ts"]})
        for dev in devs.values():
            st = (dev["status"] or "").lower()
            dev["online"] = st == "online" if st in ("online", "offline") else now - dev["last"] < ONLINE_SECONDS
        return {"devices": list(devs.values()), "now": now, **self.status()}

    def history(self, topic, rng="24h", points=240):
        span = RANGES.get(rng, 86400)
        since = time.time() - span
        bucket = max(1, span // points)
        self.flush()
        with self.lock:
            rows = self.db.execute(
                "SELECT CAST(ts / ? AS INTEGER) * ? AS b, AVG(value), MIN(value), MAX(value) FROM readings "
                "WHERE topic = ? AND ts >= ? GROUP BY b ORDER BY b", (bucket, bucket, topic, since)).fetchall()
        return {"topic": topic, "range": rng, "bucket": bucket,
                "points": [[b, round(a, 3), round(lo, 3), round(hi, 3)] for b, a, lo, hi in rows]}

    def delete_device(self, dev):
        prefix = f"{TOPIC_ROOT}/{dev}"
        if not dev or "/" in dev:
            raise ValueError("Tên thiết bị không hợp lệ")
        self.flush()
        with self.lock:
            for t in [t for t in self.latest if t == prefix or t.startswith(prefix + "/")]:
                del self.latest[t]
            self.db.execute("DELETE FROM latest WHERE topic = ? OR topic LIKE ?", (prefix, prefix + "/%"))
            self.db.execute("DELETE FROM readings WHERE topic = ? OR topic LIKE ?", (prefix, prefix + "/%"))
            self.db.commit()

    # ------------------------------------------------------------ điều khiển
    def publish(self, topic, payload, retain=False):
        topic = str(topic).strip()
        if not topic.startswith(TOPIC_ROOT + "/") or any(c in topic for c in "#+\0") or len(topic) > 200:
            raise ValueError(f"Topic phải bắt đầu bằng {TOPIC_ROOT}/ và không có ký tự # +")
        if not (self.client and self.connected):
            raise OSError(self.error or "Chưa kết nối được MQTT broker")
        info = self.client.publish(topic, str(payload)[:MAX_PAYLOAD], qos=1, retain=bool(retain))
        if info.rc != 0:
            raise OSError(f"Gửi lệnh thất bại (mã {info.rc})")

    def controls(self):
        try:
            with open(CONTROLS_FILE) as f:
                items = json.load(f)
        except (OSError, ValueError):
            items = []
        with self.lock:
            for c in items:
                st = self.latest.get(c.get("state") or c.get("topic"))
                c["current"] = st["raw"] if st else None
        return items

    def save_controls(self, items):
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("Danh sách điều khiển không hợp lệ")
        clean = []
        for c in items:
            kind = c.get("kind")
            if kind not in ("switch", "button", "slider"):
                raise ValueError(f"Loại điều khiển không hợp lệ: {kind}")
            topic = str(c.get("topic", "")).strip()
            if not topic.startswith(TOPIC_ROOT + "/") or any(ch in topic for ch in "#+"):
                raise ValueError(f"Topic lệnh phải bắt đầu bằng {TOPIC_ROOT}/ (vd {TOPIC_ROOT}/den/set)")
            item = {"id": str(c.get("id") or secrets.token_hex(4)), "kind": kind,
                    "name": str(c.get("name", "")).strip()[:60] or topic, "topic": topic,
                    "state": str(c.get("state", "")).strip()[:200], "retain": bool(c.get("retain"))}
            if kind == "switch":
                item["on"] = str(c.get("on", "on"))[:100]
                item["off"] = str(c.get("off", "off"))[:100]
            elif kind == "button":
                item["payload"] = str(c.get("payload", "1"))[:200]
            else:
                lo, hi = float(c.get("min", 0)), float(c.get("max", 100))
                if lo >= hi:
                    raise ValueError("Thanh trượt: min phải nhỏ hơn max")
                item.update(min=lo, max=hi, step=float(c.get("step", 1)) or 1)
            clean.append(item)
        tmp = CONTROLS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(clean, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CONTROLS_FILE)
        return self.controls()

    def run_control(self, cid, value=None):
        c = next((x for x in self.controls() if x["id"] == cid), None)
        if c is None:
            raise ValueError("Không có điều khiển này")
        if c["kind"] == "switch":
            payload = c["on"] if value in (True, 1, "1", "on", "true") else c["off"]
        elif c["kind"] == "button":
            payload = c["payload"]
        else:
            v = min(max(float(value), c["min"]), c["max"])
            payload = str(int(v)) if v == int(v) else str(v)
        self.publish(c["topic"], payload, c.get("retain"))
        return {"ok": True, "topic": c["topic"], "payload": payload}


class DeviceAccounts:
    """Tài khoản MQTT riêng cho từng thiết bị (vd ESP32 ở xa), quản lý từ trang /iot.

    Mỗi tài khoản <tên> chỉ dùng được iot/<tên>/# nhờ dòng "pattern readwrite iot/%u/#" trong acl của Mosquitto.
    Sửa file mật khẩu bằng mosquitto_passwd rồi gửi SIGHUP để broker nạp lại (thiết bị đang kết nối không bị ngắt).
    """
    PASSWD = os.environ.get("IOT_MOSQ_PASSWD", "/etc/mosquitto/passwd")
    META = os.path.join(DATA_DIR, "accounts.json")
    RESERVED = {"iot", "server", "admin", "root"}
    NAME_RE = r"[a-z0-9][a-z0-9-]{1,30}"

    def __init__(self):
        self.lock = threading.Lock()

    def _meta(self):
        try:
            with open(self.META) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_meta(self, m):
        tmp = self.META + ".tmp"
        with open(tmp, "w") as f:
            json.dump(m, f, ensure_ascii=False)
        os.replace(tmp, self.META)

    def _users(self):
        try:
            with open(self.PASSWD) as f:
                return [ln.split(":", 1)[0] for ln in f if ":" in ln]
        except OSError:
            return []

    def _check_name(self, name):
        import re
        if not re.fullmatch(self.NAME_RE, name or ""):
            raise ValueError("Tên chỉ gồm chữ thường, số, dấu - (2–31 ký tự), vd esp-vuon")
        if name in self.RESERVED:
            raise ValueError(f"Không dùng được tên “{name}” (tài khoản hệ thống)")

    def _fix_perms(self):
        # Broker chạy dưới user "mosquitto" và đọc lại file khi nhận SIGHUP.
        import shutil
        os.chmod(self.PASSWD, 0o600)
        try:
            shutil.chown(self.PASSWD, "mosquitto", "mosquitto")
        except (LookupError, OSError):
            pass

    @staticmethod
    def _reload():
        import subprocess
        subprocess.run(["killall", "-HUP", "mosquitto"], capture_output=True, timeout=10)

    def _set_pw(self, name, pw):
        import subprocess
        r = subprocess.run(["mosquitto_passwd", "-b", self.PASSWD, name, pw], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            raise OSError(r.stderr.strip() or "mosquitto_passwd lỗi")
        self._fix_perms()

    def list(self):
        meta = self._meta()
        return [{"name": u, "created": meta.get(u, {}).get("created"), "note": meta.get(u, {}).get("note", "")}
                for u in sorted(self._users()) if u not in self.RESERVED]

    def create(self, name, note="", reset=False):
        name = str(name or "").strip().lower()
        self._check_name(name)
        pw = secrets.token_urlsafe(15)
        with self.lock:
            exists = name in self._users()
            if reset and not exists:
                raise ValueError(f"Không có tài khoản {name}")
            if not reset and exists:
                raise ValueError(f"Tài khoản {name} đã có (dùng Đổi mật khẩu)")
            self._set_pw(name, pw)
            meta = self._meta()
            m = meta.setdefault(name, {"created": time.time()})
            if note:
                m["note"] = str(note)[:80]
            m["changed"] = time.time()
            self._save_meta(meta)
            self._reload()
        return {"name": name, "password": pw, "topic": f"{TOPIC_ROOT}/{name}"}

    def delete(self, name):
        import subprocess
        name = str(name or "").strip().lower()
        self._check_name(name)
        with self.lock:
            if name not in self._users():
                raise ValueError(f"Không có tài khoản {name}")
            r = subprocess.run(["mosquitto_passwd", "-D", self.PASSWD, name], capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                raise OSError(r.stderr.strip() or "mosquitto_passwd lỗi")
            self._fix_perms()
            meta = self._meta()
            meta.pop(name, None)
            self._save_meta(meta)
            self._reload()


def public_mqtt_host():
    """Tên Tailscale Funnel của board (nếu có) để thiết bị ở xa kết nối."""
    import subprocess
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5).stdout
        return json.loads(out)["Self"]["DNSName"].rstrip(".") or None
    except Exception:  # noqa: BLE001
        return None


class Auth:
    """Mật khẩu + phiên đăng nhập riêng cho trang IoT (giống cách làm của mật khẩu quản trị)."""
    SESSION_DAYS, ITER, MAX_FAILS, LOCK_SECONDS = 30, 200_000, 5, 300
    COOKIE = "bpi_iot"

    def __init__(self, path=AUTH_FILE):
        self.path = path
        self.lock = threading.Lock()
        self.fails = {}

    def _load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    @staticmethod
    def _hash(pw, salt, it):
        return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), it).hex()

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def is_set(self):
        return bool(self._load().get("password"))

    def set_password(self, new):
        if len(new) < 6:
            raise ValueError("Mật khẩu IoT phải dài ít nhất 6 ký tự")
        salt = secrets.token_hex(16)
        with self.lock:
            self._save({"password": {"salt": salt, "it": self.ITER, "hash": self._hash(new, salt, self.ITER)},
                        "sessions": {}})   # đổi mật khẩu -> đăng xuất mọi máy

    def clear_password(self):
        with self.lock:
            self._save({})

    def valid(self, token):
        if not token:
            return False
        exp = self._load().get("sessions", {}).get(self._key(token))
        return bool(exp) and exp > time.time()

    def login(self, ip, pw):
        now = time.time()
        with self.lock:
            cnt, until = self.fails.get(ip, [0, 0])
            if until > now:
                raise PermissionError(f"Sai quá nhiều lần, thử lại sau {int(until - now)} giây")
        p = self._load().get("password")
        if not p:
            raise ValueError("Chưa đặt mật khẩu IoT (quản trị viên đặt trong mục Cài đặt của trang IoT)")
        if hmac.compare_digest(self._hash(pw, p["salt"], p["it"]), p["hash"]):
            token = secrets.token_urlsafe(32)
            with self.lock:
                self.fails.pop(ip, None)
                a = self._load()
                sess = {k: v for k, v in a.get("sessions", {}).items() if v > now}
                sess[self._key(token)] = now + self.SESSION_DAYS * 86400
                a["sessions"] = sess
                self._save(a)
            return token
        time.sleep(1)
        with self.lock:
            cnt += 1
            self.fails[ip] = [0, now + self.LOCK_SECONDS] if cnt >= self.MAX_FAILS else [cnt, 0]
            left = self.MAX_FAILS - cnt
        raise PermissionError("Sai mật khẩu" + (f", còn {left} lần thử" if left > 0 else
                                                f", bị khóa {self.LOCK_SECONDS // 60} phút"))

    def logout(self, token):
        with self.lock:
            a = self._load()
            if a.get("sessions", {}).pop(self._key(token or ""), None) is not None:
                self._save(a)
