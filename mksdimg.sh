#!/bin/bash
# Create a bootable SD card image for Banana Pi BPI-R3 (MT7986).
# Layout (512-byte sectors), same as OpenWrt / frank-w BPI-R3 images:
#   LBA 0-33          protective MBR + GPT
#   p1 bl2        34 - 8191      (17K  .. 4M)    -> bl2.img (BootROM reads it here)
#   p2 u-boot-env 8192 - 9215    (4M   .. 4.5M)
#   p3 factory    9216 - 13311   (4.5M .. 6.5M)  (WiFi calibration data)
#   p4 fip        13312 - 17407  (6.5M .. 8.5M)  -> fip.bin (BL31 + U-Boot)
#   p5 boot       9M .. +BOOT_MB                 FAT32 (kernel, dtb, extlinux)
#   p6 rootfs     rest                           ext4
#
# Usage: ./mksdimg.sh [output.img]
#   env: SIZE_MB (default 1024), BOOT_MB (default 256), OUT_DIR (default ./out)
#        BOOT_DIR  = directory copied into the boot partition (optional)
#        ROOTFS_DIR= directory copied into the rootfs partition (optional)
# Deps: gdisk dosfstools mtools e2fsprogs
set -e
IMG=${1:-bpir3-sdcard.img}
OUT_DIR=${OUT_DIR:-./out}
SIZE_MB=${SIZE_MB:-1024}
BOOT_MB=${BOOT_MB:-256}

for f in bl2.img fip.bin; do
	[ -f "$OUT_DIR/$f" ] || { echo "missing $OUT_DIR/$f (run ./build.sh first)"; exit 1; }
done

BOOT_START=18432                          # 9 MiB
BOOT_END=$((BOOT_START + BOOT_MB * 2048 - 1))
ROOT_START=$((BOOT_END + 1))

rm -f "$IMG"
truncate -s "${SIZE_MB}M" "$IMG"

sgdisk -o "$IMG" >/dev/null
sgdisk -a 1 -n 1:34:8191        -t 1:8300 -c 1:bl2        -A 1:set:2 "$IMG" >/dev/null
sgdisk -a 1 -n 2:8192:9215      -t 2:8300 -c 2:u-boot-env "$IMG" >/dev/null
sgdisk -a 1 -n 3:9216:13311     -t 3:8300 -c 3:factory    "$IMG" >/dev/null
sgdisk -a 1 -n 4:13312:17407    -t 4:8300 -c 4:fip        "$IMG" >/dev/null
sgdisk -a 1 -n 5:$BOOT_START:$BOOT_END -t 5:0700 -c 5:boot -A 5:set:2 "$IMG" >/dev/null
sgdisk -a 2048 -n 6:$ROOT_START:0 -t 6:8300 -c 6:rootfs   "$IMG" >/dev/null

# bootloaders
dd if="$OUT_DIR/bl2.img" of="$IMG" bs=512 seek=34    conv=notrunc status=none
dd if="$OUT_DIR/fip.bin" of="$IMG" bs=512 seek=13312 conv=notrunc status=none

# filesystems: build separately, then place at partition offsets (no loop device needed)
ROOT_END=$(sgdisk -i 6 "$IMG" | awk '/Last sector/{print $3}')
ROOT_SECTORS=$((ROOT_END - ROOT_START + 1))
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkfs.vfat -F 32 -n BOOT -C "$TMP/boot.fat" $((BOOT_MB * 1024)) >/dev/null
if [ -n "$BOOT_DIR" ]; then mcopy -s -i "$TMP/boot.fat" "$BOOT_DIR"/* ::/; fi
dd if="$TMP/boot.fat" of="$IMG" bs=512 seek=$BOOT_START conv=notrunc status=none

mkfs.ext4 -q -L rootfs ${ROOTFS_DIR:+-d "$ROOTFS_DIR"} "$TMP/root.ext4" $((ROOT_SECTORS / 2))K
dd if="$TMP/root.ext4" of="$IMG" bs=512 seek=$ROOT_START conv=notrunc status=none

sgdisk -p "$IMG"
echo "Done: $IMG"
