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
    tag = 'v1.5'
    release_name = 'Flacify v1.5 — MeloBot Telegram Integration, Classical Search & Concurrency'

    release_body = (
        "# 🚀 Flacify v1.5 Release Notes\n\n"
        "### 🤖 MeloBot Telegram Integration (@melobot)\n"
        "- **High-Speed Lossless FLAC & 320 kbps MP3 Retrieval**: Direct integration with Telegram via `telethon` enables instantaneous streaming and download of genuine Lossless FLAC and Studio 320 kbps MP3 tracks via `@melobot`.\n"
        "- **Intelligent Interactive Keyboard Automation**: Automatically navigates multi-step Telegram bot dialogs—detects candidate songs, evaluates nested album tracklists, filters out promotional buttons, and picks the highest quality tier (FLAC > 320k > 128k).\n"
        "- **Single-Song Concurrency Guard**: Dedicated single-stream serialization (`_telegram_stream_lock`) enforces 1-by-1 downloads for Telegram bot queries, preventing bot flood rate limits (`FloodWaitError`) and chat state collisions.\n"
        "- **Fluent Settings Telegram Login Flow**: Connect your Telegram account directly from the Settings interface via an interactive, secure two-step login modal (phone number -> SMS/App code -> 2FA password) with live connection status.\n\n"
        "### 🎼 Classical & Multi-Part Aria Search Engine\n"
        "- **Automatic Classical Detection**: Accurately recognizes classical and opera compositions across all eras via catalog numbers (`Op`, `WAB`, `BWV`, `Hob`, `K`, `RV`) and terminology (`Symphony`, `Concerto`, `Sonata`, `Scherzo`, `Aria`, `Canzonetta`).\n"
        "- **Clean Movement & Aria Extraction**: Automatically strips 100+ character Spotify titles down to concise movement and aria phrases across colons, hyphens, and ellipses (`...`), preventing search engine query bloat.\n"
        "- **Adaptive Classical Duration Tolerance**: Expands duration tolerance for classical works to `max(45s, 15%)` with gentle penalty slopes, accommodating natural tempo variations between different conductors and orchestras.\n"
        "- **Topic Channel Verification**: Authenticates performer-named Topic channels without false 'Foreign topic channel' cover rejections.\n\n"
        "### ⚡ Concurrency & Pipeline Enhancements\n"
        "- **Dynamic Concurrency Control**: Seamlessly switches between full multi-worker parallelism (up to 10 workers for Musilon/YouTube) and serialized single-song downloads when MeloBot is active.\n"
        "- **Auto-Repair & Accurate Tag Attributions**: Ensures YouTube Music Opus and M4A downloads are accurately recorded in the library archive with proper badges.\n\n"
        "---\n\n"
        "### 📦 Installation & Verification\n"
        "Download and run **`Flacify_Setup_v1.5.exe`** below to install or update Flacify on Windows.\n\n"
        "- **Installer**: `Flacify_Setup_v1.5.exe`\n"
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
    installer_path = os.path.join(os.path.dirname(__file__), '..', 'dist', 'installer', 'Flacify_Setup_v1.5.exe')
    installer_path = os.path.abspath(installer_path)
    if not os.path.exists(installer_path):
        raise FileNotFoundError(f"Installer not found at {installer_path}")

    installer_name = os.path.basename(installer_path)
    if installer_name in existing_assets:
        print(f"Asset '{installer_name}' is already attached to release.")
        return

    file_size = os.path.getsize(installer_path)
    print(f"Uploading '{installer_name}' ({file_size:,} bytes) to GitHub Release...")

    upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={installer_name}"
    with open(installer_path, 'rb') as f:
        file_bytes = f.read()

    upload_req = urllib.request.Request(
        upload_url,
        data=file_bytes,
        headers={
            **headers,
            'Content-Type': 'application/octet-stream',
            'Content-Length': str(len(file_bytes))
        },
        method='POST'
    )

    with urllib.request.urlopen(upload_req) as resp:
        asset_data = json.loads(resp.read().decode())
        print(f"Asset uploaded successfully! ID={asset_data['id']}")
        print(f"Download URL: {asset_data.get('browser_download_url')}")

if __name__ == '__main__':
    main()
