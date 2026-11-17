"""Đo tốc độ và kết quả của server/vision.py trên toàn bộ video mẫu (chạy trên board).

    cd /root/server && python3 /root/bench_vision.py
"""
import sys
import time

sys.path.insert(0, "/root/server")
import vision  # noqa: E402

t = time.time()
v = vision.Vision("/mnt/data/camera/vtest_192x144.gray", 768, 576)
print("khởi tạo", round(time.time() - t, 2), "s")
counts, worst = [], 0.0
for i in range(len(v.gray)):
    t0 = time.perf_counter()
    r = v.process(i)
    worst = max(worst, (time.perf_counter() - t0) * 1000)
    counts.append(r["count"])
    if i in (50, 200, 400, 600):
        print(f"khung {i}: đang thấy {r['count']}, tổng {r['total']}, boxes {[p['box'] for p in r['people']][:4]}")
print(f"trung bình {r['ms']} ms/khung, chậm nhất {worst:.0f} ms, "
      f"đông nhất {max(counts)} người, trung bình {sum(counts) / len(counts):.1f}, tổng lượt {r['total']}")
