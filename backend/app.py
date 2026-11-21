"""
FastAPI application factory with health check, CORS, and WebSocket event stream.
"""

import asyncio
from contextlib import asynccontextmanager
import hmac
import mimetypes
import os
from pathlib import Path
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.mdns import get_device_name, get_or_create_pair_token
from backend.routes.library import router as library_router
from backend.routes.lyrics import router as lyrics_router
from backend.routes.media import router as media_router
from backend.routes.playlists import router as playlists_router
from backend.routes.queue import router as queue_router
from backend.routes.settings import router as settings_router
from backend.routes.sync import is_loopback_host, router as sync_router
from backend.routes.tools import router as tools_router
from backend.state import BackendState
from core import __version__

mimetypes.add_type("application/manifest+json", ".webmanifest")

_RESERVED_PREFIXES = ("api", "ws")
_DOCS_PATHS = {"docs", "redoc", "openapi.json"}


def resolve_frontend_dist(explicit: Optional[str] = None) -> Optional[Path]:
    """Resolves the built React frontend dist directory when present."""
    if explicit is not None and explicit.strip():
        candidate = Path(explicit.strip()).resolve()
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
        return None

    env_dist = os.getenv("FLACIFY_FRONTEND_DIST", "").strip()
    if env_dist:
        candidate = Path(env_dist).resolve()
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
        return None

    candidates = [
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, Path(meipass) / "frontend" / "dist")

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and (resolved / "index.html").is_file():
            return resolved
    return None


def create_app(
    state: Optional[BackendState] = None,
    *,
    run_startup_scan: bool = True,
    run_auto_sync_scheduler: bool = True,
    frontend_dist_dir: Optional[str] = None,
) -> FastAPI:
    """Creates and configures the Flacify v2.0 FastAPI application."""
    dist_dir = resolve_frontend_dist(frontend_dist_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        backend = state or BackendState(
            run_startup_scan=run_startup_scan,
            run_auto_sync_scheduler=run_auto_sync_scheduler,
        )
        app.state.backend = backend
        backend.start(asyncio.get_running_loop())
        try:
            yield
        finally:
            backend.shutdown()

    app = FastAPI(
        title="Flacify Backend API",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def mobile_pair_token_middleware(request: Request, call_next):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or not path.startswith("/api/")
            or path == "/api/health"
        ):
            return await call_next(request)

        client_host = request.client.host if request.client else ""
        if is_loopback_host(client_host):
            return await call_next(request)

        backend: Optional[BackendState] = getattr(request.app.state, "backend", None)
        if backend is None:
            return JSONResponse(status_code=503, content={"detail": "Backend initializing."})

        if not bool(backend.config.get("mobile.lan_enabled", True)):
            return JSONResponse(
                status_code=403,
                content={"detail": "LAN / mobile access is disabled on this Flacify PC."},
            )

        expected = get_or_create_pair_token(backend.config)
        auth_hdr = request.headers.get("authorization") or ""
        bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
        supplied = (
            bearer
            or (request.headers.get("x-flacify-token") or "").strip()
            or (request.query_params.get("token") or "").strip()
        )
        if not supplied or not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Flacify pairing token."},
            )

        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^(https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|"
            r"10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|"
            r"100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)(:\d+)?|"
            r"tauri://localhost|https?://tauri\.localhost)$"
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(queue_router)
    app.include_router(playlists_router)
    app.include_router(library_router)
    app.include_router(media_router)
    app.include_router(lyrics_router)
    app.include_router(settings_router)
    app.include_router(tools_router)
    app.include_router(sync_router)

    @app.get("/api/health")
    async def health():
        backend: BackendState = app.state.backend
        return {
            "status": "ok",
            "version": __version__,
            "api_version": "2.0",
            "device_name": get_device_name(backend.config),
            "lan_enabled": bool(backend.config.get("mobile.lan_enabled", True)),
            "pair_required": True,
            "queue_paused": backend.queue_manager.is_paused(),
            "queue_count": len(backend.queue_manager.get_items()),
            "ws_clients": backend.events.client_count,
            "pending_prompts": len(backend.get_pending_musilon_prompts()),
            "web_ui_enabled": dist_dir is not None,
        }

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket):
        backend: BackendState = app.state.backend
        client_host = websocket.client.host if websocket.client else ""
        if not is_loopback_host(client_host):
            if not bool(backend.config.get("mobile.lan_enabled", True)):
                await websocket.close(code=4403)
                return
            expected = get_or_create_pair_token(backend.config)
            auth_hdr = websocket.headers.get("authorization") or ""
            bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
            supplied = (
                bearer
                or (websocket.headers.get("x-flacify-token") or "").strip()
                or (websocket.query_params.get("token") or "").strip()
            )
            if not supplied or not hmac.compare_digest(supplied, expected):
                await websocket.close(code=4401)
                return

        await backend.events.connect(websocket)
        try:
            await backend.events.send_json(
                websocket,
                "connected",
                {
                    "version": __version__,
                    "api_version": "2.0",
                    "queue_paused": backend.queue_manager.is_paused(),
                    "pending_prompts": backend.get_pending_musilon_prompts(),
                },
            )
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    continue
                msg_type = data.get("type")
                if msg_type == "ping":
                    await backend.events.send_json(websocket, "pong", {})
                elif msg_type == "musilon_decision":
                    prompt_id = str(data.get("prompt_id", ""))
                    action = str(data.get("action", ""))
                    resolved = backend.resolve_musilon_prompt(prompt_id, action)
                    await backend.events.send_json(
                        websocket,
                        "ack",
                        {"resolved": resolved, "prompt_id": prompt_id},
                    )
        except WebSocketDisconnect:
            pass
        finally:
            backend.events.disconnect(websocket)

    if dist_dir is not None:
        dist_real = os.path.realpath(str(dist_dir))
        index_file = os.path.join(dist_real, "index.html")

        def _serve_spa_response(full_path: str) -> FileResponse:
            normalized = full_path.replace("\\", "/").lstrip("/")
            first_seg = normalized.split("/", 1)[0] if normalized else ""
            if first_seg in _RESERVED_PREFIXES or normalized in _DOCS_PATHS:
                raise HTTPException(status_code=404, detail="Not Found")

            if normalized:
                candidate = os.path.realpath(os.path.join(dist_real, normalized))
                try:
                    in_root = os.path.commonpath([dist_real, candidate]) == dist_real
                except ValueError:
                    in_root = False
                if not in_root:
                    raise HTTPException(status_code=404, detail="Not Found")

                if os.path.isfile(candidate):
                    cache_ctrl = (
                        "public, max-age=31536000, immutable"
                        if normalized.startswith("assets/")
                        else "public, max-age=3600"
                    )
                    return FileResponse(
                        candidate,
                        headers={"Cache-Control": cache_ctrl},
                    )

                if normalized.startswith("assets/"):
                    raise HTTPException(status_code=404, detail="Asset not found")

            return FileResponse(
                index_file,
                headers={"Cache-Control": "no-cache"},
            )

        @app.get("/", include_in_schema=False)
        async def spa_index():
            return _serve_spa_response("")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            return _serve_spa_response(full_path)

    return app
