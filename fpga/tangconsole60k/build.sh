#!/bin/sh
# Build bitstream Tang Console 60K (GW5AT-60) bằng Yosys + nextpnr-himbaechel + Apicula (>= 0.36).
# Bản nextpnr trên PyPI (YoWASP 0.11) chưa có GW5AT-60 → build nextpnr từ source (xem README mục FPGA), đặt NEXTPNR=...
# Dùng: ./build.sh hello.v [file.cst]   → build/hello.fs
set -e
cd "$(dirname "$0")"
SRC=${1:-hello.v}; CST=${2:-tangconsole60k.cst}; N=$(basename "$SRC" .v)
YOSYS=${YOSYS:-$(command -v yosys || echo yowasp-yosys)}
PNR=${NEXTPNR:-$(command -v nextpnr-himbaechel || echo /opt/nextpnr/bin/nextpnr-himbaechel)}
mkdir -p build
$YOSYS -q -l build/$N-yosys.log -p "read_verilog $SRC; synth_gowin -top top -family gw5a -nolutram -json build/$N-synth.json"
$PNR -q -l build/$N-pnr.log --json build/$N-synth.json --write build/$N.json \
    --device GW5AT-LV60PG484AC1/I0 --vopt cst=$CST
gowin_pack --cpu_as_gpio -d GW5AT-60B -o build/$N.fs build/$N.json
grep -E 'Max frequency|LUT4|DFF|IOB' build/$N-pnr.log | head -8 || true
ls -la build/$N.fs
