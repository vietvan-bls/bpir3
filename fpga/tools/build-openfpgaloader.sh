#!/bin/sh
# Biên dịch openFPGALoader TĨNH cho BPI-R3 (aarch64, chạy được trên musl của OpenWrt) + công cụ ftdi-uart.
# Chạy trong container Ubuntu 24.04. Kết quả: out/fpga/openFPGALoader, out/fpga/ftdi-uart (đã commit sẵn, chép lên board /mnt/data/fpga).
set -e
cd "$(dirname "$0")"; T=$(pwd); W=${W:-/tmp/ofl-build}; S=$W/sys
apt-get install -y g++-aarch64-linux-gnu cmake autoconf automake libtool pkg-config >/dev/null
mkdir -p $W $S && cd $W
# libftdi1 + zlib tĩnh: lấy .deb arm64 của Ubuntu ports
P=https://ports.ubuntu.com/ubuntu-ports
for f in pool/main/libf/libftdi1/libftdi1-dev_1.5-6build5_arm64.deb pool/main/z/zlib/zlib1g-dev_1.3.dfsg-3.1ubuntu2_arm64.deb; do
  [ -f $(basename $f) ] || curl -sfO $P/$f; dpkg-deb -x $(basename $f) $S; done
L=$S/usr/lib/aarch64-linux-gnu
# libusb tĩnh không udev (bản của Ubuntu cần libudev)
[ -d libusb ] || git clone -q --depth 1 https://github.com/libusb/libusb
(cd libusb && ./autogen.sh >/dev/null 2>&1; ./configure -q --host=aarch64-linux-gnu --disable-udev --enable-static --disable-shared --prefix=/usr >/dev/null && make -s -j4 >/dev/null && make -s install DESTDIR=$W/usbinst >/dev/null)
rm -f $L/libusb*; cp $W/usbinst/usr/lib/libusb-1.0.a $L/; cp -r $W/usbinst/usr/include/libusb-1.0 $S/usr/include/
sed "s#^libdir=.*#libdir=\${prefix}/lib/aarch64-linux-gnu#" $W/usbinst/usr/lib/pkgconfig/libusb-1.0.pc > $L/pkgconfig/libusb-1.0.pc
[ -d openFPGALoader ] || git clone -q --depth 1 https://github.com/trabucayre/openFPGALoader
mkdir -p openFPGALoader/build && cd openFPGALoader/build
PKG_CONFIG_SYSROOT_DIR=$S PKG_CONFIG_LIBDIR=$L/pkgconfig cmake .. -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc -DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++ -DCMAKE_FIND_ROOT_PATH=$S \
  -DBUILD_STATIC=ON -DENABLE_UDEV=OFF -DENABLE_CMSISDAP=OFF -DENABLE_LIBGPIOD=OFF -DCMAKE_EXE_LINKER_FLAGS=-static >/dev/null
PKG_CONFIG_SYSROOT_DIR=$S PKG_CONFIG_LIBDIR=$L/pkgconfig make -s -j4
O=$T/../../out/fpga; mkdir -p $O
aarch64-linux-gnu-strip -o $O/openFPGALoader openFPGALoader
aarch64-linux-gnu-gcc -O2 -static -s -I$S/usr/include/libftdi1 -I$S/usr/include/libusb-1.0 -o $O/ftdi-uart $T/ftdi-uart.c $L/libftdi1.a $L/libusb-1.0.a -lpthread
ls -la $O
