import hashlib
import os
import sys
import json
import subprocess
import urllib.request
import urllib.error


def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


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
    tag = 'v1.9.5'
    release_name = 'Flacify v1.9.5 (Final v1.x) — Karaoke & Bilingual Lyrics, 10-Band EQ, Auto-Sync, Spectrum Audit & UI Polish'

    installer_path = os.path.join(os.path.dirname(__file__), '..', 'dist', 'installer', 'Flacify_Setup_v1.9.5.exe')
    installer_path = os.path.abspath(installer_path)
    if not os.path.exists(installer_path):
        raise FileNotFoundError(f"Installer not found at {installer_path}")

    installer_sha256 = compute_sha256(installer_path)
    installer_name = os.path.basename(installer_path)

    release_body = (
        "# 🚀 Flacify v1.9.5 — Final v1.x Release\n\n"
        "> **Final v1.x Milestone:** `v1.9.5` is the **final release of the Flacify v1.x Fluent UI generation** before development shifts to **Flacify v2.0** featuring a brand-new UI rewrite.\n\n"
        "### 🎤 Live Karaoke Lyrics & Bilingual Translation\n"
        "- **Overhauled Spotify Desktop Player & Karaoke Drawer**: Redesigned `MiniPlayerBar` and `KaraokeLyricsDrawer` with synchronized lyric highlighting, click-to-seek timing, and cleaner layout controls.\n"
        "- **Real-Time Bilingual Translation**: Added inline translation to **English** and **Persian (فارسی)** directly inside the Karaoke Drawer and MiniPlayerBar.\n\n"
        "### 🎚️ 10-Band Audio Equalizer\n"
        "- **Interactive 10-Band EQ & Presets**: Shape playback frequency curves with built-in presets, preamp, and bass boost controls.\n"
        "- **Live Preview & Permanent Baking**: Audition EQ settings live in the player or permanently bake them into audio files while preserving all embedded lyrics, cover art, and metadata.\n\n"
        "### 🔄 Scheduled Playlist Auto-Sync (\"Watch Playlist\")\n"
        "- **Pin & Auto-Watch Playlists**: Pin playlists in Saved Playlists to check for newly added tracks on startup or at configurable intervals (`1h`, `3h`, `6h`, `12h`, `24h`, startup-only, or manual).\n"
        "- **Automatic Delta Queueing**: Discovers and queues newly added Spotify tracks automatically.\n\n"
        "### 🔍 Audio Spectrum Inspector & Smart Duplicate Merger\n"
        "- **Fake-Bitrate / Spectral Cutoff Audit**: Inspect tracks for upscaled transcodes with generated spectrogram previews and one-click upgrade options.\n"
        "- **Smart Duplicate & Fingerprint Merger**: Detect and merge duplicate tracks across folders using metadata and acoustic fingerprinting.\n\n"
        "### 🛠️ UI Polish & Codebase Cleanup\n"
        "- **Toolbar & Layout Fixes**: Eliminated overlapping toolbar buttons and text across Library, Saved Playlists, and Settings views.\n"
        "- **Auto-Sync Button Icon Padding Fix**: Preserved `qfluentwidgets` icon padding across Auto-Sync toggle states so the pin icon renders cleanly next to the button label.\n"
        "- **Codebase Pruning**: Removed unused imports, dead code, and redundant build/cache artifacts.\n\n"
        "---\n\n"
        "### 📦 Installation & Verification\n"
        "Download and run **`Flacify_Setup_v1.9.5.exe`** below to install or update Flacify on Windows.\n\n"
        f"- **Installer**: `{installer_name}`\n"
        f"- **SHA-256**: `{installer_sha256}`\n"
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
