# -*- mode: python ; coding: utf-8 -*-
# Запускатель для компьютеров кадровиков (окно обновления + запуск программы).
# Запуск из КОРНЯ проекта (делает scripts/build.bat):
#   pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/Launcher.spec
import os

LAUNCHER = os.path.abspath(os.path.join(SPECPATH, '..', 'launcher'))
ICON = os.path.join(SPECPATH, 'logo.ico')

a = Analysis(
    [os.path.join(LAUNCHER, 'launcher.py')],
    pathex=[LAUNCHER],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Запускателю нужен только tkinter; всё остальное не тянем, чтобы exe был небольшим.
    excludes=['pkg_resources', 'PyQt5', 'pandas', 'numpy', 'openpyxl', 'matplotlib', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='InsalubrityHistoryLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
