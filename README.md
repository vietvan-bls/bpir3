# bpir3

Build U-Boot + TF-A cho **Banana Pi BPI-R3 (MediaTek MT7986 / Filogic 830)** và tạo image thẻ SD.

## 1. Cài công cụ (Ubuntu/Debian)

```bash
sudo apt-get install -y gcc-aarch64-linux-gnu make git flex bison bc device-tree-compiler swig libssl-dev libgnutls28-dev uuid-dev gdisk dosfstools mtools e2fsprogs
```

## 2. Build bootloader

```bash
./build.sh
```

- Mặc định build cho boot từ **SD**. Build cho eMMC: `DEV=emmc ./build.sh`
- Đổi version U-Boot: `UBOOT_TAG=v2025.10 ./build.sh`
- Source được clone vào `work/`, kết quả nằm trong `out/`:

| File | Mô tả |
|---|---|
| `out/bl2.img` | TF-A BL2 (định dạng BootROM MediaTek, khởi tạo DDR4) |
| `out/fip.bin` | FIP = BL31 (TF-A) + BL33 (U-Boot) |
| `out/u-boot.bin` | U-Boot gốc (đã nằm trong fip.bin) |

Lệnh tương đương build tay:

```bash
export CROSS_COMPILE=aarch64-linux-gnu-
git clone --depth 1 -b v2025.10 https://github.com/u-boot/u-boot.git
git clone --depth 1 -b mtksoc https://github.com/mtk-openwrt/arm-trusted-firmware.git atf
make -C u-boot mt7986a_bpir3_sd_defconfig
make -C u-boot -j$(nproc)
make -C atf -j$(nproc) PLAT=mt7986 BOOT_DEVICE=sdmmc DRAM_USE_DDR4=1 USE_MKIMAGE=1 MKIMAGE=$PWD/u-boot/tools/mkimage BL33=$PWD/u-boot/u-boot.bin all fip
```

## 3. Tạo image thẻ SD

```bash
./mksdimg.sh bpir3-sdcard.img
```

Tuỳ chọn (biến môi trường):

- `SIZE_MB=2048` – kích thước image (mặc định 1024)
- `BOOT_MB=256` – kích thước phân vùng boot FAT32
- `BOOT_DIR=path/` – copy nội dung vào phân vùng boot (kernel `Image`, `*.dtb`, `extlinux/extlinux.conf`)
- `ROOTFS_DIR=path/` – copy rootfs vào phân vùng ext4

Layout GPT (sector 512 byte), giống image OpenWrt/frank-w:

| # | Tên | Sector | Offset | Nội dung |
|---|---|---|---|---|
| 1 | bl2 | 34 – 8191 | 17 KiB | `bl2.img` (BootROM đọc tại đây) |
| 2 | u-boot-env | 8192 – 9215 | 4 MiB | biến môi trường U-Boot |
| 3 | factory | 9216 – 13311 | 4.5 MiB | dữ liệu calib WiFi |
| 4 | fip | 13312 – 17407 | 6.5 MiB | `fip.bin` (BL2 tìm theo tên phân vùng `fip`) |
| 5 | boot | 18432 – … | 9 MiB | FAT32 |
| 6 | rootfs | còn lại | | ext4 |

## 4. Ghi ra thẻ SD

**Cẩn thận chọn đúng thiết bị** (`lsblk` để xem), lệnh dưới xoá toàn bộ thẻ:

```bash
sudo dd if=bpir3-sdcard.img of=/dev/sdX bs=4M conv=fsync status=progress
```

Hoặc chỉ ghi bootloader lên thẻ đã có bảng GPT như trên:

```bash
sudo dd if=out/bl2.img of=/dev/sdX bs=512 seek=34 conv=notrunc,fsync
```

```bash
sudo dd if=out/fip.bin of=/dev/sdX bs=512 seek=13312 conv=notrunc,fsync
```

## 5. Boot

1. Gạt switch boot (SW1) sang chế độ **SD** (theo bảng boot-select trên wiki BPI-R3).
2. Cắm UART debug (115200 8N1, 3.3V) để xem log BL2 → BL31 → U-Boot.
3. U-Boot dùng bootstd/distro boot: đặt `extlinux/extlinux.conf` + kernel + dtb (`mt7986a-bananapi-bpi-r3.dtb`) vào phân vùng boot để tự boot Linux.

## 6. Build OpenWrt

Dùng ImageBuilder chính thức (ghép package có sẵn, mất vài phút, không cần build từ source):

```bash
sudo apt-get install -y build-essential libncurses-dev zlib1g-dev gawk gettext libssl-dev xsltproc rsync wget unzip python3 zstd file
```

```bash
./openwrt.sh
```

- Đổi phiên bản: `OWRT_VER=25.12.6 ./openwrt.sh`
- Thêm/bớt package (`-pkg` để bỏ): `PACKAGES="luci luci-ssl wireguard-tools -ppp" ./openwrt.sh`
- Đưa sẵn cấu hình vào rootfs: `FILES_DIR=files ./openwrt.sh` (ví dụ `files/etc/config/network`)

Kết quả trong `out/openwrt/` (không commit, file lớn):

| File | Dùng cho |
|---|---|
| `*-bpi-r3-sdcard.img.gz` | ghi thẳng ra thẻ SD |
| `*-bpi-r3-squashfs-sysupgrade.itb` | nâng cấp từ OpenWrt đang chạy (`sysupgrade`) |
| `*-bpi-r3-{emmc,snand,nor}-preloader.bin` / `*-bl31-uboot.fip` | bootloader để cài lên eMMC/NAND/NOR |

Ghi thẻ SD:

```bash
gunzip -c out/openwrt/openwrt-*-bananapi_bpi-r3-sdcard.img.gz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
```

Gạt switch boot sang SD, cắm mạng vào cổng LAN, truy cập `http://192.168.1.1` (LuCI, user `root`, chưa có mật khẩu).
Từ image SD, U-Boot của OpenWrt có menu để cài OpenWrt sang NAND/eMMC.
