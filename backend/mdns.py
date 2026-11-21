"""
LAN IP detection, pairing token management, and mDNS service announcement (`_flacify._tcp.local.`).
"""

import logging
import re
import secrets
import socket
import threading
from typing import Any, List, Optional

logger = logging.getLogger("backend.mdns")

_SERVICE_TYPE = "_flacify._tcp.local."
_LOOPBACK_HOSTS = frozenset(
    {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", "testclient"}
)


def is_loopback_host(host: Optional[str]) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def detect_reachable_lan_ips() -> List[str]:
    """
    Returns non-loopback, non-link-local IPv4 addresses reachable on LAN or VPN (e.g. Tailscale),
    ordered with the primary outbound interface IP first.
    """
    ordered: List[str] = []

    def _add(ip: str) -> None:
        clean = (ip or "").strip()
        if not clean or clean in ordered:
            return
        if clean.startswith("127.") or clean.startswith("169.254.") or clean == "0.0.0.0":
            return
        ordered.append(clean)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            _add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            _add(info[4][0])
    except OSError:
        pass

    return ordered


def get_device_name(cfg: Any) -> str:
    """Returns configured mobile display name or the OS hostname fallback."""
    configured = str(cfg.get("mobile.device_name", "") or "").strip()
    if configured:
        return configured
    try:
        return socket.gethostname() or "Flacify PC"
    except OSError:
        return "Flacify PC"


def get_or_create_pair_token(cfg: Any) -> str:
    """Reads `mobile.pair_token` or generates and persists a cryptographically random token."""
    existing = str(cfg.get("mobile.pair_token", "") or "").strip()
    if existing:
        return existing

    token = secrets.token_urlsafe(24)
    try:
        cfg.set("mobile.pair_token", token)
        if hasattr(cfg, "save") and callable(cfg.save):
            cfg.save()
    except Exception as exc:
        logger.debug(f"Could not persist generated mobile pair token: {exc}")
    return token


class FlacifyMdnsBroadcaster:
    """Broadcasts `_flacify._tcp.local.` over LAN mDNS/Zeroconf so Android finds the PC automatically."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._zeroconf: Optional[Any] = None
        self._info: Optional[Any] = None
        self._generation: int = 0

    @staticmethod
    def _build_dns_host_label(device_name: str) -> str:
        raw = re.sub(r"[^a-z0-9-]+", "-", (device_name or "").lower()).strip("-")
        return raw[:40].strip("-") or "flacify"

    def next_generation(self) -> int:
        """Advances and returns the monotonic broadcaster generation counter."""
        with self._lock:
            self._generation += 1
            return self._generation

    @staticmethod
    def _close_zeroconf(zc: Optional[Any], info: Optional[Any]) -> None:
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
        except Exception:
            pass
        try:
            zc.close()
        except Exception:
            pass

    def _stop_locked(self, *, bump_generation: bool = True) -> tuple[Optional[Any], Optional[Any]]:
        if bump_generation:
            self._generation += 1
        zc = self._zeroconf
        info = self._info
        self._zeroconf = None
        self._info = None
        return zc, info

    def start(
        self,
        port: int,
        device_name: str,
        version: str,
        *,
        generation: Optional[int] = None,
    ) -> bool:
        """Registers the Flacify service over Zeroconf; non-fatal if unavailable."""
        with self._lock:
            if generation is not None:
                if generation != self._generation:
                    return False
                target_gen = generation
            else:
                self._generation += 1
                target_gen = self._generation
            old_zc, old_info = self._stop_locked(bump_generation=False)

        self._close_zeroconf(old_zc, old_info)

        zc: Optional[Any] = None
        info: Optional[Any] = None
        try:
            from zeroconf import ServiceInfo, Zeroconf

            ips = detect_reachable_lan_ips()
            if not ips:
                return False

            packed_addrs = [socket.inet_aton(ip) for ip in ips]
            safe_instance = "".join(
                ch if (ch.isalnum() or ch in (" ", "-", "_")) else "-"
                for ch in (device_name or "Flacify PC")
            ).strip() or "Flacify PC"
            service_name = f"Flacify ({safe_instance[:40]}).{_SERVICE_TYPE}"
            host_label = self._build_dns_host_label(device_name)

            info = ServiceInfo(
                type_=_SERVICE_TYPE,
                name=service_name,
                addresses=packed_addrs,
                port=int(port),
                properties={
                    b"version": str(version).encode("utf-8"),
                    b"api": b"2.1",
                    b"name": str(device_name or "Flacify PC").encode("utf-8"),
                    b"pair": b"1",
                },
                server=f"{host_label}.local.",
            )
            zc = Zeroconf()
            zc.register_service(info, allow_name_change=True)

            with self._lock:
                if target_gen != self._generation:
                    stale = True
                else:
                    self._zeroconf = zc
                    self._info = info
                    stale = False

            if stale:
                self._close_zeroconf(zc, info)
                return False

            logger.info(
                f"mDNS advertising {service_name} on {ips[0]}:{port}"
            )
            return True
        except Exception as exc:
            logger.debug(f"mDNS broadcaster disabled/unavailable: {exc}")
            self._close_zeroconf(zc, None)
            self.stop()
            return False

    def stop(self) -> None:
        """Unregisters and shuts down Zeroconf cleanly."""
        with self._lock:
            zc, info = self._stop_locked(bump_generation=True)
        self._close_zeroconf(zc, info)
