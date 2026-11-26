"""
Android USB Cable Sync Bridge (`adb reverse`) helpers, device detection,
and optional Google Platform-Tools installation.
"""

import logging
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple
import zipfile

import requests

from core.paths import get_resource_path, get_user_bin_dir

logger = logging.getLogger("backend.usb_sync")

_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MAX_PLATFORM_TOOLS_ZIP_BYTES = 100 * 1024 * 1024
_install_lock = threading.Lock()


def _adb_binary_name() -> str:
    return "adb.exe" if os.name == "nt" else "adb"


def find_adb_executable() -> Optional[str]:
    """Locates `adb` across Flacify user bin, PATH, Android SDK, and bundled resources."""
    exe_name = _adb_binary_name()
    candidates: List[Optional[str]] = [
        str(get_user_bin_dir() / "platform-tools" / exe_name),
        shutil.which("adb"),
    ]

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        candidates.append(
            str(Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / exe_name)
        )

    for env_key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk_root = (os.getenv(env_key) or "").strip()
        if sdk_root:
            candidates.append(str(Path(sdk_root) / "platform-tools" / exe_name))

    candidates.append(str(get_resource_path("bin", "platform-tools", exe_name)))

    for cand in candidates:
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def _validate_serial(serial: Optional[str]) -> Optional[str]:
    if serial is None:
        return None
    cleaned = str(serial).strip()
    if not cleaned:
        return None
    if cleaned.startswith("-") or not _SERIAL_RE.match(cleaned):
        raise ValueError(f"Invalid ADB device serial: {cleaned!r}")
    return cleaned


def _run_adb(adb_path: str, args: List[str], timeout: float = 8.0) -> Tuple[int, str, str]:
    kwargs: Dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    res = subprocess.run([adb_path, *args], **kwargs)
    return res.returncode, res.stdout or "", res.stderr or ""


def parse_adb_devices_output(raw: str) -> List[Dict[str, Any]]:
    """Parses `adb devices -l` stdout into normalized device dictionaries."""
    devices: List[Dict[str, Any]] = []
    for raw_line in (raw or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("list of devices attached"):
            continue
        if line.startswith("* "):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        serial = parts[0]
        state = parts[1]
        kv: Dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                k, v = token.split(":", 1)
                kv[k] = v

        raw_model = kv.get("model") or kv.get("device") or serial
        model = raw_model.replace("_", " ").strip() or serial

        devices.append(
            {
                "serial": serial,
                "state": state,
                "model": model,
                "product": kv.get("product", ""),
                "device": kv.get("device", ""),
                "transport_id": kv.get("transport_id", ""),
                "is_emulator": serial.startswith("emulator-"),
                "reverse_active": False,
            }
        )
    return devices


def parse_reverse_list_output(raw: str, port: int) -> bool:
    """Returns True when `adb reverse --list` includes `tcp:<port> tcp:<port>`."""
    target_port = int(port)
    pattern = re.compile(rf"(?:^|\s)tcp:{target_port}\s+tcp:{target_port}(?:\s|$)")
    return any(pattern.search(line) for line in (raw or "").splitlines())


def get_usb_sync_status(port: int) -> Dict[str, Any]:
    """Queries ADB availability, attached Android devices, and active USB reverse tunnels."""
    target_port = int(port)
    adb_path = find_adb_executable()
    status: Dict[str, Any] = {
        "adb_available": bool(adb_path),
        "adb_path": adb_path or "",
        "port": target_port,
        "usb_url": f"http://127.0.0.1:{target_port}",
        "devices": [],
        "ready_count": 0,
        "unauthorized_count": 0,
        "active_count": 0,
        "reverse_active": False,
        "error": "",
    }
    if not adb_path:
        return status

    try:
        rc, stdout, stderr = _run_adb(adb_path, ["devices", "-l"], timeout=8.0)
    except Exception as exc:
        status["error"] = f"Could not run adb: {exc}"
        return status

    if rc != 0:
        status["error"] = (stderr or stdout or f"adb exited with code {rc}").strip()
        return status

    devices = parse_adb_devices_output(stdout)
    ready_count = 0
    unauthorized_count = 0
    active_count = 0

    for dev in devices:
        state = dev["state"]
        if state == "device":
            ready_count += 1
            try:
                rev_rc, rev_out, _ = _run_adb(
                    adb_path, ["-s", dev["serial"], "reverse", "--list"], timeout=5.0
                )
                is_rev = rev_rc == 0 and parse_reverse_list_output(rev_out, target_port)
            except Exception:
                is_rev = False
            dev["reverse_active"] = is_rev
            if is_rev:
                active_count += 1
        elif state == "unauthorized":
            unauthorized_count += 1

    status["devices"] = devices
    status["ready_count"] = ready_count
    status["unauthorized_count"] = unauthorized_count
    status["active_count"] = active_count
    status["reverse_active"] = active_count > 0
    return status


def _apply_reverse_action(
    port: int, serial: Optional[str], *, enable: bool
) -> Dict[str, Any]:
    target_port = int(port)
    validated_serial = _validate_serial(serial)
    adb_path = find_adb_executable()
    if not adb_path:
        raise FileNotFoundError(
            "Android Debug Bridge (adb) is not installed on this PC."
        )

    pre_status = get_usb_sync_status(target_port)
    if pre_status["error"] and not pre_status["devices"]:
        return {
            **pre_status,
            "success": False,
            ("enabled_serials" if enable else "disabled_serials"): [],
            "errors": [pre_status["error"]],
        }

    errors: List[str] = []
    targets: List[str] = []
    devices_by_serial = {d["serial"]: d for d in pre_status["devices"]}

    if validated_serial:
        matched = devices_by_serial.get(validated_serial)
        if matched and matched["state"] != "device":
            if matched["state"] == "unauthorized":
                errors.append(
                    f"Device {validated_serial} is unauthorized — unlock your phone and tap Allow on the USB debugging prompt."
                )
            else:
                errors.append(
                    f"Device {validated_serial} is in state '{matched['state']}' and cannot be bridged."
                )
        else:
            targets.append(validated_serial)
    else:
        targets = [d["serial"] for d in pre_status["devices"] if d["state"] == "device"]
        if not targets:
            if pre_status["unauthorized_count"] > 0:
                errors.append(
                    "Phone detected but unauthorized — unlock your phone and tap Allow on the USB debugging prompt."
                )
            else:
                errors.append(
                    "No ready USB Android phone detected. Plug in a USB cable with USB Debugging enabled."
                )

    acted_serials: List[str] = []
    adb_args = (
        ["reverse", f"tcp:{target_port}", f"tcp:{target_port}"]
        if enable
        else ["reverse", "--remove", f"tcp:{target_port}"]
    )

    for target in targets:
        try:
            rc, out, err = _run_adb(adb_path, ["-s", target, *adb_args], timeout=8.0)
            if rc == 0:
                acted_serials.append(target)
            else:
                detail = (err or out or f"adb returned exit code {rc}").strip()
                errors.append(f"{target}: {detail}")
        except Exception as exc:
            errors.append(f"{target}: {exc}")

    updated = get_usb_sync_status(target_port)
    key = "enabled_serials" if enable else "disabled_serials"
    return {
        **updated,
        "success": len(acted_serials) > 0 and not errors,
        key: acted_serials,
        "errors": errors,
    }


def enable_usb_reverse(port: int, serial: Optional[str] = None) -> Dict[str, Any]:
    """Activates `adb reverse tcp:<port> tcp:<port>` for connected Android devices."""
    return _apply_reverse_action(port, serial, enable=True)


def disable_usb_reverse(port: int, serial: Optional[str] = None) -> Dict[str, Any]:
    """Removes `adb reverse` forwarding for `tcp:<port>` on connected Android devices."""
    return _apply_reverse_action(port, serial, enable=False)


def _platform_tools_zip_url() -> str:
    if os.name == "nt":
        suffix = "windows"
    elif sys.platform == "darwin":
        suffix = "darwin"
    else:
        suffix = "linux"
    return f"https://dl.google.com/android/repository/platform-tools-latest-{suffix}.zip"


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    resolved_dest = dest_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            norm_name = member.filename.replace("\\", "/")
            if not norm_name or norm_name.startswith("/") or ":" in norm_name.split("/")[0]:
                raise ValueError(f"Unsafe zip entry path: {member.filename!r}")
            target = (resolved_dest / norm_name).resolve()
            if target != resolved_dest and not str(target).startswith(
                str(resolved_dest) + os.sep
            ):
                raise ValueError(f"Zip traversal detected: {member.filename!r}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def install_platform_tools() -> Dict[str, Any]:
    """Downloads and installs official Google Android Platform-Tools into `%LOCALAPPDATA%\\Flacify\\bin\\platform-tools`."""
    with _install_lock:
        user_bin = get_user_bin_dir()
        target_dir = user_bin / "platform-tools"
        url = _platform_tools_zip_url()

        staging_dir = Path(tempfile.mkdtemp(prefix="flacify_adb_", dir=str(user_bin)))
        zip_path = staging_dir / "platform-tools.zip"
        extract_dir = staging_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            resp = requests.get(url, stream=True, timeout=(15, 120))
            resp.raise_for_status()
            total = 0
            with open(zip_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_PLATFORM_TOOLS_ZIP_BYTES:
                        raise RuntimeError(
                            "Downloaded Platform-Tools archive exceeded 100 MB safety limit."
                        )
                    fh.write(chunk)

            _safe_extract_zip(zip_path, extract_dir)
            extracted_tools = extract_dir / "platform-tools"
            if not extracted_tools.is_dir():
                raise RuntimeError("Platform-Tools zip did not contain expected folder.")

            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=False)
            shutil.move(str(extracted_tools), str(target_dir))

            adb_exe = target_dir / _adb_binary_name()
            if not adb_exe.is_file():
                raise RuntimeError("adb executable missing after Platform-Tools extraction.")

            if os.name != "nt":
                adb_exe.chmod(adb_exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            return {
                "success": True,
                "adb_path": str(adb_exe),
                "message": "Android Platform Tools (adb) installed successfully.",
            }
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
