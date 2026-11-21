"""
Settings, Credentials & Engine Auth REST endpoints (/api/settings/*).
"""

import asyncio
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend.mdns import is_loopback_host
from backend.serializers import mask_config_value
from backend.state import BackendState
from core import utils as core_utils

logger = logging.getLogger("backend.routes.settings")

router = APIRouter(prefix="/api/settings", tags=["settings"])

SPOTIFY_REDIRECT_URI = "http://127.0.0.1:9900/callback"

_ALLOWED_EXACT_KEYS = {"source_engine"}
_ALLOWED_KEY_PREFIXES = (
    "musilon.",
    "telegram.",
    "spotify.",
    "download.",
    "ui.",
    "playlists.",
    "export.",
    "export_m3u.",
)
_MUTABLE_MOBILE_KEYS = frozenset({"mobile.lan_enabled", "mobile.device_name"})
_QUALITY_PRIORITY_320 = [
    "musilon_mp3_320",
    "musilon_flac_16",
    "musilon_flac_24",
    "ytm_opus",
]
_QUALITY_PRIORITY_FLAC = [
    "musilon_flac_16",
    "musilon_flac_24",
    "musilon_mp3_320",
    "ytm_opus",
]
_VALID_TARGET_FORMATS = {"original", "alac", "mp3", "flac", "opus"}
_VALID_LYRICS_MODES = {"embedded_only", "separate_folder", "same_folder"}


class SettingsUpdateRequest(BaseModel):
    values: Dict[str, Any]


class MusilonLoginRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    run_test: bool = True


class TelegramSendCodeRequest(BaseModel):
    phone: str


class TelegramVerifyRequest(BaseModel):
    code: str
    phone: Optional[str] = None
    password: Optional[str] = None
    phone_code_hash: Optional[str] = None


class SpotifyCredentialsRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class SpotifyAuthCallbackRequest(BaseModel):
    code_or_url: str


class OpenFolderRequest(BaseModel):
    path: Optional[str] = None
    reveal: bool = False


def _get_backend(request: Request) -> BackendState:
    return request.app.state.backend


def _save_config(cfg: Any) -> None:
    if hasattr(cfg, "save") and callable(cfg.save):
        cfg.save()


def _is_allowed_config_key(key: str) -> bool:
    if not isinstance(key, str) or not key or ".." in key or key.endswith("."):
        return False
    if key in _ALLOWED_EXACT_KEYS or key in _MUTABLE_MOBILE_KEYS:
        return True
    return any(key.startswith(prefix) and len(key) > len(prefix) for prefix in _ALLOWED_KEY_PREFIXES)


def _effective_source_engine(cfg: Any) -> str:
    engine_name = str(cfg.get("source_engine", "musilon") or "musilon").strip().lower()
    if engine_name == "melobot" or (
        bool(cfg.get("telegram.enabled", False))
        and not bool(cfg.get("musilon.enabled", True))
    ):
        return "melobot"
    return "musilon"


def _build_settings_response(backend: BackendState) -> Dict[str, Any]:
    cfg = backend.config
    if hasattr(cfg, "to_dict") and callable(cfg.to_dict):
        masked_config = cfg.to_dict(mask_secrets=True)
    elif hasattr(cfg, "data"):
        masked_config = mask_config_value("", cfg.data)
    elif hasattr(cfg, "_data"):
        masked_config = mask_config_value("", cfg._data)
    else:
        masked_config = {}

    cookie = str(cfg.get("musilon.session_cookie", "") or "").strip()
    username = str(cfg.get("musilon.username", "") or "").strip()
    password = str(cfg.get("musilon.password", "") or "").strip()
    sp_secret = str(cfg.get("spotify.client_secret", "") or "").strip()
    tg_hash = str(cfg.get("telegram.api_hash", "") or "").strip()

    has_cookie_auth = (
        "next-auth" in cookie
        or "__Secure-next-auth" in cookie
        or "wordpress_logged_in" in cookie
        or "wordpress_sec" in cookie
        or cookie.startswith("eyJ")
    )
    has_cred_auth = bool(username and password)
    musilon_configured = has_cookie_auth or has_cred_auth

    eff_engine = _effective_source_engine(cfg)
    concurrency_locked = eff_engine == "melobot"
    base_concurrency = int(cfg.get("download.concurrency", 5) or 5)

    return {
        "config": masked_config,
        "secrets_set": {
            "musilon_session_cookie": bool(cookie),
            "musilon_password": bool(password),
            "spotify_client_secret": bool(sp_secret),
            "telegram_api_hash": bool(tg_hash),
            "mobile_pair_token": bool(str(cfg.get("mobile.pair_token", "") or "").strip()),
        },
        "derived": {
            "effective_source_engine": eff_engine,
            "concurrency_locked": concurrency_locked,
            "effective_concurrency": 1 if concurrency_locked else base_concurrency,
            "musilon_configured": musilon_configured,
            "musilon_badge_state": "active" if musilon_configured else "guest",
        },
    }


def _sync_musilon_engine_credentials(backend: BackendState) -> None:
    cfg = backend.config
    cookie = str(cfg.get("musilon.session_cookie", "") or "")
    uname = str(cfg.get("musilon.username", "") or "")
    pwd = str(cfg.get("musilon.password", "") or "")
    enabled = bool(cfg.get("musilon.enabled", True))
    engine = backend.musilon_engine
    if hasattr(engine, "set_credentials") and callable(engine.set_credentials):
        engine.set_credentials(
            session_cookie=cookie,
            username=uname,
            password=pwd,
            enabled=enabled,
        )
    engine.username = uname
    engine.password = pwd
    engine.enabled = enabled


def _apply_source_engine(backend: BackendState, engine_name: str) -> None:
    cfg = backend.config
    if engine_name == "melobot":
        cfg.set("source_engine", "melobot")
        cfg.set("musilon.enabled", False)
        cfg.set("telegram.enabled", True)
        backend.musilon_engine.enabled = False
        if hasattr(backend.queue_manager, "update_concurrency"):
            backend.queue_manager.update_concurrency(1)
    else:
        cfg.set("source_engine", "musilon")
        cfg.set("musilon.enabled", True)
        cfg.set("telegram.enabled", False)
        backend.musilon_engine.enabled = True
        if hasattr(backend.queue_manager, "update_concurrency"):
            base_concur = int(cfg.get("download.concurrency", 5) or 5)
            backend.queue_manager.update_concurrency(base_concur)


@router.get("")
async def get_settings(request: Request):
    backend = _get_backend(request)
    return _build_settings_response(backend)


@router.patch("")
async def update_settings(request: Request, body: SettingsUpdateRequest):
    if not body.values:
        raise HTTPException(status_code=400, detail="No setting values supplied.")

    client_host = request.client.host if request.client else ""
    for key in body.values:
        if key == "mobile.pair_token":
            raise HTTPException(
                status_code=403,
                detail="mobile.pair_token can only be rotated locally via POST /api/sync/token/regenerate.",
            )
        if isinstance(key, str) and key.startswith("mobile."):
            if key not in _MUTABLE_MOBILE_KEYS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported or disallowed configuration key: '{key}'",
                )
            if not is_loopback_host(client_host):
                raise HTTPException(
                    status_code=403,
                    detail=f"{key} can only be changed locally on the host PC.",
                )
            continue
        if not _is_allowed_config_key(key):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported or disallowed configuration key: '{key}'",
            )

    backend = _get_backend(request)
    cfg = backend.config
    values = dict(body.values)
    updated_keys: List[str] = []

    musilon_creds_dirty = False
    spotify_creds_dirty = False
    auto_sync_dirty = False
    cooldown_min_val: Optional[int] = None
    cooldown_max_val: Optional[int] = None
    engine_switch_target: Optional[str] = None

    if "source_engine" in values:
        eng = str(values["source_engine"] or "").strip().lower()
        if eng not in ("musilon", "melobot"):
            raise HTTPException(
                status_code=400,
                detail="source_engine must be 'musilon' or 'melobot'.",
            )
        engine_switch_target = eng
    elif "telegram.enabled" in values:
        engine_switch_target = "melobot" if bool(values["telegram.enabled"]) else "musilon"

    for key, raw_val in values.items():
        if key in ("source_engine", "telegram.enabled"):
            continue

        if key == "musilon.enabled":
            if engine_switch_target is not None:
                continue
            val = bool(raw_val)
            cfg.set(key, val)
            backend.musilon_engine.enabled = val
            updated_keys.append(key)
            continue

        if key in ("musilon.session_cookie", "musilon.username", "musilon.password"):
            val = str(raw_val or "").strip()
            cfg.set(key, val)
            musilon_creds_dirty = True
            updated_keys.append(key)
            continue

        if key == "musilon.cooldown_min_sec":
            try:
                cooldown_min_val = max(0, min(300, int(raw_val)))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid cooldown_min_sec: {exc}")
            continue

        if key == "musilon.cooldown_max_sec":
            try:
                cooldown_max_val = max(0, min(300, int(raw_val)))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid cooldown_max_sec: {exc}")
            continue

        if key == "telegram.safe_delay_sec":
            try:
                val = max(0.0, min(30.0, float(raw_val)))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid safe_delay_sec: {exc}")
            cfg.set(key, val)
            updated_keys.append(key)
            continue

        if key == "download.concurrency":
            try:
                val = max(1, min(10, int(raw_val)))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid concurrency: {exc}")
            cfg.set(key, val)
            updated_keys.append(key)
            if engine_switch_target is None and _effective_source_engine(cfg) != "melobot":
                if hasattr(backend.queue_manager, "update_concurrency"):
                    backend.queue_manager.update_concurrency(val)
            continue

        if key == "download.preferred_quality":
            q = str(raw_val or "").strip().lower()
            if q in ("320", "mp3", "320k", "mp3_320"):
                cfg.set("download.preferred_quality", "320")
                cfg.set("download.quality_priority", list(_QUALITY_PRIORITY_320))
            elif q == "flac":
                cfg.set("download.preferred_quality", "flac")
                cfg.set("download.quality_priority", list(_QUALITY_PRIORITY_FLAC))
            else:
                raise HTTPException(
                    status_code=400,
                    detail="download.preferred_quality must be '320' or 'flac'.",
                )
            updated_keys.extend(["download.preferred_quality", "download.quality_priority"])
            continue

        if key == "download.target_format":
            fmt = str(raw_val or "").strip().lower()
            if fmt not in _VALID_TARGET_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid download.target_format '{fmt}'.",
                )
            cfg.set(key, fmt)
            updated_keys.append(key)
            continue

        if key == "download.lyrics_mode":
            mode = str(raw_val or "").strip().lower()
            if mode not in _VALID_LYRICS_MODES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid download.lyrics_mode '{mode}'.",
                )
            cfg.set("download.lyrics_mode", mode)
            cfg.set("download.save_lrc", mode != "embedded_only")
            updated_keys.extend(["download.lyrics_mode", "download.save_lrc"])
            continue

        if key == "download.output_dir":
            raw_dir = str(raw_val or "").strip()
            norm = os.path.normpath(raw_dir) if raw_dir else ""
            cfg.set(key, norm)
            if hasattr(backend.ytdlp_engine, "output_dir"):
                backend.ytdlp_engine.output_dir = norm
            updated_keys.append(key)
            continue

        if key in ("download.cookies_file", "download.proxy"):
            cfg.set(key, str(raw_val or "").strip())
            updated_keys.append(key)
            continue

        if key in ("spotify.client_id", "spotify.client_secret"):
            cfg.set(key, str(raw_val or "").strip())
            spotify_creds_dirty = True
            updated_keys.append(key)
            continue

        if key.startswith("playlists.auto_sync_"):
            cfg.set(key, raw_val)
            auto_sync_dirty = True
            updated_keys.append(key)
            continue

        if key == "mobile.lan_enabled":
            cfg.set(key, bool(raw_val))
            updated_keys.append(key)
            continue

        if key == "mobile.device_name":
            clean_name = re.sub(r"[\r\n\t\x00-\x1f\x7f]+", " ", str(raw_val or "")).strip()[:64]
            cfg.set(key, clean_name)
            updated_keys.append(key)
            continue

        cfg.set(key, raw_val)
        updated_keys.append(key)

    if cooldown_min_val is not None or cooldown_max_val is not None:
        cur_min = int(cfg.get("musilon.cooldown_min_sec", 15) or 0)
        cur_max = int(cfg.get("musilon.cooldown_max_sec", 35) or 0)
        if cooldown_min_val is not None and cooldown_max_val is not None:
            new_min = min(cooldown_min_val, cooldown_max_val)
            new_max = cooldown_max_val
            cfg.set("musilon.cooldown_min_sec", new_min)
            cfg.set("musilon.cooldown_max_sec", new_max)
            updated_keys.extend(["musilon.cooldown_min_sec", "musilon.cooldown_max_sec"])
        elif cooldown_min_val is not None:
            new_min = min(cooldown_min_val, cur_max)
            cfg.set("musilon.cooldown_min_sec", new_min)
            updated_keys.append("musilon.cooldown_min_sec")
        elif cooldown_max_val is not None:
            new_max = max(cooldown_max_val, cur_min)
            cfg.set("musilon.cooldown_max_sec", new_max)
            updated_keys.append("musilon.cooldown_max_sec")

    if engine_switch_target is not None:
        _apply_source_engine(backend, engine_switch_target)
        updated_keys.extend(["source_engine", "musilon.enabled", "telegram.enabled"])

    if musilon_creds_dirty:
        _sync_musilon_engine_credentials(backend)

    if spotify_creds_dirty and hasattr(backend.spotify_client, "update_credentials"):
        backend.spotify_client.update_credentials(
            client_id=str(cfg.get("spotify.client_id", "") or ""),
            client_secret=str(cfg.get("spotify.client_secret", "") or ""),
        )

    if auto_sync_dirty:
        backend.reschedule_auto_sync()

    if any(k.startswith("mobile.") for k in updated_keys) and hasattr(backend, "refresh_mdns"):
        backend.refresh_mdns()

    _save_config(cfg)
    dedup_updated = list(dict.fromkeys(updated_keys))
    return {"updated": dedup_updated, **_build_settings_response(backend)}


@router.post("/musilon/login")
async def login_musilon(request: Request, body: Optional[MusilonLoginRequest] = None):
    backend = _get_backend(request)
    cfg = backend.config
    req = body or MusilonLoginRequest()

    user = (
        req.username
        if req.username is not None
        else str(cfg.get("musilon.username", "") or "")
    ).strip()
    pwd = (
        req.password
        if req.password is not None
        else str(cfg.get("musilon.password", "") or "")
    ).strip()

    if not user or not pwd:
        raise HTTPException(
            status_code=400,
            detail="Please provide your Musilon email and password.",
        )
    if "@" not in user:
        raise HTTPException(
            status_code=400,
            detail="Musilon requires your registered email address (e.g. name@gmail.com), not your username.",
        )

    cfg.set("musilon.username", user)
    cfg.set("musilon.password", pwd)
    _sync_musilon_engine_credentials(backend)
    _save_config(cfg)

    success, msg = await asyncio.to_thread(
        backend.musilon_engine.login_with_credentials, user, pwd
    )

    cookie_saved = False
    if success:
        session = getattr(backend.musilon_engine, "session", None)
        cookies_obj = getattr(session, "cookies", None) if session is not None else None
        cookie_dict: Dict[str, Any] = {}
        if cookies_obj is not None and hasattr(cookies_obj, "get_dict"):
            cookie_dict = cookies_obj.get_dict() or {}
        elif isinstance(cookies_obj, dict):
            cookie_dict = cookies_obj
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        if cookie_str:
            cfg.set("musilon.session_cookie", cookie_str)
            _sync_musilon_engine_credentials(backend)
            _save_config(cfg)
            cookie_saved = True

        if req.run_test:
            connected, is_auth, is_vip, _test_msg = await asyncio.to_thread(
                backend.musilon_engine.test_connection
            )
            badge_state = (
                "vip"
                if is_vip
                else ("active" if is_auth else ("guest" if connected else "offline"))
            )
        else:
            connected, is_auth, is_vip = True, True, False
            badge_state = "active"
    else:
        connected, is_auth, is_vip = False, False, False
        badge_state = "offline"

    return {
        "success": bool(success),
        "message": msg,
        "badge_state": badge_state,
        "connected": bool(connected),
        "is_authenticated": bool(is_auth),
        "is_vip": bool(is_vip),
        "session_cookie_saved": cookie_saved,
    }


@router.post("/musilon/test")
async def test_musilon(request: Request):
    backend = _get_backend(request)
    connected, is_auth, is_vip, msg = await asyncio.to_thread(
        backend.musilon_engine.test_connection
    )
    badge_state = (
        "vip"
        if is_vip
        else ("active" if is_auth else ("guest" if connected else "offline"))
    )
    return {
        "connected": bool(connected),
        "is_authenticated": bool(is_auth),
        "is_vip": bool(is_vip),
        "message": msg,
        "badge_state": badge_state,
    }


@router.get("/telegram/status")
async def get_telegram_status(request: Request):
    backend = _get_backend(request)

    def _check():
        is_auth = bool(backend.melobot_engine.is_authorized())
        user = backend.melobot_engine.get_me() if is_auth else None
        return is_auth, user

    try:
        is_auth, user = await asyncio.to_thread(_check)
    except Exception as exc:
        logger.warning(f"Telegram status check failed: {exc}")
        return {"authorized": False, "user": None, "display": "Not Connected"}

    display = "Not Connected"
    if is_auth:
        if user:
            name = user.get("first_name") or user.get("username") or "Connected"
            phone = user.get("phone") or ""
            display = f"Connected: {name} (+{phone})" if phone else f"Connected: {name}"
        else:
            display = "Connected"

    return {
        "authorized": is_auth,
        "user": user,
        "display": display,
    }


@router.post("/telegram/send-code")
async def send_telegram_code(request: Request, body: TelegramSendCodeRequest):
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(
            status_code=400, detail="Please enter a valid phone number."
        )

    backend = _get_backend(request)
    backend.config.set("telegram.phone", phone)
    _save_config(backend.config)

    res = await asyncio.to_thread(backend.melobot_engine.send_code, phone)
    res = res or {}
    success = bool(res.get("success"))
    phone_hash = res.get("phone_code_hash")
    if success and phone_hash:
        backend.set_telegram_phone_hash(phone, phone_hash)

    return {
        "success": success,
        "phone_code_hash": phone_hash,
        "error": res.get("error"),
    }


@router.post("/telegram/verify")
async def verify_telegram_code(request: Request, body: TelegramVerifyRequest):
    code = body.code.strip()
    if not code:
        raise HTTPException(
            status_code=400, detail="Please enter the verification code."
        )

    backend = _get_backend(request)
    phone = (body.phone or str(backend.config.get("telegram.phone", "") or "")).strip()
    phone_code_hash = body.phone_code_hash or (
        backend.get_telegram_phone_hash(phone) if phone else None
    )

    res = await asyncio.to_thread(
        backend.melobot_engine.sign_in,
        code=code,
        password=body.password,
        phone_code_hash=phone_code_hash,
        phone=phone or None,
    )
    res = res or {}
    success = bool(res.get("success"))
    if success and phone:
        backend.clear_telegram_phone_hash(phone)

    return {
        "success": success,
        "needs_password": bool(res.get("needs_password", False)),
        "user": res.get("user"),
        "error": res.get("error"),
    }


@router.post("/telegram/logout")
async def logout_telegram(request: Request):
    backend = _get_backend(request)
    ok = await asyncio.to_thread(backend.melobot_engine.log_out)
    return {"success": bool(ok), "authorized": False}


def _sync_spotify_credentials(
    backend: BackendState,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> tuple[str, str]:
    cfg = backend.config
    if client_id is not None:
        cfg.set("spotify.client_id", client_id.strip())
    if client_secret is not None:
        cfg.set("spotify.client_secret", client_secret.strip())
    if client_id is not None or client_secret is not None:
        _save_config(cfg)

    cid = str(cfg.get("spotify.client_id", "") or "").strip()
    sec = str(cfg.get("spotify.client_secret", "") or "").strip()
    if hasattr(backend.spotify_client, "update_credentials"):
        backend.spotify_client.update_credentials(client_id=cid, client_secret=sec)
    return cid, sec


@router.get("/spotify/status")
async def get_spotify_status(
    request: Request,
    fetch_user: bool = Query(default=False),
):
    backend = _get_backend(request)
    cid, sec = _sync_spotify_credentials(backend)
    has_keys = bool(cid and sec)

    has_user_auth = False
    user_name = ""
    if has_keys:
        has_user_auth = bool(
            backend.spotify_client.has_user_auth(allow_network=False)
        )
        user_name = getattr(backend.spotify_client, "_cached_user_name", "") or ""
        if has_user_auth and fetch_user and not user_name:
            try:
                user_name = await asyncio.to_thread(
                    backend.spotify_client.get_current_user_name
                )
            except Exception as exc:
                logger.debug(f"Could not fetch Spotify username: {exc}")

    mode = (
        "authorized"
        if (has_keys and has_user_auth)
        else ("keys_only" if has_keys else "guest")
    )
    return {
        "has_keys": has_keys,
        "has_user_auth": has_user_auth,
        "user_name": user_name or "",
        "mode": mode,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
    }


@router.post("/spotify/validate")
async def validate_spotify_keys(
    request: Request, body: Optional[SpotifyCredentialsRequest] = None
):
    backend = _get_backend(request)
    req = body or SpotifyCredentialsRequest()
    cid, sec = _sync_spotify_credentials(
        backend, client_id=req.client_id, client_secret=req.client_secret
    )
    if not cid or not sec:
        raise HTTPException(
            status_code=400,
            detail="Both Spotify Client ID and Client Secret are required.",
        )

    try:
        res = await asyncio.to_thread(
            backend.spotify_client.resolve,
            "https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg",
        )
        sample_title = res[0].title if res else ""
        has_user_auth = bool(
            backend.spotify_client.has_user_auth(allow_network=False)
        )
        auth_status = (
            "User Authorized (Full Library Access)"
            if has_user_auth
            else "Keys Valid (Click 'Authorize' to unlock >100 songs)"
        )
        return {
            "valid": True,
            "sample_title": sample_title,
            "has_user_auth": has_user_auth,
            "message": f"API Verified: '{sample_title}' — {auth_status}",
        }
    except Exception as exc:
        return {
            "valid": False,
            "sample_title": "",
            "has_user_auth": False,
            "error": str(exc),
            "message": str(exc),
        }


@router.post("/spotify/authorize")
async def authorize_spotify_account(request: Request):
    backend = _get_backend(request)
    cid, sec = _sync_spotify_credentials(backend)
    if not cid or not sec:
        raise HTTPException(
            status_code=400,
            detail="Please enter both Client ID and Client Secret before authorizing.",
        )

    ok = await asyncio.to_thread(
        backend.spotify_client.authorize_user, force_new=True
    )
    user_name = ""
    if ok:
        try:
            user_name = await asyncio.to_thread(
                backend.spotify_client.get_current_user_name
            )
        except Exception:
            pass
    msg = (
        f"Logged in as @{user_name}! Full playlist access unlocked."
        if (ok and user_name)
        else (
            "Spotify account successfully authorized!"
            if ok
            else "Authorization was cancelled or did not return tokens."
        )
    )
    return {
        "success": bool(ok),
        "user_name": user_name or "",
        "message": msg,
    }


@router.get("/spotify/auth-url")
async def get_spotify_auth_url(request: Request):
    backend = _get_backend(request)
    cid, sec = _sync_spotify_credentials(backend)
    if not cid or not sec:
        raise HTTPException(
            status_code=400,
            detail="Please enter both Client ID and Client Secret first.",
        )
    auth_url = await asyncio.to_thread(backend.spotify_client.get_auth_url)
    return {
        "auth_url": auth_url,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
    }


@router.post("/spotify/auth-callback")
async def spotify_auth_callback(
    request: Request, body: SpotifyAuthCallbackRequest
):
    code_or_url = body.code_or_url.strip()
    if not code_or_url:
        raise HTTPException(
            status_code=400,
            detail="Authorization code or callback URL is required.",
        )

    backend = _get_backend(request)
    _sync_spotify_credentials(backend)
    ok = await asyncio.to_thread(
        backend.spotify_client.parse_and_save_auth_code, code_or_url
    )
    user_name = ""
    if ok:
        try:
            user_name = await asyncio.to_thread(
                backend.spotify_client.get_current_user_name
            )
        except Exception:
            pass
    return {
        "success": bool(ok),
        "user_name": user_name or "",
    }


@router.post("/spotify/disconnect")
async def disconnect_spotify(request: Request):
    backend = _get_backend(request)
    await asyncio.to_thread(backend.spotify_client.clear_user_auth)
    return {"success": True, "has_user_auth": False}


@router.get("/ffmpeg/status")
async def get_ffmpeg_status():
    ff_path = await asyncio.to_thread(core_utils.ensure_ffmpeg)
    return {
        "installed": bool(ff_path),
        "path": ff_path or "",
    }


@router.post("/ffmpeg/install")
async def install_ffmpeg(request: Request):
    backend = _get_backend(request)

    def _progress_cb(pct: float, msg: str) -> None:
        backend.events.emit_threadsafe(
            "tool_progress",
            {
                "tool": "ffmpeg_install",
                "current": round(float(pct), 1),
                "total": 100,
                "percent": round(float(pct), 1),
                "message": msg,
            },
        )

    res = await asyncio.to_thread(
        core_utils.download_ffmpeg, progress_callback=_progress_cb
    )
    backend.events.emit_threadsafe(
        "tool_completed",
        {
            "tool": "ffmpeg_install",
            "success": bool(res),
            "path": res or "",
        },
    )
    return {
        "success": bool(res),
        "path": res or "",
        "message": (
            f"FFmpeg installed at {res}"
            if res
            else "FFmpeg download or validation failed."
        ),
    }


@router.post("/open-folder")
async def open_local_folder(
    request: Request, body: Optional[OpenFolderRequest] = None
):
    client_host = request.client.host if request.client else ""
    if not is_loopback_host(client_host):
        raise HTTPException(
            status_code=403,
            detail="Opening local folders is only allowed locally on the host PC.",
        )

    backend = _get_backend(request)
    req = body or OpenFolderRequest()
    raw_target = (
        req.path
        if req.path is not None and req.path.strip()
        else str(backend.config.get("download.output_dir", "") or "")
    ).strip()

    if not raw_target or not os.path.exists(raw_target):
        raise HTTPException(
            status_code=404,
            detail=f"Path does not exist: {raw_target}",
        )

    target = os.path.normpath(raw_target)
    if os.name == "nt":
        if os.path.isfile(target):
            if req.reveal:
                subprocess.Popen(["explorer", f"/select,{target}"])
            else:
                os.startfile(os.path.dirname(target))
        else:
            os.startfile(target)
    elif os.name == "posix":
        import sys

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        folder_target = os.path.dirname(target) if os.path.isfile(target) else target
        subprocess.Popen([opener, folder_target])

    return {"opened": True, "path": target}
