"""
Thread-safe WebSocket Event Hub replacing gui/bridge.py for v2.0.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger("backend.ws")


class EventHub:
    """
    Thread-safe WebSocket connection registry and event broadcaster.
    Allows core worker threads to safely emit real-time JSON events to all
    connected frontend clients.
    """

    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def set_loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        """Sets or clears the active asyncio event loop used for thread-safe broadcasts."""
        with self._lock:
            self._loop = loop

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts a WebSocket client and registers it for broadcasts."""
        await websocket.accept()
        with self._lock:
            self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Unregisters a WebSocket client."""
        with self._lock:
            self._clients.discard(websocket)

    async def send_json(
        self, websocket: WebSocket, event_type: str, payload: Dict[str, Any]
    ) -> None:
        """Sends a structured event envelope to a single WebSocket client."""
        envelope = {
            "type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        await websocket.send_json(envelope)

    async def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Broadcasts a structured event envelope to all connected clients."""
        with self._lock:
            clients = list(self._clients)

        if not clients:
            return

        envelope = {
            "type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        stale: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(envelope)
            except Exception:
                stale.append(ws)

        if stale:
            with self._lock:
                for ws in stale:
                    self._clients.discard(ws)

    def emit_threadsafe(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        Safely schedules an event broadcast from any background Python thread.
        """
        with self._lock:
            loop = self._loop

        if loop is None or loop.is_closed() or not loop.is_running():
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(event_type, payload), loop
            )
        except RuntimeError:
            pass
