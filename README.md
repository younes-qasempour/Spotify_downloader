# Spotify Downloader — High-Fidelity Desktop Suite

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/GUI-PyQt6%20Fluent%20Design-0078D4?logo=windows11&logoColor=white" alt="Windows 11 Fluent">
  <img src="https://img.shields.io/badge/Audio-Lossless%20FLAC%2016%2F24-emerald?logo=flac" alt="Lossless FLAC">
  <img src="https://img.shields.io/badge/Safety%20Net-YouTube%20Music%20Opus-red?logo=youtubemusic&logoColor=white" alt="YouTube Music">
  <img src="https://img.shields.io/badge/Tagging-Mutagen%20%2B%20LRCLIB-orange" alt="Tagging">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
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

### 🔍 4-Tier Musilon Discovery Engine
Musilon's catalog is probed across four concurrent search vectors with smart scoring to ensure 100% accurate resolution:
- **Vector 1 (Live REST API):** Queries `/wp-json/play/search?search={query}` used by the Musilon web player for real-time JSON responses.
- **Vector 2 (WordPress Station API):** Queries native `/wp-json/wp/v2/station?search={query}&per_page=30`.
- **Vector 3 (Artist Taxonomy Discography):** Resolves artist taxonomy `/wp-json/wp/v2/artist?search={name}` and scans their complete catalog archive.
- **Vector 4 (HTML Fallback):** Resilient HTML scraping via `/search/{query}/` and `/?s={query}`.
- **Anti-False-Positive Heuristics:** Hard foreign artist rejection (`-999.0` penalty), remix/acoustic penalties (`-70.0`), and strict title similarity scoring prevent mismatched downloads.

### 🖼️ Artwork & Tagging Perfection
- **Unique Album Art**: Fetches individual 640×640 front cover artwork directly from Spotify's CDN per track (no shared or generic cover art).
- **Embedded Tags**: Complete Vorbis comments (FLAC/Opus), ID3v2.4 (MP3), and MP4 metadata (M4A) via `mutagen`.
- **Synchronized Lyrics**: Automated companion `.lrc` files fetched from LRCLIB and embedded directly into audio container tags.
- **Watermark Scrubbing**: Automatically strips promotional site tags and watermarks (e.g. `[Musilon]`, `- Musilon`) from filenames and audio metadata.

### ⚡ Windows 11 Fluent Design GUI
- Built with `PyQt6` and `PyQt6-Fluent-Widgets`.
- **Virtualized Card Delegate**: Renders hundreds of tracks smoothly with zero Windows GDI handle exhaustion.
- **Queue Management**: Start, Pause, Resume, and Clear controls with live metric counters (Total, Downloading, Completed, Failed).
- **Settings View**: Visual status indicators, one-click FFmpeg downloader, directory chooser, and VIP credential testing.
- **Clipboard Auto-Detect**: Instantly recognizes copied Spotify URLs upon focusing the app or via `Ctrl+V`.

---

## 🏗️ Architecture

```
Spotify-Downloader/
├── config.example.json       # Clean template for configuration settings
├── requirements.txt          # Python dependencies
├── build_windows.spec        # PyInstaller specification for standalone binary
├── main.py                   # Unified entrypoint (GUI default or --headless CLI)
│
├── core/                     # HEADLESS MULTIMEDIA ENGINE (Zero GUI Dependencies)
│   ├── config.py             # Thread-safe persistent JSON config manager
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
        └── settings_view.py  # VIP credentials, fallback toggle, directory picker
```

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.10+** (tested on Python 3.11 – 3.14 on Windows 11)
- **Node.js** (required for executing ArvanCloud JS challenges on Musilon)
- **FFmpeg** (optional for lossless FLAC; recommended for Opus/M4A transcoding. Can be auto-installed via the app Settings tab)

### Installation

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

4. **Prepare configuration:**
   Copy `config.example.json` to `config.json`:
   ```bash
   copy config.example.json config.json
   ```

---

## 💻 Usage

### 1. Launch Desktop GUI (Default)
```bash
python main.py
```
- Paste any Spotify track, album, or playlist URL into the top search bar (or use `Ctrl+V`).
- Click **Analyze & Enqueue**.
- Click **Start All** to begin high-speed parallel downloads.

### 2. Run Headless CLI Mode
For automated environments, servers, or terminal workflows:
```bash
# Download a single track
python main.py --headless "https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg"

# Download an entire playlist to a specific directory
python main.py --headless "https://open.spotify.com/playlist/37i9dQZF1EIguyCzHJlUGq" --output "D:/Music"
```

---

## ⚙️ Configuration (`config.json`)

All runtime settings are stored in `config.json` (excluded from git tracking):

| Key | Type | Description | Default |
|---|---|---|---|
| `musilon.session_cookie` | String | VIP session cookies for Musilon high-speed CDN access | `""` |
| `musilon.username` | String | Musilon account email or username | `""` |
| `musilon.password` | String | Musilon account password | `""` |
| `musilon.enabled` | Boolean | Enable or disable Musilon Tier 1–3 downloads | `true` |
| `spotify.client_id` | String | Official Spotify Developer Client ID (optional) | `""` |
| `spotify.client_secret`| String | Official Spotify Developer Client Secret (optional) | `""` |
| `download.output_dir` | String | Local directory where audio files and `.lrc` are saved | `downloads` |
| `download.naming_template` | String | File naming pattern (`{artist}`, `{title}`, `{album}`, `{track_num}`) | `"{artist} - {title}"` |
| `download.allow_fallback` | Boolean | Allow YouTube Music Opus fallback when track is absent on Musilon | `true` |
| `download.save_lrc` | Boolean | Generate synchronized `.lrc` timestamped lyrics files | `true` |
| `download.embed_cover_art`| Boolean | Embed 640×640 JPEG album art into audio container | `true` |
| `download.concurrency` | Integer | Maximum simultaneous background download streams | `2` |

---

## 🛡️ Security & Privacy
- **Zero Hardcoded Secrets**: Credentials, session tokens, and account information are strictly saved in `config.json` and kept local.
- **Git Shield**: `.gitignore` strictly ignores `config.json`, cookies, local music files, scratch test scripts, and third-party binaries (`bin/ffmpeg.exe`).

---

## 📦 Building Standalone Windows Executable

To compile a standalone `.exe` installer or portable folder:
```bash
pip install pyinstaller
pyinstaller build_windows.spec
```
The output executable will be generated in `dist/SpotifyDownloader/SpotifyDownloader.exe`.

---

## 📄 License
This project is open-source software licensed under the [MIT License](LICENSE).
