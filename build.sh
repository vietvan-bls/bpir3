#!/bin/bash
# Build U-Boot + TF-A (BL2/FIP) for Banana Pi BPI-R3 (MT7986), SD card boot.
# Deps (Ubuntu): gcc-aarch64-linux-gnu flex bison device-tree-compiler swig libgnutls28-dev uuid-dev libssl-dev bc
set -e
DEV=${DEV:-sd}          # sd | emmc
UBOOT_TAG=${UBOOT_TAG:-v2025.10}
W=${W:-$PWD/work}; OUT=$PWD/out
export CROSS_COMPILE=aarch64-linux-gnu-
mkdir -p "$W" "$OUT"
[ -d "$W/u-boot" ] || git clone --depth 1 -b "$UBOOT_TAG" https://github.com/u-boot/u-boot.git "$W/u-boot"
[ -d "$W/atf" ] || git clone --depth 1 -b mtksoc https://github.com/mtk-openwrt/arm-trusted-firmware.git "$W/atf"
make -C "$W/u-boot" mt7986a_bpir3_${DEV}_defconfig
make -C "$W/u-boot" -j"$(nproc)"
case $DEV in sd) BD=sdmmc;; emmc) BD=emmc;; esac
make -C "$W/atf" -j"$(nproc)" PLAT=mt7986 BOOT_DEVICE=$BD DRAM_USE_DDR4=1 \
  USE_MKIMAGE=1 MKIMAGE="$W/u-boot/tools/mkimage" BL33="$W/u-boot/u-boot.bin" all fip
cp "$W/atf/build/mt7986/release/bl2.img" "$W/atf/build/mt7986/release/fip.bin" "$W/u-boot/u-boot.bin" "$OUT/"
ls -la "$OUT"
