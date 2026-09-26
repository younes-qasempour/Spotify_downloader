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
│   ├── archive.py           # SQLite music library archive, deduplication & auto-repair
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

### 18. High-Performance Cover Art Extraction & Virtualized Thumbnail Cache
- **Problem:** Downloaded tracks in the All Songs table lacked album artwork thumbnails because remote URLs were volatile and not indexed offline.
- **Fix:**
  - Implemented `extract_embedded_cover(file_path)` in `core/utils.py` supporting FLAC, MP3 (ID3 APIC), Opus/OGG (metadata_block_picture base64 decode), and M4A/MP4 (covr atom).
  - Built thread-safe `ThumbnailCache` with `ThumbnailSignalEmitter` for background extraction without UI lag.
  - Connected `sig_loaded` Qt signals to update TableView cells smoothly.

### 19. Clean Album vs. Playlist Separation
- **Problem:** Playlists and placeholder albums (like "Spotify Playlist") were polluting the Albums tab.
- **Fix:**
  - Filtered `ArchiveManager.get_albums()` to strictly require `collection_type = 'album'` or genuine album tags, rejecting placeholders.
  - Added dedicated empty states for unpopulated tabs.

### 20. In-App Playlist / Album Navigation & Cover Thumbnails
- **Problem:** Clicking playlist cards did not open their songs in the GUI, and playlist/album cards lacked thumbnail covers.
- **Fix:**
  - `TrackMetadata` now records `collection_cover_url` from Spotify embed/API.
  - In `core/queue_manager.py`, the playlist's cover art is downloaded and saved as `{folder}/cover.jpg`.
  - In `core/archive.py`, `resolve_collection_cover()` automatically locates `cover.jpg` or derives it from audio tracks.
  - `CollectionCard` displays a rounded 54×54 cover thumbnail and handles full-card mouse clicks (`mousePressEvent`) with pointing hand cursor.
  - Clicking any playlist or album card opens the collection view with a navigation banner (`[ ← Back to Playlists ]`, thumbnail, title, stats, and Explorer button), displaying only that collection's songs while strictly preserving individual song cover art.

### 21. Musilon VIP Expiration, Paywall Rejection & Auto-Reauth Retries
- **Symptom:** Downloads were completing with tiny ~207 KB files that could not play.
- **Cause:** When session cookies expired, Musilon returned an HTML warning webpage (`اخطار دانلود - موزیلون`) with HTTP 200 OK. The downloader streamed this HTML into audio files without inspecting `Content-Type` or magic bytes, skipping YouTube fallback and recording corrupt records in `archive.db`. Additionally, `test_connection()` evaluated `is_vip = True` purely if the cookie *name* existed in the jar.
- **Fix:**
  - Implemented `detect_audio_header()` and `is_valid_audio_file()` in `core/utils.py` checking magic bytes (`fLaC`, `ID3`, `OggS`, `ftyp`).
  - In `core/musilon.py`, `download_file()` rejects non-audio `Content-Type` and initial HTML bytes (`MusilonVipError`).
  - Added `ensure_vip_session(force=True)` and `download_track_with_retry()`: immediately re-authenticates VIP session with username/password, refreshes download nonce/URL, and retries up to 5-10 attempts before falling back to YouTube Music.
  - In `core/archive.py`, `find_track()` validates audio integrity and purges corrupt HTML files.

### 22. Pure Song Folders & Isolated Cache Storage
- **Problem:** Music folders were cluttered with `cover.jpg`, hidden `.cover_synced` marker files, and `.lrc` lyrics files.
- **Fix:**
  - Relocated collection covers to a dedicated app cache directory: `cache/covers/{folder_name}.jpg`.
  - Completely eliminated `.cover_synced` marker files.
  - In `core/config.py`, added `download.lyrics_mode` defaulting to `"embedded_only"`, embedding lyrics directly into audio tags so ZERO extra files exist in the song folder.
  - Added `purge_corrupt_and_cleanup_library()` in `core/archive.py` to purge corrupt files, relocate existing covers, and clean `.cover_synced` files.

### 23. Embedded Synchronized CRLF Lyrics for Windows Audio Players (Vorbis & ID3)
- **Symptom:** Embedded lyrics inside FLAC, Opus, and MP3 containers were displayed as a single run-on block or failed to scroll synchronously in desktop players (foobar2000, Windows Media Player, MusicBee, AIMP).
- **Cause:** LRCLIB provides Unix LF (`\n`) newlines. Windows audio parsers strictly expect Windows CRLF (`\r\n`) line endings. Furthermore, different players expect different tag keys: some read `LYRICS`, others read `UNSYNCEDLYRICS`, and MP3 engines require the `USLT` frame with CRLF.
- **Fix:**
  - Standardized lyrics string normalization in `core/lyrics.py` to ensure all synchronized and plain lyrics strictly use CRLF (`\r\n`).
  - In `core/tagger.py`, write both `LYRICS` and `UNSYNCEDLYRICS` Vorbis comments for FLAC/OggOpus, and properly formed `USLT` frame with language `'eng'` and descriptor `''` for MP3.
  - Verified across players that synchronized playback and timestamps function flawlessly.

### 24. Deep Scan Library Auto-Repair & Multi-Tier Cover Art Healing
- **Problem:** Files downloaded prior to CRLF normalization or during transient network drops lacked synchronized lyrics or high-resolution cover artwork.
- **Fix:**
  - Implemented `repair_library()` in `core/archive.py` with multi-tier cover art resolution cascade:
    1. Direct Spotify track artwork
    2. Spotify oEmbed 640×640 lookup
    3. Collection cover from app cache (`cache/covers/{collection}.jpg`)
    4. Existing embedded cover extraction
  - Deep scan queries LRCLIB for synchronized lyrics, updates tags with CRLF, and extracts/heals cover art in-place without re-downloading audio streams.
  - Added visual "Deep Scan & Repair" card with live progress bar and status log in `gui/views/settings_view.py`.

### 25. Cover / Collaborative Version False Positives & Station Duration Validation
- **Symptom:** Downloading Kavinsky's *Nightcall* fetched the 2024 Olympic remake sung by Angèle & Phoenix (2:59) instead of the original 2010 song (4:18).
- **Cause:**
  - `_score_candidate()` rewarded any candidate containing the artist name token without penalizing unrequested collaborator/cover artists, tying both at 140.0.
  - Musilon engine did not inspect candidate track duration against the Spotify metadata (`258,413` ms).
- **Fix:**
  - Added exact artist match bonus (+35.0) and unrequested collaborator penalty (-45.0) in `_score_candidate()`.
  - Added heavy cover/tribute penalty (-90.0).
  - Added station duration validation in `_extract_source()` against target duration with strict tolerance (>20s & >10% mismatch rejected).
  - Implemented configurable preferred quality (defaulting to 320 kbps MP3 with GUI toggle to Lossless FLAC).

### 26. Track False Positives & Mismatches in YtdlpEngine and MusilonEngine
- **Symptoms:**
  - Creepy Nuts – *Running Wheel* downloaded as Creepy Nuts – *Mirage* (YTM fallback).
  - Drowning Pool – *Bodies* downloaded as Offset – *Bodies* (album *KIARIOFFSET*, Musilon VIP).
- **Causes:**
  1. `YtdlpEngine.resolve_track()` scored candidates on duration proximity ($\le 3$s = 100) and artist name in title, but **never verified that the candidate title matched the track title**. A popular video by the same artist with similar duration (*Mirage*, 139s vs 137s) scored 126.2 and triggered early break.
  2. `MusilonEngine._score_candidate()` ignored the station host slug (`url_artist_slug`) and allowed sampling/featured artist credits to satisfy `art_match = True`. Offset's station `/station/offset/bodies-8/` scored 95.0 (> 70) despite being hosted by a foreign lead artist.
- **Fixes:**
  1. In `core/ytdlp_engine.py`: Added strict anti-false-positive title matching requiring variant or token overlap (0-overlap candidates disqualified with `continue`), channel/uploader artist validation, quoted and auto-generated search queries, expanded unwanted keywords, and safe early termination requiring confirmed title and artist match.
  2. In `core/musilon.py`: Added station host slug validation in `_score_candidate()`. If `url_artist_slug` belongs to a foreign artist not present in `target_artists`, the station is rejected with `-999.0`.
  3. Re-downloaded and repaired both audio files and their records in `archive.db`.

### 27. Karaoke / Fan Lyrics False Positive & Title Sub-Variant Query Decomposition (YtdlpEngine)
- **Symptom:** Creepy Nuts – *よふかしのうた - Yofukashino Uta* downloaded as a fan-made karaoke lyric video (`Creepy Nuts【よふかしのうた】＊カラオケ字幕＊歌詞動画＊日本語字幕＊`, ID `9OMJl4EJFsE`, uploaded by `あめり。`).
- **Causes:**
  1. `unwanted_keywords` lacked Japanese keywords (`カラオケ`, `ニコカラ`, `歌詞動画`, `字幕`, `練習用`, `インスト`, `オフボーカル`, `カバー`, etc.).
  2. The bilingual hyphenated title (`"よふかしのうた - Yofukashino Uta"`) was searched only as a full combined string in auto-generated/topic queries, which failed to match the official YouTube Music studio release titled `"Yofukashino Uta"` (`zArhnXbh3Yc`, Sony Music Labels).
  3. `YtdlpEngine` credited +20.0 artist points simply for having the artist name in the candidate title, even when uploaded by an unrelated third-party channel (`あめり。`), and allowed early termination on third-party uploads.
  4. Foreign Topic channels (such as `Yoshiaki Dewa - Topic`) were not disqualified when matching soundtrack titles.
- **Fixes:**
  1. Expanded `unwanted_keywords` with Japanese, Korean, and fan-upload terms.
  2. Decomposed bilingual/hyphenated titles into individual sub-variants for auto-generated, topic, and official audio search queries.
  3. Enforced strict artist channel validation: disqualified candidates lacking the artist in both title and channel; disqualified foreign artist Topic channels; boosted verified official/Topic channels (+35.0) while heavily penalizing third-party channels (-25.0).
  4. Restricted early search termination strictly to verified official/Topic channels with exact title match and duration proximity <= 3.0s.
  5. Updated `YtdlpEngine.download_track()` to verify timestamps of newly extracted audio and automatically scrub conflicting stale format files.
  6. Re-downloaded and tagged the authentic studio track (`zArhnXbh3Yc`, 240s, 3.91 MB) with synchronized lyrics and album art across library collections (`This Is Creepy Nuts`, `On Repeat`, `Mirage Radio`) and updated `archive.db`.

### 28. Album Track Numbering, Dual Naming Patterns & Collection Order Preservation
- **Symptom:** Album downloads lacked song numbers in their filenames (e.g. `Nirvana - Smells Like Teen Spirit.mp3`), causing Windows Explorer and media players to sort them alphabetically (e.g. `Breed` appearing before `Smells Like Teen Spirit`) rather than in album track order. Furthermore, local deduplication copying previously downloaded songs into an album folder retained unnumbered playlist tags without `TRACKNUMBER`.
- **Fix:**
  1. Implemented configurable `download.album_naming_template` (default: `"{track_num}. {artist} - {title}"`) alongside `download.naming_template` (`"{artist} - {title}"` for playlists and singles) in `core/config.py`, `config.json`, and Settings GUI.
  2. Updated `DownloadQueueManager` and `CascadingAudioEngine` to dynamically route album tracks with `track_number > 0` through the album naming template.
  3. Added automatic retagging when copying archived tracks into album folders so that deduplicated files receive genuine `TRACKNUMBER` tags, disc numbers, and album metadata.
  4. Updated `ArchiveManager.scan_local_directory()` and `repair_library()` to detect track numbers from leading digits in filenames (`01. ...`, `01 - ...`) if tags are stripped.
  5. Enhanced `TrackCardDelegate` to display track numbers (`01. Title`) on album track cards in the UI and updated `CompletedView` sort to account for `disc_number`.
### 29. YouTube High-Precision Matcher, Query Optimization & Fake Cover Disqualification
- **Symptom:** YouTube download was broken and returning mismatched songs:
  - Nirvana *Smells Like Teen Spirit* resolved to *(Butch Vig Mix)*.
  - Post Malone *Sunflower* resolved to a fake cover by `Jaco - Topic` (*Originally Performed by...*).
  - Tracks with subtitles or remasters (e.g. *Radio Edit*, *2020 Remaster*) caused the search engine to execute separate queries for the subtitle alone (e.g. `ytsearch10:Artist "Radio Edit" auto-generated`), matching completely different songs by the same artist and prematurely halting search due to a false-positive `score >= 90.0` early-break.
  - Search queries included `- "{qv}"` which YouTube interpreted as a negation operator (NOT title), actively suppressing the target song.
  - Excessive duration tolerance (22s) combined with weak partial-word title matching allowed wrong songs from the same album to match.
  - Temporary `.webm` files were checked before FFmpeg post-processing completed, causing post-processed `.opus` files to be missed or misdetected.
- **Fix:**
  1. **Structured Title Cleaning & Parsing (`_clean_title_for_search`):** Separates core song title from feature artists (`feat.`, `with`), remaster/anniversary dates, and movie/soundtrack tags. Tracks boolean flags (`is_remaster`, `is_live`, `is_acoustic`, `is_remix`, `is_instrumental`, `is_radio_edit`).
  2. **Targeted Search Queries:** Eliminated broken `- ""` negation and messy quote fragments. Produces 3–5 targeted queries per track (`auto-generated`, `Topic`, `official audio`, clean artist + core title) executed sequentially in a single `YoutubeDL` session.
  3. **Multi-Factor Anti-False-Positive Candidate Scoring (`_score_candidate`):**
     - Levenshtein SequenceMatcher ratio + word token overlap + exact match bonus.
     - Significant missing word penalty (-15.0 per missing word) and extraneous word penalty (-8.0 per extra word not in target or artist).
     - Disqualifies known cover/tribute/karaoke markers (`originally performed by`, `in the style of`, `as made famous by`, `tribute to`, `vocal version`, `piano version`, `instrumental version`, `karaoke`, `cover by`, etc.).
     - Foreign Topic Channel Disqualification: Strictly disqualifies any `* - Topic` channel unless it matches the target artist or is `Various Artists - Topic`.
     - Strict Version Matching: -35.0 penalty for unexpected mixes/remixes, -40.0 penalty for unexpected live recordings, -30.0 for unexpected acoustic tracks.
     - Official delivery bonus: +45.0 for artist Topic channels, +35.0 for official artist channels, +15.0 for description auto-generated markers.
     - Proximity scoring based on duration (diff <= 1.5s receives +32..35 points).
  4. **Strict Early-Stop Guard:** Requires `score >= 120.0`, `diff <= 2.5s`, Topic/official channel delivery, and `version_penalty == 0.0`.
  5. **Post-Processor Hooks in `download_track()`:** Added `ydl_pp_hook` on `postprocessor_hooks` to capture the final post-processed audio file path directly (`.opus` or `.m4a`), with fallback to valid candidate URLs.
  6. **Hardened `detect_audio_header()`:** Extended in `core/utils.py` to accept either raw bytes or file paths safely.

### 30. Saved Playlists & Decoupled On-Demand Batch Download System
- **Rationale & Problem:**
  - High-tier services (e.g. Musilon VIP) impose daily download limits (~100–200 tracks/day).
  - Users commonly import large Spotify playlists containing 500 to 5,000+ tracks.
  - Pushing 1,000+ tracks directly into the download queue exhausts daily quotas, forces unwanted low-bitrate fallbacks, and clutters the UI.
  - The user required a decoupled workflow: **first save the complete playlist metadata offline into a local database**, and then provide **on-demand batch audio downloading** with arbitrary batch sizes (e.g., 22, 33, 50, 100, 200).
- **Implementation:**
  1. **SQLite Storage Layer (`core/archive.py`):**
     - Tables: `saved_playlists` (id, name, spotify_url, cover_url, total_tracks, created_at, updated_at) and `saved_playlist_tracks` (id, playlist_id, spotify_id, title, artist, album, duration_ms, track_number, disc_number, isrc, cover_url, status, file_path, added_at).
     - Composite indexes on `(playlist_id, status)` and `spotify_id` for fast query performance across 10,000+ records.
     - Methods: `save_playlist()`, `get_saved_playlists()`, `get_saved_playlist()`, `get_saved_playlist_tracks()`, `delete_saved_playlist()`, `mark_saved_track_downloaded()`, `mark_saved_tracks_queued()`, `update_saved_track_status()`.
     - Made `_db_lock = threading.RLock()` to prevent reentrant deadlocks during nested query calls.
     - Made cover art caching fully asynchronous in a background daemon thread so saving is instantaneous.
  2. **Download Queue Synchronization (`core/queue_manager.py`):**
     - In `_process_item()`, upon track download completion, calls `self.archive.mark_saved_track_downloaded(track.id, file_path)`.
  3. **Dedicated Presentation View (`gui/views/playlists_view.py`):**
     - Level 0 (Playlists Overview): URL input card ("Save Playlist"), metric summary cards (Saved Playlists, Total Tracks, Downloaded, Pending), search bar, and sleek `SavedPlaylistCard`s with thumbnails, stats, and progress bars.
     - Level 1 (Playlist Detail View): Back button, playlist banner, batch download controls with `SpinBox` (arbitrary batch size 1–5000), quick presets (`[25]`, `[50]`, `[100]`, `[200]`, `[All Pending]`), "Download Next Batch", and "Download Selected".
     - TableView: Virtualized list showing track title, artist, duration, album art, and status badges (`Pending`, `Queued`, `Completed`).
     - Real-time Qt signal bridge integration to dynamically update progress bars and badges.
  4. **Sidebar Navigation Integration (`gui/main_window.py`):**
     - Registered `PlaylistsView` as a dedicated top-level sidebar view: `Playlists` (`FluentIcon.ALBUM`).

---

## 4. Verification History

| Test Date | Track | Source Resolved | Result | Output Files |
|-----------|-------|-----------------|--------|--------------|
| 2026-09-08 | Coldplay — *Yellow* | Tier 4 (YTM Fallback) | ✅ Success (100%) | `downloads/Coldplay - Yellow.m4a`<br>`downloads/Coldplay - Yellow.lrc` |
| 2026-09-08 | Creepy Nuts — *Bling-Bang-Bang-Born* | Tier 1-3 (Musilon CDN) | ✅ Success (100%) | `downloads/Creepy Nuts - Bling-Bang-Bang-Born.mp3`<br>`downloads/Creepy Nuts - Bling-Bang-Bang-Born.lrc` |
| 2026-09-08 | The Black Eyed Peas — *Pump It* | Smart Candidate Scoring | ✅ Success (100%) | Score: +160 (exact) vs -78 (workout mix) |
| 2026-09-08 | Creepy Nuts — *Bling-Bang-Bang-Born* | Smart Candidate Scoring | ✅ Success (100%) | Score: +160 (vocal) vs +26 (instrumental rejected) |
| 2026-09-08 | Standalone FFmpeg Engine | `bin/ffmpeg.exe` | ✅ Success (100%) | Verified `ffmpeg version 6.1.1` |
| 2026-09-10 | Synchronized CRLF Lyrics & Vorbis Tagging | LRCLIB + Mutagen FLAC/Opus | ✅ Success (100%) | Verified CRLF line breaks and multi-tag mapping across downloaded tracks |
| 2026-09-10 | Deep Scan Library Auto-Repair | `ArchiveManager.repair_library()` | ✅ Success (100%) | Healed plain tracks to synchronized lyrics and regenerated covers |
| 2026-09-13 | Kavinsky — *Nightcall* | Musilon 320k (Anti-Cover + Duration Filter) | ✅ Success (100%) | Resolved `nightcall-2` (4:18, 320kbps MP3) vs cover (2:59 rejected) |
| 2026-09-15 | Creepy Nuts — *よふかしのうた* | YTM Auto-Generated (Sony Music) | ✅ Success (100%) | `downloads/This Is Creepy Nuts/Creepy Nuts - よふかしのうた - Yofukashino Uta.m4a` (240s, Sony Music) |
| 2026-09-17 | Album Song Numbering & Ordering | Mutagen FLAC/MP3 + Dual Naming | ✅ Success (100%) | All 13 Nevermind and 15 LEGION tracks renamed `01..N`, tagged, and ordered |

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
python -c "from core.tagger import AudioTagger; from core.spotify_client import TrackMetadata; t = TrackMetadata(id='1', title='Test', artists=['Artist'], album='Album', release_date='2024', duration_ms=1000); print(AudioTagger())"
```

