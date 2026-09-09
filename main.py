import os
import sys
import argparse
import logging
import traceback

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    if sys.stdout:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from core.utils import resource_path

# Global exception logger
def exception_hook(exctype, value, tb):
    print("\n[CRITICAL ERROR] Uncaught exception occurred:")
    traceback.print_exception(exctype, value, tb)
    try:
        with open("gui_startup_error.log", "w", encoding="utf-8") as f:
            traceback.print_exception(exctype, value, tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = exception_hook


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    )


def run_headless_cli(spotify_url: str, output_dir: str | None = None):
    """Headless CLI downloader demonstrating 100% decoupled core engine."""
    from core.config import config
    from core.spotify_client import SpotifyClient
    from core.resolver import CascadingAudioEngine
    from core.musilon import MusilonEngine
    from core.ytdlp_engine import YtdlpEngine
    from core.lyrics import LyricsEngine
    from core.tagger import AudioTagger

    if output_dir:
        config.set("download.output_dir", os.path.abspath(output_dir))

    dest_dir = config.get("download.output_dir")
    print(f"\n[CLI Mode] Resolving Spotify URL: {spotify_url}")
    print(f"[CLI Mode] Output Directory: {dest_dir}\n")

    sp = SpotifyClient(
        client_id=config.get("spotify.client_id", ""),
        client_secret=config.get("spotify.client_secret", "")
    )
    tracks = sp.resolve(spotify_url)
    print(f"Extracted {len(tracks)} track(s) from Spotify metadata.")

    musilon_eng = MusilonEngine(
        session_cookie=config.get("musilon.session_cookie", ""),
        username=config.get("musilon.username", ""),
        password=config.get("musilon.password", ""),
        enabled=config.get("musilon.enabled", True)
    )
    ytdlp_eng = YtdlpEngine(output_dir=dest_dir)
    lyrics_eng = LyricsEngine()
    tagger = AudioTagger()

    engine = CascadingAudioEngine(
        musilon_engine=musilon_eng,
        ytdlp_engine=ytdlp_eng,
        lyrics_engine=lyrics_eng,
        tagger=tagger
    )

    for idx, t in enumerate(tracks, 1):
        print(f"\n--- [{idx}/{len(tracks)}] {t.title} - {t.artist_str} ({t.duration_sec:.1f}s) ---")
        print("Resolving audio source (Tier 1-3 Musilon -> Tier 4 YTM)...")
        resolved = engine.resolve_source(t)
        if not resolved:
            print("❌ No matching source found.")
            continue

        print(f"✓ Source Resolved: {resolved.source_type} [{resolved.quality_badge}]")

        def prog_cb(pct, spd, eta):
            sys.stdout.write(f"\rDownloading: {pct:.1f}% | Speed: {spd} | ETA: {eta}  ")
            sys.stdout.flush()

        def status_cb(st):
            print(f"Status: {st}")

        try:
            saved_path = engine.download_and_tag(
                track=t,
                resolved=resolved,
                output_dir=dest_dir,
                progress_callback=prog_cb,
                status_callback=status_cb
            )
            print(f"\n✓ Completed: {saved_path}")
        except Exception as e:
            print(f"\n❌ Error: {e}")

    print("\n[CLI Mode] Finished processing all tracks.")


def run_gui():
    """Launches the Windows 11 Fluent Design Desktop Application."""
    print("==================================================", flush=True)
    print("  Spotify Downloader — High-Fidelity Desktop Suite", flush=True)
    print("==================================================", flush=True)
    print("Initializing Fluent UI application...", flush=True)

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    # Fix Windows taskbar icon grouping
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SpotifyDownloader.HighFidelity.1.0")
        except Exception:
            pass

    # High-DPI Scaling policy
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Spotify Downloader")
    app.setOrganizationName("HighFidelityAudio")

    from gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    print("✓ GUI window launched successfully.", flush=True)
    print("Close the desktop window or press Ctrl+C to terminate.\n", flush=True)

    sys.exit(app.exec())


def main():
    parser = argparse.ArgumentParser(description="High-Fidelity Windows Spotify Downloader")
    parser.add_argument("--headless", type=str, help="Run in headless CLI mode with a Spotify URL")
    parser.add_argument("--output", type=str, help="Override output directory")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.headless:
        run_headless_cli(args.headless, args.output)
    else:
        run_gui()


if __name__ == "__main__":
    main()
