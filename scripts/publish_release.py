import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request


def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_github_token() -> str:
    p = subprocess.Popen(
        ["git", "credential", "fill"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, _ = p.communicate("protocol=https\nhost=github.com\n\n")
    creds = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    token = creds.get("password")
    if not token:
        raise ValueError("No GitHub token found in git credential manager")
    return token


def _refresh_assets(repo: str, release_id: int, headers: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/{release_id}",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return {a["name"]: a["id"] for a in data.get("assets", [])}


class _ProgressFile:
    """File-like wrapper that logs upload progress so large assets never appear stalled."""

    def __init__(self, path: str, total_bytes: int, label: str) -> None:
        self._fh = open(path, "rb")
        self._total = total_bytes
        self._label = label
        self._sent = 0
        self._last_log = time.monotonic()

    def __len__(self) -> int:
        return self._total

    def read(self, size: int = -1) -> bytes:
        chunk = self._fh.read(size if size and size > 0 else 262144)
        if chunk:
            self._sent += len(chunk)
            now = time.monotonic()
            if now - self._last_log >= 5.0 or self._sent >= self._total:
                pct = (self._sent * 100.0 / self._total) if self._total else 100.0
                print(
                    f"  [{self._label}] {self._sent / (1024 * 1024):.1f} / "
                    f"{self._total / (1024 * 1024):.1f} MB ({pct:.0f}%)",
                    flush=True,
                )
                self._last_log = now
        return chunk

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "_ProgressFile":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def upload_asset(
    repo: str,
    release_id: int,
    asset_path: str,
    existing_assets: dict,
    headers: dict,
    token: str,
) -> dict:
    import requests

    asset_name = os.path.basename(asset_path)
    file_size = os.path.getsize(asset_path)
    print(f"Uploading '{asset_name}' ({file_size:,} bytes) to GitHub Release...", flush=True)

    upload_url = (
        f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
        f"?name={asset_name}"
    )
    upload_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "FlacifyReleaseAgent",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(file_size),
    }

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            current_assets = (
                existing_assets if attempt == 1 else _refresh_assets(repo, release_id, headers)
            )
            if asset_name in current_assets:
                old_asset_id = current_assets[asset_name]
                print(
                    f"Deleting previous/incomplete asset '{asset_name}' (ID={old_asset_id})...",
                    flush=True,
                )
                del_req = urllib.request.Request(
                    f"https://api.github.com/repos/{repo}/releases/assets/{old_asset_id}",
                    headers=headers,
                    method="DELETE",
                )
                urllib.request.urlopen(del_req, timeout=30)

            print(f"Uploading '{asset_name}' attempt {attempt}/{max_retries}...", flush=True)
            curl_bin = shutil.which("curl.exe") or shutil.which("curl")
            if curl_bin:
                safe_path = asset_path.replace("\\", "/").replace('"', '\\"')
                curl_cfg = "\n".join([
                    f'url = "{upload_url}"',
                    'request = "POST"',
                    f'header = "Authorization: Bearer {token}"',
                    'header = "Accept: application/vnd.github+json"',
                    'header = "User-Agent: FlacifyReleaseAgent"',
                    'header = "X-GitHub-Api-Version: 2022-11-28"',
                    'header = "Content-Type: application/octet-stream"',
                    f'header = "Content-Length: {file_size}"',
                    f'data-binary = "@{safe_path}"',
                    "connect-timeout = 30",
                    "max-time = 900",
                    "speed-limit = 2048",
                    "speed-time = 60",
                    "keepalive-time = 20",
                    "show-error",
                    'write-out = "\\n%{http_code}"',
                ])
                proc = subprocess.run(
                    [curl_bin, "-sS", "-K", "-"],
                    input=curl_cfg,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                lines = proc.stdout.strip().splitlines()
                http_code = int(lines[-1]) if lines and lines[-1].isdigit() else 0
                body_text = "\n".join(lines[:-1]) if lines and lines[-1].isdigit() else proc.stdout
                if proc.returncode == 0 and http_code in (200, 201):
                    asset_data = json.loads(body_text)
                    print(
                        f"Asset '{asset_name}' uploaded successfully! "
                        f"ID={asset_data['id']} URL={asset_data.get('browser_download_url')}",
                        flush=True,
                    )
                    return asset_data
                err_detail = proc.stderr.strip() or body_text
                raise RuntimeError(
                    f"curl upload failed for '{asset_name}' (rc={proc.returncode}, HTTP {http_code}): {err_detail}"
                )

            with _ProgressFile(asset_path, file_size, asset_name) as pf:
                resp = requests.post(
                    upload_url,
                    data=pf,
                    headers=upload_headers,
                    timeout=(30, 300),
                )
            if resp.status_code in (200, 201):
                asset_data = resp.json()
                print(
                    f"Asset '{asset_name}' uploaded successfully! "
                    f"ID={asset_data['id']} URL={asset_data.get('browser_download_url')}",
                    flush=True,
                )
                return asset_data
            raise RuntimeError(
                f"Upload failed for '{asset_name}' with HTTP {resp.status_code}: {resp.text}"
            )
        except Exception as exc:
            print(f"Upload error on attempt {attempt} for '{asset_name}': {exc}", flush=True)
            if attempt < max_retries:
                time.sleep(3)
            else:
                raise


def main() -> None:
    repo = "younes-qasempour/Spotify_downloader"
    tag = "v2.2.0"
    release_name = (
        "Flacify v2.2.0 — High-Speed USB Cable Sync, Upgraded Library Sidebar "
        "& Desktop Polish"
    )

    installer_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "dist", "installer")
    )
    windows_installer = os.path.join(installer_dir, "Flacify_Setup_v2.2.0.exe")
    android_apk = os.path.join(installer_dir, "Flacify_Android_v2.2.0.apk")

    for path in (windows_installer, android_apk):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Release asset not found: {path}")

    win_name = os.path.basename(windows_installer)
    win_size = os.path.getsize(windows_installer)
    win_sha256 = compute_sha256(windows_installer)

    apk_name = os.path.basename(android_apk)
    apk_size = os.path.getsize(android_apk)
    apk_sha256 = compute_sha256(android_apk)

    release_body = (
        "# Flacify v2.2.0 — High-Speed USB Cable Sync, Library Sidebar & Desktop Polish\n\n"
        "Flacify **v2.2.0** adds **plug-and-play USB Cable Sync (`adb reverse`)** with automatic Wi-Fi fallback, "
        "alongside major Windows Desktop Studio polish for the Library sidebar, Mini Player, and clean app shutdown.\n\n"
        "### ⚡ What's New in v2.2.0\n"
        "- **High-Speed USB Cable Sync (`adb reverse` + Auto Wi-Fi Fallback):**\n"
        "  - **PC USB Bridge (`Settings → Mobile Sync`):** Automatically detects connected Android phones every 4s, offers a one-click **Install ADB (Platform-Tools)** button if missing, and opens `adb reverse tcp:8765 tcp:8765` over USB (loopback-secured).\n"
        "  - **Android USB-First Auto-Switch:** Automatically tries `http://127.0.0.1:8765` first when plugged in (without overwriting your saved Wi-Fi PC IP) and falls back seamlessly to Wi-Fi/Tailscale if unplugged — even syncing over USB with phone Wi-Fi turned off.\n"
        "  - **3× Faster Transfers & Live Speed Telemetry:** Upgrades Android file streaming buffers to `256 KB`, enables **3 concurrent track downloads** over USB, and displays live **`MB/s` transfer speeds** and active transport (`USB Cable · High Speed` vs `Wi-Fi / LAN`) in both the Sync screen and foreground notification.\n"
        "- **Upgraded \"Your Library\" Left Sidebar & Cold-Start Fix:** Removes the 7-item playlist cap and unifies Saved Playlists, Offline Playlists, and Offline Albums with filter pills, search, sorting (`Recent`, `A–Z`, `Most Tracks`), hover Quick-Play, collapsed cover strip, storage footer, and reliable cold-start query/WS hydration.\n"
        "- **Studio Mini Player Polish:** Fixes top/bottom control clipping on resize, locks lyrics scrolling strictly inside the drawer container, and returns to the Full Studio window instead of exiting the app when closed.\n"
        "- **Close Confirmation Modal & Complete Process Cleanup:** Closing Flacify prompts with `Cancel`, `Hide to Tray`, or `Close Everything`, cleanly terminating the entire `flacify-backend.exe` process tree on exit.\n\n"
        "### 📱 Included from v2.0.0 – v2.1.0\n"
        "- **One-Scan QR & mDNS Pairing + Resumable FLAC Sync:** Offline Android Room + WorkManager sync with `ETag` / HTTP `Range`, offline Media3 player + synced lyrics, and Android Share Sheet (`Send to Flacify PC`).\n"
        "- **Tauri v2 Desktop Studio + Web PWA:** Frameless Windows 11 window, real-time WebSocket queue, 10-band EQ, Audio Spectrum Inspector, M3U8/Device Exporter, and single-folder deduplication.\n\n"
        "---\n\n"
        "### 📦 Downloads & Verification\n\n"
        "| Platform | Artifact | Size | SHA-256 |\n"
        "|---|---|---|---|\n"
        f"| **Windows 10/11 (x64)** | `{win_name}` | `{win_size:,}` bytes ({win_size / (1024 * 1024):.2f} MB) | `{win_sha256}` |\n"
        f"| **Android (API 26+)** | `{apk_name}` | `{apk_size:,}` bytes ({apk_size / (1024 * 1024):.2f} MB) | `{apk_sha256}` |\n\n"
        "> **Upgrading on Windows?** Close any running Flacify window or backend process before running `Flacify_Setup_v2.2.0.exe`. All settings and your SQLite library in `%LOCALAPPDATA%\\Flacify` are preserved.\n"
    )

    token = get_github_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "FlacifyReleaseAgent",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1. Check if release already exists
    check_req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        headers=headers,
    )
    release_data = None
    try:
        with urllib.request.urlopen(check_req) as resp:
            release_data = json.loads(resp.read().decode())
            print(f"Found existing release: ID={release_data['id']}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print("Release does not exist yet. Creating release...")
        else:
            raise

    # 2. Create or update release metadata
    if not release_data:
        payload = json.dumps(
            {
                "tag_name": tag,
                "target_commitish": "main",
                "name": release_name,
                "body": release_body,
                "draft": False,
                "prerelease": False,
            }
        ).encode("utf-8")
        create_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases",
            data=payload,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(create_req) as resp:
            release_data = json.loads(resp.read().decode())
            print(f"Release created successfully! ID={release_data['id']}")
    else:
        patch_payload = json.dumps(
            {
                "name": release_name,
                "body": release_body,
                "draft": False,
                "prerelease": False,
            }
        ).encode("utf-8")
        patch_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/{release_data['id']}",
            data=patch_payload,
            headers={**headers, "Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(patch_req) as resp:
            release_data = json.loads(resp.read().decode())
            print(f"Updated existing release metadata: ID={release_data['id']}")

    release_id = release_data["id"]
    existing_assets = {a["name"]: a["id"] for a in release_data.get("assets", [])}

    # 3. Upload both Android Companion APK and Windows Installer
    for asset_path in (android_apk, windows_installer):
        upload_asset(repo, release_id, asset_path, existing_assets, headers, token)

    print(f"Release URL: {release_data.get('html_url')}")


if __name__ == "__main__":
    main()
