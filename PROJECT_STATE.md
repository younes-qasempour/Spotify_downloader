# Project State & Developer Notes: Spotify Downloader

> **Note for Future AI Agents & Developers:**
> Read this document first to avoid starting from scratch. It contains the exact architecture, solved edge cases, gotchas, verified test cases, and component layout.

---

## 1. Project Overview & Architecture

A high-performance Windows 11 desktop application and CLI tool that downloads Spotify tracks, albums, and playlists (1,000+ tracks) without crashes, rate-limit bans, or UI freezing.

### Decoupled Two-Layer Architecture
- **`core/`**: 100% headless, platform-agnostic Python multimedia engine with **zero GUI dependencies**. Communicates state exclusively through thread-safe callbacks.
- **`gui/`**: Windows 11 Fluent Design presentation layer using `PyQt6` and `PyQt6-Fluent-Widgets`. Communicates with `core/` strictly via worker threads and Qt signals (`gui/bridge.py`).

```
d:\Spotify-Downloader\
├── config.json              # Local configuration (download dir, cookies, credentials)
├── requirements.txt         # Core dependencies (PyQt6, PyQt6-Fluent-Widgets, yt-dlp, mutagen, etc.)
├── main.py                  # Dual-mode entry point (GUI default, --headless CLI)
│
├── core/                    # HEADLESS MULTIMEDIA ENGINE
│   ├── config.py            # Thread-safe JSON config manager
│   ├── spotify_client.py    # Spotify metadata resolver (API + guest embed scraper)
│   ├── musilon.py           # Musilon VIP engine (ArvanCloud solver, CDN downloader, jitter)
│   ├── ytdlp_engine.py      # YouTube Music fallback engine (±5s duration validation)
│   ├── lyrics.py            # LRCLIB client (synced .lrc + plain lyrics)
│   ├── tagger.py            # Mutagen tagging (ID3v2.4, Vorbis, MP4, cover art)
│   ├── resolver.py          # Cascading engine (Tiers 1-3 Musilon -> Tier 4 YTM)
│   ├── queue_manager.py     # Producer-consumer queue with callback hooks
│   └── utils.py             # Filename sanitizer, watermark cleaner, ffmpeg detector
│
└── gui/                     # FLUENT DESIGN PRESENTATION LAYER
    ├── styles.py            # Dark theme color palette and styling constants
    ├── bridge.py            # EngineSignalBridge (Core callbacks -> Qt signals)
    ├── queue_model.py       # Virtualized TrackQueueModel (QAbstractTableModel)
    ├── queue_delegate.py    # TrackCardDelegate (74px high custom card painter)
    ├── main_window.py       # FluentWindow with acrylic sidebar and view switcher
    └── views/
        ├── queue_view.py    # Queue view (sticky input, metric cards, table)
        ├── completed_view.py# Completed library (explorer / double-click play)
        └── settings_view.py # Settings (CardWidget-based, shared MusilonEngine)
```

---

## 2. High-Fidelity Cascading Ladder
1. **Tier 1 (Target):** Musilon Lossless FLAC 16-bit (CD Quality, 44.1 kHz).
2. **Tier 2 (Fallback A):** Musilon Hi-Res FLAC 24-bit (Studio Master, 48–96 kHz).
3. **Tier 3 (Fallback B):** Musilon Studio MP3 320 kbps (CBR).
4. **Tier 4 (Safety Net):** YouTube Music native high-bitrate Opus stream via `yt-dlp` with strict $\pm 5$s duration filter.

---

## 3. Critical Solved Gotchas & Bug Fixes (DO NOT REVERT)

### 1. `TableView` Row Height Squashing Bug
- **Symptom:** When enqueuing a track, the UI appeared completely frozen or squashed.
- **Cause:** `qfluentwidgets.TableView` forcibly sets `verticalHeader().defaultSectionSize(38)` and `ResizeMode.Fixed`. Our `TrackCardDelegate` is `74px` high (`CARD_HEIGHT = 74`).
- **Fix:** Both `QueueView` and `CompletedView` must call:
  ```python
  self.table.verticalHeader().setDefaultSectionSize(76)
  self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
  ```
  and `self.table.setRowHeight(row, 76)` upon row insertion, followed by `self.table.viewport().update()`.

### 2. Musilon CDN Hotlinking (HTTP 403 Forbidden)
- **Symptom:** Downloads from `dl2.musilon.com` returned HTTP 403 Forbidden.
- **Cause:** Musilon's CDN servers check the HTTP `Referer` header and reject hotlinking.
- **Fix:** `MusilonEngine.session.headers` and `download_file()` must explicitly include:
  ```python
  headers={"Referer": "https://musilon.com/"}
  ```

### 3. Settings View Instance Synchronization
- **Symptom:** Logging in or toggling Musilon in Settings did not affect downloads.
- **Cause:** `SettingsView` was creating an isolated `MusilonEngine` instance rather than referencing the engine managed by `MainWindow`.
- **Fix:** Pass `musilon_engine=self.musilon_engine` from `MainWindow` into `SettingsView(musilon_engine=self.musilon_engine, parent=self)`.

### 4. Mutagen ID3 Delete Error on Fresh MP3s
- **Symptom:** `TypeError: Missing filename or fileobj argument` during tagging.
- **Cause:** Calling `audio.delete()` on an unattached `ID3()` instance.
- **Fix:** Call `audio.delete(file_path)` inside a protected `try/except` block.

### 5. Spotify Embed `releaseDate` Data Type
- **Symptom:** Embed scraper sometimes returned `releaseDate` as a dictionary: `{'isoString': '2025-02-05T00:00:00Z'}`.
- **Fix:** In `SpotifyClient._format_guest_track_entity()`, extract the string and format to `YYYY-MM-DD`.

### 6. ArvanCloud Challenge Bypass
- **Musilon Protection:** ArvanCloud JS challenge with `__arcsjs` cookies.
- **Fix:** `MusilonEngine._solve_arvancloud_challenge()` executes the challenge script in headless Node.js via `subprocess.run(['node', '-e', ...])` and injects resulting cookies into `requests.Session`.

### 8. `TrackCardDelegate` TableView Hover Hook Bug
- **Symptom:** Hovering over the TableView threw `AttributeError: 'TrackCardDelegate' object has no attribute 'setHoverRow'`.
- **Cause:** `qfluentwidgets.TableView._setHoverRow(row)` expects the delegate to implement `setHoverRow`, `setPressedRow`, and `setSelectedRows`.
- **Fix:** In `TrackCardDelegate`, implement:
  ```python
  def setHoverRow(self, row: int):
      self.hoverRow = row
      if self.parent() and hasattr(self.parent(), "viewport"):
          self.parent().viewport().update()
  ```
  along with `setPressedRow` and `setSelectedRows`.

### 10. WordPress OR Search Pollution & Cascading Search Strategy
- **Symptom:** Searching for multi-word artists (e.g. `The Black Eyed Peas Pump It`) returned completely unrelated songs because WordPress's search engine used broad OR-matching on words like "The", "Black", "Peas", and skipped the actual song.
- **Fix:** In `MusilonEngine.resolve_track()`, use a cascading multi-stage search strategy: (1) simplified artist + clean title, (2) title alone, (3) base title without features. Pool and score candidates across queries.

### 11. Unwanted Version / Instrumental Mismatch Filter
- **Symptom:** When downloading songs with multiple versions (e.g. `Bling-Bang-Bang-Born`), the instrumental or workout version was chosen because it appeared first in search results.
- **Fix:** Implement `_score_candidate()` with a -100 penalty for unwanted modifiers (`instrumental`, `karaoke`, `workout mix`, `remix`, `acoustic`, `cover`) when the original Spotify track does not contain that modifier.

### 12. Strict Quality Priority (FLAC -> 320k -> YouTube Fallback)
- **Symptom:** Musilon guest or preview tracks returned a 128 kbps stream preview URL, which the app downloaded instead of falling back to high-quality YouTube Music.
- **Fix:** In `MusilonEngine._extract_source()` and `CascadingAudioEngine.resolve_source()`, strictly reject 128 kbps preview streams. Only FLAC (16/24-bit) or MP3 320 kbps are accepted from Musilon; otherwise, seamlessly fall back to YouTube Music native Opus/AAC.

### 13. Automatic Standalone FFmpeg Integration
- **Symptom:** `ffmpeg executable not found in bundle or PATH` repeated on systems without global FFmpeg.
- **Fix:** Implemented `download_ffmpeg()` in `core/utils.py` to auto-fetch the standalone 64-bit Windows FFmpeg (~29MB gzip) directly into `bin/ffmpeg.exe`. Added one-click download card in `gui/views/settings_view.py`.

### 14. Smart Folder Organization (Playlists, Albums, Singles)
- **Requirement:** Playlist tracks save to `{output_dir}/{playlist_name}/`, album tracks to `{output_dir}/{album_name}/`, and individual songs to `{output_dir}/Singles/`.
- **Fix:**
  - `TrackMetadata` records `collection_type` (`"track"`, `"album"`, `"playlist"`) and `collection_name`.
  - Added `target_folder` property to `TrackMetadata` using `sanitize_filename()`.
  - Both `CascadingAudioEngine.download_and_tag()` and `DownloadQueueManager._process_item()` route downloads into `{base_output_dir}/{target_folder}/` without double-nesting.

### 15. Chunk-Level Pause / Resume Synchronization
- **Symptom:** Pausing the queue in the GUI only prevented new tracks from starting, while in-flight downloads continued consuming network bandwidth and writing bytes.
- **Fix:**
  - In `core/musilon.py`, passed a `pause_wait` callback inside the `resp.iter_content()` chunk streaming loop to block worker threads on `threading.Event.wait()` immediately without dropping TCP connections or corrupting partial files.
  - In `core/ytdlp_engine.py`, intercepted the yt-dlp `progress_hook` with `pause_wait()`.
  - In `gui/views/queue_view.py`, dynamically toggle between "Pause" (`FluentIcon.PAUSE`) and "Resume" (`FluentIcon.PLAY`), updating active card statuses to `Paused`.

### 16. Failed Songs Bulk Retry (High-Capacity Resilience)
- **Problem:** When downloading large 1,000–5,000 track libraries, transient Wi-Fi/network drops can cause dozens of songs to fail. Requiring the user to restart or reload the playlist was inefficient.
- **Fix:**
  - Added `DownloadQueueManager.retry_failed() -> int` and `retry_track(track_id) -> bool` to reset failed items to `Queued` and re-inject them into the worker queue without re-scraping Spotify.
  - Added dynamic "Retry Failed (X)" button in the queue control bar and a "Retry Download" option in the right-click context menu.

### 17. Persistent SQLite Music Archive & Local Deduplication (`archive.db`)
- **Problem:** If a song was already downloaded (e.g. in `Singles/` or another playlist), enqueuing it in a new playlist would waste bandwidth re-downloading it from Musilon or YouTube.
- **Fix:**
  - Implemented `core/archive.py` (`ArchiveManager`) using SQLite with composite indexes on `(artist, title)`, `isrc`, and `downloaded_at`.
  - Three-tier matching: matches by Spotify ID, ISRC, or normalized `(artist, title)` and verifies the audio file exists on disk.
  - If a track exists in another directory, the queue manager copies the audio file and `.lrc` locally in ~2ms into the new playlist subfolder, tags the card with `Local Archive`, and completes instantly with 0 internet usage.
  - `CompletedView` acts as an offline library with real-time search, track count stats, double-click playback (`os.startfile`), and Explorer integration. Pre-existing files in `downloads/` are automatically indexed in the background on startup.

---

## 4. Verification History

| Test Date | Track | Source Resolved | Result | Output Files |
|-----------|-------|-----------------|--------|--------------|
| 2026-09-08 | Coldplay — *Yellow* | Tier 4 (YTM Fallback) | ✅ Success (100%) | `downloads/Coldplay - Yellow.m4a`<br>`downloads/Coldplay - Yellow.lrc` |
| 2026-09-08 | Creepy Nuts — *Bling-Bang-Bang-Born* | Tier 1-3 (Musilon CDN) | ✅ Success (100%) | `downloads/Creepy Nuts - Bling-Bang-Bang-Born.mp3`<br>`downloads/Creepy Nuts - Bling-Bang-Bang-Born.lrc` |
| 2026-09-08 | The Black Eyed Peas — *Pump It* | Smart Candidate Scoring | ✅ Success (100%) | Score: +160 (exact) vs -78 (workout mix) |
| 2026-09-08 | Creepy Nuts — *Bling-Bang-Bang-Born* | Smart Candidate Scoring | ✅ Success (100%) | Score: +160 (vocal) vs +26 (instrumental rejected) |
| 2026-09-08 | Standalone FFmpeg Engine | `bin/ffmpeg.exe` | ✅ Success (100%) | Verified `ffmpeg version 6.1.1` |

## 5. Development Cheat Sheet

### Run the GUI Application:
```powershell
python main.py
```

### Run Headless CLI Download:
```powershell
python main.py --headless "https://open.spotify.com/track/<track_id>"
```

### Validate Core Modules Without GUI:
```powershell
python -c "from core.spotify_client import SpotifyClient; c = SpotifyClient(); print(c.resolve('https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg'))"
```

### Validate Tagging Pipeline:
```powershell
python -c "from core.tagger import AudioTagger; from core.spotify_client import TrackMetadata; t = TrackMetadata(id='1', title='Test', artists=['Artist'], album='Album', release_date='2024', duration_ms=1000); print(AudioTagger().tag_file('scratch/test_dl.m4a', t, None, True, False))"
```
