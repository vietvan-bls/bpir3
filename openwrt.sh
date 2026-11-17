#!/bin/bash
# Build OpenWrt image for Banana Pi BPI-R3 using the official ImageBuilder.
# Output: out/openwrt/*bananapi_bpi-r3-sdcard.img.gz (+ sysupgrade.itb, emmc/nand/nor bootloaders)
#
# Usage: ./openwrt.sh
#   env: OWRT_VER  (default 25.12.6)
#        PACKAGES  extra packages, "-pkg" removes one (default: LuCI + a few tools)
#        FILES_DIR directory overlaid onto rootfs (e.g. files/etc/config/network)
# Deps: build-essential libncurses-dev zlib1g-dev gawk git gettext libssl-dev xsltproc rsync wget unzip python3 zstd file
set -e
OWRT_VER=${OWRT_VER:-25.12.6}
PROFILE=bananapi_bpi-r3
PACKAGES=${PACKAGES:-"luci luci-ssl htop nano tcpdump ethtool kmod-usb-storage block-mount"}
W=${W:-$PWD/work}; OUT=$PWD/out/openwrt
IB=openwrt-imagebuilder-$OWRT_VER-mediatek-filogic.Linux-x86_64
URL=https://downloads.openwrt.org/releases/$OWRT_VER/targets/mediatek/filogic

mkdir -p "$W" "$OUT"
if [ ! -d "$W/$IB" ]; then
	wget -q --show-progress -O "$W/$IB.tar.zst" "$URL/$IB.tar.zst"
	tar --zstd -xf "$W/$IB.tar.zst" -C "$W"
	rm "$W/$IB.tar.zst"
fi

make -C "$W/$IB" image PROFILE=$PROFILE PACKAGES="$PACKAGES" \
	${FILES_DIR:+FILES="$(realpath "$FILES_DIR")"} BIN_DIR="$OUT"

ls -la "$OUT" | grep -E 'bpi-r3-(sdcard|squashfs|emmc|snand|nor)'
