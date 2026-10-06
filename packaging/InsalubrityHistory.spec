# -*- mode: python ; coding: utf-8 -*-
# Запуск из КОРНЯ проекта (делает scripts/build.bat):
#   pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/InsalubrityHistory.spec
import os

SRC = os.path.abspath(os.path.join(SPECPATH, '..', 'src'))
ICON = os.path.join(SPECPATH, 'logo.ico')

a = Analysis(
    [os.path.join(SRC, 'insalubrity_history.py')],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pkg_resources программе не нужен, а его runtime-хук PyInstaller 6.9 падает при старте
    # (No module named 'jaraco') с новыми версиями setuptools.
    excludes=['pkg_resources'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='InsalubrityHistory',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='InsalubrityHistory',
)
