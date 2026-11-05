# Flacify — High-Fidelity Audio Scraper & Desktop Suite

<p align="center">
  <img src="assets/icon.png" alt="Flacify Logo" width="128" height="128"><br>
  <strong>Next-Generation High-Fidelity Spotify Audio Downloader & Library Manager for Windows 11</strong><br><br>
  <a href="https://github.com/younes-qasempour/Spotify_downloader/releases"><img src="https://img.shields.io/badge/Release-v1.8.0-blue?style=for-the-badge&logo=windows11&logoColor=white" alt="Release v1.8.0"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/GUI-PyQt6%20Fluent%20Design-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows 11 Fluent">
  <img src="https://img.shields.io/badge/Audio-24bit%20Hi--Res%20%7C%2016bit%20FLAC-00C853?style=for-the-badge&logo=flac&logoColor=white" alt="Lossless FLAC">
  <img src="https://img.shields.io/badge/Safety%20Net-YouTube%20Music%20Opus-FF0000?style=for-the-badge&logo=youtubemusic&logoColor=white" alt="YouTube Music">
  <img src="https://img.shields.io/badge/License-MIT-purple?style=for-the-badge" alt="License">
</p>

---

## 📖 Overview

**Flacify** is a Windows desktop application and headless CLI for resolving Spotify metadata and downloading available audio for tracks, albums, and playlists. Availability, quality, provider limits, and successful downloads depend on the source and configuration.

Flacify supports lossless sources where available, provider pacing, ISRC-assisted matching, synchronized lyrics, and an offline SQLite library manager. Fallback sources and optional conversion can produce different formats or quality.

Built on a completely **decoupled two-layer architecture**:
- **Headless Multimedia Engine (`core/`)**: High-performance, multi-threaded core with zero GUI dependencies.
- **Fluent Design Presentation Layer (`gui/`)**: Immersive Windows 11 user experience featuring Mica/Acrylic styling, virtualized table views, and real-time status diagnostics.

---

## 🌟 Key Features

### 🛡️ Reliability Architecture, Source Review & Queue Recovery (v1.7.2)
- **Recoverable Download Queue & Staging Crash Recovery:** Active and pending jobs are durably tracked in `ReliabilityStore` (`reliability.db`), automatically restoring unfinished queues upon restart. Abandoned .part, `.ytdl`, or unindexed staging files are safely cleaned or recovered into the library archive.
- **Interactive Source-Match Review:** Scores candidates across duration variance, artist matching, and version tags; prompts review on ambiguous matches to eliminate incorrect recordings.
- **Reversible Library Repair & Backup Rollback:** Preview metadata and duplicate repairs before applying them, with automatic backups enabling one-click rollback.
- **Bounded Metadata Prefetching & LRU Cache:** Controlled concurrency prefetching loads metadata without memory bloat or network socket exhaustion on multi-thousand track playlists.
- **Provider-Wide Cooldown Coordination:** Coordinates rate limits and 429 backoffs across all worker threads to prevent aggressive retry spikes.
- **Sandboxed Challenge Execution:** ArvanCloud anti-bot JS challenges execute in an isolated sandbox with strict timeouts, zero filesystem access, and QuickJS / Node confinement.
- **Stage-Aware Progress & Diagnostics:** Granular stages (resolving, downloading, transcoding, tagging, normalization) with tooltip hints and guided recovery actions.
- **Pre-Flight Output Batch Preview:** Preview target folders, filenames, format conversions, and duplicate collision strategies before downloading.
- **Atomic Settings Validation & Feedback:** Validates settings changes with atomic batch persistence (`config.set_many()`) and actionable error toasts.

### 🎛️ High-Density UI & Collapsible Batch Controls (v1.6.1)
- **High-Density Track Layout:** Optimized table item height to 56px and cover art to 40x40 with crisp typography, fitting 10+ songs on screen without vertical scrolling.
- **Collapsible Batch Download Drawer:** Replaced bulky configuration blocks with a sleek, space-saving expandable drawer (`Batch Options ▾`) featuring instant batch presets (25, 50, 100, 200, All Pending) and custom spinbox controls.
- **Unified Single-Row Action Headers:** Consolidated search bars, playlist controls, and library statistics into compact, clean 32-50px headers across all views.
- **Compact 72px Player Bar:** Slimmed docked audio player dock to maximize screen real estate while retaining full scrubbing and playback capabilities.

### 🏛️ Centralized Library & Deduplication (v1.6.0)
- **Configurable Output Directory:** Downloads are saved under the configured output directory.
- **Archive Reuse:** Previously indexed tracks can be reused or copied into collection folders, reducing repeat transfers. Reuse is not guaranteed in every case.
- **Normalized Matching:** Archive lookup can use identifiers and normalized artist/title metadata; review results where recording versions matter.

### 📦 Multi-Device Track & Playlist Exporter (v1.6.0)
- **Portable Song Exporter:** Easily export any playlist or selection to external USB drives, car stereos, or portable DAPs with optional on-the-fly transcoding to MP3 (320 kbps CBR via FFmpeg), FLAC, or Opus.
- **Multi-Platform `.m3u8` Playlist Exporter:** Generates lightweight playlist files preserving exact original Spotify track sequence:
  - **Android Universal:** Filename-only matching (`Song.flac`) recognized automatically by Poweramp, Musicolet, GoneMAD, and VLC Android.
  - **Windows PC:** Absolute paths for VLC, PotPlayer, KMPlayer, and Foobar2000 with instant *"Play in Default Player"* launch.

### 🤖 MeloBot Telegram Integration & FastTelethon Acceleration (v1.5.2)
- **10x Faster Downloads & Direct MTProto Streaming:** Upgraded download pipeline with optimized MTProto routines and native crypto acceleration (`cryptg`), speeding up candidate search and media transfers by up to 10x via `@melobot`.
- **Push-Event Navigation:** Uses Telethon push updates (`events.NewMessage` and `events.MessageEdited`) to reduce polling; provider rate limits can still occur.
- **Deduplicated Multi-Click Retries:** Tracks button message IDs to prevent duplicate clicks and retries unacknowledged clicks up to 3 times at 5s intervals within an adaptive 45s delivery window.
- **Strict Quality Enforcement & Genuine Badges:** Rejects unwanted 128 kbps standard files when high/lossless quality is requested, verifies physical on-disk bitrates before tagging, and displays dedicated emerald lossless badges for `MeloBot FLAC`.
- **Intelligent Bot Interactive Keyboard Navigation:** Automatically negotiates multi-step Telegram bot dialogs—detects search candidates, navigates album menus, rejects promotional/navigation buttons, and selects optimal audio quality tiers (FLAC > 320k > 128k).
- **Single-Song Serialized Concurrency Guard:** Serializes Telegram bot queries to reduce flood limits and chat state collisions.
- **Dedicated Telegram Settings & Auth Flow:** Connect your Telegram account directly from the Fluent Settings interface via an interactive, secure two-step login modal (phone number -> SMS/App code -> 2FA password).

### 🎼 Classical & Multi-Part Aria Search Engine (v1.5)
- **Automatic Classical Detection:** Identifies classical and opera works across all eras (Mozart, Bruckner, Beethoven, Bach, Vivaldi, etc.) via catalog numbers (`Op`, `WAB`, `BWV`, `Hob`, `K`, `RV`) and composition terminology (`Symphony`, `Concerto`, `Sonata`, `Scherzo`, `Aria`, `Canzonetta`).
- **Clean Movement & Aria Extraction:** Automatically strips complex 100+ character Spotify titles down to core movement and aria phrases across colons, hyphens, and ellipses (`...`), preventing search engine query bloat.
- **Adaptive Classical Duration Tolerance:** Expands duration matching to $\max(45.0\text{s}, \text{target\_dur} \times 0.15)$ with gentle penalty slopes, accommodating natural tempo variations between different conductors and orchestras.
- **Topic Channel Verification:** Accurately verifies performer-named Topic channels without false "Foreign topic channel" rejections.

### 🎧 Audio Sources and Quality
Depending on the selected source, quality settings, availability, and fallback setting, a track can use Musilon or MeloBot FLAC or 320 kbps MP3, or YouTube Music Opus/AAC via `yt-dlp`. The default quality preference is 320 kbps, not the highest lossless tier. YouTube fallback is conditional on the fallback setting and finding a suitable match.

### 🔍 Precision Catalog Matching & Anti-False-Positive Heuristics
- **ISRC Resolution:** Uses International Standard Recording Codes (ISRC), when available, to help match tracks. Matching is not a guarantee that a recording is correct.
- **Dynamic Context Inspection:** Queries live track metadata via `/api/tracks/{id}/context` to detect bit depth, sample rates, and available audio tiers.
- **Anti-False-Positive Scoring:** Enforces strict artist validation, penalizes foreign artist uploads (`-999.0`), and penalizes unrequested remixes, karaoke, live versions, and tribute covers.
- **Quality Step-Down Fallback:** Can handle HTTP 409 (`DOWNLOAD_QUALITY_UNAVAILABLE`) by trying a lower quality tier; downloads can still fail.

### 🛡️ VIP Integration & Stealth Anti-Ban Shield
- **Direct Credentials Authentication:** Seamless login via NextAuth Directus flow using your registered Musilon email and password with automatic session renewal.
- **Real-Time Download Budget Diagnostics:** Queries `/api/media/download-budget` live to track your daily quota (150 Lossless / 150 Standard songs/day) directly within the UI.
- **Single-Stream CDN Mutex:** Restricts concurrent CDN streaming to 1 active connection while allowing YouTube Music and local deduplication to operate in parallel.
- **Human Jitter & Cooldown Countdown:** Safe mode uses a configurable randomized post-download cooldown (default 15–35 seconds) with a status countdown. The stream lock is released before this cooldown, so another worker may begin a download during it; it does not guarantee protection from rate limits.
- **Pause-and-Prompt On Limit:** If daily limits or rate-limits are reached, the app cleanly pauses and prompts you with options to switch to YouTube Music or gracefully stop.

### 📜 Synchronized CRLF Lyrics & Audio Tagging
- **Embedded Synchronized Lyrics:** Automatically fetches synchronized time-stamped lyrics from LRCLIB and embeds them directly into Vorbis comments (`LYRICS`, `UNSYNCEDLYRICS`) and ID3 (`USLT`).
- **Windows CRLF Formatting:** Standardizes all lyrics line breaks to Windows CRLF (`\r\n`), ensuring seamless scrolling in desktop players like foobar2000, Windows Media Player, MusicBee, and AIMP.
- **High-Resolution Front Cover Artwork:** Injects authentic 640×640 album artwork directly from Spotify's CDN into FLAC picture blocks, ID3 APIC frames, and MP4 cover atoms.
- **Watermark Scrubbing:** Automatically strips promotional site watermarks (e.g. `[Musilon]`, `- musilon.com`) from metadata tags and filenames.

### 📁 Smart Folder Organization & Track Numbering
- **Optional collection folders:** When collection subfolders are enabled, tracks can be placed under a sanitized collection folder in the configured output directory. By default, files are saved directly in the output directory.
- **Album naming:** Album filenames can include track numbering (`01. Artist - Title.flac`) using the album naming template.
- **Isolated App Cache:** Album covers and marker files are stored in `%LOCALAPPDATA%\Flacify\cache`, leaving your music folders 100% clean.

### 💾 Offline Saved Playlists & Differential Sync
- **Metadata Archiving:** Import massive playlists (500 to 5,000+ tracks) and save their full track listings instantly into a local SQLite database without queuing audio downloads.
- **Flexible Batch Downloading:** Download tracks in custom batches (25, 50, 100, 200, or custom size) with a single click, keeping you comfortably under daily quota limits.
- **Persistent Progress Tracking:** Visual progress bars, track counters (Total, Downloaded, Pending), and track-level status badges (`Pending`, `Queued`, `Completed`).
- **Differential Playlist Synchronization:** Single-click incremental synchronization compares online Spotify playlists against local database storage, purges deleted tracks, and automatically enqueues newly added delta tracks directly into the download queue with live notifications.
- **Freeze-Free Queue Ingestion:** Vectorized batch model insertions eliminate UI freezes when enqueuing thousands of tracks simultaneously.

### 🎧 Dynamic Audio Device Switching & Universal Keyboard Controls (v1.4.2)
- **Automatic Audio Output Migration:** Dynamically tracks Windows default playback endpoint changes. Switching default devices in Windows (plugging in earphones, connecting Bluetooth headphones, or changing the taskbar sound output) immediately migrates the audio stream without restarting the application or stopping playback.
- **Audio Output Device Picker:** Dedicated audio device button (`FluentIcon.HEADPHONE`) on the mini-player bar displays a quick menu to choose between "System Default (Auto-Switch)" or any specific connected sound device.
- **Universal Keyboard Controls:** Space (Play/Pause), Left/Right arrows (Seek -5s / +5s, Shift for 10s), Ctrl+Left/Right (Previous/Next track), Up/Down arrows (Volume), and hotkeys (J/K/L/M/N/P) work everywhere across the app.
- **Smart Text-Input Isolation:** Normal typing in search inputs, URLs, playlist rename dialogs, or tag editor dialogs is completely protected and never hijacked.
- **Windows Media Hardware & Headset Integration:** Full support for dedicated multimedia keyboard keys and Bluetooth headset buttons via `WM_APPCOMMAND` and Windows global media hotkeys (`VK_MEDIA_PLAY_PAUSE`, `VK_MEDIA_NEXT_TRACK`, etc.).

### ✏️ Manual Playlist Renaming & Metadata Customization (v1.4.1)
- **Manual Playlist Renaming:** Rename any saved playlist or downloaded library collection with a single click via an interactive Fluent dialog.
- **Custom Artwork & Cover Customization:** Select local image files (.jpg, .png, .webp) via file picker or specify custom URLs with real-time preview thumbnails.
- **In-Place Track Metadata Editing:** Edit title, artist, and album tags for individual tracks directly within saved playlists and synchronize them across the archive.
- **Complete Library & Disk Synchronization:** Renaming playlists automatically updates database records, disk folder names, and cached album art seamlessly.

### 🎚️ Universal Audio Transcoder & Loudness Normalization
- **Universal Audio Transcoder (`core/transcoder.py`):** User-selectable target container via FFmpeg:
  - **Original Stream (Default):** Retains pristine native stream without re-encoding.
  - **Apple Lossless (`alac` `.m4a`):** Bit-perfect lossless container for iPhone, iPad, and Apple Music library integration.
  - **MP3 320 kbps CBR (`mp3`):** Universal high-bitrate compatibility for legacy car stereos and hardware players.
  - **FLAC 16/24-bit (`flac`):** High-resolution studio master preservation.
  - **Opus 256 kbps (`opus`):** Next-gen high-efficiency acoustic fidelity.
- **ReplayGain 2.0 / EBU R128 Loudness Normalization:** Integrated EBU R128 loudness analysis and non-destructive `REPLAYGAIN_TRACK_GAIN` and `REPLAYGAIN_TRACK_PEAK` tagging across FLAC, MP3, M4A, and Opus containers, with batch library calculation.

### ⚡ High-Performance Architecture & UI Acceleration (v1.4.0)
- **Tab Transitions:** Uses Fluent slide animations for navigation between views.
- **Atomic Batch Model Ingestion:** Single-pass atomic batch loading (`set_items`) renders thousands of offline library tracks in under 0.08 seconds without GUI freezing.
- **De-Duplicated Album Aggregation:** Unified album clustering groups tracks strictly by album identity with primary artist resolution, consolidating soundtrack and compilation albums into singular entries.
- **Non-Blocking Network & Local Scans:** Fully decoupled background OAuth token validation and pre-cached in-memory scanning eliminate UI event loop stalls.

### 🎵 In-App Mini-Player & Synchronized Lyrics
- **Built-in Audio Dock:** Bottom player bar with Play/Pause, Seek scrubber, Volume slider, and Track art/metadata preview.
- **Live Synchronized Karaoke Lyrics:** Dynamic floating lyrics display with real-time scrolling and active line highlighting synchronized with audio playback.
- **Instant Library Playback:** Double-click or right-click any track in Completed or Playlists view to play immediately without external media players.

### 🌐 Universal Ingestion & Audiophile Enhancements
- **Universal Input:** Queue arbitrary media links (YouTube, SoundCloud, Bandcamp, Vimeo, etc.) or free-text search queries directly into the queue.
- **Companion M3U8 Playlists:** Automatically exports UTF-8 relative `.m3u8` playlists alongside downloaded tracks.
- **Windows 11 System Tray:** Minimize to tray with quick background controls and native notifications.

### ⚡ Persistent SQLite Library & Instant Deduplication (`archive.db`)
- **Thread-Safe WAL Architecture:** SQLite database with WAL journal mode and context-managed connections to eliminate Windows file locking conflicts.
- **Local Archive Reuse:** Previously downloaded tracks may be found via Spotify ID, ISRC, or normalized `(artist, title)` and reused or copied locally.
- **Offline Library View:** Searchable library with Songs, Albums, and Playlists navigation, cover art thumbnails, double-click playback (`os.startfile`), and Explorer reveal.
- **Reversible Repairs:** The Recovery & Tools workspace previews explicit archive-metadata repairs and byte-identical duplicate hardlink replacements, with backups and conflict-checked undo. It does not automatically fetch missing artwork or lyrics for a library-wide repair.

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
│   ├── queue_manager.py      # Producer-consumer queue and recoverable jobs
│   ├── staging_recovery.py   # Explicit inspection and recovery of staged downloads
│   ├── library_repair.py     # Preview, backup, and undo for library repairs
│   ├── output_preview.py     # Non-mutating output path estimates
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
│       ├── reliability_view.py # Recovery & Tools workspace
│       └── settings_view.py  # Credentials, download preferences, and validation
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
1. Download **`Flacify_Setup_v1.0.1.exe`** from the latest [GitHub Release](https://github.com/younes-qasempour/Spotify_downloader/releases).
2. Run the installer wizard (installs per-user into `%LOCALAPPDATA%\Programs\Flacify` without requiring Administrator privileges).
3. Launch **Flacify** from your Start Menu or Desktop shortcut.

### Option 2: Running from Source

#### Prerequisites
- **Python 3.10+** on Windows
- **Embedded JavaScript runtime:** `quickjs-ng` is installed from `requirements.txt` and imported as `quickjs`; Node.js is not required for the Musilon challenge handler. The release build specifies `quickjs` and `_quickjs` as hidden imports. The handler runs the selected challenge script in an isolated, time- and memory-limited context without host filesystem or network bindings. If the runtime is missing, the challenge is unsupported, or evaluation fails, the challenge fails closed rather than executing through Node.js; Musilon may be unavailable until the issue is resolved.
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
- **Controls:** Use the queue controls for starting, pausing, and retrying downloads. See **Recovery & Tools** below before retrying interrupted work.

### 2. Headless CLI Mode
For servers, scheduled tasks, or scripting environments:
```powershell
# Download a single track using the configured quality preference
python main.py --headless "https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg"

# Download available tracks from a playlist to a custom folder
python main.py --headless "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" --output "D:\Music\TopHits"
```

The CLI processes the supplied URL directly; it does not use the GUI's recoverable queue, interactive source-approval dialog, repair workspace, or output preview. `--output` also saves the output directory in settings.

### 3. Recovery & Tools (GUI)

Open **Recovery & Tools** in the top bar. These actions are explicit; opening the workspace does not start downloads or automatically recover staged files.

#### Recoverable queue and diagnostics

Unfinished queue metadata is saved in `%LOCALAPPDATA%\Flacify\reliability.sqlite3` when storage is available. After restart, previously failed items return as **Failed** and other unfinished items as **Stopped**; completed and cancelled items are not restored. Restoring the queue itself does not start downloads. This is job recovery, not a promise to resume partial bytes, and storage errors can prevent persistence.

In **Recovery & output**, inspect the status, processing stage, error, and diagnostic hint; use **Refresh diagnostics** if needed. Hints are based on the available status and error text, not a definitive diagnosis. Correct the underlying problem before choosing **Retry selected (starts downloads)** or **Retry failed / stopped (starts downloads)**. **Important:** either retry can start all queued, stopped, paused, and failed items, not just the selected rows. Other queue-wide start actions, including Studio download and sync actions, can also start restored work. Completed files are not part of the recovered queue.

**Startup safety limitation:** watched-playlist synchronization can run automatically at startup or on its schedule and, when it discovers tracks to auto-download, call the queue-wide start operation. This can start restored items without an explicit retry. To avoid that path, disable watched-playlist automatic syncing and auto-download before restarting, or set `playlists.auto_sync_on_startup` and `playlists.auto_download_synced_tracks` to `false` and `playlists.auto_sync_interval_hours` to `0` in the configuration while Flacify is closed. Preserve a backup before editing settings manually.

#### Abandoned staging

In **Abandoned staging**, choose **Scan abandoned staging** to inspect the configured output folder and its subfolders. Only recognized, owned, unlocked staging directories are listed; active, foreign, and unsafe directories are omitted. Normal cancellation or errors may clean up temporary files, so not every interrupted download has recoverable staging.

Select one **ready** row and choose **Recover ready**. Recovery rechecks ownership, locking, payload hashes, and audio validity, then publishes without overwriting existing audio; it may add a filename suffix. It requires filesystem hardlink support. If a matching queue item exists, Flacify attempts to register it as completed; otherwise a library scan can index the recovered file. If publication is interrupted, staged files or markers may remain and an output may already exist; inspect both locations and check for duplicates before retrying. **Discard selected…** permanently removes the selected owned staging contents after confirmation; inspect them first. Incomplete or invalid stages cannot be recovered with **Recover ready**.

#### Review uncertain source matches

**Review uncertain source matches before transfer** is enabled by default in the workspace. When the GUI queue flags a candidate as uncertain, the dialog compares requested and candidate title, artist, duration, version, provider, and quality, with reasons in its details. Approve only the intended recording; rejecting or closing the dialog stops that item. The review is heuristic: missing candidate details and matches not flagged as uncertain are not proof of correctness. Archive reuse bypasses source matching, and the headless CLI has no approval prompt.

#### Metadata prefetch and provider cooldowns

In **Metadata prefetch**, enter up to 24 public HTTPS Spotify track or album URLs, one per line, and select **Prefetch metadata**. This fetches metadata, not audio, and shows at most 24 unique tracks; playlists and private links are not supported by this workspace. Prefetch uses configured Spotify API credentials when available, with the public guest resolver as a fallback. Public Spotify track/album metadata is cached locally for up to 15 minutes when the cache is available, so changes may not appear immediately. **Enqueue previewed tracks (does not press Start)** submits the preview to the queue; if workers are already running, those tracks may begin processing immediately.

Spotify, Musilon, and lyrics requests coordinate certain rate-limit cooldowns within the running process. A provider can still return an error or require a later retry; wait for the indicated delay or quota reset rather than repeatedly retrying. Cooldowns are not persisted across restarts. Musilon safe-mode song cooldowns are separate from these provider response cooldowns.

#### Output preview

In **Recovery & output**, **Preview queued output paths** estimates paths for non-completed queue items using current naming, folder, and format settings and reports detected collisions. It does not create or reserve files. Native format is shown as `.<native>` until resolution, so collisions with the eventual extension cannot be fully predicted. Actual paths can differ due to archive reuse, format conversion failures, later filesystem changes, and publication-time collision checks; treat the preview as an estimate, not a guarantee.

#### Reversible repairs

In **Reversible repairs**, choose an archived audio file and **Preview archive metadata repair**, or choose a duplicate and a byte-identical keeper and **Preview hardlink replacement**. The metadata repair uses the archive's title, artist, and other stored fields; it does not download artwork or lyrics. Supported audio files are FLAC, MP3, M4A, Opus, and Ogg. Duplicate replacement requires distinct, byte-identical files on the same device and a filesystem supporting hardlinks; future in-place edits to either linked path affect both.

Review the preview before applying. Changing the inputs invalidates it, and apply rechecks the files and preview. The original is copied to `%LOCALAPPDATA%\Flacify\repair_backups` before replacement, and the journal records the action; backups are not automatically removed. In **Repair history**, refresh, select one applied repair, and choose **Undo selected repair**. Undo restores the backed-up original only if the current file and backup still match the journal; changed, missing, or unsafe paths are refused. Keep independent backups of important music, and preserve the repair journal and backup copies if you need undo later.

---

## ⚙️ Configuration & Settings

Settings are stored in `%LOCALAPPDATA%\Flacify\config.json`; existing user values can differ from the defaults below. Use the in-app settings controls where available. Do not share the config file, cookies, account credentials, or session data.

| Setting Key | Default | Description |
|-------------|---------|-------------|
| `source_engine` | `"musilon"` | Primary source (`"musilon"` or `"melobot"`); YouTube Music is a fallback |
| `telegram.enabled` | `false` | Enables Telegram/MeloBot integration |
| `telegram.preferred_quality` | `"320"` | Preferred Telegram quality |
| `download.allow_128k` | `false` | Allows MeloBot's 128 kbps option when enabled |
| `musilon.enabled` | `true` | Enables high-speed lossless Musilon CDN downloads |
| `musilon.username` | `""` | Registered Musilon email address |
| `musilon.password` | `""` | Musilon account password |
| `musilon.safe_mode` | `true` | Enables the randomized post-download song cooldown; rate limits can still occur |
| `musilon.cooldown_min_sec` | `15` | Minimum safe-mode post-download cooldown seconds |
| `musilon.cooldown_max_sec` | `35` | Maximum safe-mode post-download cooldown seconds |
| `download.allow_fallback` | `true` | Allows YouTube Music fallback when a suitable source is available |
| `download.output_dir` | `~/Music/Spotify Downloads` | Base output directory (stored as an absolute path) |
| `download.naming_template` | `{artist} - {title}` | File naming pattern for singles and playlists |
| `download.album_naming_template` | `{track_num}. {artist} - {title}` | File naming pattern for album tracks |
| `download.preferred_quality` | `"320"` | Preferred source quality; the Settings control offers MP3 320k or lossless FLAC |
| `download.lyrics_mode` | `"embedded_only"` | Lyrics placement (`"embedded_only"`, `"separate_folder"`, `"same_folder"`) |
| `download.target_format` | `"original"` | Desired output format; conversion may require FFmpeg |
| `download.review_uncertain_matches` | `true` | Ask for GUI approval of uncertain queue source matches |

### Settings validation and recovery

The Settings view reports invalid or unsaved changes and restores affected controls to the previous settings. For example, choose a non-empty absolute output path; proxy URLs need a supported HTTP, HTTPS, or SOCKS scheme and host; naming templates may use `{artist}`, `{title}`, `{album}`, `{track_num}`, `{track_number}`, `{track}`, `{disc_num}`, and `{disc_number}`. Cooldown settings accept 0–600 seconds in the configuration manager; the GUI controls allow 0–300 and keep the minimum no greater than the maximum. If saving fails, check disk space and permissions for the configuration folder, then retry.

Validation applies to settings changed through the configuration manager; do not assume manually edited JSON is fully validated on load. Malformed JSON is backed up as a `config.corrupted_*.json.bak` file before defaults are written. If backup or loading fails, saving is refused rather than overwriting the original; inspect and back up the file before correcting it.

---

## 📦 Compiling Standalone Executable & Installer

To build the standalone production executable and Inno Setup installer:
```powershell
python build_windows.py
```

This automated pipeline:
1. Validates and generates multi-resolution Windows icons (`assets/icon.ico`).
2. Invokes **PyInstaller** using `app.spec` to create a slim, windowed `dist/Flacify` application bundle.
3. Invokes **Inno Setup 6** (`ISCC.exe`) to generate `dist/installer/Flacify_Setup_v1.7.2.exe` with a complete uninstaller and mutex process guard.

---

## 🧪 Testing

Run the offline suite in an isolated temporary application-data directory:
```powershell
python -B scripts\run_tests.py
```

---

## 🛡️ Security & Privacy

- **Local Data:** Configuration, queue recovery data, and repair backups are stored under `%LOCALAPPDATA%\Flacify` by default. Treat configuration, cookies, session files, logs, and databases as sensitive; local storage does not imply encryption.
- **Git Hygiene:** Review changes before committing; ignore rules are not a guarantee that credentials or local files cannot be committed.
- **Non-Admin Installation:** Installs per-user into the local app folder without requiring elevation or modifying system-level directories.

---

## ⚖️ Legal Disclaimer

This software is developed strictly for **educational, personal backup, and private research purposes**. Flacify does not host, distribute, or stream any copyrighted audio files. Users are responsible for complying with the terms of service of any third-party platforms and applicable local copyright laws.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
