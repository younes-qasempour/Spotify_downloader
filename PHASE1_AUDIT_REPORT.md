# Phase 1 Bug Fix Report

## Scope and outcome

Phase 1 implements bug remediation only. No Phase 2 product features have been implemented.
The final offline regression run passed **289 tests**, including **166 new audit tests**.
This is evidence for the tested paths, not a claim that every possible defect or live-service incompatibility has been eliminated.

## Codebase and data-flow map

- **Entry points:** `main.py` launches the PyQt6 desktop application by default; `--headless <URL>` uses the CLI pipeline.
- **Presentation:** `gui/main_window.py`, native views, models, and the Qt signal bridge handle desktop interaction. `gui/web_api.py` serves the embedded `gui/web_ui` application through a loopback HTTP server.
- **Metadata:** `core/spotify_client.py` parses Spotify links/URIs and obtains metadata through Spotipy/OAuth or public embed pages. `TrackMetadata` carries identity, collection, artwork, and duration information.
- **Scheduling:** `core/queue_manager.py` owns worker threads, pause/stop state, archive reuse, provider concurrency limits, and progress/completion callbacks.
- **Source selection:** `core/resolver.py` chooses Musilon, Telegram/MeloBot, or YouTube/YouTube Music according to configuration and fallback policy. Their provider adapters handle searches and transfers.
- **Audio pipeline:** provider transfer -> private staging directory -> container extraction/remux -> integrity check -> optional transcoding -> lyrics -> Mutagen metadata/artwork -> optional loudness normalization -> final validation -> publication -> archive completion.
- **Persistence/export:** `core/archive.py` stores downloaded tracks and saved playlists in SQLite; `core/exporter.py` handles device exports and M3U8 files. Configuration and writable-data locations are managed by `core/config.py` and `core/paths.py`.
- **Dependencies:** PyQt6/WebEngine/Fluent Widgets, Spotipy, yt-dlp, Mutagen, Requests, BeautifulSoup, Pillow, and Telethon are declared in `requirements.txt`. FFmpeg supplies media processing; SQLite is provided by Python. Musilon challenge execution can additionally invoke Node.js.
- **Distribution:** `app.spec`, `build_windows.py`, and `installer.iss` define the Windows packaging path. A fresh installer build was not performed during this audit.

Existing functionality already includes synced lyrics, M3U8 export, format selection, duplicate handling, saved playlists, and differential sync. These should not be presented as entirely new features in Phase 2.

## Production files modified: root causes and fixes

| File | Exact root cause | Remediation |
| --- | --- | --- |
| `core/spotify_client.py` | Substring URL matching accepted malformed links and invalid IDs; absent album artwork raised `IndexError`; absent/private guest entities could produce misleading results; multiline embed JSON failed extraction; API rate limits amplified into more requests; OAuth requests lacked explicit timeouts; sessions lacked an explicit close operation. | Validate complete hosts/paths and 22-character IDs, reject control characters, handle missing artwork/entities, parse multiline embeds, propagate rate limits without fallback amplification, bound OAuth requests, close responses, and expose deduplicated session cleanup. |
| `core/musilon.py` | Recursive challenge retries reset the retry budget; `429`/`503` handling ignored `Retry-After` and could lose the quota exception type; login sessions/cookies survived credential changes; error inspection buffered streamed bodies. | Use a bounded retry loop, respect bounded `Retry-After` values and preserve typed quota errors, close discarded responses and temporary sessions, clear stale cookies, and inspect only a bounded error-body prefix. |
| `core/lyrics.py` | Rate limits, server errors, and timeouts triggered additional search or translation requests; response lifetimes were implicit. | Stop a lookup after transient/rate-limit failures, retain untranslated text when appropriate, close responses, and preserve normal not-found/JSON fallback behavior. |
| `core/ytdlp_engine.py` | Prefix cleanup could delete neighboring files; failed attempts could reuse stale paths or accept nonzero results; literal percent signs were interpreted as templates; library-owned FFmpeg processing did not honor cancellation. | Isolate each attempt, validate successful output, publish only completed results, escape literal paths, make retries cancellable, disable library-owned extraction/fixups, and perform equivalent audio extraction through a bounded cancellable FFmpeg helper. |
| `core/transcoder.py` | Direct output writes and failure cleanup could destroy an existing destination; a missing FFmpeg binary could produce mislabeled copies; source deletion was not safely tied to publication. | Stage conversions/copies, preserve prior output on failure, reject unavailable conversion rather than mislabel audio, forward cancellation, and delete the source only after successful publication. |
| `core/tagger.py` | Missing imports broke tagging paths; MP3 tags were deleted before a successful replacement save; PNG covers used incorrect MIME/MP4 flags; artwork was insufficiently validated; hidden WebM remuxing could delete a source behind a boolean API. | Restore imports, remove destructive pre-deletion, validate/normalize artwork and use correct image flags, and require the resolver to remux before tagging. Unsupported WAV tagging fails without modification. |
| `core/utils.py` | FFmpeg work lacked a common cancellation/reaping path; normalization could replace audio before metadata restoration succeeded; failed measurements could be treated as usable; binary installation replaced files before validation; Windows device names/truncation and audio-header validation had edge cases. | Add bounded FFmpeg execution with pipe draining and process reaping, stage normalization plus metadata restoration, reject failed measurements, validate staged installation, harden filename sanitization, distinguish RIFF/WAVE, and reject unparseable containers. |
| `core/resolver.py` | Downloads and post-processing wrote directly into final library destinations; cancellation could leave companion files; tagging failure was ignored; remuxing was unbounded and conversion/normalization did not receive cancellation. | Stage the complete operation, clean failed/cancelled attempts, validate before publishing, avoid existing filename collisions, publish companion lyrics with the completed audio, propagate tagging failures, wire bounded cancellation-aware processing, and close providers explicitly. |
| `core/queue_manager.py` | Stop missed several active statuses; retry/start could reset an in-flight item's cancellation; paused item cancellation could strand a worker; duplicate queue entries could be reprocessed; fallback handlers used variables initialized too late; missing output could be marked completed; archive reuse overwrote final files directly. | Track active IDs, preserve cancellation until worker exit, poll pause waits, reject stale entries, initialize fallback callbacks/options before resolution, convert uncaught processing errors to failed states, require actual output, stage archive copies, coordinate publication, and join workers before closing providers. |
| `core/melobot.py` | The background event loop/session had no shutdown method; a timed-out coroutine was cancelled without waiting for its file cleanup; a synchronous pause callback blocked the Telegram event loop; failure cleanup could remove a prior destination. | Disconnect without logging out, cancel/drain and close the loop, wait for timeout cleanup, poll caller cancellation, await pause work off the event loop, and atomically replace only successful transfers. |
| `core/archive.py` | A single failed validation or temporarily missing path caused lookup/cleanup to delete user audio or archive records. | Preserve files and records after validation/unavailability failures; only adopt a replacement path after successful validation. Explicit user deletion and duplicate merging were not redesigned. |
| `core/config.py` | Any read error could be treated as corruption and overwrite settings/credentials; failed backups/saves were swallowed; listeners could report a change that was not persisted. | Recover malformed JSON only after a durable unique backup, preserve unreadable data, block saving after unsafe load, propagate persistence errors, and roll back failed `set()` changes without success notification. |
| `core/paths.py` | Copying a SQLite database directly omitted committed data still present in WAL; migration could overwrite a concurrently initialized destination. | Use SQLite backup into staging and publish without overwriting another instance's database. |
| `core/exporter.py` | Equal basenames or format convergence collided; size-only checks accepted partial exports; direct writes damaged existing output; source/destination aliases were unsafe. | Disambiguate batch destinations, verify byte-identical copy reuse, protect source aliases, stage copies/transcodes with the requested basename, publish atomically, and forward cancellation. |
| `gui/web_api.py` | Prefix-based CORS checks trusted attacker suffix domains; dispatch did not validate request origin/Host; static-path prefix checks allowed sibling-directory traversal; the audio route served non-audio files. | Validate exact loopback authorities/listening ports and security headers before dispatch, reject foreign browser requests, enforce resolved static containment, and restrict audio-serving extensions. |
| `gui/main_window.py` | Closing the window stopped the queue but did not wait for provider cleanup. | Begin orderly queue/provider shutdown outside the GUI event loop. |
| `main.py` | GUI/CLI exit did not guarantee provider shutdown; CLI source-resolution errors escaped the per-track handler and a missing result could be printed as completed. | Close metadata/provider sessions in cleanup paths, wait for orderly GUI shutdown after the event loop exits, handle per-track resolution failures, and reject absent output. |
| `app.spec` | Copying entire source directories as data could bundle stray caches or private files alongside compiled modules. | Remove broad source-directory data inclusion while explicitly retaining the embedded web application's assets. |
| `.gitignore` | Telegram session journals were not explicitly ignored. | Add `*.session-journal`. |

## Test and report files modified or added

| File | Purpose |
| --- | --- |
| `tests/test_audit_network.py` | 39 offline regressions covering URL/entity parsing, rate limits, retry bounds, timeouts, and response cleanup. |
| `tests/test_audit_audio.py` | 55 regressions covering downloads, FFmpeg extraction/cancellation/reaping, atomic conversion/normalization, tagging, image handling, and filesystem validation; includes generated audio and real local FFmpeg checks. |
| `tests/test_audit_pipeline.py` | 16 regressions covering queue races, pause/stop/retry, missing output, fallback errors, archive-copy preservation, staging cleanup, cancellation propagation, and Spotify/Telegram lifecycle cleanup. |
| `tests/test_audit_storage.py` | 39 isolated regressions covering configuration failures, non-destructive archive handling, WAL migration, export collisions/atomicity, and packaging exclusions. |
| `tests/test_audit_web_security.py` | 17 regressions covering untrusted origins/hosts, security headers, static traversal, and non-audio file access. |
| `tests/test_exporter.py` | Update the transcode test double for the optional cancellation argument; retain existing assertions, including the output basename contract. |
| `tests/test_melobot.py` | Keep the unauthorized-client test offline with an explicit async boundary mock and close the engine after the test. |
| `scripts/run_tests.py` | Run all tests with disposable application-data paths, offscreen Qt, blocked external connections, and cleanup of created Telegram engines. |
| `PHASE1_AUDIT_REPORT.md` | Record the codebase map, complete changed-file inventory, root causes, fixes, validation, and remaining boundaries. |

## Verification

- Reproduction tests were run before the corresponding production fixes. They demonstrated malformed URL acceptance, retry amplification, destructive writes/deletions, cancellation leaks, false completion, and loopback request/path vulnerabilities.
- Final full-suite command: `python -B scripts\run_tests.py`.
- Final result: **289 tests passed in 16.803 seconds**, exit code **0**, on **Python 3.14.6**.
- The suite includes offscreen desktop component/navigation tests, generated local audio, real FFmpeg processing and process-reaping checks, and a local-file yt-dlp integration check.
- The combined run initially exposed an outdated export mock signature and sandbox folder naming; those were corrected without removing assertions. A subsequent export basename assertion was resolved by retaining the basename inside a private staging directory.
- `git diff --check` passed; Git emitted line-ending conversion notices only.
- No live Spotify/Musilon/Telegram/YouTube downloads or fresh Windows installer build were performed. Real credentials and real library audio are not needed by the isolated suite.

## Remaining boundaries and risks

- Cancellation cleans up ordinary failures and cooperative stops. In-flight library/network calls may take their configured timeout to return; power loss or forced process termination can still leave hidden staging directories. Startup recovery requires a separate design.
- Current integrity checks are not exhaustive full-file decoding. WebM header-only detection is retained for compatibility. Unsupported WAV metadata tagging remains unsupported.
- Direct metadata editing of existing library files remains in-place. Explicit deletion and duplicate merging remain user-authorized operations and were not converted into a transactional/undo system.
- Musilon's existing remote JavaScript challenge execution through Node.js still warrants an isolation/security review. Shared Telegram application credentials remain in source; private user sessions/tokens were not found tracked by the filename-based Git check. Those design choices were not silently replaced in this compatibility-focused pass.
- The loopback audio endpoint now rejects non-audio extensions, but is not a library-directory sandbox or authorization boundary against other local processes.
- Configuration persistence errors now propagate rather than report success. Inline, user-friendly recovery guidance in every settings UI remains a polish opportunity.
- Export collision disambiguation is per batch; converted exports are conservatively rebuilt rather than trusted by file size. Persistent cross-batch ownership/provenance is not implemented.
- Packaging data selection is covered by tests, but a fresh packaged startup/installer validation is still needed. The pre-existing hard-coded installer output-name/fallback selection in `build_windows.py` was not changed and should be reviewed before release.

Phase 2 is proposal-only until the user selects and approves improvements.