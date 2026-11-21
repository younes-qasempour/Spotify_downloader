"""
FastAPI route modules for Flacify v2.0 backend.
"""

from backend.routes.library import router as library_router
from backend.routes.lyrics import router as lyrics_router
from backend.routes.media import router as media_router
from backend.routes.playlists import router as playlists_router
from backend.routes.queue import router as queue_router
from backend.routes.settings import router as settings_router
from backend.routes.tools import router as tools_router

__all__ = [
    "library_router",
    "lyrics_router",
    "media_router",
    "playlists_router",
    "queue_router",
    "settings_router",
    "tools_router",
]
