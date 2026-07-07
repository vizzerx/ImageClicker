# -*- coding: utf-8 -*-
"""
สร้าง version_info.txt สำหรับฝัง metadata ลง image_clicker.exe (PyInstaller)
รันก่อน `pyinstaller image_clicker.spec` เสมอ (ดู .github/workflows/build-windows.yml)

ที่มาของเลขเวอร์ชัน (เรียงตามลำดับความสำคัญ):
  1. argv[1] ถ้าระบุมา (เช่น "v1.5" จาก GITHUB_REF_NAME ตอน build บน CI)
  2. `git describe --tags` (สำหรับ build บนเครื่องตัวเองแบบไม่มี CI)
  3. "0.0.0-dev" (fallback สุดท้าย กันสคริปต์ fail ถ้าไม่มี git tag เลย)
"""
import os
import re
import sys
import subprocess

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "version_info.txt")

FILE_DESCRIPTION = "Automate click your things"
PRODUCT_NAME = "Image Clicker"
LEGAL_COPYRIGHT = "Image Clicker"


def resolve_version_string():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    try:
        out = subprocess.run(["git", "describe", "--tags"], capture_output=True,
                             text=True, check=True).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    return "0.0.0-dev"


def parse_version_tuple(version_str):
    """แปลง 'v1.5.2' หรือ '1.5' เป็น (1,5,2,0) เติม 0 ให้ครบ 4 ตัวเสมอ
    ตัวเลขที่แปลงไม่ได้ (เช่น '-dev', commit hash ต่อท้ายจาก git describe) จะถูกตัดทิ้ง"""
    version_str = version_str.lstrip("vV")
    nums = re.findall(r"\d+", version_str)[:4]
    nums = [int(n) for n in nums] + [0] * (4 - len(nums))
    return tuple(nums[:4])


def main():
    version_str = resolve_version_string()
    vtuple = parse_version_tuple(version_str)
    display = ".".join(str(n) for n in vtuple)

    content = f'''# UTF-8
#
# ไฟล์นี้สร้างอัตโนมัติโดย scripts/gen_version_info.py — ไม่ต้องแก้เอง
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vtuple!r},
    prodvers={vtuple!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'FileDescription', u'{FILE_DESCRIPTION}'),
        StringStruct(u'FileVersion', u'{display}'),
        StringStruct(u'InternalName', u'image_clicker'),
        StringStruct(u'LegalCopyright', u'{LEGAL_COPYRIGHT}'),
        StringStruct(u'OriginalFilename', u'image_clicker.exe'),
        StringStruct(u'ProductName', u'{PRODUCT_NAME}'),
        StringStruct(u'ProductVersion', u'{display}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
'''
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"เขียน {OUT_PATH} แล้ว (เวอร์ชัน: {version_str} -> {display})")


if __name__ == "__main__":
    main()
