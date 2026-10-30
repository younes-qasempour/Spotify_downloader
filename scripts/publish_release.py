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
    tag = 'v1.6.2'
    release_name = 'Flacify v1.6.2 — EBU R128 Volume Boost & Balancing, Japanese/Take Resolution & Bug Fixes'

    release_body = (
        "# 🚀 Flacify v1.6.2 Release Notes\n\n"
        "### 🔊 High-Fidelity EBU R128 Volume Boost & Loudness Balancing\n"
        "- **Automatic & Batch Loudness Normalization (`-9.0 LUFS`)**: Quiet or unevenly mastered tracks are now automatically boosted and balanced to a uniform, punchy `-9.0 LUFS` target using EBU R128 integrated loudness measurement.\n"
        "- **Zero-Distortion Lookahead Brickwall Limiter**: Uses a 5ms lookahead peak limiter (`alimiter=limit=0.95`) at `-0.4 dBFS` so quiet songs gain +4 dB to +9 dB of clean loudness without digital clipping or inter-sample distortion.\n"
        "- **100% Metadata, 640x640 Cover Art & Lyrics Preservation**: Snapshots and restores all ID3v2.3/Vorbis/MP4 tags, embedded cover art, synchronized `.lrc` lyrics, and genres during normalization, while stamping `REPLAYGAIN_TRACK_GAIN` and `FLACIFY_NORMALIZED` tags.\n"
        "- **One-Click Library & Track Volume Controls**: Added **Boost & Balance All Songs Volume** in *Settings -> Library Maintenance*, an **Auto-Boost & Balance Audio Volume (EBU R128)** toggle in *Settings -> Tagging*, and a right-click **Boost & Balance Track Volume** context menu option in the *Completed Library*.\n"
        "- **Persistent Player Volume**: Upgraded the built-in player default volume to `100%` and persisted volume slider changes across sessions.\n\n"
        "### 🎯 Japanese Katakana, Full-Width Unicode & Studio Take Resolution Fixes\n"
        "- **Cross-Script Katakana & Full-Width Normalization**: Added full-width ASCII (`\uFF01-\uFF5E`, `＊`, `（`, `）`, `〜`) normalization and a cross-script Katakana/Romaji `phonetic_skeleton` matcher in both `MeloBotEngine` and `YtdlpEngine` (resolving tracks like `ORANGE RANGE - ＊〜アスタリスク〜（アルバムバージョン）` against `*Asterisk` / `＊～アスタリスク～`).\n"
        "- **Japanese Quotation Bracket Preservation**: Fixed a regex bug in `YtdlpEngine._score_candidate` where Japanese title brackets (`「...」`, `『...』`) were inadvertently stripped as parenthetical noise.\n"
        "- **Studio Take & Version Disambiguation**: Stripped non-searchable version suffixes (`(アルバムバージョン)`, `(Album Version)`, `(Single Version)`, `- Take 1`, `- Prise 1`) from search queries while expanding duration tolerance (`36s`) for multi-take archival recordings (resolving tracks like `Jacques Brel - Jaurès - Take 1`).\n"
        "- **MeloBot Quality Button Loop Fix**: Fixed an infinite re-click loop in `MeloBotEngine._async_query_melobot` where a duration mismatch on an audio delivery did not clear `last_clicked_msg`, eliminating 45-second timeouts.\n\n"
        "### 🛠️ Stability & Codebase Bug Fixes\n"
        "- **Windows UTF-8 Subprocess Decoding**: Fixed `UnicodeDecodeError` crashes in background FFmpeg reader threads (`core/transcoder.py` and `core/utils.py`) when processing files with Japanese, Persian, or French metadata on Windows (`cp1252`).\n"
        "- **Missing ReplayGain Batch Method**: Implemented `ArchiveManager.retag_all_library_replaygain` in `core/archive.py` and fixed a duplicate button reference in `SettingsView`.\n"
        "- **SQLite Resource Leak Fix**: Ensured all `sqlite3.Connection` handles in `ArchiveManager.resolve_collection_cover` are deterministically closed via `contextlib.closing`.\n\n"
        "---\n\n"
        "### 📦 Installation & Verification\n"
        "Download and run **`Flacify_Setup_v1.6.2.exe`** below to install or update Flacify on Windows.\n\n"
        "- **Installer**: `Flacify_Setup_v1.6.2.exe`\n"
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
    installer_path = os.path.join(os.path.dirname(__file__), '..', 'dist', 'installer', 'Flacify_Setup_v1.6.2.exe')
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
