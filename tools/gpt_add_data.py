#!/usr/bin/env python3
"""Thêm phân vùng "data" vào phần trống cuối thẻ SD của BPI-R3, KHÔNG đụng MBR (hybrid) và các phân vùng cũ.

Image sdcard của OpenWrt có GPT tạo cho đĩa ~512 MB, MBR là hybrid. sgdisk/sfdisk hoặc từ chối,
hoặc ghi đè MBR, nên script này tự sửa GPT:
  - thêm entry mới (Linux filesystem) từ START_LBA tới hết thẻ
  - cập nhật last_usable_lba / alternate_lba của header chính
  - ghi bảng dự phòng (backup GPT) ở cuối thẻ đúng chuẩn

Dùng:  python3 gpt_add_data.py /dev/mmcblk0          (chạy thử, chỉ in ra)
       python3 gpt_add_data.py /dev/mmcblk0 --write  (ghi thật)
"""
import binascii
import os
import struct
import sys

SECTOR = 512
START_LBA = 1048576  # 512 MiB, ngay sau phân vùng production
NAME = "data"
# GUID "Linux filesystem" 0FC63DAF-8483-4772-8E79-3D69D8477DE4 ở dạng byte GPT (mixed-endian).
# (python3-light trên OpenWrt không có module uuid.)
LINUX_FS_LE = bytes.fromhex("AF3DC60F838472478E793D69D8477DE4")


def random_guid_le():
    b = bytearray(os.urandom(16))
    b[7] = (b[7] & 0x0F) | 0x40  # version 4 (trường time_hi_and_version, little-endian)
    b[8] = (b[8] & 0x3F) | 0x80  # variant RFC 4122
    return bytes(b)


def crc(b):
    return binascii.crc32(b) & 0xFFFFFFFF


def main():
    dev = sys.argv[1]
    write = "--write" in sys.argv
    fd = os.open(dev, os.O_RDWR if write else os.O_RDONLY)
    disk_sectors = os.lseek(fd, 0, os.SEEK_END) // SECTOR

    os.lseek(fd, SECTOR, os.SEEK_SET)
    hdr = bytearray(os.read(fd, SECTOR))
    if hdr[:8] != b"EFI PART":
        sys.exit("Không thấy GPT header ở sector 1")
    hsize, = struct.unpack_from("<I", hdr, 12)
    cur_lba, alt_lba, first_use, last_use = struct.unpack_from("<QQQQ", hdr, 24)
    ent_lba, n_ent, ent_size, ent_crc = struct.unpack_from("<QIII", hdr, 72)

    os.lseek(fd, ent_lba * SECTOR, os.SEEK_SET)
    ents = bytearray(os.read(fd, n_ent * ent_size))
    if crc(bytes(ents)) != ent_crc:
        sys.exit("CRC bảng phân vùng chính sai, dừng lại")

    print(f"Thẻ: {disk_sectors} sector ({disk_sectors * SECTOR / 2**30:.1f} GiB)")
    print(f"Header: alt_lba={alt_lba} last_usable={last_use} entries={n_ent}x{ent_size}")
    used_max, free_slot = 0, None
    for i in range(n_ent):
        e = ents[i * ent_size:(i + 1) * ent_size]
        if e[:16] == b"\0" * 16:
            if free_slot is None:
                free_slot = i
            continue
        f, l = struct.unpack_from("<QQ", e, 32)
        name = e[56:128].decode("utf-16le").rstrip("\0")
        print(f"  p{i + 1}: {name:12s} {f}-{l}")
        if name == NAME:
            sys.exit(f"Đã có phân vùng '{NAME}' (p{i + 1}), không làm gì")
        used_max = max(used_max, l)

    if used_max >= START_LBA:
        sys.exit(f"Phân vùng cũ dùng tới {used_max}, chồng lên {START_LBA}")
    tbl_sectors = (n_ent * ent_size + SECTOR - 1) // SECTOR
    new_alt = disk_sectors - 1
    new_last_use = disk_sectors - 1 - tbl_sectors - 1
    end_lba = new_last_use
    print(f"Thêm p{free_slot + 1} '{NAME}': {START_LBA}-{end_lba} "
          f"({(end_lba - START_LBA + 1) * SECTOR / 2**30:.1f} GiB)")

    e = bytearray(ent_size)
    e[0:16] = LINUX_FS_LE
    e[16:32] = random_guid_le()
    struct.pack_into("<QQQ", e, 32, START_LBA, end_lba, 0)
    e[56:56 + 2 * len(NAME)] = NAME.encode("utf-16le")
    ents[free_slot * ent_size:(free_slot + 1) * ent_size] = e
    new_ent_crc = crc(bytes(ents))

    def make_header(my_lba, other_lba, table_lba):
        h = bytearray(hdr)
        struct.pack_into("<QQQQ", h, 24, my_lba, other_lba, first_use, new_last_use)
        struct.pack_into("<QIII", h, 72, table_lba, n_ent, ent_size, new_ent_crc)
        struct.pack_into("<I", h, 16, 0)
        struct.pack_into("<I", h, 16, crc(bytes(h[:hsize])))
        return bytes(h)

    primary = make_header(1, new_alt, ent_lba)
    backup_tbl_lba = new_alt - tbl_sectors
    backup = make_header(new_alt, 1, backup_tbl_lba)

    if not write:
        print("Chạy thử: chưa ghi gì. Thêm --write để ghi.")
        return
    # Ghi bảng dự phòng trước, header chính sau cùng (nếu mất điện giữa chừng, header chính vẫn là bản cũ).
    os.lseek(fd, backup_tbl_lba * SECTOR, os.SEEK_SET); os.write(fd, bytes(ents))
    os.lseek(fd, new_alt * SECTOR, os.SEEK_SET); os.write(fd, backup)
    os.lseek(fd, ent_lba * SECTOR, os.SEEK_SET); os.write(fd, bytes(ents))
    os.lseek(fd, 1 * SECTOR, os.SEEK_SET); os.write(fd, primary)
    os.fsync(fd)
    os.close(fd)
    print("Đã ghi GPT.")


if __name__ == "__main__":
    main()
