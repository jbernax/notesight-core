"""RFC 6238 / RFC 4226 TOTP (Time-Based One-Time Password) Service.

Implements pure standard-library TOTP generation, validation, and backup recovery codes
with zero external runtime dependencies.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import struct
import threading
import time
import urllib.parse
import uuid
from typing import List, Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings

logger = logging.getLogger(__name__)


class TotpService:
    """Service providing RFC 6238 TOTP generation, verification, and backup codes."""

    TIME_STEP: int = 30  # 30-second time intervals per RFC 6238
    DIGITS: int = 6      # Standard 6-digit one-time passcodes
    ISSUER: str = "NoteSight"

    _redis_client: Optional[object] = None
    _redis_available: bool = True
    _last_redis_retry: float = 0.0
    _lock = threading.Lock()
    _in_memory_consumed: dict[str, float] = {}

    @classmethod
    def _get_redis(cls):
        with cls._lock:
            now = time.time()
            if not cls._redis_available:
                if now - cls._last_redis_retry < 10.0:
                    return None
                cls._last_redis_retry = now

            if cls._redis_client is None:
                try:
                    import redis
                    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                    client.ping()
                    cls._redis_client = client
                    cls._redis_available = True
                except Exception as e:
                    cls._redis_available = False
                    cls._redis_client = None
                    cls._last_redis_retry = now
                    return None
            return cls._redis_client

    @classmethod
    def _is_counter_consumed(cls, user_id: str | int | uuid.UUID, counter: int) -> bool:
        redis_client = cls._get_redis()
        key = f"totp:used:{user_id}:{counter}"
        if redis_client is not None:
            try:
                acquired = redis_client.set(key, "1", ex=90, nx=True)
                return not acquired
            except Exception as e:
                logger.warning("Redis error checking TOTP replay, falling back to memory: %s", e)
                cls._redis_available = False
                cls._redis_client = None

        with cls._lock:
            now = time.time()
            # purge expired entries
            cls._in_memory_consumed = {k: exp for k, exp in cls._in_memory_consumed.items() if exp > now}
            if key in cls._in_memory_consumed:
                return True
            cls._in_memory_consumed[key] = now + 90.0
            return False

    @classmethod
    def _get_fernet(cls) -> Fernet:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
        return Fernet(key)

    @classmethod
    def encrypt_secret(cls, plain_secret: str) -> str:
        """Encrypt TOTP secret using authenticated symmetric encryption (Fernet)."""
        if not plain_secret:
            return plain_secret
        fernet = cls._get_fernet()
        try:
            fernet.decrypt(plain_secret.encode("utf-8"))
            return plain_secret
        except Exception:
            pass
        return fernet.encrypt(plain_secret.encode("utf-8")).decode("utf-8")

    @classmethod
    def decrypt_secret(cls, cipher_or_plain: str) -> str:
        """Decrypt TOTP secret with transparent fallback for legacy plaintext secrets."""
        if not cipher_or_plain:
            return cipher_or_plain
        try:
            fernet = cls._get_fernet()
            return fernet.decrypt(cipher_or_plain.encode("utf-8")).decode("utf-8")
        except (InvalidToken, Exception):
            return cipher_or_plain

    @classmethod
    def record_temp_token_failure(cls, temp_token: str) -> int:
        """Record a failed 2FA verification attempt against a temp_token.
        Returns the new failure count.
        """
        token_hash = hashlib.sha256(temp_token.encode("utf-8")).hexdigest()
        key = f"totp:failed:{token_hash}"
        redis_client = cls._get_redis()
        if redis_client is not None:
            try:
                count = redis_client.incr(key)
                if count == 1:
                    redis_client.expire(key, 300)
                return count
            except Exception as e:
                logger.warning("Redis error incrementing 2FA failure: %s", e)
                cls._redis_available = False
                cls._redis_client = None

        with cls._lock:
            current = cls._in_memory_consumed.get(key, 0.0)
            new_count = int(current) + 1
            cls._in_memory_consumed[key] = float(new_count)
            return new_count

    @staticmethod
    def generate_secret(byte_length: int = 20) -> str:
        """Generate a cryptographically secure Base32 secret string (160 bits)."""
        random_bytes = secrets.token_bytes(byte_length)
        # Base32 standard encoding without padding for maximum authenticator compatibility
        return base64.b32encode(random_bytes).decode("ascii").rstrip("=")

    @classmethod
    def generate_totp_uri(cls, secret: str, account_email: str, issuer: str | None = None) -> str:
        """Generate standard otpauth:// URI for authenticator QR codes (Google Authenticator, Authy, 1Password)."""
        app_issuer = issuer or cls.ISSUER
        encoded_issuer = urllib.parse.quote(app_issuer)
        encoded_account = urllib.parse.quote(account_email)
        label = f"{encoded_issuer}:{encoded_account}"

        params = {
            "secret": secret.strip().upper(),
            "issuer": app_issuer,
            "algorithm": "SHA1",
            "digits": str(cls.DIGITS),
            "period": str(cls.TIME_STEP),
        }
        query_string = urllib.parse.urlencode(params)
        return f"otpauth://totp/{label}?{query_string}"

    @classmethod
    def compute_totp(cls, secret: str, timestamp: float | None = None) -> str:
        """Compute the 6-digit TOTP code for a given timestamp (defaults to current time)."""
        if timestamp is None:
            timestamp = time.time()

        counter = int(timestamp // cls.TIME_STEP)
        return cls._compute_hotp(secret, counter)

    @classmethod
    def verify_code(
        cls,
        secret: str,
        code: str,
        window: int = 1,
        timestamp: float | None = None,
        user_id: str | int | uuid.UUID | None = None,
    ) -> bool:
        """Verify a user-provided 6-digit TOTP code against a secret.

        Allows a clock drift window (default 1 = +/- 30 seconds).
        Uses constant-time comparison to prevent timing attacks.
        Prevents replay attacks within window when user_id is provided.
        """
        if not secret or not code:
            return False

        clean_code = code.strip().replace(" ", "").replace("-", "")
        if len(clean_code) != cls.DIGITS or not clean_code.isdigit():
            return False

        if timestamp is None:
            timestamp = time.time()

        current_counter = int(timestamp // cls.TIME_STEP)

        # Check [counter - window, counter + window]
        for offset in range(-window, window + 1):
            counter = current_counter + offset
            expected_code = cls._compute_hotp(secret, counter)
            if hmac.compare_digest(clean_code, expected_code):
                if user_id is not None:
                    if cls._is_counter_consumed(user_id, counter):
                        logger.warning("Replayed TOTP code rejected for user_id=%s, counter=%s", user_id, counter)
                        return False
                return True

        return False

    @staticmethod
    def generate_backup_codes(count: int = 10) -> List[str]:
        """Generate formatted human-readable backup recovery codes (e.g. 'a1b2-c3d4')."""
        codes: List[str] = []
        for _ in range(count):
            token = secrets.token_hex(4)  # 8 hex characters
            formatted = f"{token[:4]}-{token[4:]}".upper()
            codes.append(formatted)
        return codes

    @staticmethod
    def hash_backup_code(code: str) -> str:
        """Compute SHA-256 hash of a normalized backup code."""
        normalized = code.strip().upper().replace("-", "").replace(" ", "")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def verify_and_consume_backup_code(
        cls, plain_code: str, hashed_codes: List[str]
    ) -> Tuple[bool, List[str]]:
        """Verify an entered backup code against the user's stored list of hashed codes.

        If valid, removes the consumed code from the list and returns (True, updated_hashed_codes).
        """
        if not plain_code or not hashed_codes:
            return False, hashed_codes

        target_hash = cls.hash_backup_code(plain_code)
        updated_codes = []
        code_matched = False

        for stored_hash in hashed_codes:
            if not code_matched and hmac.compare_digest(target_hash, stored_hash):
                code_matched = True
                # Skip adding this code, effectively consuming it
                continue
            updated_codes.append(stored_hash)

        return code_matched, updated_codes

    @classmethod
    def _compute_hotp(cls, secret: str, counter: int) -> str:
        """Compute RFC 4226 HMAC-based One-Time Password."""
        # Normalize secret: uppercase and add required base32 padding
        normalized_secret = secret.strip().upper().replace(" ", "")
        missing_padding = len(normalized_secret) % 8
        if missing_padding != 0:
            normalized_secret += "=" * (8 - missing_padding)

        try:
            key = base64.b32decode(normalized_secret, casefold=True)
        except Exception:
            return ""

        # 8-byte big-endian integer counter
        counter_bytes = struct.pack(">Q", counter)

        # HMAC-SHA1 computation
        mac = hmac.new(key, counter_bytes, hashlib.sha1).digest()

        # Dynamic truncation (RFC 4226 section 5.4)
        offset = mac[-1] & 0x0F
        binary = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF

        # Modulo 10^digits
        otp = binary % (10**cls.DIGITS)
        return f"{otp:0{cls.DIGITS}d}"
