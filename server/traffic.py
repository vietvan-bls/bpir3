"""Thống kê các máy trong mạng của board đã vào trang web nào, dựa vào log DNS của dnsmasq.

dnsmasq ghi mỗi câu hỏi DNS thành một dòng (uci dhcp logqueries=1, logfacility=/tmp/dnsmasq.log):
    ... query[A] www.youtube.com from 192.168.2.133
Board chỉ biết TÊN MIỀN (HTTPS mã hóa phần còn lại), nên không biết xem video/bài nào.

Một "phút" = một phút có ít nhất một câu hỏi DNS của máy đó tới trang đó; dùng để ước lượng thời gian dùng.
Dữ liệu từng ngày lưu ở DATA_DIR/YYYY-MM-DD.json, giữ KEEP_DAYS ngày.
"""
import collections
import json
import os
import re
import subprocess
import threading
import time

LOG = os.environ.get("DNS_LOG", "/tmp/dnsmasq.log")
DATA_DIR = os.environ.get("TRAFFIC_DIR", "/mnt/data/traffic")
KEEP_DAYS = 30
MAX_LOG = 4 * 1024 * 1024      # log trong RAM lớn hơn mức này thì cắt về 0 (dnsmasq ghi kiểu append nên không sao)
SAVE_EVERY = 60
RECENT_GAP = 60                # sự kiện "vừa truy cập": mỗi (máy, tên miền) tối đa 1 lần / 60 s
MAX_HOSTS = 6                  # số tên miền con ví dụ lưu cho mỗi trang

QUERY_RE = re.compile(r"query\[(A|AAAA|HTTPS)\] (\S+) from (\S+)")

# Tên miền phụ của cùng một dịch vụ được gộp lại. (tên hiển thị, nhóm, đuôi tên miền)
# nhóm "nen" = dịch vụ chạy nền của hệ điều hành/quảng cáo/đo lường, giao diện có thể ẩn.
SERVICES = [
    ("YouTube", "video", ["youtube.com", "googlevideo.com", "ytimg.com", "youtu.be", "youtube-nocookie.com",
                          "youtubei.googleapis.com", "yt3.ggpht.com", "youtubekids.com"]),
    ("TikTok", "video", ["tiktok.com", "tiktokcdn.com", "tiktokv.com", "tiktokcdn-us.com", "tiktokv.us",
                         "ibytedtos.com", "ibyteimg.com", "byteoversea.com", "musical.ly", "tiktokcdn-eu.com"]),
    ("Netflix", "video", ["netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com", "nflxso.net"]),
    ("Twitch", "video", ["twitch.tv", "ttvnw.net", "jtvnw.net"]),
    ("FPT Play", "video", ["fptplay.vn", "fptplay.net"]),
    ("Facebook", "mxh", ["facebook.com", "fbcdn.net", "fb.com", "facebook.net", "fbsbx.com", "fb.me"]),
    ("Messenger", "chat", ["messenger.com"]),
    ("Instagram", "mxh", ["instagram.com", "cdninstagram.com"]),
    ("Threads", "mxh", ["threads.net", "threads.com"]),
    ("WhatsApp", "chat", ["whatsapp.com", "whatsapp.net"]),
    ("X (Twitter)", "mxh", ["twitter.com", "x.com", "twimg.com", "t.co"]),
    ("Reddit", "mxh", ["reddit.com", "redd.it", "redditmedia.com", "redditstatic.com"]),
    ("Zalo", "chat", ["zalo.me", "zaloapp.com", "zadn.vn", "zalo.vn", "zdn.vn"]),
    ("Telegram", "chat", ["telegram.org", "t.me", "telegram.me", "telesco.pe"]),
    ("Discord", "chat", ["discord.com", "discord.gg", "discordapp.com", "discordapp.net", "discord.media"]),
    ("Shopee", "mua", ["shopee.vn", "shopee.com", "susercontent.com", "shopeemobile.com", "shopee.io"]),
    ("Lazada", "mua", ["lazada.vn", "lazada.com", "slatic.net", "alicdn.com"]),
    ("Tiki", "mua", ["tiki.vn", "tikicdn.com"]),
    ("Spotify", "nhac", ["spotify.com", "scdn.co", "spotifycdn.com"]),
    ("Zing MP3", "nhac", ["zingmp3.vn", "zmdcdn.me"]),
    ("ChatGPT", "ai", ["chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com"]),
    ("Claude", "ai", ["claude.ai", "anthropic.com", "claude.com"]),
    ("Gemini", "ai", ["gemini.google.com", "bard.google.com"]),
    ("GitHub", "web", ["github.com", "githubusercontent.com", "githubassets.com", "github.io"]),
    ("Gmail", "web", ["mail.google.com", "gmail.com"]),
    ("Google", "web", ["google.com", "google.com.vn", "gstatic.com", "googleusercontent.com", "ggpht.com"]),
    ("Steam", "game", ["steampowered.com", "steamcommunity.com", "steamstatic.com", "steamserver.net"]),
    ("Roblox", "game", ["roblox.com", "rbxcdn.com"]),
    ("Liên Quân / Garena", "game", ["garena.com", "garena.vn", "garenanow.com"]),
    # Máy hỏi các tên này thường đang bật DNS mã hóa (DoH/DoT) -> các truy cập sau đó có thể không ghi được.
    ("DNS mã hóa riêng", "dns", ["dns.google", "dns.google.com", "cloudflare-dns.com", "one.one.one.one",
                                  "dns.quad9.net", "doh.opendns.com", "dns.nextdns.io", "nextdns.io",
                                  "adguard-dns.com", "dns.adguard.com", "dns.adguard-dns.com",
                                  "doh.cleanbrowsing.org", "doh.dns.sb", "dns.sb", "use-application-dns.net"]),
    ("Cloudflare tunnel", "nen", ["trycloudflare.com", "argotunnel.com"]),
    ("Apple (nền)", "nen", ["apple.com", "icloud.com", "mzstatic.com", "apple-dns.net", "cdn-apple.com",
                            "aaplimg.com", "icloud-content.com", "push.apple.com"]),
    ("Microsoft (nền)", "nen", ["microsoft.com", "windowsupdate.com", "msftconnecttest.com", "msftncsi.com",
                                "live.com", "office.com", "office.net", "msn.com", "bing.com", "msedge.net",
                                "azureedge.net", "windows.com", "skype.com", "microsoftonline.com", "akadns.net",
                                "trafficmanager.net", "azure.com", "msauth.net", "msftauth.net", "sfx.ms"]),
    ("Google (nền)", "nen", ["googleapis.com", "gvt1.com", "gvt2.com", "gvt3.com", "googlesyndication.com",
                             "doubleclick.net", "google-analytics.com", "googletagmanager.com",
                             "googleadservices.com", "app-measurement.com", "firebaseio.com", "crashlytics.com",
                             "connectivitycheck.gstatic.com", "android.com", "googlezip.net", "1e100.net"]),
    ("Samsung / OPPO (nền)", "nen", ["samsung.com", "samsungcloud.com", "samsungapps.com", "heytapmobi.com",
                                     "heytapdl.com", "oppomobile.com", "coloros.com", "heytap.com", "realme.com",
                                     "xiaomi.com", "miui.com", "xiaomi.net", "allawnos.com", "allawntech.com"]),
    ("Quảng cáo / đo lường", "nen", ["appsflyer.com", "adjust.com", "branch.io", "applovin.com", "unity3d.com",
                                     "unityads.unity3d.com", "criteo.com", "scorecardresearch.com", "adnxs.com",
                                     "amazon-adsystem.com", "taboola.com", "outbrain.com", "hotjar.com",
                                     "sentry.io", "mixpanel.com", "segment.io", "amplitude.com", "onesignal.com"]),
    ("CDN chung", "nen", ["akamaized.net", "akamaihd.net", "akamai.net", "edgekey.net", "edgesuite.net",
                          "cloudfront.net", "fastly.net", "cloudflare.com", "cloudflare.net", "jsdelivr.net",
                          "cdnjs.com", "amazonaws.com"]),
    ("NTP / giờ hệ thống", "nen", ["pool.ntp.org", "time.android.com", "time.windows.com", "time.apple.com"]),
]
_SUFFIX = {}
for _name, _cat, _domains in SERVICES:
    for _d in _domains:
        _SUFFIX[_d] = (_name, _cat)

# Đuôi tên miền 2 cấp hay gặp (để "abc.com.vn" được tính là một trang, không phải "com.vn").
TWO_LEVEL = {"com.vn", "net.vn", "org.vn", "edu.vn", "gov.vn", "vn.ua", "co.uk", "org.uk", "ac.uk", "com.au",
             "co.jp", "co.kr", "com.cn", "com.sg", "com.tw", "com.hk", "co.id", "com.br", "co.th", "com.my"}

IGNORE_SUFFIX = (".lan", ".local", ".arpa", ".home", ".internal", ".localdomain", ".invalid")


def classify(host):
    """Trả về (tên trang, nhóm) cho một tên miền, hoặc None nếu bỏ qua."""
    host = host.lower().rstrip(".")
    if "." not in host or host.endswith(IGNORE_SUFFIX) or re.fullmatch(r"[\d.]+|[\da-f:]+", host):
        return None
    parts = host.split(".")
    for i in range(len(parts) - 1):          # khớp đuôi dài nhất trước: mail.google.com trước google.com
        hit = _SUFFIX.get(".".join(parts[i:]))
        if hit:
            return hit
    n = 3 if ".".join(parts[-2:]) in TWO_LEVEL and len(parts) >= 3 else 2
    return ".".join(parts[-n:]), "web"


def _today(t=None):
    return time.strftime("%Y-%m-%d", time.localtime(t))


class Traffic:
    def __init__(self, log=LOG, data_dir=DATA_DIR, lan_ips=()):
        self.log, self.dir = log, data_dir
        self.skip_ips = {"127.0.0.1", "::1", *lan_ips}
        self.lock = threading.Lock()
        self.day = _today()
        self.data = self._load(self.day)          # {mac: {"name","ip","h":[24],"s":{site:{...}}}}
        self.recent = collections.deque(maxlen=400)
        self._last_minute = {}                     # (mac, site) -> phút gần nhất đã tính
        self._last_recent = {}                     # (mac, host) -> lúc ghi sự kiện gần nhất
        self._mac_cache, self._mac_time = {}, 0
        self._names = {}
        self.dirty = False
        os.makedirs(self.dir, exist_ok=True)
        threading.Thread(target=self._run, daemon=True).start()

    # ---------- lưu trữ
    def _path(self, day):
        return os.path.join(self.dir, day + ".json")

    def _load(self, day):
        try:
            with open(self._path(day)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        with self.lock:
            text = json.dumps(self.data, separators=(",", ":"), ensure_ascii=False)
            day, self.dirty = self.day, False
        tmp = self._path(day) + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, self._path(day))

    def flush(self):
        """Lưu ngay (gọi khi server tắt)."""
        if self.dirty:
            self._save()

    def _prune(self):
        cutoff = _today(time.time() - KEEP_DAYS * 86400)
        for name in os.listdir(self.dir):
            if name.endswith(".json") and name[:-5] < cutoff:
                os.remove(os.path.join(self.dir, name))

    def days(self):
        names = sorted((n[:-5] for n in os.listdir(self.dir) if n.endswith(".json")), reverse=True)
        return names if self.day in names else [self.day] + names

    # ---------- IP -> MAC, MAC -> tên máy
    def _refresh_macs(self):
        cache = {}
        try:
            out = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            m = re.match(r"(\S+) dev \S+ lladdr ([0-9a-f:]{17})", line)
            if m:
                cache[m.group(1)] = m.group(2)
        names = {}
        try:
            with open("/tmp/dhcp.leases") as f:
                for line in f:
                    p = line.split()
                    if len(p) >= 4:
                        cache.setdefault(p[2], p[1].lower())
                        if p[3] != "*":
                            names[p[1].lower()] = p[3]
        except OSError:
            pass
        self._mac_cache, self._names, self._mac_time = cache, names, time.time()

    def _mac_of(self, ip):
        mac = self._mac_cache.get(ip)
        if mac is None and time.time() - self._mac_time > 5:
            self._refresh_macs()
            mac = self._mac_cache.get(ip)
        return mac or ip    # chưa biết MAC thì dùng tạm IP

    # ---------- xử lý log
    def _handle(self, line, now):
        m = QUERY_RE.search(line)
        if not m:
            return
        host, ip = m.group(2).lower().rstrip("."), m.group(3)
        if ip in self.skip_ips:
            return
        cls = classify(host)
        if cls is None:
            return
        site, cat = cls
        mac = self._mac_of(ip)
        minute = int(now // 60)
        with self.lock:
            dev = self.data.setdefault(mac, {"name": "", "ip": ip, "h": [0] * 24, "s": {}})
            dev["ip"] = ip
            dev["name"] = self._names.get(mac) or dev.get("name", "")
            s = dev["s"].setdefault(site, {"c": cat, "m": 0, "q": 0, "f": int(now), "l": int(now), "x": []})
            s["q"] += 1
            s["l"] = int(now)
            if host not in s["x"] and len(s["x"]) < MAX_HOSTS:
                s["x"].append(host)
            if self._last_minute.get((mac, site)) != minute:
                self._last_minute[(mac, site)] = minute
                s["m"] += 1
                dev["h"][time.localtime(now).tm_hour] += 1
            if now - self._last_recent.get((mac, host), 0) >= RECENT_GAP:
                self._last_recent[(mac, host)] = now
                self.recent.append({"t": int(now), "mac": mac, "host": host, "site": site, "c": cat})
            self.dirty = True

    def _roll_day(self, now):
        day = _today(now)
        if day == self.day:
            return
        if self.dirty:
            self._save()
        with self.lock:
            self.day, self.data = day, {}
            self._last_minute.clear()
            self._last_recent.clear()
        self._prune()

    def _run(self):
        f, pos, last_save = None, 0, time.time()
        while True:
            try:
                if f is None:
                    f = open(self.log, "rb")
                    f.seek(0, os.SEEK_END)      # chỉ đọc dòng mới; dòng cũ đã tính trước khi server khởi động lại
                    pos = f.tell()
                size = os.path.getsize(self.log)
                if size < pos:                   # log bị cắt / dnsmasq tạo lại file
                    f.seek(0)
                    pos = 0
                chunk = f.read()
                if chunk:
                    now = time.time()
                    self._roll_day(now)
                    end = chunk.rfind(b"\n") + 1  # giữ lại dòng chưa ghi xong
                    f.seek(pos + end)
                    pos += end
                    for line in chunk[:end].decode("utf-8", "replace").splitlines():
                        self._handle(line, now)
                if pos > MAX_LOG:
                    os.truncate(self.log, 0)
                    f.seek(0)
                    pos = 0
            except FileNotFoundError:
                f = None
            except OSError:
                f = None
            now = time.time()
            self._roll_day(now)
            if self.dirty and now - last_save >= SAVE_EVERY:
                try:
                    self._save()
                except OSError:
                    pass
                last_save = now
            time.sleep(1)

    # ---------- API
    def report(self, day=None, top=60):
        day = day or self.day
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("ngày không hợp lệ")
        if day == self.day:
            with self.lock:
                data = json.loads(json.dumps(self.data))
        else:
            data = self._load(day)
        if not self._names:
            self._refresh_macs()
        out = []
        for mac, dev in data.items():
            sites = sorted(({"site": k, **v} for k, v in dev["s"].items()), key=lambda s: (-s["m"], -s["q"]))
            out.append({
                "mac": mac, "name": self._names.get(mac) or dev.get("name", ""), "ip": dev.get("ip", ""),
                "hours": dev["h"],
                "minutes": sum(s["m"] for s in sites if s["c"] != "nen"),
                "sites": sites[:top], "site_count": len(sites),
            })
        out.sort(key=lambda d: -d["minutes"])
        return {"day": day, "today": self.day, "days": self.days(), "devices": out,
                "bytes": nlbw_bytes(None if day == self.day else day)}

    def recent_events(self, mac=None, since=0, limit=100):
        with self.lock:
            ev = [e for e in self.recent if e["t"] > since and (not mac or e["mac"] == mac)]
        return ev[-limit:][::-1]


def nlbw_bytes(day):
    """Dung lượng mỗi máy trong ngày (nlbwmon, chu kỳ 1 ngày). {mac: {"rx","tx","conns"}}
    day=None: ngày hiện tại (còn trong RAM của nlbwmon); ngày cũ đọc từ file đã lưu (-t)."""
    try:
        out = subprocess.run(["nlbw", "-c", "json", "-g", "mac"] + (["-t", day] if day else []),
                             capture_output=True, text=True, timeout=5).stdout
        j = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    cols = j.get("columns", [])
    res = {}
    for row in j.get("data", []):
        r = dict(zip(cols, row))
        mac = str(r.get("mac", "")).lower()
        if mac:
            res[mac] = {"rx": r.get("rx_bytes", 0), "tx": r.get("tx_bytes", 0), "conns": r.get("conns", 0)}
    return res
