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
    tag = 'v1.4.1'
    release_name = 'Flacify v1.4.1 — Manual Playlist Renaming & Metadata Editing'

    release_body = (
        "# 🚀 Flacify v1.4.1 Release Notes\n\n"
        "### ✏️ Manual Playlist Renaming & Metadata Editing\n"
        "- **Playlist Title & Metadata Editor**: Added an intuitive, modern Fluent dialog allowing users to manually rename any saved playlist, update its Spotify source URL, and customize its artwork.\n"
        "- **Cover Artwork Customizer**: Users can now select custom local images (.jpg, .png, .webp) via file picker or specify remote URLs with instant real-time artwork previewing.\n"
        "- **Track Metadata Editing**: Right-click any track within a playlist detail view to edit its title, artist, or album directly, synchronizing changes with both the playlist and the offline archive.\n"
        "- **Completed Library Synchronization**: Renaming playlists automatically updates associated collection records, disk storage folder names, and cached artwork across both the Playlists tab and Completed Library.\n"
        "- **Action Buttons & Context Menus**: Added dedicated Edit buttons (`FluentIcon.EDIT`) and rich right-click context menus across playlist cards and banners for rapid management.\n\n"
        "---\n\n"
        "### 📦 Installation & Verification\n"
        "Download and run **`Flacify_Setup_v1.4.1.exe`** below to install or update Flacify on Windows.\n\n"
        "- **Installer**: `Flacify_Setup_v1.4.1.exe`\n"
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
    installer_path = os.path.join(os.path.dirname(__file__), '..', 'dist', 'installer', 'Flacify_Setup_v1.4.1.exe')
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
