# Flacify — High-Fidelity Audio Scraper & Desktop Suite

<p align="center">
  <img src="assets/icon.png" alt="Flacify Logo" width="128" height="128"><br>
  <strong>Next-Generation High-Fidelity Spotify Audio Downloader & Library Manager for Windows 11</strong><br><br>
  <a href="https://github.com/younes-qasempour/Spotify_downloader/releases"><img src="https://img.shields.io/badge/Release-v1.0.0-blue?style=for-the-badge&logo=windows11&logoColor=white" alt="Release v1.0.0"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/GUI-PyQt6%20Fluent%20Design-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows 11 Fluent">
  <img src="https://img.shields.io/badge/Audio-24bit%20Hi--Res%20%7C%2016bit%20FLAC-00C853?style=for-the-badge&logo=flac&logoColor=white" alt="Lossless FLAC">
  <img src="https://img.shields.io/badge/Safety%20Net-YouTube%20Music%20Opus-FF0000?style=for-the-badge&logo=youtubemusic&logoColor=white" alt="YouTube Music">
  <img src="https://img.shields.io/badge/License-MIT-purple?style=for-the-badge" alt="License">
</p>

---

## 📖 Overview

**Flacify** is a production-grade, distribution-ready Windows 11 desktop application and headless CLI suite engineered to download Spotify tracks, full albums, and massive playlists (1,000+ tracks) at **true studio-master fidelity** without crashes, rate-limit bans, audio transcoding artifacts, or memory leaks.

Unlike conventional downloaders that record compressed, lossy audio or re-encode degraded streams, Flacify combines **direct high-speed lossless CDN retrieval** with **stealth anti-ban pacing**, **exact ISRC matching**, **embedded CRLF synchronized lyrics**, and an **offline SQLite library manager**.

Built on a completely **decoupled two-layer architecture**:
- **Headless Multimedia Engine (`core/`)**: High-performance, multi-threaded core with zero GUI dependencies.
- **Fluent Design Presentation Layer (`gui/`)**: Immersive Windows 11 user experience featuring Mica/Acrylic styling, virtualized table views, and real-time status diagnostics.

---

## 🌟 Key Features

### 🎧 High-Fidelity Cascading Audio Ladder
Every queued track automatically traverses an intelligent cascading resolution ladder to guarantee the highest acoustic fidelity available:
1. **Tier 1 (Target):** **Musilon Studio Master 24-bit Hi-Res FLAC** (48 kHz – 96 kHz / 24-bit PCM).
2. **Tier 2 (Lossless):** **Musilon CD-Quality 16-bit FLAC** (44.1 kHz / 16-bit Lossless).
3. **Tier 3 (Pristine):** **Musilon Studio 320 kbps MP3 / OGG** (Constant Bitrate, 320 kbps).
4. **Tier 4 (Safety Net):** **YouTube Music native Opus/AAC** stream via `yt-dlp` with strict $\pm 5$s duration matching. *Engages automatically if a song is not indexed on lossless CDNs.*

### 🔍 Precision Catalog Matching & Anti-False-Positive Heuristics
- **Exact ISRC Resolution:** Matches tracks against International Standard Recording Codes (ISRC) for instant 100% verified track matching.
- **Dynamic Context Inspection:** Queries live track metadata via `/api/tracks/{id}/context` to detect bit depth, sample rates, and available audio tiers.
- **Anti-False-Positive Scoring:** Enforces strict artist validation, penalizes foreign artist uploads (`-999.0`), and penalizes unrequested remixes, karaoke, live versions, and tribute covers.
- **Quality Step-Down Fallback:** Seamlessly handles HTTP 409 (`DOWNLOAD_QUALITY_UNAVAILABLE`) by stepping down from 24-bit to 16-bit or 320k without download failures.

### 🛡️ VIP Integration & Stealth Anti-Ban Shield
- **Direct Credentials Authentication:** Seamless login via NextAuth Directus flow using your registered Musilon email and password with automatic session renewal.
- **Real-Time Download Budget Diagnostics:** Queries `/api/media/download-budget` live to track your daily quota (150 Lossless / 150 Standard songs/day) directly within the UI.
- **Single-Stream CDN Mutex:** Restricts concurrent CDN streaming to 1 active connection while allowing YouTube Music and local deduplication to operate in parallel.
- **Human Jitter & Cooldown Countdown:** Enforces randomized pacing (15–35s) with a live UI countdown timer (`VIP Cooldown (18s)`) and non-blocking cancellation.
- **Pause-and-Prompt On Limit:** If daily limits or rate-limits are reached, the app cleanly pauses and prompts you with options to switch to YouTube Music or gracefully stop.

### 📜 Synchronized CRLF Lyrics & Audio Tagging
- **Embedded Synchronized Lyrics:** Automatically fetches synchronized time-stamped lyrics from LRCLIB and embeds them directly into Vorbis comments (`LYRICS`, `UNSYNCEDLYRICS`) and ID3 (`USLT`).
- **Windows CRLF Formatting:** Standardizes all lyrics line breaks to Windows CRLF (`\r\n`), ensuring seamless scrolling in desktop players like foobar2000, Windows Media Player, MusicBee, and AIMP.
- **High-Resolution Front Cover Artwork:** Injects authentic 640×640 album artwork directly from Spotify's CDN into FLAC picture blocks, ID3 APIC frames, and MP4 cover atoms.
- **Watermark Scrubbing:** Automatically strips promotional site watermarks (e.g. `[Musilon]`, `- musilon.com`) from metadata tags and filenames.

### 📁 Smart Folder Organization & Track Numbering
- **Playlists:** Saved to `{output_dir}/{playlist_name}/`.
- **Albums:** Saved to `{output_dir}/{album_name}/` with album track numbering (`01. Artist - Title.flac`), preserving genuine track and disc order.
- **Singles:** Standalone tracks are neatly routed to `{output_dir}/Singles/`.
- **Isolated App Cache:** Album covers and marker files are stored in `%LOCALAPPDATA%\Flacify\cache`, leaving your music folders 100% clean.

### 💾 Offline Saved Playlists & On-Demand Batch Downloads
- **Metadata Archiving:** Import massive playlists (500 to 5,000+ tracks) and save their full track listings instantly into a local SQLite database without queuing audio downloads.
- **Flexible Batch Downloading:** Download tracks in custom batches (25, 50, 100, 200, or custom size) with a single click, keeping you comfortably under daily quota limits.
- **Persistent Progress Tracking:** Visual progress bars, track counters (Total, Downloaded, Pending), and track-level status badges (`Pending`, `Queued`, `Completed`).

### ⚡ Persistent SQLite Library & Instant Deduplication (`archive.db`)
- **Zero-Bandwidth Re-Downloads:** Tracks previously downloaded into any playlist or single folder are instantly detected via Spotify ID, ISRC, or normalized `(artist, title)` and copied locally in ~2ms.
- **Offline Library View:** Searchable library with Songs, Albums, and Playlists navigation, cover art thumbnails, double-click playback (`os.startfile`), and Explorer reveal.
- **Deep Scan Auto-Repair:** One-click repair engine scans existing audio files, identifies missing cover art or lyrics, and heals them in-place without re-downloading audio streams.

---

## 🏗️ Architecture & Data Flow

```mermaid
flowchart TD
    A[Spotify URL / URI] --> B[Spotify Metadata Resolver]
    B --> C{SQLite Archive Check}
    C -- "Already Downloaded" --> D[Instant Local Copy & Retag (~2ms)]
    C -- "New Track" --> E[Cascading Audio Ladder]
    
    subgraph Engine [Multi-Tier Audio Ladder]
        E --> F{Musilon VIP Engine}
        F -- "Catalog Match" --> G[Lossless FLAC 24/16-bit or 320k]
        F -- "409 / Unavailable" --> H[Step-Down Quality Fallback]
        H --> G
        F -- "No Match / Rate Limit" --> I[YouTube Music Safety Net]
        I --> J[Native Opus/AAC Stream via yt-dlp]
    end

    G --> K[Chunked Stream & Magic Byte Validation]
    J --> K
    K --> L[LRCLIB Synced CRLF Lyrics Fetch]
    L --> M[Mutagen Tagging & 640x640 Artwork Injection]
    M --> N[Smart Folder Organization & File Output]
    N --> O[SQLite Archive Indexing (archive.db)]
    D --> O
```

---

## 📂 Repository Structure

```
Flacify/
├── app.spec                  # PyInstaller configuration for standalone release
├── build_windows.py          # Automated pipeline orchestrator (PyInstaller + Inno Setup)
├── installer.iss             # Inno Setup 6 per-user Windows installer configuration
├── version_info.txt          # Embedded Windows PE version resource metadata
├── config.example.json       # Clean template for configuration settings
├── requirements.txt          # Production Python dependencies
├── main.py                   # Unified entrypoint (GUI default or --headless CLI)
│
├── assets/                   # APPLICATION BRANDING & ICONS
│   ├── icon.ico              # Multi-resolution icon (16x16 to 256x256)
│   ├── icon.png              # High-res 256x256 application logo
│   └── convert_icon.py       # Reusable icon generation utility
│
├── core/                     # HEADLESS MULTIMEDIA ENGINE (Zero GUI Dependencies)
│   ├── paths.py              # Centralized path manager (%LOCALAPPDATA%\Flacify)
│   ├── config.py             # Thread-safe persistent JSON config manager
│   ├── archive.py            # SQLite music library archive, deduplication & repair
│   ├── spotify_client.py     # Spotify Web API client + guest scraper fallback
│   ├── musilon.py            # Musilon VIP engine (NextAuth, REST catalog, ISRC matcher)
│   ├── ytdlp_engine.py       # YouTube Music fallback engine (±5s duration validation)
│   ├── lyrics.py             # LRCLIB lyrics client (synchronized .lrc + plain lyrics)
│   ├── tagger.py             # Mutagen metadata tagger & cover art embedder
│   ├── resolver.py           # Cascading ladder engine (Musilon -> YTM safety net)
│   ├── queue_manager.py      # Producer-consumer thread queue with callback hooks
│   └── utils.py              # Filename sanitizer, FFmpeg detector/downloader
│
├── gui/                      # WINDOWS 11 FLUENT PRESENTATION LAYER
│   ├── styles.py             # Dark theme palette and styling tokens
│   ├── bridge.py             # Qt Signal Bridge between background threads & event loop
│   ├── queue_model.py        # Virtualized TrackQueueModel (QAbstractTableModel)
│   ├── queue_delegate.py     # TrackCardDelegate (74px high custom card painter)
│   ├── main_window.py        # FluentWindow with navigation sidebar
│   └── views/
│       ├── queue_view.py     # Queue management, URL inputs, metric cards
│       ├── playlists_view.py # Saved Playlists manager & batch download controls
│       ├── completed_view.py # Completed downloads library with direct file launcher
│       └── settings_view.py  # VIP credentials, quota diagnostics, auto-repair
│
└── tests/                    # AUTOMATED TEST SUITE
    ├── test_utils.py         # Utilities, sanitization, and duration formatting tests
    ├── test_spotify_client.py# Metadata resolving and entity parsing tests
    ├── test_archive.py       # SQLite archive and deduplication tests
    └── test_gui.py           # PyQt6 GUI model and signal bridge tests
```

---

## 💾 Installation

### Option 1: Standalone Windows Installer (Recommended)
1. Download **`Flacify_Setup_v1.0.0.exe`** from the latest [GitHub Release](https://github.com/younes-qasempour/Spotify_downloader/releases).
2. Run the installer wizard (installs per-user into `%LOCALAPPDATA%\Programs\Flacify` without requiring Administrator privileges).
3. Launch **Flacify** from your Start Menu or Desktop shortcut.

### Option 2: Running from Source

#### Prerequisites
- **Python 3.10+** (tested on Python 3.10 through 3.14 on Windows 10/11)
- **Node.js** (required for dynamic ArvanCloud challenge bypass)
- **FFmpeg** (bundled automatically in the installer; auto-downloadable via Settings in source mode)

#### Step-by-Step Setup
```powershell
# 1. Clone the repository
git clone https://github.com/younes-qasempour/Spotify_downloader.git
cd Spotify_downloader

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the application
python main.py
```

---

## 💻 Usage Guide

### 1. Graphical Interface (GUI)
```powershell
python main.py
```
- **Paste Spotify Link:** Copy any track, album, or playlist URL from Spotify and press `Ctrl+V` or paste into the top search bar.
- **Analyze & Enqueue:** Resolves metadata instantly and populates the virtualized queue.
- **Batch Download:** In the **Playlists** tab, save full playlists offline and download them in manageable batches (25, 50, 100 songs).
- **Controls:** Start, Pause, Resume, or Retry Failed tracks at any time with live progress indicators.

### 2. Headless CLI Mode
For servers, scheduled tasks, or scripting environments:
```powershell
# Download a single track at maximum available quality
python main.py --headless "https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg"

# Download a complete album or playlist to a custom folder
python main.py --headless "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" --output "D:/Music/TopHits"
```

---

## ⚙️ Configuration & Settings

All settings are configured via the in-app **Settings** view or stored in `%LOCALAPPDATA%\Flacify\config.json`:

| Setting Key | Default | Description |
|-------------|---------|-------------|
| `musilon.enabled` | `true` | Enables high-speed lossless Musilon CDN downloads |
| `musilon.username` | `""` | Registered Musilon email address |
| `musilon.password` | `""` | Musilon account password |
| `musilon.safe_mode` | `true` | Enforces human jitter & cooldown pacing to prevent rate limits |
| `musilon.cooldown_min_sec` | `15` | Minimum cooldown seconds between consecutive Musilon downloads |
| `musilon.cooldown_max_sec` | `35` | Maximum cooldown seconds between consecutive Musilon downloads |
| `download.allow_fallback` | `true` | Automatically falls back to YouTube Music if Musilon lacks the track |
| `download.output_dir` | `~/Music` | Base root directory for all music downloads |
| `download.naming_template` | `{artist} - {title}` | File naming pattern for singles and playlists |
| `download.album_naming_template` | `{track_num}. {artist} - {title}` | File naming pattern for album tracks |
| `download.preferred_quality` | `lossless` | Preferred quality tier (`lossless`, `hires`, `high`, `standard`) |
| `download.lyrics_mode` | `embedded_only` | Lyrics embedding mode (`embedded_only`, `both`, `disabled`) |

---

## 📦 Compiling Standalone Executable & Installer

To build the standalone production executable and Inno Setup installer:
```powershell
python build_windows.py
```

This automated pipeline:
1. Validates and generates multi-resolution Windows icons (`assets/icon.ico`).
2. Invokes **PyInstaller** using `app.spec` to create a slim, windowed `dist/Flacify` application bundle.
3. Invokes **Inno Setup 6** (`ISCC.exe`) to generate `dist/installer/Flacify_Setup_v1.0.0.exe` with a complete uninstaller and mutex process guard.

---

## 🧪 Testing

Run the automated test suite covering core utilities, Spotify resolving, archive deduplication, and GUI components:
```powershell
python -m unittest discover -s tests -p "test_*.py"
```

---

## 🛡️ Security & Privacy

- **Protected Secrets:** Account credentials, session cookies, and local database records are stored strictly in your local `%LOCALAPPDATA%\Flacify` directory.
- **Git Shield:** `.gitignore` ensures that personal credentials, configuration overrides, local music files, and cache records are never committed to version control.
- **Non-Admin Installation:** Installs per-user into the local app folder without requiring elevation or modifying system-level directories.

---

## ⚖️ Legal Disclaimer

This software is developed strictly for **educational, personal backup, and private research purposes**. Flacify does not host, distribute, or stream any copyrighted audio files. Users are responsible for complying with the terms of service of any third-party platforms and applicable local copyright laws.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
