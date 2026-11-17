"""Thư viện nhạc trên board: các file trong MUSIC_DIR (kể cả thư mục con), đọc tên bài / ca sĩ / album /
thời lượng / ảnh bìa bằng `ffmpeg -i` (OpenWrt không có ffprobe). Thông tin được lưu tạm trong
MUSIC_DIR/.index.json để lần sau không phải đọc lại.

Cùng thư mục này được minidlna chia sẻ qua DLNA cho các app nghe nhạc.
"""
import json
import os
import re
import shutil
import subprocess
import threading

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/mnt/data/music")
TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac",
         ".ogg": "audio/ogg", ".opus": "audio/ogg", ".oga": "audio/ogg", ".wav": "audio/wav",
         ".webm": "audio/webm"}
MAX_UPLOAD = 1024 * 1024 * 1024     # 1 GB mỗi file
KEEP_FREE = 512 * 1024 * 1024       # chừa lại ít nhất 512 MB trống trên thẻ


def _probe(path):
    """Đọc metadata bằng `ffmpeg -i` (in ra stderr rồi báo lỗi vì không có file đầu ra, như vậy là bình thường)."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path], capture_output=True, timeout=20).stderr
    except (OSError, subprocess.SubprocessError):
        return {}
    text = out.decode("utf-8", "replace")
    meta, in_input_meta = {}, False
    for line in text.splitlines():
        if line.startswith("Input #0"):
            in_input_meta = True
            continue
        if in_input_meta:
            m = re.match(r"\s{4}(\w+)\s*:\s(.*)", line)
            if m and m.group(1).lower() in ("title", "artist", "album", "album_artist", "date", "track"):
                meta.setdefault(m.group(1).lower(), m.group(2).strip())
            elif re.match(r"\s{2}Duration:", line):
                in_input_meta = False
        d = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", line)
        if d:
            meta["dur"] = round(int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)), 1)
        if re.search(r"Stream #0:\d+.*Video: (mjpeg|png)", line):   # ảnh bìa gắn trong file
            meta["cover"] = True
    return meta


class Library:
    def __init__(self, root=MUSIC_DIR):
        self.root = os.path.realpath(root)
        os.makedirs(self.root, exist_ok=True)
        self.index_file = os.path.join(self.root, ".index.json")
        self.lock = threading.Lock()
        self.index = self._load()       # relpath -> {"mt","size", metadata...}
        self.pending = []
        self.wake = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    def _load(self):
        try:
            with open(self.index_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        with self.lock:
            text = json.dumps(self.index, ensure_ascii=False)
        tmp = self.index_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, self.index_file)

    # ---------- đường dẫn an toàn
    def path_of(self, rel):
        """relpath (từ trình duyệt) -> đường dẫn thật; chặn ../ và file không phải nhạc."""
        full = os.path.realpath(os.path.join(self.root, rel or ""))
        if not full.startswith(self.root + os.sep) or os.path.splitext(full)[1].lower() not in TYPES:
            raise ValueError("Bài hát không hợp lệ")
        if any(p.startswith(".") for p in os.path.relpath(full, self.root).split(os.sep)):
            raise ValueError("Bài hát không hợp lệ")
        if not os.path.isfile(full):
            raise FileNotFoundError("Không tìm thấy bài hát")
        return full

    # ---------- quét thư viện
    def scan(self):
        found = {}
        for dirpath, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in TYPES:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                found[os.path.relpath(full, self.root).replace(os.sep, "/")] = (int(st.st_mtime), st.st_size)
        changed = False
        with self.lock:
            for rel in list(self.index):
                if rel not in found:
                    del self.index[rel]
                    changed = True
            for rel, (mt, size) in found.items():
                cur = self.index.get(rel)
                if not cur or cur.get("mt") != mt or cur.get("size") != size:
                    self.index[rel] = {"mt": mt, "size": size, "new": True}
                    if rel not in self.pending:
                        self.pending.append(rel)
                    changed = True
        if self.pending:
            self.wake.set()
        if changed:
            self._save()

    def _worker(self):
        while True:
            self.wake.wait()
            self.wake.clear()
            while True:
                with self.lock:
                    if not self.pending:
                        break
                    rel = self.pending.pop(0)
                meta = _probe(os.path.join(self.root, rel))
                with self.lock:
                    if rel in self.index:
                        self.index[rel].update(meta)
                        self.index[rel].pop("new", None)
            try:
                self._save()
            except OSError:
                pass

    def tracks(self):
        self.scan()
        with self.lock:
            items = list(self.index.items())
            scanning = len(self.pending)
        out = []
        for rel, m in items:
            base = os.path.splitext(os.path.basename(rel))[0]
            artist, title = m.get("artist", ""), m.get("title", "")
            if not title and " - " in base:          # tên file kiểu "Ca sĩ - Tên bài.mp3"
                artist, title = (artist or base.split(" - ", 1)[0]), base.split(" - ", 1)[1]
            out.append({"id": rel, "title": title or base, "artist": artist, "album": m.get("album", ""),
                        "folder": os.path.dirname(rel), "dur": m.get("dur", 0), "size": m["size"],
                        "cover": bool(m.get("cover")), "added": m["mt"]})
        out.sort(key=lambda t: (t["folder"].lower(), t["artist"].lower(), t["title"].lower()))
        du = shutil.disk_usage(self.root)
        return {"tracks": out, "scanning": scanning, "free": du.free, "total": du.total,
                "used": sum(t["size"] for t in out)}

    def cover(self, rel):
        """Ảnh bìa gắn trong file (lưu đệm ở .covers/)."""
        full = self.path_of(rel)
        cache_dir = os.path.join(self.root, ".covers")
        os.makedirs(cache_dir, exist_ok=True)
        key = re.sub(r"[^\w.-]", "_", rel) + f".{int(os.stat(full).st_mtime)}.jpg"
        cached = os.path.join(cache_dir, key)
        if not os.path.exists(cached):
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", full, "-an", "-frames:v", "1",
                                "-vf", "scale=300:300:force_original_aspect_ratio=decrease", cached],
                               capture_output=True, timeout=20)
            if r.returncode or not os.path.exists(cached):
                raise FileNotFoundError("Bài này không có ảnh bìa")
        with open(cached, "rb") as f:
            return f.read()

    # ---------- tải lên / xóa
    def clean_name(self, name):
        name = os.path.basename((name or "").replace("\\", "/")).strip()
        name = re.sub(r"[\x00-\x1f<>:\"|?*]", "", name).lstrip(".")
        ext = os.path.splitext(name)[1].lower()
        if not name or ext not in TYPES:
            raise ValueError("Chỉ nhận file nhạc: " + ", ".join(sorted(TYPES)))
        return name[:180 - len(ext)] + ext if len(name) > 180 else name

    def save_upload(self, name, length, stream):
        name = self.clean_name(name)
        if length <= 0:
            raise ValueError("File rỗng")
        if length > MAX_UPLOAD:
            raise ValueError("File quá lớn (tối đa 1 GB)")
        if shutil.disk_usage(self.root).free - length < KEEP_FREE:
            raise ValueError("Thẻ nhớ sắp đầy")
        base, ext = os.path.splitext(name)
        dst, n = os.path.join(self.root, name), 2
        while os.path.exists(dst):
            dst, n = os.path.join(self.root, f"{base} ({n}){ext}"), n + 1
        tmp = os.path.join(self.root, f".upload-{threading.get_ident()}.part")
        left = length
        try:
            with open(tmp, "wb") as f:
                while left:
                    chunk = stream.read(min(left, 256 * 1024))
                    if not chunk:
                        raise ValueError("Tải lên bị ngắt giữa chừng")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self.scan()
        return os.path.relpath(dst, self.root).replace(os.sep, "/")

    def delete(self, rel):
        os.remove(self.path_of(rel))
        self.scan()
