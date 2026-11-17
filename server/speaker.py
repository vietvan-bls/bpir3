"""Phát nhạc ra loa USB cắm vào board (ALSA): ffmpeg giải mã -> aplay.

Trang web chỉ làm "remote": chọn bài, dừng, chuyển bài, tua, âm lượng. Nhạc chạy trên board nên tắt
màn hình điện thoại vẫn phát tiếp.

- Tạm dừng = dừng tiến trình và nhớ vị trí; phát tiếp = chạy lại từ vị trí đó (ffmpeg -ss).
- Card USB hay tự rút ra cắm lại (mất nguồn / firmware reset): aplay báo lỗi -> chờ card xuất hiện lại
  rồi phát tiếp từ vị trí cũ. Mỗi lần card cắm lại âm lượng về 100%, nên trước mỗi lần phát đều đặt lại.
"""
import os
import random
import re
import signal
import subprocess
import threading
import time

RATE = 48000
RETRY_LIMIT = 5
MAX_VOLUME = 200        # 0–100: mixer của card; 100–200: tăng thêm bằng phần mềm tới +BOOST_DB
BOOST_DB = 12.0


def soft_gain_db(volume):
    return round(max(0, volume - 100) / (MAX_VOLUME - 100) * BOOST_DB, 1)


def find_card():
    """Card ALSA đầu tiên có đường phát (playback). Trả về số card hoặc None."""
    try:
        with open("/proc/asound/cards") as f:
            cards = re.findall(r"^\s*(\d+)\s+\[", f.read(), re.M)
    except OSError:
        return None
    for c in cards:
        if os.path.exists(f"/proc/asound/card{c}/pcm0p"):
            return int(c)
    return None


def card_name(card):
    try:
        with open("/proc/asound/cards") as f:
            m = re.search(rf"^\s*{card}\s+\[[^\]]*\]:\s*(.*)$", f.read(), re.M)
            return m.group(1).split(" - ", 1)[-1].strip() if m else ""
    except OSError:
        return ""


def _mixer_control(card):
    try:
        out = subprocess.run(["amixer", "-c", str(card), "scontrols"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    names = re.findall(r"'([^']+)',\d+", out)
    for pref in ("PCM", "Master", "Speaker", "Headphone"):
        if pref in names:
            return pref
    return names[0] if names else None


class Speaker:
    def __init__(self, library):
        self.lib = library
        self.lock = threading.RLock()
        self.queue, self.idx = [], -1        # danh sách id bài, vị trí đang phát
        self.state = "stopped"               # stopped | playing | paused
        self.offset = 0.0                    # vị trí (giây) lúc bắt đầu tiến trình hiện tại
        self.started = 0.0                   # time.time() lúc bắt đầu tiến trình hiện tại
        self.volume = 60
        self.shuffle = False
        self.repeat = False
        self.error = ""
        self.procs = None
        self.gen = 0                         # tăng mỗi lần đổi bài/tua -> luồng theo dõi cũ tự bỏ

    # ---------- trạng thái
    def position(self):
        if self.state == "playing":
            return self.offset + (time.time() - self.started)
        return self.offset

    def current(self):
        if 0 <= self.idx < len(self.queue):
            return self.queue[self.idx]
        return None

    def status(self):
        card = find_card()
        with self.lock:
            tid = self.current()
            info = None
            if tid:
                info = next((t for t in self.lib.tracks()["tracks"] if t["id"] == tid), {"id": tid, "title": tid})
            dur = (info or {}).get("dur") or 0
            pos = self.position()
            return {"available": card is not None, "card": card_name(card) if card is not None else "",
                    "state": self.state, "track": info, "pos": round(min(pos, dur) if dur else pos, 1),
                    "dur": dur, "index": self.idx, "count": len(self.queue), "volume": self.volume,
                    "max_volume": MAX_VOLUME, "boost_db": soft_gain_db(self.volume),
                    "shuffle": self.shuffle, "repeat": self.repeat, "error": self.error}

    # ---------- âm lượng
    def apply_volume(self, card=None):
        card = find_card() if card is None else card
        if card is None:
            return
        ctl = _mixer_control(card)
        if ctl:
            subprocess.run(["amixer", "-q", "-c", str(card), "sset", ctl, f"{min(self.volume, 100)}%"],
                           capture_output=True, timeout=5)

    def set_volume(self, v):
        v = int(v)
        if not 0 <= v <= MAX_VOLUME:
            raise ValueError(f"Âm lượng 0–{MAX_VOLUME}")
        with self.lock:
            old_gain = soft_gain_db(self.volume)
            self.volume = v
            # Phần tăng thêm bằng phần mềm nằm trong ffmpeg -> đổi mức thì chạy lại từ vị trí hiện tại.
            if soft_gain_db(v) != old_gain and self.state == "playing":
                self._start(self.position())
                return
        self.apply_volume()

    # ---------- tiến trình phát
    def _kill(self):
        if self.procs:
            for p in self.procs:
                try:
                    p.send_signal(signal.SIGTERM)
                except OSError:
                    pass
            for p in self.procs:
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()
            self.procs = None

    def _start(self, pos, retries=0):
        """Bắt đầu phát bài hiện tại từ giây `pos`. Gọi khi đang giữ lock."""
        self._kill()
        self.gen += 1
        tid = self.current()
        if tid is None:
            self.state, self.offset = "stopped", 0.0
            return
        card = find_card()
        if card is None:
            self.state, self.error = "paused", "Không thấy loa USB, cắm lại loa rồi bấm phát"
            self.offset = pos
            return
        try:
            path = self.lib.path_of(tid)
        except (ValueError, FileNotFoundError):
            self.error = "Bài không còn trên board, chuyển bài sau"
            return self._advance(auto=True)
        self.apply_volume(card)
        gain = soft_gain_db(self.volume)
        # Tăng âm: alimiter giữ đỉnh dưới 0 dB để không bị rè (vỡ tiếng) khi bài vốn đã to.
        af = ["-af", f"volume={gain}dB,alimiter=limit=0.95:level=false"] if gain > 0 else []
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{pos:.2f}", "-i", path,
                                "-vn", *af, "-ac", "2", "-ar", str(RATE), "-f", "s16le", "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        play = subprocess.Popen(["aplay", "-q", "-D", f"plughw:{card},0", "-f", "S16_LE", "-c", "2",
                                 "-r", str(RATE), "-t", "raw", "-B", "200000"],
                                stdin=dec.stdout, stderr=subprocess.PIPE)
        dec.stdout.close()
        self.procs = (dec, play)
        self.state, self.offset, self.started, self.error = "playing", pos, time.time(), ""
        threading.Thread(target=self._watch, args=(self.gen, play, dec, retries), daemon=True).start()

    def _watch(self, gen, play, dec, retries):
        err = play.stderr.read().decode("utf-8", "replace")
        rc = play.wait()
        dec.wait()
        with self.lock:
            if gen != self.gen:          # đã đổi bài / tua / dừng -> tiến trình bị mình tắt, bỏ qua
                return
            self.procs = None
            if rc == 0 and dec.returncode == 0:
                return self._advance(auto=True)
            # aplay lỗi: thường do card USB vừa rút ra cắm lại -> chờ rồi phát tiếp chỗ cũ
            pos = self.position()
            if retries >= RETRY_LIMIT:
                self.state, self.offset = "paused", pos
                self.error = "Loa USB lỗi: " + (err.strip().splitlines() or ["không rõ"])[-1][:150]
                return
            self.state, self.offset, self.error = "paused", pos, "Loa USB bị ngắt, đang kết nối lại…"
        time.sleep(2)
        with self.lock:
            if gen == self.gen:
                self._start(pos, retries + 1)

    def _advance(self, auto=False, step=1):
        if not self.queue:
            self.state = "stopped"
            return
        nxt = self.idx + step
        if nxt >= len(self.queue):
            if auto and not self.repeat:
                self.state, self.offset = "stopped", 0.0
                self.idx = 0
                return
            nxt = 0
        elif nxt < 0:
            nxt = len(self.queue) - 1
        self.idx = nxt
        self._start(0.0)

    # ---------- lệnh từ trang web
    def command(self, body):
        act = body.get("action")
        with self.lock:
            if act == "play":
                ids = [str(i) for i in body.get("ids") or []][:5000]
                if not ids:
                    raise ValueError("Danh sách bài trống")
                idx = int(body.get("index", 0))
                if not 0 <= idx < len(ids):
                    raise ValueError("Vị trí bài không hợp lệ")
                if self.shuffle:      # bài được chọn phát trước, còn lại trộn
                    first = ids.pop(idx)
                    random.shuffle(ids)
                    ids, idx = [first] + ids, 0
                self.queue, self.idx = ids, idx
                self._start(0.0)
            elif act == "toggle":
                if self.state == "playing":
                    act = "pause"
                elif self.current():
                    act = "resume"
                else:
                    raise ValueError("Chưa chọn bài")
            if act == "pause" and self.state == "playing":
                pos = self.position()
                self.gen += 1
                self._kill()
                self.state, self.offset = "paused", pos
            elif act == "resume" and self.state != "playing" and self.current():
                self._start(self.offset)
            elif act == "stop":
                self.gen += 1
                self._kill()
                self.state, self.offset = "stopped", 0.0
            elif act == "next":
                self._advance(step=1)
            elif act == "prev":
                if self.position() > 3 and self.current():
                    self._start(0.0)
                else:
                    self._advance(step=-1)
            elif act == "seek":
                pos = max(0.0, float(body.get("pos", 0)))
                if self.state == "playing":
                    self._start(pos)
                else:
                    self.offset = pos
            elif act == "volume":
                self.set_volume(body.get("volume", self.volume))
            elif act == "shuffle":
                self.shuffle = bool(body.get("on"))
            elif act == "repeat":
                self.repeat = bool(body.get("on"))
            elif act not in ("play", "pause", "resume"):
                raise ValueError("Lệnh không hợp lệ")
        return self.status()

    def shutdown(self):
        with self.lock:
            self.gen += 1
            self._kill()
