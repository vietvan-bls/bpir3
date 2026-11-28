#!/usr/bin/env python3
"""Công cụ CAN tối giản cho BPI-R3 (OpenWrt không có gói can-utils) — dùng socketcan của Python.
  can.py up [bitrate] [iface]          bật cổng (mặc định 500000, can0)
  can.py down [iface]
  can.py dump [iface]                  in mọi khung nhận được (Ctrl-C để dừng)
  can.py send ID#DATA [iface]          vd: can.py send 123#DEADBEEF   ·  ID 8 chữ số hex = khung mở rộng 29 bit"""
import socket, struct, subprocess, sys, time

FMT = "=IB3x8s"

def sock(iface):
    s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW); s.bind((iface,)); return s

def main(a):
    cmd = a[0] if a else "dump"
    if cmd == "up":
        br = a[1] if len(a) > 1 else "500000"; i = a[2] if len(a) > 2 else "can0"
        subprocess.run(["ip", "link", "set", i, "down"])
        subprocess.run(["ip", "link", "set", i, "type", "can", "bitrate", br, "restart-ms", "100"], check=True)
        subprocess.run(["ip", "link", "set", i, "up"], check=True); print(i, "up", br)
    elif cmd == "down":
        subprocess.run(["ip", "link", "set", a[1] if len(a) > 1 else "can0", "down"], check=True)
    elif cmd == "send":
        cid, data = a[1].split("#"); i = a[2] if len(a) > 2 else "can0"
        n = int(cid, 16) | (socket.CAN_EFF_FLAG if len(cid) > 3 else 0); d = bytes.fromhex(data)
        sock(i).send(struct.pack(FMT, n, len(d), d.ljust(8, b"\0")))
    elif cmd == "dump":
        s = sock(a[1] if len(a) > 1 else "can0")
        while True:
            n, l, d = struct.unpack(FMT, s.recv(16))
            ext = n & socket.CAN_EFF_FLAG; cid = n & (0x1FFFFFFF if ext else 0x7FF)
            print("%.3f  %s  [%d]  %s" % (time.time(), ("%08X" if ext else "%03X") % cid, l, d[:l].hex(" ").upper()), flush=True)
    else:
        print(__doc__)

if __name__ == "__main__":
    try: main(sys.argv[1:])
    except KeyboardInterrupt: pass
