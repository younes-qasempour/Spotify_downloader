import os
import sys
import json
import subprocess
import urllib.request
import urllib.error

def get_github_token() -> str:
    p = subprocess.Popen(
        ['git', 'credential', 'fill'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    out, _ = p.communicate('protocol=https\nhost=github.com\n\n')
    creds = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    token = creds.get('password')
    if not token:
        raise ValueError('No GitHub token found in git credential manager')
    return token

def main():
    repo = 'younes-qasempour/Spotify_downloader'
    tag = 'v1.5.2'
    release_name = 'Flacify v1.5.2 — FastTelethon 10x Acceleration, MTProto Push Engine & Audio Hardening'

    release_body = (
        "# 🚀 Flacify v1.5.2 Release Notes\n\n"
        "### ⚡ 10x Faster MeloBot Downloads & Smart Title Matching\n"
        "- **Accelerated Telegram Transfers**: Upgraded download pipeline with optimized MTProto routines and native crypto acceleration (`cryptg`), speeding up candidate search and audio downloads by up to 10x.\n"
        "- **Smart Title Normalization**: Enhanced Persian/English candidate scoring with multi-word artist and title matching, ensuring top-ranked candidates are accurately chosen on the first pass.\n\n"
        "### 🛡️ FloodWait Elimination & MTProto Push Event Navigation\n"
        "- **Push-Event Message Pipeline**: Replaced high-frequency polling with native Telethon push updates (`events.NewMessage` and `events.MessageEdited`), completely eliminating Telegram `FloodWaitError` bans.\n"
        "- **Deduplicated Button Clicks & Adaptive Retries**: Prevents duplicate keyboard clicks with message ID tracking and retries unacknowledged clicks up to 3 times at 5s intervals within an adaptive 45s delivery window.\n"
        "- **Zombie Coroutine Termination**: Safely cancels background asyncio futures on timeouts or exceptions, preventing leaked background coroutines from colliding with subsequent downloads.\n\n"
        "### 🎼 Quality Priority & True Bitrate Attribution\n"
        "- **Strict 128k Fallback Rejection**: Strictly rejects 128 kbps audio when High (320k) or Lossless (FLAC) quality is requested, safely stepping down to YouTube Music Opus.\n"
        "- **Dynamic Physical Bitrate Calculation**: Accurately computes on-disk audio bitrates from file size and duration before assigning badges, preventing false 320k labeling.\n"
        "- **Emerald FLAC Badge Styling**: Added dedicated vibrant emerald badges for genuine `MeloBot FLAC` lossless downloads.\n\n"
        "### 🔧 Engine Hardening & Thread Safety\n"
        "- **WebM to Opus Remux Synchronization**: Fixes file path desynchronization in `CascadingAudioEngine` when remuxing YouTube WebM containers to Opus via FFmpeg.\n"
        "- **Genre Cache Thread Locking**: Added `threading.RLock` to `GenreResolver`, eliminating Windows `PermissionError` [WinError 32] during multi-worker concurrent downloads.\n"
        "- **Safe Qt Signal Bridge**: Wrapped all background worker thread signal emissions with `safe_emit` and `safe_invoke` to prevent `RuntimeError: wrapped C/C++ object has been deleted` crashes.\n"
        "- **Clean Partial File Purge**: Incomplete `.part` files are automatically removed upon connection drops or timeouts.\n\n"
        "---\n\n"
        "### 📦 Installation & Verification\n"
        "Download and run **`Flacify_Setup_v1.5.2.exe`** below to install or update Flacify on Windows.\n\n"
        "- **Installer**: `Flacify_Setup_v1.5.2.exe`\n"
    )

    token = get_github_token()
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'FlacifyReleaseAgent',
        'X-GitHub-Api-Version': '2022-11-28'
    }

    # 1. Check if release already exists
    check_req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/tags/{tag}', headers=headers)
    release_data = None
    try:
        with urllib.request.urlopen(check_req) as resp:
            release_data = json.loads(resp.read().decode())
            print(f"Found existing release: ID={release_data['id']}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("Release does not exist yet. Creating release...")
        else:
            raise

    # 2. Create release if not present
    if not release_data:
        payload = json.dumps({
            'tag_name': tag,
            'target_commitish': 'main',
            'name': release_name,
            'body': release_body,
            'draft': False,
            'prerelease': False
        }).encode('utf-8')
        create_req = urllib.request.Request(
            f'https://api.github.com/repos/{repo}/releases',
            data=payload,
            headers={**headers, 'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(create_req) as resp:
            release_data = json.loads(resp.read().decode())
            print(f"Release created successfully! ID={release_data['id']}")

    release_id = release_data['id']
    existing_assets = {a['name']: a['id'] for a in release_data.get('assets', [])}

    # 3. Upload asset
    installer_path = os.path.join(os.path.dirname(__file__), '..', 'dist', 'installer', 'Flacify_Setup_v1.5.2.exe')
    installer_path = os.path.abspath(installer_path)
    if not os.path.exists(installer_path):
        raise FileNotFoundError(f"Installer not found at {installer_path}")

    installer_name = os.path.basename(installer_path)
    if installer_name in existing_assets:
        old_asset_id = existing_assets[installer_name]
        print(f"Deleting previous asset '{installer_name}' (ID={old_asset_id}) to re-upload freshly compiled build...")
        del_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/assets/{old_asset_id}",
            headers=headers,
            method='DELETE'
        )
        urllib.request.urlopen(del_req)
        print("Previous asset deleted.")

    file_size = os.path.getsize(installer_path)
    print(f"Uploading '{installer_name}' ({file_size:,} bytes) to GitHub Release...")

    upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={installer_name}"
    import requests
    import time

    upload_headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'FlacifyReleaseAgent',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/octet-stream',
        'Content-Length': str(file_size)
    }

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Uploading attempt {attempt}/{max_retries}...")
            with open(installer_path, 'rb') as f:
                resp = requests.post(
                    upload_url,
                    data=f,
                    headers=upload_headers,
                    timeout=(30, 300)
                )
            if resp.status_code in (200, 201):
                asset_data = resp.json()
                print(f"Asset uploaded successfully! ID={asset_data['id']}")
                print(f"Download URL: {asset_data.get('browser_download_url')}")
                return
            elif resp.status_code == 422:
                print("Asset may already exist or validation failed:", resp.text)
                return
            else:
                print(f"Upload failed with status {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Upload error on attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                raise

if __name__ == '__main__':
    main()
