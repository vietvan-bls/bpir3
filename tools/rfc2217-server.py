#!/usr/bin/env python3
"""Chia sẻ cổng serial của board qua RFC2217 (esptool/pyserial ở máy khác dùng rfc2217://host:port, có điều khiển DTR/RTS).
Chạy trên BPI-R3: PYTHONPATH=/mnt/data/pylib python3 rfc2217-server.py /dev/ttyUSB0 [port] [bind]
Mặc định chỉ nghe 127.0.0.1:4000 → truy cập qua SSH: ssh -L 4000:127.0.0.1:4000 …"""
import socket, sys, threading
import serial, serial.rfc2217

dev = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
bind = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"

ser = serial.serial_for_url(dev, do_not_open=True); ser.timeout = 0.05; ser.dtr = False; ser.rts = False
ser.open()
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind((bind, port)); srv.listen(1)
print(f"RFC2217 {dev} → {bind}:{port}", flush=True)
while True:
    conn, addr = srv.accept(); conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("client", addr, flush=True)
    class W:  # PortManager cần đối tượng có .write()
        def write(self, d): conn.sendall(d)
    pm = serial.rfc2217.PortManager(ser, W())
    alive = [True]
    def reader():
        while alive[0]:
            try:
                d = ser.read(ser.in_waiting or 1)
                if d: conn.sendall(b"".join(pm.escape(d)))
            except Exception: break
        alive[0] = False
    t = threading.Thread(target=reader, daemon=True); t.start()
    try:
        while alive[0]:
            d = conn.recv(1024)
            if not d: break
            ser.write(b"".join(pm.filter(d)))
    except Exception: pass
    alive[0] = False; t.join(); conn.close(); ser.dtr = False; ser.rts = False
    print("client gone", flush=True)
