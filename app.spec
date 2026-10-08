# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Static data files to bundle
datas = [
    ('assets', 'assets'),
    ('core', 'core'),
    ('gui', 'gui'),
]

# Include bin directory (contains bundled ffmpeg.exe)
if os.path.isdir('bin'):
    datas.append(('bin', 'bin'))

# Include configuration templates if present
for extra_file in ['config.example.json', 'config.json', 'cookies.txt']:
    if os.path.isfile(extra_file):
        datas.append((extra_file, '.'))

# Collect PyQt-Fluent-Widgets resources (fonts, SVGs, QSS stylesheets)
try:
    datas += collect_data_files('qfluentwidgets')
except Exception as e:
    print(f"Notice: collect_data_files('qfluentwidgets'): {e}")

# Collect certifi SSL certificate bundle for secure HTTPS requests
try:
    datas += collect_data_files('certifi')
except Exception as e:
    print(f"Notice: collect_data_files('certifi'): {e}")

# Hidden imports that dynamic loaders or reflection might omit
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.sip',
    'qfluentwidgets',
    'yt_dlp',
    'mutagen',
    'sqlite3',
    'threading',
    'logging',
    'logging.handlers',
    'requests',
    'urllib3',
    'certifi',
    'bs4',
    'spotipy',
    'spotipy.oauth2',
    'PIL',
    'PIL.Image',
    'PIL.JpegImagePlugin',
    'PIL.PngImagePlugin',
    'PIL.WebPImagePlugin',
]

hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('mutagen')
hiddenimports += collect_submodules('yt_dlp')

# Exclude unnecessary large packages to shrink the bundle footprint by 150MB+
excludes = [
    'PyQt6.QtWebEngine',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtQuick',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtQml',
    'PyQt6.Qt3DCore',
    'PyQt6.Qt3DRender',
    'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic',
    'PyQt6.Qt3DExtras',
    'PyQt6.Qt3DAnimation',
    'PyQt6.QtTest',
    'PyQt6.QtSensors',
    'PyQt6.QtBluetooth',
    'PyQt6.QtNfc',
    'PyQt6.QtPositioning',
    'PyQt6.QtRemoteObjects',
    'scipy',
    'matplotlib',
    'pandas',
    'sklearn',
    'tkinter',
    'unittest',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Flacify',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico' if os.path.isfile('assets/icon.ico') else None,
    version='version_info.txt' if os.path.isfile('version_info.txt') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Flacify',
)
