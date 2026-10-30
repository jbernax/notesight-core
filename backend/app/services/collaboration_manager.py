import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from fastapi import WebSocket
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

PEER_PALETTE = [
    "#6366f1",  # Indigo
    "#10b981",  # Emerald
    "#f59e0b",  # Amber
    "#ec4899",  # Pink
    "#8b5cf6",  # Purple
    "#06b6d4",  # Cyan
    "#f97316",  # Orange
    "#14b8a6",  # Teal
]


@dataclass
class PeerSession:
    client_id: str
    websocket: WebSocket
    user_id: str | None
    user_name: str
    avatar_url: str | None
    color: str
    current_measure: int = 1
    current_staff: int = 0
    current_tool: str = "select"
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "avatar_url": self.avatar_url,
            "color": self.color,
            "current_measure": self.current_measure,
            "current_staff": self.current_staff,
            "current_tool": self.current_tool,
        }


class CollaborationManager:
    """Manages real-time WebSocket rooms, presence indicators, distributed measure locks, and broadcast events."""

    def __init__(self) -> None:
        # job_id -> {client_id: PeerSession}
        self._rooms: dict[str, dict[str, PeerSession]] = {}
        # job_id -> {measure_num: client_id}
        self._measure_locks: dict[str, dict[int, str]] = {}
        self._color_indices: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._worker_id: str = str(uuid.uuid4())
        self._redis: aioredis.Redis | None = None
        self._redis_available: bool = True
        self._last_redis_retry: float = 0.0
        self._redis_retry_delay: float = 10.0
        self._listener_tasks: dict[str, asyncio.Task[Any]] = {}

    def reset(self) -> None:
        """Reset all in-memory rooms, locks, and listener tasks for clean state between tests."""
        self._rooms.clear()
        self._measure_locks.clear()
        self._color_indices.clear()
        for task in self._listener_tasks.values():
            if not task.done():
                task.cancel()
        self._listener_tasks.clear()

    async def _get_redis(self) -> aioredis.Redis | None:
        """Return an active async Redis client, attempting backoff reconnects if previously failed."""
        now = time.monotonic()
        if not self._redis_available:
            if now - self._last_redis_retry < self._redis_retry_delay:
                return None
            self._last_redis_retry = now
            self._redis_retry_delay = min(60.0, self._redis_retry_delay * 2)

        if self._redis is None:
            try:
                self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                await self._redis.ping()
                self._redis_available = True
                self._redis_retry_delay = 10.0
                logger.info("Connected to Redis for distributed collaboration pubsub & locks")
            except Exception as exc:
                self._redis_available = False
                self._last_redis_retry = now
                self._redis = None
                logger.warning("Redis unavailable for collaboration, falling back to local memory: %s", exc)
                return None

        return self._redis

    async def _ensure_listener(self, job_id: str) -> None:
        if job_id in self._listener_tasks and not self._listener_tasks[job_id].done():
            return
        redis = await self._get_redis()
        if redis is None:
            return
        task = asyncio.create_task(self._room_subscriber(job_id))
        self._listener_tasks[job_id] = task

    async def _room_subscriber(self, job_id: str) -> None:
        channel_name = f"studio:room:{job_id}"
        pubsub = None
        try:
            redis = await self._get_redis()
            if redis is None:
                return
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel_name)
            async for raw_msg in pubsub.listen():
                if raw_msg.get("type") == "message":
                    try:
                        data = json.loads(raw_msg.get("data", "{}"))
                        # Skip if published by this worker instance
                        if data.get("sender_worker") == self._worker_id:
                            continue
                        exclude = data.get("exclude_client_id")
                        msg = data.get("message")
                        if msg:
                            await self._local_broadcast(job_id, msg, exclude_client_id=exclude)
                    except Exception as err:
                        logger.warning("Error processing Redis pubsub message on %s: %s", channel_name, err)
        except asyncio.CancelledError:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel_name)
                    if hasattr(pubsub, "aclose"):
                        await pubsub.aclose()
                    elif hasattr(pubsub, "close"):
                        await pubsub.close()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Pubsub subscriber error on %s: %s", channel_name, exc)

    async def register_peer(
        self,
        job_id: str,
        client_id: str,
        websocket: WebSocket,
        user_id: str | None = None,
        user_name: str = "Musician",
        avatar_url: str | None = None,
    ) -> PeerSession:
        async with self._lock:
            if job_id not in self._rooms:
                self._rooms[job_id] = {}
                self._measure_locks[job_id] = {}
                self._color_indices[job_id] = 0

            color_idx = self._color_indices[job_id] % len(PEER_PALETTE)
            color = PEER_PALETTE[color_idx]
            self._color_indices[job_id] += 1

            peer = PeerSession(
                client_id=client_id,
                websocket=websocket,
                user_id=user_id,
                user_name=user_name,
                avatar_url=avatar_url,
                color=color,
            )
            self._rooms[job_id][client_id] = peer
            logger.info("Peer %s (%s) joined collaboration room %s", user_name, client_id, job_id)

        # Distribute peer registration to Redis
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.hset(f"studio:peers:{job_id}", client_id, json.dumps(peer.to_dict()))
                await redis.expire(f"studio:peers:{job_id}", 86400)
            except Exception as exc:
                logger.warning("Failed to record peer in Redis: %s", exc)

        await self._ensure_listener(job_id)
        return peer

    async def _scan_keys(self, redis: Any, pattern: str) -> list[Any]:
        """Fetch keys non-blockingly using SCAN cursor iteration instead of KEYS *."""
        keys: list[Any] = []
        if hasattr(redis, "scan_iter"):
            res = redis.scan_iter(match=pattern, count=100)
            if hasattr(res, "__aiter__"):
                async for k in res:
                    keys.append(k)
            elif hasattr(res, "__iter__"):
                for k in res:
                    keys.append(k)
            elif asyncio.iscoroutine(res):
                keys.extend(await res)
        else:
            raw_keys = await redis.keys(pattern)
            keys.extend(raw_keys)
        return keys

    async def unregister_peer(self, job_id: str, client_id: str) -> list[int]:
        released_measures: list[int] = []
        async with self._lock:
            if job_id in self._measure_locks:
                for m_num, c_id in list(self._measure_locks[job_id].items()):
                    if c_id == client_id:
                        released_measures.append(m_num)
                        del self._measure_locks[job_id][m_num]

            if job_id in self._rooms and client_id in self._rooms[job_id]:
                del self._rooms[job_id][client_id]
                logger.info("Peer %s left collaboration room %s", client_id, job_id)

                if not self._rooms[job_id]:
                    del self._rooms[job_id]
                    if job_id in self._measure_locks:
                        del self._measure_locks[job_id]
                    if job_id in self._color_indices:
                        del self._color_indices[job_id]
                    # Cancel subscriber task if no local peers left in room
                    task = self._listener_tasks.pop(job_id, None)
                    if task and not task.done():
                        task.cancel()

        # Clean up Redis records
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.hdel(f"studio:peers:{job_id}", client_id)
                pattern = f"studio:lock:{job_id}:*"
                keys = await self._scan_keys(redis, pattern)
                for k in keys:
                    val = await redis.get(k)
                    if val:
                        try:
                            parsed = json.loads(val)
                            if parsed.get("client_id") == client_id:
                                await redis.delete(k)
                                k_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                                m_str = k_str.split(":")[-1]
                                if m_str.isdigit():
                                    m_int = int(m_str)
                                    if m_int not in released_measures:
                                        released_measures.append(m_int)
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("Failed to unregister peer from Redis: %s", exc)

        return released_measures

    async def update_presence(
        self,
        job_id: str,
        client_id: str,
        measure: int,
        staff: int,
        tool: str,
    ) -> dict[str, Any] | None:
        async with self._lock:
            peer = self._rooms.get(job_id, {}).get(client_id)
            if not peer:
                return None
            peer.current_measure = measure
            peer.current_staff = staff
            peer.current_tool = tool
            res = peer.to_dict()

        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.hset(f"studio:peers:{job_id}", client_id, json.dumps(res))
            except Exception as exc:
                logger.warning("Failed to update peer presence in Redis: %s", exc)

        return res

    async def acquire_lock(
        self,
        job_id: str,
        client_id: str,
        measure: int,
        user_name: str = "Collaborator",
    ) -> bool:
        redis = await self._get_redis()
        if redis is not None:
            try:
                key = f"studio:lock:{job_id}:{measure}"
                # Check if lock already held by this client
                current_val = await redis.get(key)
                if current_val:
                    try:
                        parsed = json.loads(current_val)
                        if parsed.get("client_id") == client_id:
                            # Re-assert TTL
                            await redis.expire(key, 120)
                            return True
                        return False
                    except Exception:
                        return False

                # Not held, acquire with 120s TTL
                payload = json.dumps({"client_id": client_id, "user_name": user_name})
                acquired = await redis.set(key, payload, ex=120, nx=True)
                if acquired:
                    async with self._lock:
                        locks = self._measure_locks.setdefault(job_id, {})
                        locks[measure] = client_id
                    return True
                return False
            except Exception as exc:
                logger.warning("Distributed lock acquisition failed via Redis, using fallback: %s", exc)

        # Fallback to local memory lock
        async with self._lock:
            if job_id not in self._rooms or client_id not in self._rooms[job_id]:
                return False

            locks = self._measure_locks.setdefault(job_id, {})
            current_holder = locks.get(measure)
            if current_holder is None or current_holder == client_id:
                locks[measure] = client_id
                return True
            return False

    async def release_lock(self, job_id: str, client_id: str, measure: int) -> bool:
        released = False
        redis = await self._get_redis()
        if redis is not None:
            try:
                key = f"studio:lock:{job_id}:{measure}"
                current_val = await redis.get(key)
                if current_val:
                    try:
                        parsed = json.loads(current_val)
                        if parsed.get("client_id") == client_id:
                            await redis.delete(key)
                            released = True
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Distributed lock release failed via Redis: %s", exc)

        async with self._lock:
            locks = self._measure_locks.get(job_id, {})
            if locks.get(measure) == client_id:
                del locks[measure]
                released = True

        return released

    async def get_room_peers(self, job_id: str) -> list[dict[str, Any]]:
        redis = await self._get_redis()
        if redis is not None:
            try:
                hash_key = f"studio:peers:{job_id}"
                all_raw = await redis.hgetall(hash_key)
                if all_raw:
                    peers: list[dict[str, Any]] = []
                    for raw in all_raw.values():
                        try:
                            peers.append(json.loads(raw))
                        except Exception:
                            pass
                    if peers:
                        return peers
            except Exception as exc:
                logger.warning("Failed to fetch distributed peers from Redis: %s", exc)

        async with self._lock:
            return [p.to_dict() for p in self._rooms.get(job_id, {}).values()]

    async def get_room_locks(self, job_id: str) -> dict[int, str]:
        redis = await self._get_redis()
        if redis is not None:
            try:
                pattern = f"studio:lock:{job_id}:*"
                keys = await self._scan_keys(redis, pattern)
                locks: dict[int, str] = {}
                for k in keys:
                    k_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                    m_str = k_str.split(":")[-1]
                    if m_str.isdigit():
                        val = await redis.get(k)
                        if val:
                            try:
                                parsed = json.loads(val)
                                locks[int(m_str)] = parsed.get("user_name", "Collaborator")
                            except Exception:
                                locks[int(m_str)] = "Collaborator"
                return locks
            except Exception as exc:
                logger.warning("Failed to fetch distributed locks from Redis: %s", exc)

        async with self._lock:
            local_locks = self._measure_locks.get(job_id, {})
            room = self._rooms.get(job_id, {})
            return {
                m: room[c_id].user_name if c_id in room else "Collaborator"
                for m, c_id in local_locks.items()
            }

    async def _local_broadcast(
        self,
        job_id: str,
        message: dict[str, Any],
        exclude_client_id: str | None = None,
    ) -> None:
        peers_to_send: list[tuple[str, WebSocket]] = []
        async with self._lock:
            room = self._rooms.get(job_id, {})
            for c_id, peer in room.items():
                if exclude_client_id and c_id == exclude_client_id:
                    continue
                peers_to_send.append((c_id, peer.websocket))

        dead_clients: list[str] = []
        for c_id, ws in peers_to_send:
            try:
                await ws.send_json(message)
            except Exception as exc:
                logger.warning("Failed to send message to peer %s: %s", c_id, exc)
                dead_clients.append(c_id)

        for c_id in dead_clients:
            await self.unregister_peer(job_id, c_id)

    async def broadcast(
        self,
        job_id: str,
        message: dict[str, Any],
        exclude_client_id: str | None = None,
    ) -> None:
        # 1. Immediate local delivery to connected WebSockets on this worker
        await self._local_broadcast(job_id, message, exclude_client_id)

        # 2. Redis Pub/Sub relay for other worker processes / pods
        redis = await self._get_redis()
        if redis is not None:
            try:
                payload = json.dumps({
                    "sender_worker": self._worker_id,
                    "exclude_client_id": exclude_client_id,
                    "message": message,
                })
                await redis.publish(f"studio:room:{job_id}", payload)
            except Exception as exc:
                logger.warning("Failed to publish broadcast to Redis channel studio:room:%s: %s", job_id, exc)


# Global singleton instance
collaboration_manager = CollaborationManager()
