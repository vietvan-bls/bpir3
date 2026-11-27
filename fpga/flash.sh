#!/bin/sh
# Nạp bitstream lên FPGA cắm USB vào BPI-R3 (openFPGALoader ở /mnt/data/fpga trên board).
# Dùng: ./flash.sh file.fs [board] [-f]     board mặc định tangnano4k; -f = ghi flash (giữ sau khi rút điện)
# Cần lệnh SSH vào board: biến BPI_SSH (mặc định script `b` trong PATH, xem CLAUDE.md).
set -e
FS=$1; BOARD=${2:-tangnano4k}; FLASH=$3; SSH=${BPI_SSH:-b}
[ -f "$FS" ] || { echo "dùng: $0 file.fs [board] [-f]"; exit 1; }
cat "$FS" | $SSH "cat > /tmp/up.fs && /mnt/data/fpga/openFPGALoader -b $BOARD $FLASH /tmp/up.fs; rm -f /tmp/up.fs"
