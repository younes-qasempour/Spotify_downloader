"""
CLI entry point for launching the Flacify v2.0 backend & Production Web server.
"""

import argparse
import os
import socket
import threading
import time
import webbrowser

import uvicorn

from backend.app import create_app, resolve_frontend_dist


def _detect_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return ""


def _schedule_browser_open(url: str, delay_sec: float = 1.0) -> None:
    def _worker() -> None:
        time.sleep(delay_sec)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Flacify v2.0 FastAPI backend & Web UI server"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host interface to bind (defaults to FLACIFY_HOST, else 0.0.0.0 when mobile.lan_enabled is true)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FLACIFY_PORT", "8765")),
        help="Port to listen on (default: 8765 or FLACIFY_PORT)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable Uvicorn auto-reload for development",
    )
    parser.add_argument(
        "--no-startup-scan",
        action="store_true",
        help="Skip background startup directory indexing",
    )
    parser.add_argument(
        "--frontend-dist",
        default=os.getenv("FLACIFY_FRONTEND_DIST"),
        help="Path to built frontend dist/ folder to serve as SPA",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the Web UI in your default browser on startup",
    )
    args = parser.parse_args()

    os.environ["FLACIFY_PORT"] = str(args.port)
    bind_host = args.host or os.getenv("FLACIFY_HOST", "").strip()
    if not bind_host:
        try:
            from core.config import config as _core_cfg

            bind_host = (
                "0.0.0.0"
                if bool(_core_cfg.get("mobile.lan_enabled", True))
                else "127.0.0.1"
            )
        except Exception:
            bind_host = "127.0.0.1"

    os.environ["FLACIFY_BIND_HOST"] = bind_host

    if args.frontend_dist:
        os.environ["FLACIFY_FRONTEND_DIST"] = args.frontend_dist

    dist_dir = resolve_frontend_dist(args.frontend_dist)
    browse_host = "127.0.0.1" if bind_host in ("0.0.0.0", "::", "") else bind_host
    local_url = f"http://{browse_host}:{args.port}"

    print(f"Flacify v2.0 Server starting on {local_url}")
    if bind_host == "0.0.0.0":
        lan_ip = _detect_lan_ip()
        if lan_ip:
            print(f"  LAN access: http://{lan_ip}:{args.port}")
    if dist_dir is not None:
        print(f"  Web UI enabled: serving built SPA from {dist_dir}")
    else:
        print("  API-only mode: build frontend/dist to enable Web UI at /")

    if args.open:
        _schedule_browser_open(local_url)

    if args.reload:
        uvicorn.run(
            "backend.app:create_app",
            host=bind_host,
            port=args.port,
            reload=True,
            factory=True,
        )
    else:
        app = create_app(
            run_startup_scan=not args.no_startup_scan,
            run_mdns=True,
            frontend_dist_dir=args.frontend_dist,
        )
        uvicorn.run(app, host=bind_host, port=args.port)


if __name__ == "__main__":
    main()
