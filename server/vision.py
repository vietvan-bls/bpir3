"""Phát hiện và tracking người (camera thật hoặc video mẫu), chỉ dùng numpy (OpenWrt không có OpenCV).

Cách làm:
  1. Phân tích trên ảnh xám thu nhỏ 192x144: camera thật thì ffmpeg xuất song song với luồng MJPEG (LiveVision);
     video mẫu thì tạo sẵn bằng ffmpeg, khớp từng khung với file MJPEG (Vision).
  2. Trừ nền: nền = trung vị của ~60 khung rải đều (video mẫu) hoặc khung đầu tiên (camera thật), sau đó cập nhật
     chậm ở những chỗ không có người. Bật/tắt đèn làm cả cảnh đổi -> dựng lại nền ngay.
     Pixel lệch nền > DIFF_THRESH là "tiền cảnh".
  3. Lọc nhiễu bằng phép mở/đóng hình thái học, gom pixel liền nhau thành vùng (connected components)
     trên lưới 96x72, bỏ vùng quá nhỏ -> mỗi vùng là một "người".
  4. Tracker: ghép vùng ở khung này với người ở khung trước theo khoảng cách tâm (tham lam, gần nhất trước).
     Người mới phải xuất hiện >= CONFIRM_HITS khung mới được tính (bỏ nhiễu chớp nhoáng),
     mất dấu quá MAX_MISSED khung thì xóa.

Hạn chế: người đi sát nhau bị gộp thành một vùng; vật chuyển động khác cũng bị tính.
Muốn nhận diện "người" chuẩn hơn cần mô hình AI (YOLO/MobileNet-SSD), nặng hơn nhiều với CPU này.
"""
import time
from collections import deque

import numpy as np

DIFF_THRESH = 28      # độ lệch xám so với nền để coi là tiền cảnh
BG_RATE = 0.02        # tốc độ cập nhật nền
MIN_AREA = 10         # diện tích tối thiểu (ô 8x8 px ảnh gốc) để coi là người
MIN_HEIGHT = 3        # chiều cao tối thiểu (ô)
MAX_DIST = 70         # khoảng cách tâm tối đa (px ảnh gốc) để ghép cùng một người
MAX_MISSED = 6        # mất dấu quá số khung này thì xóa
CONFIRM_HITS = 3      # xuất hiện đủ số khung này mới tính là người
TRAIL_LEN = 25        # số điểm vệt đường đi
SCENE_CHANGE = 0.45   # > tỉ lệ này pixel lệch nền -> coi là đổi ánh sáng / camera bị xoay: dựng lại nền


def _dilate(m):
    r = m.copy()
    r[1:] |= m[:-1]; r[:-1] |= m[1:]; r[:, 1:] |= m[:, :-1]; r[:, :-1] |= m[:, 1:]
    return r


def _erode(m):
    r = m.copy()
    r[1:] &= m[:-1]; r[:-1] &= m[1:]; r[:, 1:] &= m[:, :-1]; r[:, :-1] &= m[:, 1:]
    return r


def _components(mask):
    """Gom ô True liền nhau (4 hướng). Trả về list (x0, y0, x1, y1, area) theo ô."""
    h, w = mask.shape
    left = set(zip(*np.nonzero(mask)))
    out = []
    while left:
        stack = [left.pop()]
        y0 = y1 = stack[0][0]; x0 = x1 = stack[0][1]; area = 0
        while stack:
            y, x = stack.pop()
            area += 1
            y0, y1, x0, x1 = min(y0, y), max(y1, y), min(x0, x), max(x1, x)
            for n in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if n in left:
                    left.remove(n)
                    stack.append(n)
        out.append((x0, y0, x1, y1, area))
    return out


class MotionDetector:
    def __init__(self, bg, full_w, full_h):
        self.bg = bg.astype(np.float32)
        self.h, self.w = self.bg.shape
        self.cell = (full_w / (self.w / 2), full_h / (self.h / 2))  # kích thước 1 ô lưới (px ảnh gốc)
        self.scene_changed = False

    @classmethod
    def from_frames(cls, gray_frames, full_w, full_h):
        n = len(gray_frames)
        return cls(np.median(gray_frames[:: max(1, n // 60)], axis=0), full_w, full_h)

    def detect(self, g):
        gf = g.astype(np.float32)
        fg = np.abs(gf - self.bg) > DIFF_THRESH
        self.scene_changed = fg.mean() > SCENE_CHANGE
        if self.scene_changed:          # bật/tắt đèn, camera tự chỉnh sáng, bị xoay: lấy khung này làm nền mới
            self.bg = gf
            return []
        # cập nhật nền chậm ở chỗ không có người (để thích nghi thay đổi ánh sáng)
        self.bg = np.where(fg, self.bg, self.bg * (1 - BG_RATE) + gf * BG_RATE)
        m = _dilate(_erode(fg))                 # mở: bỏ chấm nhiễu
        m = _erode(_dilate(_dilate(m)))         # đóng: nối các phần cơ thể
        m2 = m.reshape(self.h // 2, 2, self.w // 2, 2).any(axis=(1, 3))  # lưới 96x72
        cw, ch = self.cell
        boxes = []
        for x0, y0, x1, y1, area in _components(m2):
            if area >= MIN_AREA and (y1 - y0 + 1) >= MIN_HEIGHT:
                boxes.append((x0 * cw, y0 * ch, (x1 - x0 + 1) * cw, (y1 - y0 + 1) * ch))
        return boxes


class Tracker:
    def __init__(self):
        self.next_id = 1
        self.tracks = {}   # id -> dict
        self.total = 0     # tổng số người (đã xác nhận) từng xuất hiện

    def reset(self):
        self.tracks.clear()

    def update(self, boxes):
        cents = [(x + w / 2, y + h / 2) for x, y, w, h in boxes]
        pairs = []
        for tid, t in self.tracks.items():
            for j, (cx, cy) in enumerate(cents):
                d = ((t["cx"] - cx) ** 2 + (t["cy"] - cy) ** 2) ** 0.5
                if d < MAX_DIST:
                    pairs.append((d, tid, j))
        pairs.sort()
        used_t, used_d = set(), set()
        for d, tid, j in pairs:
            if tid in used_t or j in used_d:
                continue
            used_t.add(tid); used_d.add(j)
            t = self.tracks[tid]
            t["box"], (t["cx"], t["cy"]) = boxes[j], cents[j]
            t["hits"] += 1; t["missed"] = 0
            t["trail"].append((round(t["cx"]), round(t["cy"])))
            if t["hits"] == CONFIRM_HITS:
                self.total += 1
                t["num"] = self.total
        for tid in [t for t in self.tracks if t not in used_t]:
            self.tracks[tid]["missed"] += 1
            if self.tracks[tid]["missed"] > MAX_MISSED:
                del self.tracks[tid]
        for j in range(len(boxes)):
            if j not in used_d:
                cx, cy = cents[j]
                self.tracks[self.next_id] = {"box": boxes[j], "cx": cx, "cy": cy, "hits": 1, "missed": 0,
                                             "num": None, "trail": deque([(round(cx), round(cy))], TRAIL_LEN)}
                self.next_id += 1
        visible = [t for t in self.tracks.values() if t["num"] is not None and t["missed"] == 0]
        return [{"id": t["num"], "box": [round(v) for v in t["box"]], "trail": list(t["trail"])}
                for t in visible]


class Vision:
    """Chạy detector + tracker cho từng khung camera, giữ kết quả mới nhất."""

    def __init__(self, gray_path, full_w, full_h, small_w=192, small_h=144):
        self.gray = np.fromfile(gray_path, np.uint8).reshape(-1, small_h, small_w)
        self.full = (full_w, full_h)
        self.det = MotionDetector.from_frames(self.gray, full_w, full_h)
        self.trk = Tracker()
        self.last_index = -1
        self.result = {"frame": -1, "people": [], "count": 0, "total": 0, "ms": 0}
        self.ms_avg = 0.0

    def process(self, index):
        t0 = time.perf_counter()
        if index < self.last_index:      # video quay lại từ đầu -> cảnh nhảy, xóa track cũ
            self.trk.reset()
        self.last_index = index
        people = self.trk.update(self.det.detect(self.gray[index % len(self.gray)]))
        ms = (time.perf_counter() - t0) * 1000
        self.ms_avg = ms if not self.ms_avg else self.ms_avg * 0.9 + ms * 0.1
        self.result = {"frame": index, "w": self.full[0], "h": self.full[1], "people": people,
                       "count": len(people), "total": self.trk.total, "ms": round(self.ms_avg, 1)}
        return self.result


class LiveVision:
    """Như Vision nhưng nhận từng ảnh xám từ camera thật (không biết trước toàn bộ video)."""

    def __init__(self, full_w, full_h):
        self.full = (full_w, full_h)
        self.det = None
        self.trk = Tracker()
        self.n = 0
        self.ms_avg = 0.0
        self.motion_at = 0.0          # lần cuối thấy chuyển động (dùng cho cảnh báo sau này)
        self.result = {"frame": -1, "w": full_w, "h": full_h, "people": [], "count": 0, "total": 0, "ms": 0}

    def process_gray(self, g):
        t0 = time.perf_counter()
        self.n += 1
        if self.det is None:
            self.det = MotionDetector(g, *self.full)
            boxes = []
        else:
            boxes = self.det.detect(g)
            if self.det.scene_changed:
                self.trk.reset()
        people = self.trk.update(boxes)
        if people:
            self.motion_at = time.time()
        ms = (time.perf_counter() - t0) * 1000
        self.ms_avg = ms if not self.ms_avg else self.ms_avg * 0.9 + ms * 0.1
        self.result = {"frame": self.n, "w": self.full[0], "h": self.full[1], "people": people,
                       "count": len(people), "total": self.trk.total, "ms": round(self.ms_avg, 1)}
        return self.result
