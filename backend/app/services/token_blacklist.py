import hashlib
import logging
import threading
import time
from typing import Optional
import jwt
import redis
from app.config import settings

logger = logging.getLogger(__name__)


class TokenBlacklistService:
    """
    Token revocation service backed by Redis, with in-memory fallback
    for local test isolation or temporary Redis disconnection.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis_client: Optional[redis.Redis] = None
        self._redis_available: bool = True
        self._last_retry_time: float = 0.0
        self._retry_interval: float = 10.0
        self._lock = threading.RLock()
        self._in_memory_revoked: dict[str, float] = {}  # key -> expiry_timestamp
        self._in_memory_user_revoked: dict[str, float] = {}  # user -> revoked_before_timestamp

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
                        logger.info("Redis connectivity restored for token blacklist.")
                    self._redis_available = True
                    self._retry_interval = 10.0
                except Exception as e:
                    if self._redis_available:
                        logger.warning("Redis connection failed for token blacklist, using in-memory store: %s", e)
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = now
                    self._retry_interval = min(60.0, self._retry_interval * 2.0)
                    return None
            return self._redis_client

    def _extract_token_metadata(self, token: str) -> dict:
        """Decode token payload without verifying expiration to inspect jti/exp/iat/sub."""
        try:
            return jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        except Exception:
            return {}

    def _get_token_identifier(self, payload: dict, token: str) -> str:
        """Get unique jti or sha256 fingerprint of the token string."""
        jti = payload.get("jti")
        if jti:
            return str(jti)
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    MAX_IN_MEMORY_KEYS: int = 10000

    def _prune_memory_store_if_needed(self, now: float | None = None) -> None:
        """Bound in-memory blacklist stores to prevent unbounded memory growth."""
        if now is None:
            now = time.time()
        with self._lock:
            # 1. Prune expired token entries
            expired = [k for k, exp in self._in_memory_revoked.items() if exp <= now]
            for k in expired:
                self._in_memory_revoked.pop(k, None)

            # 2. Bound revoked tokens
            while len(self._in_memory_revoked) >= self.MAX_IN_MEMORY_KEYS:
                oldest = next(iter(self._in_memory_revoked))
                self._in_memory_revoked.pop(oldest, None)

            # 3. Bound user revoked timestamps
            while len(self._in_memory_user_revoked) >= self.MAX_IN_MEMORY_KEYS:
                oldest = next(iter(self._in_memory_user_revoked))
                self._in_memory_user_revoked.pop(oldest, None)

    def revoke_token(self, token: str) -> None:
        """Revoke an active JWT token until its natural expiration."""
        payload = self._extract_token_metadata(token)
        identifier = self._get_token_identifier(payload, token)
        exp = payload.get("exp")
        now = time.time()

        max_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
        if exp:
            ttl = min(max_ttl, max(1, int(exp - now)))
            expiry_ts = now + ttl
        else:
            # Fallback to standard token lifetime if exp not specified
            ttl = min(max_ttl, settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600)
            expiry_ts = now + ttl

        client = self._get_redis()
        if client is not None:
            try:
                client.set(f"blacklist:token:{identifier}", "1", ex=ttl)
                return
            except Exception as exc:
                logger.warning("Redis error setting revoked token, using memory: %s", exc)
                with self._lock:
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = now
                    self._retry_interval = min(60.0, self._retry_interval * 2.0)

        with self._lock:
            self._prune_memory_store_if_needed(now)
            self._in_memory_revoked[identifier] = expiry_ts

    def revoke_all_user_tokens(self, user_identifier: str) -> None:
        """
        Invalidate all tokens issued for a specific user prior to the current timestamp.
        Used upon password change to terminate lingering sessions.
        """
        now = time.time()
        ttl = max(settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600, settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)

        client = self._get_redis()
        if client is not None:
            try:
                client.set(f"blacklist:user:{user_identifier}:revoked_before", str(now), ex=ttl)
                return
            except Exception as exc:
                logger.warning("Redis error revoking user tokens, using memory: %s", exc)
                with self._lock:
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = now
                    self._retry_interval = min(60.0, self._retry_interval * 2.0)

        with self._lock:
            self._prune_memory_store_if_needed(now)
            self._in_memory_user_revoked[user_identifier] = now

    def is_token_revoked(self, token: str) -> bool:
        """Check if a token has been explicitly revoked or invalidated by a user-wide logout."""
        payload = self._extract_token_metadata(token)
        identifier = self._get_token_identifier(payload, token)
        now = time.time()

        client = self._get_redis()
        if client is not None:
            try:
                # 1. Check specific token blacklist
                if client.exists(f"blacklist:token:{identifier}"):
                    return True

                # 2. Check user-wide revocation timestamp
                sub = payload.get("sub")
                if sub:
                    revoked_before_str = client.get(f"blacklist:user:{sub}:revoked_before")
                    if revoked_before_str:
                        revoked_before = float(revoked_before_str)
                        token_iat = float(payload.get("iat", 0))
                        if token_iat < revoked_before:
                            return True
                return False
            except Exception as exc:
                logger.warning("Redis error checking token revocation, checking memory: %s", exc)
                with self._lock:
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = now
                    self._retry_interval = min(60.0, self._retry_interval * 2.0)

        with self._lock:
            # 1. Check specific token
            expiry_ts = self._in_memory_revoked.get(identifier)
            if expiry_ts is not None:
                if expiry_ts > now:
                    return True
                # Clean up expired entry
                del self._in_memory_revoked[identifier]

            # 2. Check user revocation
            sub = payload.get("sub")
            if sub and sub in self._in_memory_user_revoked:
                revoked_before = self._in_memory_user_revoked[sub]
                token_iat = float(payload.get("iat", 0))
                if token_iat < revoked_before:
                    return True

        return False

    def consume_stream_ticket(self, jti: str, ttl: int = 60) -> bool:
        """
        Mark a stream ticket jti as consumed (single-use).
        Returns True if the ticket was successfully consumed (first use).
        Returns False if the ticket was already consumed (replay).
        """
        client = self._get_redis()
        if client is not None:
            try:
                res = client.set(f"stream_ticket:used:{jti}", "1", ex=ttl, nx=True)
                return bool(res)
            except Exception as exc:
                logger.warning("Redis error consuming stream ticket, using memory: %s", exc)
                with self._lock:
                    self._redis_available = False
                    self._redis_client = None
                    self._last_retry_time = time.time()

        with self._lock:
            now = time.time()
            exp = self._in_memory_revoked.get(f"ticket:{jti}")
            if exp is not None and exp > now:
                return False
            self._in_memory_revoked[f"ticket:{jti}"] = now + ttl
            return True

    def reset(self) -> None:
        """Reset blacklist state (for testing)."""
        with self._lock:
            self._in_memory_revoked.clear()
            self._in_memory_user_revoked.clear()

        client = self._get_redis()
        if client is not None:
            try:
                keys = client.keys("blacklist:*")
                ticket_keys = client.keys("stream_ticket:*")
                all_keys = list(keys) + list(ticket_keys)
                if all_keys:
                    client.delete(*all_keys)
            except Exception:
                pass


token_blacklist = TokenBlacklistService()
token_blacklist_service = token_blacklist
