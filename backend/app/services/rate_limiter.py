import math
import time
import uuid
import threading
import logging
from typing import Callable, Optional
import redis
from fastapi import Request, HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter using Redis sorted sets (ZSET),
    with automatic in-memory fallback if Redis is unavailable or during testing.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis_client: Optional[redis.Redis] = None
        self._redis_available: bool = True
        self._last_retry_time: float = 0.0
        self._retry_interval: float = 10.0
        self._lock = threading.RLock()
        self._in_memory_store: dict[str, list[float]] = {}

    def _get_redis(self) -> Optional[redis.Redis]:
        with self._lock:
            now = time.time()
            if not self._redis_available:
                if now - self._last_retry_time < self._retry_interval:
                    return None
                self._last_retry_time = now

            if self._redis_client is None:
                try:
                    client = redis.from_url(self.redis_url, decode_responses=True)
                    client.ping()
                    self._redis_client = client
                    if not self._redis_available:
                        logger.info("Redis connectivity restored for rate limiter.")
                    self._redis_available = True
                    self._retry_interval = 10.0
                except Exception as e:
                    if self._redis_available:
                        logger.warning("Redis connection failed for rate limiter, falling back to in-memory store: %s", e)
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = now
                    self._retry_interval = min(60.0, self._retry_interval * 2.0)
                    return None
            return self._redis_client

    MAX_IN_MEMORY_KEYS: int = 10000

    def _prune_memory_store_if_needed(self, now: float, window_seconds: int = 60) -> None:
        """Bound in-memory store size and evict expired / LRU entries."""
        if len(self._in_memory_store) < self.MAX_IN_MEMORY_KEYS:
            return

        window_start = now - window_seconds
        # Evict up to 100 oldest expired or LRU keys
        keys_to_remove = []
        for k, ts_list in self._in_memory_store.items():
            if not ts_list or max(ts_list) <= window_start:
                keys_to_remove.append(k)
                if len(keys_to_remove) >= 100:
                    break
        for k in keys_to_remove:
            self._in_memory_store.pop(k, None)

        while len(self._in_memory_store) >= self.MAX_IN_MEMORY_KEYS:
            oldest_key = next(iter(self._in_memory_store))
            self._in_memory_store.pop(oldest_key, None)

    def is_rate_limited(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """
        Check if the request exceeds limit within window_seconds.
        Returns:
            (is_limited: bool, retry_after_seconds: int)
        """
        now = time.time()
        client = self._get_redis()

        if client is not None:
            try:
                window_start = now - window_seconds
                pipe = client.pipeline()
                # 1. Remove entries older than the rolling window
                pipe.zremrangebyscore(key, 0, window_start)
                # 2. Count requests currently in the window
                pipe.zcard(key)
                # 3. Retrieve the oldest timestamp in the window (for accurate Retry-After)
                pipe.zrange(key, 0, 0, withscores=True)
                results = pipe.execute()

                current_count = results[1]
                oldest_entries = results[2]

                if current_count >= limit:
                    # Calculate retry_after based on when oldest entry slides out
                    if oldest_entries:
                        oldest_ts = float(oldest_entries[0][1])
                        retry_after = max(1, math.ceil(oldest_ts + window_seconds - now))
                    else:
                        retry_after = window_seconds
                    return True, retry_after

                # Add current request with unique member
                member = f"{now}-{uuid.uuid4().hex[:8]}"
                pipe = client.pipeline()
                pipe.zadd(key, {member: now})
                pipe.expire(key, window_seconds + 5)
                pipe.execute()
                return False, 0
            except Exception as exc:
                logger.warning("Redis error during rate limiting check, falling back to in-memory: %s", exc)
                with self._lock:
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = now
                    self._retry_interval = min(60.0, self._retry_interval * 2.0)

        # In-memory sliding window fallback
        with self._lock:
            self._prune_memory_store_if_needed(now, window_seconds)
            window_start = now - window_seconds
            timestamps = self._in_memory_store.get(key, [])
            # Filter out expired timestamps
            valid_timestamps = [ts for ts in timestamps if ts > window_start]

            if len(valid_timestamps) >= limit:
                oldest_ts = valid_timestamps[0]
                retry_after = max(1, math.ceil(oldest_ts + window_seconds - now))
                self._in_memory_store[key] = valid_timestamps
                return True, retry_after

            valid_timestamps.append(now)
            self._in_memory_store[key] = valid_timestamps
            return False, 0

    def reset(self, key: Optional[str] = None) -> None:
        """Reset rate limiter state (useful in testing)."""
        with self._lock:
            if key:
                self._in_memory_store.pop(key, None)
            else:
                self._in_memory_store.clear()

        client = self._get_redis()
        if client is not None:
            try:
                if key:
                    client.delete(key)
                else:
                    keys = client.keys("ratelimit:*")
                    if keys:
                        client.delete(*keys)
            except Exception:
                pass


# Global singleton instance
rate_limiter = SlidingWindowRateLimiter()


import hashlib
import ipaddress
import re
import jwt

TRUSTED_PROXY_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def is_trusted_proxy(ip_str: str) -> bool:
    """Check if an IP string belongs to localhost or RFC1918 / Docker private networks."""
    if ip_str in {"testclient", "localhost"}:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in TRUSTED_PROXY_NETWORKS)
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """Safely extract client IP from connection or validated trusted proxy header."""
    client_host = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and is_trusted_proxy(client_host):
        # Extract the right-most untrusted client IP
        ips = [re.sub(r"[^a-fA-F0-9:.]", "", part.strip()) for part in forwarded.split(",") if part.strip()]
        for ip in reversed(ips):
            if ip and not is_trusted_proxy(ip):
                return ip
        for ip in ips:
            if ip:
                return ip
    return client_host


def rate_limit(limit: Optional[int] = None, window_seconds: int = 60, scope: str = "ip") -> Callable:
    """
    FastAPI dependency for rate limiting endpoints.
    Args:
        limit: Max allowed requests within window (defaults to settings per scope)
        window_seconds: Rolling window size in seconds (default 60)
        scope: "ip" or "user"
    """
    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        effective_limit = limit
        if effective_limit is None:
            if scope == "user":
                effective_limit = settings.UPLOAD_RATE_LIMIT_PER_MINUTE
            else:
                effective_limit = settings.AUTH_RATE_LIMIT_PER_MINUTE

        ip = get_client_ip(request)
        if scope == "user":
            auth_header = request.headers.get("authorization", "")
            user_id = None
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]
                try:
                    payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
                    sub = payload.get("sub")
                    if sub and isinstance(sub, str):
                        user_id = sub.strip().lower()
                except Exception:
                    pass
            if user_id:
                key = f"ratelimit:user:{user_id}"
            else:
                key = f"ratelimit:user_ip:{ip}"
        else:
            key = f"ratelimit:ip:{ip}"

        is_limited, retry_after = rate_limiter.is_rate_limited(key, effective_limit, window_seconds)
        if is_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
