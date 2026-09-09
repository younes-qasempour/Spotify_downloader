# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect package data
datas = [
    ('core', 'core'),
    ('gui', 'gui'),
]

# Collect qfluentwidgets data files (fonts, icons, themes)
try:
    datas += collect_data_files('qfluentwidgets')
except Exception:
    pass

# Include ffmpeg.exe if present
if os.path.isfile('ffmpeg.exe'):
    datas.append(('ffmpeg.exe', '.'))
elif os.path.isfile('bin/ffmpeg.exe'):
    datas.append(('bin/ffmpeg.exe', 'bin'))

# Hidden imports
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'qfluentwidgets',
    'spotipy',
    'yt_dlp',
    'mutagen',
    'mutagen.flac',
    'mutagen.mp3',
    'mutagen.id3',
    'mutagen.mp4',
    'mutagen.oggopus',
    'PIL',
    'bs4',
    'requests',
]
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('mutagen')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='SpotifyDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Set to True for debug console, False for clean Windows GUI
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SpotifyDownloader',
)
