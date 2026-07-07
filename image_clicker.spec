# -*- mode: python ; coding: utf-8 -*-

import os

# version_info.txt ถูกสร้างโดย scripts/gen_version_info.py ก่อนรัน pyinstaller
# (ดู .github/workflows/build-windows.yml) ถ้ายังไม่ได้รัน ให้ build ต่อได้โดยไม่มี
# metadata แทนที่จะ fail ทั้งหมด
_version_file = 'version_info.txt' if os.path.exists('version_info.txt') else None

a = Analysis(
    ['image_clicker.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# --onedir: แตกไฟล์ครั้งเดียวตอน build ไม่ต้อง extract ใหม่ทุกครั้งที่เปิด
# (onefile เดิมทำให้เปิดช้าบน Windows เพราะต้องแตกไฟล์ทั้งหมดไปที่ temp ทุกครั้ง)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='image_clicker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
    version=_version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='image_clicker',
)
