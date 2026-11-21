# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [
    ("assets", "assets"),
]

if os.path.isdir("bin"):
    datas.append(("bin", "bin"))

if os.path.isfile("config.example.json"):
    datas.append(("config.example.json", "."))

if os.path.isdir(os.path.join("frontend", "dist")):
    datas.append((os.path.join("frontend", "dist"), os.path.join("frontend", "dist")))

try:
    datas += collect_data_files("certifi")
except Exception as exc:
    print(f"Notice: collect_data_files('certifi'): {exc}")

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "websockets",
    "fastapi",
    "starlette",
    "pydantic",
    "anyio",
    "yt_dlp",
    "mutagen",
    "sqlite3",
    "requests",
    "urllib3",
    "certifi",
    "bs4",
    "spotipy",
    "spotipy.oauth2",
    "PIL",
    "PIL.Image",
    "PIL.JpegImagePlugin",
    "PIL.PngImagePlugin",
    "PIL.WebPImagePlugin",
    "qrcode",
    "qrcode.image.svg",
    "zeroconf",
    "ifaddr",
]

for pkg in (
    "backend",
    "core",
    "mutagen",
    "yt_dlp",
    "telethon",
    "uvicorn",
    "websockets",
    "qrcode",
    "zeroconf",
    "ifaddr",
):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

excludes = [
    "PyQt6",
    "PySide6",
    "qfluentwidgets",
    "scipy",
    "matplotlib",
    "pandas",
    "sklearn",
    "tkinter",
    "unittest",
]

a = Analysis(
    ["backend/entry.py"],
    pathex=["."],
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
    name="flacify-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if os.path.isfile("assets/icon.ico") else None,
    version="version_info.txt" if os.path.isfile("version_info.txt") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="flacify-backend",
)
