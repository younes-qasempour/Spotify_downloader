# Flacify — High-Fidelity Audio Scraper & Desktop Suite

<p align="center">
  <img src="assets/icon.png" alt="Flacify Logo" width="128" height="128"><br>
  <img src="https://img.shields.io/badge/Release-v1.0.0-blue?style=flat-square" alt="Version 1.0.0">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white&style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/GUI-PyQt6%20Fluent%20Design-0078D4?logo=windows11&logoColor=white&style=flat-square" alt="Windows 11 Fluent">
  <img src="https://img.shields.io/badge/Audio-Lossless%20FLAC%2016%2F24-emerald?logo=flac&style=flat-square" alt="Lossless FLAC">
  <img src="https://img.shields.io/badge/Safety%20Net-YouTube%20Music%20Opus-red?logo=youtubemusic&logoColor=white&style=flat-square" alt="YouTube Music">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
</p>

A production-grade, visually stunning Windows 11 desktop application and headless CLI suite designed to download Spotify tracks, albums, and massive playlists (1,000+ tracks) at studio-master fidelity without crashes, rate-limit bans, or UI freezing.

Built on a clean **two-layer decoupled architecture** separating a **Headless Core Multimedia Engine** (`core/`) from a **Windows 11 Fluent Design Interface** (`gui/`).

---

## 🌟 Key Features

### 🎧 High-Fidelity Cascading Audio Engine
Every queued track traverses an intelligent cascading resolution ladder to ensure the highest possible acoustic fidelity:
1. **Tier 1 (Target):** Musilon Lossless FLAC 16-bit (CD Quality, 44.1 kHz / 16-bit PCM).
2. **Tier 2 (Hi-Res):** Musilon Studio Master FLAC 24-bit (48–96 kHz / 24-bit).
3. **Tier 3 (Studio MP3):** Musilon Pristine MP3 320 kbps (Constant Bitrate).
4. **Tier 4 (Safety Net):** YouTube Music native high-bitrate Opus stream via `yt-dlp` with strict track duration tolerance ($\pm 5$s). **Activates strictly when Musilon catalog has no matching candidate.**

### 🔍 4-Tier Discovery Engine
Musilon's catalog is probed across four concurrent search vectors with smart scoring to ensure 100% accurate resolution:
- **Vector 1 (Live REST API):** Queries `/wp-json/play/search?search={query}` used by the web player for real-time JSON responses.
- **Vector 2 (WordPress Station API):** Queries native `/wp-json/wp/v2/station?search={query}&per_page=30`.
- **Vector 3 (Artist Taxonomy Discography):** Resolves artist taxonomy `/wp-json/wp/v2/artist?search={name}` and scans their complete catalog archive.
- **Vector 4 (HTML Fallback):** Resilient HTML scraping via `/search/{query}/` and `/?s={query}`.
- **Anti-False-Positive Heuristics:** Hard foreign artist rejection (`-999.0` penalty), remix/acoustic penalties (`-70.0`), and strict title similarity scoring prevent mismatched downloads.

### 🖼️ Artwork & Tagging Perfection
- **Unique Album Art**: Fetches individual 640×640 front cover artwork directly from Spotify's CDN per track (no shared or generic cover art).
- **Embedded Tags**: Complete Vorbis comments (FLAC/Opus), ID3v2.4 (MP3), and MP4 metadata (M4A) via `mutagen`.
- **Synchronized Lyrics**: Automated companion `.lrc` files or embedded lyrics fetched from LRCLIB with Windows CRLF (`\r\n`) timestamps for full compatibility with desktop music players.
- **Watermark Scrubbing**: Automatically strips promotional site tags and watermarks (e.g. `[Musilon]`, `- Musilon`) from filenames and audio metadata.

### 📁 Smart Folder Organization
Downloads are automatically organized into dedicated subdirectories within your chosen download directory based on the Spotify entity:
- **Playlists:** Saved into a folder named after the playlist (e.g. `Music/Chill Moody Mix/`).
- **Albums:** Saved into a separate folder named after the album (e.g. `Music/Random Access Memories/`).
- **Singles:** Standalone tracks are neatly placed into a dedicated `Music/Singles/` folder.

### ⚡ Windows 11 Fluent Design GUI
- Built with `PyQt6` and `PyQt6-Fluent-Widgets`.
- **Virtualized Card Delegate**: Renders hundreds of tracks smoothly with zero Windows GDI handle exhaustion.
- **Queue Management**: Start, Pause, Resume, Retry Failed, and Clear controls with live metric counters (Total, Downloading, Completed, Failed).
- **Offline Completed Library**: Interactive library view with Songs, Albums, and Playlists navigation, search filter, thumbnail covers, double-click playback, and Explorer reveal.
- **Settings View & Auto-Repair**: Visual status badges, one-click FFmpeg auto-downloader, directory chooser, VIP credential testing, and a Deep Scan Auto-Repair tool to heal missing lyrics or cover art.
- **Clipboard Auto-Detect**: Instantly recognizes copied Spotify URLs upon focusing the app or via `Ctrl+V`.

---

## 🏗️ Architecture

```
Flacify/
├── app.spec                  # PyInstaller configuration for standalone release
├── build_windows.py          # Automated pipeline orchestrator (PyInstaller + Inno Setup)
├── installer.iss             # Inno Setup 6 per-user Windows installer configuration
├── version_info.txt          # Embedded Windows PE version resource metadata
├── config.example.json       # Clean template for configuration settings
├── requirements.txt          # Python dependencies
├── main.py                   # Unified entrypoint (GUI default or --headless CLI)
│
├── assets/                   # APPLICATION BRANDING & ICONS
│   ├── icon.ico              # Multi-resolution icon (16x16 up to 256x256)
│   ├── icon.png              # High-res 256x256 application logo
│   └── convert_icon.py       # Reusable icon generation utility
│
├── core/                     # HEADLESS MULTIMEDIA ENGINE (Zero GUI Dependencies)
│   ├── paths.py              # Centralized path manager (%LOCALAPPDATA%\Flacify)
│   ├── config.py             # Thread-safe persistent JSON config manager
│   ├── archive.py            # SQLite music library archive, deduplication & auto-repair
│   ├── spotify_client.py     # Spotify Web API client + guest scraper fallback
│   ├── musilon.py            # Musilon VIP engine (ArvanCloud solver, 4-tier search, CDN downloader)
│   ├── ytdlp_engine.py       # YouTube Music fallback engine (yt-dlp wrapper)
│   ├── lyrics.py             # LRCLIB lyrics client (synchronized .lrc + plain lyrics)
│   ├── tagger.py             # Mutagen metadata tagger & cover art embedder
│   ├── resolver.py           # Cascading ladder engine (Musilon -> YTM safety net)
│   ├── queue_manager.py      # Producer-consumer thread queue with callback hooks
│   └── utils.py              # Filename sanitizer, FFmpeg detector/downloader
│
└── gui/                      # WINDOWS 11 FLUENT PRESENTATION LAYER
    ├── styles.py             # Dark theme palette and styling tokens
    ├── bridge.py             # Qt Signal Bridge between background threads & event loop
    ├── queue_model.py        # Virtualized TrackQueueModel (QAbstractTableModel)
    ├── queue_delegate.py     # TrackCardDelegate (74px high custom card painter)
    ├── main_window.py        # FluentWindow with navigation sidebar
    └── views/
        ├── queue_view.py     # Queue management, URL inputs, metric cards, context menu
        ├── completed_view.py # Completed downloads library with direct file launcher
        └── settings_view.py  # VIP credentials, fallback toggle, directory picker, auto-repair
```

---

## 💾 Installation

### Option 1: Standalone Windows Installer (Recommended)
Download the latest installer from [Releases](https://github.com/younes-qasempour/Spotify_downloader/releases):
- Download **`Flacify_Setup_v1.0.0.exe`**.
- Run the setup wizard (installs per-user without requiring administrator privileges).
- Launch **Flacify** directly from your Start Menu or Desktop shortcut.

### Option 2: Running from Source

#### Prerequisites
- **Python 3.10+** (tested on Python 3.11 – 3.14 on Windows 11)
- **Node.js** (required for solving dynamic JavaScript challenges on Musilon)
- **FFmpeg** (bundled in binary releases; auto-installable via the Settings tab in source mode)

#### Setup Steps
1. **Clone the repository:**
   ```bash
   git clone https://github.com/younes-qasempour/Spotify_downloader.git
   cd Spotify_downloader
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch Flacify:**
   ```bash
   python main.py
   ```

---

## 💻 Usage

### 1. Desktop GUI
```bash
python main.py
```
- Paste any Spotify track, album, or playlist URL into the top search bar (or use `Ctrl+V`).
- Click **Analyze & Enqueue**.
- Click **Start All** to begin high-speed parallel downloads.

### 2. Headless CLI Mode
For automated environments, servers, or terminal workflows:
```bash
# Download a single track
python main.py --headless "https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg"

# Download an entire playlist to a specific directory
python main.py --headless "https://open.spotify.com/playlist/37i9dQZF1EIguyCzHJlUGq" --output "D:/Music"
```

---

## 📦 Building Standalone Installer

To compile the production standalone executable and Inno Setup installer:
```bash
python build_windows.py
```
This automatically:
1. Verifies/generates `assets/icon.ico`.
2. Runs PyInstaller with `app.spec` in `onedir` windowed mode.
3. Invokes Inno Setup 6 (`ISCC.exe`) to produce `dist/installer/Flacify_Setup_v1.0.0.exe`.

---

## 🔧 YouTube Fallback & Cookie Setup Guide

The application uses an intelligent multi-tier discovery pipeline:
- **Tiers 1–3 (Musilon VIP):** High-speed direct CDN access providing MP3 320 kbps, 16-bit FLAC, and 24-bit Hi-Res audio.
- **Tier 4 (YouTube Music Fallback):** Automatically triggers when a track is not present on Musilon (e.g. Japanese City Pop, regional releases, indie tracks, video game OSTs, or obscure b-sides).

### Exporting `cookies.txt` for YouTube
YouTube enforces anti-bot verification against automated downloaders. Providing your browser cookies allows seamless downloads:
1. Install a browser extension:
   - **Chrome / Edge / Brave:** [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbngbenkjcffliehddfacccg)
   - **Firefox:** [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
2. Log into [youtube.com](https://youtube.com) in your browser.
3. Export `cookies.txt`.
4. Place the file in `%LOCALAPPDATA%\Flacify\cookies.txt` or select it in the app's **Settings** tab.

---

## 🛡️ Security & Privacy
- **Zero Leaked Secrets**: User credentials, session tokens, and local databases are stored exclusively in `%LOCALAPPDATA%\Flacify` and are never committed to git.
- **Git Shield**: `.gitignore` strictly protects `config.json`, cookies, local music files, databases (`archive.db`), and third-party binaries.

---

## 📄 License
This project is open-source software licensed under the [MIT License](LICENSE).
