# Flacify Android Companion (`v2.2.0`)

Native Kotlin + Jetpack Compose companion app (`com.flacify.android`, `versionCode = 3`, `versionName = "2.2.0"`) for pairing with Flacify Desktop over high-speed USB Cable (`adb reverse`) or Wi-Fi/LAN, syncing lossless `.flac` playlists offline, playing synced audio via Media3, and sharing Spotify URLs directly to your PC download queue.

## Features

- **QR Code, mDNS & Emulator Pairing (`SyncScreen`):**
  - Scan the pairing QR code shown in Flacify Desktop **Settings → Mobile Sync** via CameraX + ZXing (`QrScannerDialog`).
  - Auto-discover PCs broadcasting `_flacify._tcp.local.` over local Wi-Fi using Android `NsdManager` (`MdnsDiscoveryManager`).
  - One-tap Android Emulator bridge preset (`http://10.0.2.2:8765`) or manual host + pairing token setup persisted in Jetpack DataStore (`ConnectionSettingsStore`).
- **Offline-First Lossless Sync (`sync/` + `data/`):**
  - Downloads `/api/sync/manifest` into local Room SQLite (`FlacifyDatabase` v2 with `MIGRATION_1_2`).
  - Streams original bit-perfect audio files (`/api/sync/tracks/{trackId}/file`), album artwork, and synced lyrics via WorkManager (`FlacifySyncWorker`) and `ResumableFileDownloader` supporting `ETag` and HTTP `Range` / `If-Range` resume.
- **Playlists, Searchable Library & Offline Player (`ui/` + `player/`):**
  - Offline playlist toggles (`Keep Offline`) on **Playlists** (`PlaylistsScreen` / `PlaylistDetailScreen`).
  - Filterable offline catalog on **Library** (`LibraryScreen` + `LibraryFilterEngine`).
  - Lossless background playback via Media3 ExoPlayer & `MediaSessionService` (`FlacifyPlaybackService`, `FlacifyPlayerController`) with persistent `MiniPlayerBar`, expandable `NowPlayingSheet`, queue navigation, and interactive tap-to-seek synced lyrics (`FlacLyricsExtractor`, `LrcParser`).
- **Share Sheet to PC (`share/`):**
  - Registers Android `ACTION_SEND` (`Send to Flacify PC` via `ShareReceiverActivity`) to forward Spotify track, album, playlist, or `spotify.link` links to `POST /api/sync/share`.
  - Automatically queues failed shares in Room and flushes via WorkManager (`PendingShareWorker`) once your PC is reachable again.

## Tech Stack

- **SDK & Build:** `compileSdk = 36`, `targetSdk = 35`, `minSdk = 26`, AGP `9.0.1`, Kotlin `2.2.10`, KSP `2.2.10-2.0.2`
- **UI:** Jetpack Compose (BOM `2025.05.00`), Material 3, Navigation Compose `2.9.0`, Coil `2.7.0`
- **Persistence & Sync:** Room `2.7.2`, WorkManager `2.10.1`, DataStore Preferences `1.1.7`, OkHttp `4.12.0`, `kotlinx-serialization-json` `1.8.1`
- **Playback & QR:** AndroidX Media3 (`ExoPlayer` / `MediaSession` `1.6.1`), CameraX `1.4.2`, ZXing Core `3.5.3`

## Package Structure

```text
android/app/src/
├── main/java/com/flacify/android/
│   ├── FlacifyApplication.kt          # App container (DB, stores, sync/share managers)
│   ├── MainActivity.kt                # Single-activity Compose host
│   ├── data/                          # Room entities/DAO/DB, ConnectionSettingsStore, LocalMediaStorage, Repository
│   ├── network/                       # FlacifyApiClient, ApiModels, MdnsDiscoveryManager, PairingUriParser
│   ├── player/                        # FlacifyPlaybackService, FlacifyPlayerController, FlacLyricsExtractor, LrcParser
│   ├── share/                         # ShareReceiverActivity, ShareToPcManager, PendingShareWorker, ShareUrlExtractor
│   ├── sync/                          # FlacifySyncManager, FlacifySyncWorker, ResumableFileDownloader, SyncPlanner
│   └── ui/                            # FlacifyApp, SyncScreen, PlaylistsScreen, LibraryScreen, MiniPlayerBar, NowPlayingSheet
└── test/java/com/flacify/android/     # 9 JUnit test suites (25 unit tests)
```

## Building, Testing & Installing

Requires **JDK 17 or 21** (e.g., Android Studio JBR) and Android SDK platform `36`.

```powershell
cd android
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"

# Run all 25 unit tests and Android Lint
.\gradlew.bat testDebugUnitTest lintDebug

# Build the debug APK (`app/build/outputs/apk/debug/app-debug.apk`)
.\gradlew.bat assembleDebug

# Install or update on a connected phone or booted Android Emulator
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r ".\app\build\outputs\apk\debug\app-debug.apk"
```
