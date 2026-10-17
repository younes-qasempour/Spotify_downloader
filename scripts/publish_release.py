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
    tag = 'v1.5.1'
    release_name = 'Flacify v1.5.1 — Candidate vs Quality Button Isolation & Audio Duration Guard'

    release_body = (
        "# 🚀 Flacify v1.5.1 Release Notes\n\n"
        "### 🛡️ Candidate Menu vs Quality Button Isolation in MeloBot\n"
        "- **Fixed False Quality Button Triggers**: Keyboards containing candidate icons (`🎵`, `📀`, `🗣`, `👤`, `🎬`, `🎧`) or album tracklists are now strictly evaluated as Candidate Menus via `_score_candidate`, never as Quality Menus.\n"
        "- **Eliminated Loose Substring Matching**: Removed loose substrings (e.g. `'original'`, `'hq'`) that previously caused buttons like *'🎵 Goosebumps Original Studio Cast Recording Company'* to be erroneously clicked as 320k quality buttons instead of evaluating candidates.\n"
        "- **Isolated Quality Selector**: Quality buttons now strictly require dedicated quality identifiers (`کیفیت عالی`, `کیفیت ۳۲۰`, `کیفیت FLAC`, `320 kbps`, `128 kbps`, `flac`) and reject long candidate strings.\n\n"
        "### ⏱️ Delivered Audio Duration Verification\n"
        "- **Automatic Duration Guard**: Every audio file delivered by MeloBot is now validated against `track.duration_sec`. If delivered audio exceeds duration tolerance (e.g. a 5-minute cast recording track for a 2:42 song), it is safely rejected and resolution continues or falls back to YouTube Music.\n\n"
        "---\n\n"
        "### 📦 Installation & Verification\n"
        "Download and run **`Flacify_Setup_v1.5.1.exe`** below to install or update Flacify on Windows.\n\n"
        "- **Installer**: `Flacify_Setup_v1.5.1.exe`\n"
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
    installer_path = os.path.join(os.path.dirname(__file__), '..', 'dist', 'installer', 'Flacify_Setup_v1.5.1.exe')
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
