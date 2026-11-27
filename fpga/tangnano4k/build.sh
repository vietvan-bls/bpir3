#!/bin/sh
# Build bitstream Tang Nano 4K bằng toolchain mã nguồn mở (Yosys + nextpnr-himbaechel + Apicula).
# Cài: pip install yowasp-yosys yowasp-nextpnr-himbaechel-gowin apycula
# Dùng: ./build.sh hello.v [file.cst]   → build/hello.fs
set -e
cd "$(dirname "$0")"
SRC=${1:-hello.v}; CST=${2:-tangnano4k.cst}; N=$(basename "$SRC" .v)
YOSYS=$(command -v yosys || echo yowasp-yosys)
PNR=$(command -v nextpnr-himbaechel || echo yowasp-nextpnr-himbaechel-gowin)
mkdir -p build
$YOSYS -q -l build/$N-yosys.log -p "read_verilog $SRC; synth_gowin -top top -json build/$N-synth.json"
$PNR -q -l build/$N-pnr.log --json build/$N-synth.json --write build/$N.json \
    --device GW1NSR-LV4CQN48PC7/I6 --vopt family=GW1NS-4 --vopt cst=$CST
gowin_pack -c -d GW1NS-4 --mspi_as_gpio -o build/$N.fs build/$N.json
grep -E 'Max frequency|LUT4|DFF|IOB' build/$N-pnr.log | head -8 || true
ls -la build/$N.fs
