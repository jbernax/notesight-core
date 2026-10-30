import collections
from datetime import datetime, timezone
import json
import logging
import time
import uuid
from typing import Any
import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from app.auth import get_user_from_token_str
from app.config import settings
from app.database import SessionLocal
from app.models import Job, ScoreShare, User
from app.services.collaboration_manager import collaboration_manager
from app.services.musicxml_sanitizer import sanitize_musicxml_string

logger = logging.getLogger(__name__)

router = APIRouter(tags=["collaboration"])

MAX_WS_MESSAGE_SIZE = 2 * 1024 * 1024  # 2 MB
WS_RATE_LIMIT_MESSAGES = 30
WS_RATE_LIMIT_WINDOW = 10.0  # seconds


def _authenticate_and_authorize_ws(
    job_uuid: uuid.UUID,
    token: str | None,
    share_token: str | None,
    guest_name: str,
) -> tuple[bool, bool, bool, str | None, str, str | None]:
    """
    Synchronously verify user token, job existence, and authorization in worker thread.
    Returns: (job_found, is_authorized, can_edit, user_id, user_name, avatar_url)
    """
    user_id: str | None = None
    user_name: str = guest_name.strip() or "Musician"
    avatar_url: str | None = None
    current_user: User | None = None

    with SessionLocal() as db:
        try:
            if token:
                try:
                    current_user = get_user_from_token_str(token, db, allow_stream_ticket=True)
                    if current_user:
                        user_id = str(current_user.id)
                        user_name = current_user.full_name or current_user.email.split("@")[0]
                        avatar_url = current_user.avatar_url
                except Exception as exc:
                    logger.warning("Token decoding or authentication failed for websocket client: %s", exc)

            job = db.query(Job).filter(Job.id == job_uuid).first()
            if not job:
                return (False, False, False, None, user_name, None)

            is_authorized = False
            can_edit = False
            # 1. Owner is always authorized with edit permissions
            if current_user and job.user_id == current_user.id:
                is_authorized = True
                can_edit = True
            elif share_token:
                # 2. Caller provided explicit share token (must match active share)
                share = (
                    db.query(ScoreShare)
                    .filter(
                        ScoreShare.job_id == job.id,
                        ScoreShare.share_token == share_token,
                        ScoreShare.is_active == True,  # noqa: E712
                    )
                    .first()
                )
                if share and (not share.expires_at or share.expires_at > datetime.now(timezone.utc)):
                    is_authorized = True
                    can_edit = False

            return (True, is_authorized, can_edit, user_id, user_name, avatar_url)
        finally:
            db.rollback()


@router.websocket("/ws/studio/{job_id}")
async def studio_collaboration_websocket(
    websocket: WebSocket,
    job_id: str,
) -> None:
    """Real-time multi-user collaborative score editing and presence room endpoint."""
    # 0. Validate Origin header on handshake
    origin = websocket.headers.get("origin")
    if origin:
        is_origin_allowed = False
        if "*" in settings.CORS_ORIGINS:
            is_origin_allowed = True
        else:
            norm_origin = origin.rstrip("/")
            allowed = {o.rstrip("/") for o in settings.CORS_ORIGINS}
            if norm_origin in allowed or (
                settings.ENVIRONMENT.lower() in ("development", "test", "testing")
                and (
                    norm_origin.startswith("http://localhost")
                    or norm_origin.startswith("http://127.0.0.1")
                    or norm_origin in ("http://testserver", "https://testserver")
                )
            ):
                is_origin_allowed = True
        if not is_origin_allowed:
            logger.warning("Rejected WebSocket connection with untrusted origin: %s", origin)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Untrusted Origin")
            return

    try:
        val_job_uuid = uuid.UUID(job_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid job ID")
        return

    # Extract query params from connection URL
    token = websocket.query_params.get("token")
    share_token = websocket.query_params.get("share_token")
    guest_name = websocket.query_params.get("guest_name", "Musician")

    # Validate that the score job exists and verify authorization in worker threadpool
    job_found, is_authorized, can_edit, user_id, user_name, avatar_url = await run_in_threadpool(
        _authenticate_and_authorize_ws,
        val_job_uuid,
        token,
        share_token,
        guest_name,
    )

    if not job_found:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Score job not found")
        return

    if not is_authorized:
        logger.warning("Unauthorized WebSocket connection attempt rejected for score job %s", job_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized access to score room")
        return

    await websocket.accept()
    client_id = str(uuid.uuid4())

    peer = await collaboration_manager.register_peer(
        job_id=job_id,
        client_id=client_id,
        websocket=websocket,
        user_id=user_id,
        user_name=user_name,
        avatar_url=avatar_url,
    )

    try:
        # 1. Send initial room snapshot to the connecting peer
        peers = await collaboration_manager.get_room_peers(job_id)
        locks = await collaboration_manager.get_room_locks(job_id)
        await websocket.send_json({
            "type": "room_state",
            "your_client_id": client_id,
            "your_color": peer.color,
            "can_edit": can_edit,
            "peers": peers,
            "locks": locks,
        })

        # 2. Announce peer arrival to existing peers in the room
        await collaboration_manager.broadcast(
            job_id=job_id,
            message={
                "type": "peer_joined",
                "peer": peer.to_dict(),
            },
            exclude_client_id=client_id,
        )

        message_timestamps: collections.deque[float] = collections.deque()

        # 3. Message loop
        while True:
            data: dict[str, Any] = await websocket.receive_json()

            # Sliding rate limit check: max 30 messages / 10 seconds
            now = time.time()
            while message_timestamps and now - message_timestamps[0] > WS_RATE_LIMIT_WINDOW:
                message_timestamps.popleft()

            if len(message_timestamps) >= WS_RATE_LIMIT_MESSAGES:
                logger.warning("WebSocket client %s exceeded message rate limit", client_id)
                await websocket.send_json({
                    "type": "error",
                    "message": "Rate limit exceeded (maximum 30 messages per 10 seconds)",
                })
                continue

            message_timestamps.append(now)

            # Enforce 2 MB maximum payload size
            try:
                raw_bytes_len = len(json.dumps(data).encode("utf-8"))
            except Exception:
                raw_bytes_len = 0
            if raw_bytes_len > MAX_WS_MESSAGE_SIZE:
                logger.warning("WebSocket message from %s exceeds 2 MB limit", client_id)
                await websocket.send_json({
                    "type": "error",
                    "message": "WebSocket message exceeds 2 MB limit",
                })
                continue

            msg_type = data.get("type")

            if msg_type == "presence":
                measure = int(data.get("measure", 1))
                staff = int(data.get("staff", 0))
                tool = str(data.get("tool", "select"))
                updated = await collaboration_manager.update_presence(job_id, client_id, measure, staff, tool)
                if updated:
                    await collaboration_manager.broadcast(
                        job_id=job_id,
                        message={
                            "type": "presence_update",
                            "peer": updated,
                        },
                        exclude_client_id=client_id,
                    )

            elif msg_type == "measure_lock":
                measure = int(data.get("measure", 1))
                if not can_edit:
                    await websocket.send_json({
                        "type": "lock_ack",
                        "measure": measure,
                        "acquired": False,
                        "reason": "Read-only access: measure locking is restricted to the score owner",
                    })
                    continue
                acquired = await collaboration_manager.acquire_lock(job_id, client_id, measure, user_name=peer.user_name)
                await websocket.send_json({
                    "type": "lock_ack",
                    "measure": measure,
                    "acquired": acquired,
                })
                if acquired:
                    await collaboration_manager.broadcast(
                        job_id=job_id,
                        message={
                            "type": "measure_locked",
                            "measure": measure,
                            "client_id": client_id,
                            "holder_name": peer.user_name,
                        },
                        exclude_client_id=client_id,
                    )

            elif msg_type == "measure_unlock":
                measure = int(data.get("measure", 1))
                released = await collaboration_manager.release_lock(job_id, client_id, measure)
                if released:
                    await collaboration_manager.broadcast(
                        job_id=job_id,
                        message={
                            "type": "measure_unlocked",
                            "measure": measure,
                        },
                    )

            elif msg_type == "score_mutation":
                if not can_edit:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Read-only access: score mutations are restricted to the score owner",
                    })
                    continue
                musicxml = str(data.get("musicxml", ""))
                description = str(data.get("description", "Notation change"))
                if len(musicxml.encode("utf-8")) > MAX_WS_MESSAGE_SIZE:
                    await websocket.send_json({
                        "type": "error",
                        "message": "MusicXML payload exceeds 2 MB limit",
                    })
                    continue

                if musicxml.strip():
                    try:
                        sanitized_xml, _ = sanitize_musicxml_string(musicxml)
                    except Exception as exc:
                        logger.warning("MusicXML sanitization failed on score_mutation: %s", exc)
                        await websocket.send_json({
                            "type": "error",
                            "message": "Invalid MusicXML notation payload",
                        })
                        continue

                    await collaboration_manager.broadcast(
                        job_id=job_id,
                        message={
                            "type": "score_delta",
                            "musicxml": sanitized_xml,
                            "author": peer.user_name,
                            "client_id": client_id,
                            "description": description,
                        },
                        exclude_client_id=client_id,
                    )

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Peer %s disconnected normally", client_id)
    except Exception as exc:
        logger.warning("Peer %s disconnected with exception: %s", client_id, exc)
    finally:
        released_measures = await collaboration_manager.unregister_peer(job_id, client_id)
        # Notify room of departure and any unlocked measures
        await collaboration_manager.broadcast(
            job_id=job_id,
            message={
                "type": "peer_left",
                "client_id": client_id,
                "user_name": peer.user_name,
            },
        )
        for m in released_measures:
            await collaboration_manager.broadcast(
                job_id=job_id,
                message={
                    "type": "measure_unlocked",
                    "measure": m,
                },
            )
