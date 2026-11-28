#!/bin/sh
# Kho linh kiện + IoT trên Linux / Raspberry Pi. Lần đầu: python3 -m pip install -r requirements-desktop.txt
cd "$(dirname "$0")" && exec python3 desktop.py "$@"
