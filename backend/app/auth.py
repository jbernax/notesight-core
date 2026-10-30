import re
import bcrypt
from datetime import datetime, timedelta, timezone
import jwt
from app.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

def validate_password(password: str) -> bool:
    """
    Validates that a password meets complexity requirements:
    - At least 8 characters long
    - At least one uppercase letter
    - At least one number
    - At least one special character
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if len(password) > 128:
        raise ValueError("Password cannot exceed 128 characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one special character")
    return True

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(plain_bytes, hashed_bytes)

import uuid
from app.services.token_blacklist import token_blacklist

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Inject jti (JWT ID) and iat (issued at) for token tracking and blacklisting
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())
    if "iat" not in to_encode:
        to_encode["iat"] = now.timestamp()
        
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())
    if "iat" not in to_encode:
        to_encode["iat"] = now.timestamp()

    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
import jwt.exceptions

import logging

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

def get_user_from_token_str(token: str, db: Session, allow_stream_ticket: bool = False) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    revoked_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token has been revoked",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token_blacklist.is_token_revoked(token):
        raise revoked_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("type")
        purpose = payload.get("purpose")

        is_stream_ticket = token_type == "stream_ticket" or purpose == "stream_ticket"
        if is_stream_ticket:
            if not allow_stream_ticket:
                logger.warning("Stream ticket rejected for standard endpoint")
                raise credentials_exception
            jti = payload.get("jti")
            if not jti:
                raise credentials_exception
            exp = payload.get("exp")
            now = datetime.now(timezone.utc).timestamp()
            ttl = max(1, int(exp - now)) if exp else 60
            if not token_blacklist.consume_stream_ticket(str(jti), ttl=ttl):
                logger.warning("Stream ticket %s was already consumed (replay prevented)", jti)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Stream ticket has already been used or expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        elif token_type != "access":
            # Enforce strict token type: prevent refresh/verification/reset token confusion
            logger.warning("Token type confusion blocked: received type '%s', expected 'access'", token_type)
            raise credentials_exception

        email = payload.get("sub")
        if not isinstance(email, str):
            raise credentials_exception
    except jwt.exceptions.InvalidTokenError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return get_user_from_token_str(token, db)


optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token", auto_error=False)


def get_optional_current_user(
    token: str | None = Depends(optional_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if not token:
        return None
    try:
        return get_user_from_token_str(token, db)
    except Exception:
        return None


def create_email_verification_token(email: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT token for email address verification (valid for 24 hours)."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=24))
    to_encode = {
        "sub": email,
        "type": "email_verification",
        "jti": str(uuid.uuid4()),
        "iat": now.timestamp(),
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_2fa_temp_token(email: str, expires_delta: timedelta | None = None) -> str:
    """Create a temporary signed token for completing 2FA challenge (valid for 5 minutes)."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=5))
    to_encode = {
        "sub": email,
        "type": "2fa_temp",
        "jti": str(uuid.uuid4()),
        "iat": now.timestamp(),
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_2fa_temp_token(token: str) -> str:
    """Verify temporary 2FA token and return user email."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired 2FA verification session",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token_blacklist.is_token_revoked(token):
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "2fa_temp":
            raise credentials_exception
        email = payload.get("sub")
        if not isinstance(email, str):
            raise credentials_exception
        return email
    except jwt.exceptions.InvalidTokenError:
        raise credentials_exception


def verify_email_token(token: str) -> str:
    """Decode and validate an email verification token, returning the user email."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "email_verification":
            raise ValueError("Invalid token type for email verification")
        email = payload.get("sub")
        if not email or not isinstance(email, str):
            raise ValueError("Token does not contain a valid email address")
        return email
    except jwt.ExpiredSignatureError:
        raise ValueError("Verification link has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid verification token.")


def create_password_reset_token(email: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT token for password reset (valid for 1 hour)."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=1))
    to_encode = {
        "sub": email,
        "type": "password_reset",
        "jti": str(uuid.uuid4()),
        "iat": now.timestamp(),
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_password_reset_token(token: str) -> str:
    """Validate a password reset token, checking for revocation and expiration."""
    if token_blacklist.is_token_revoked(token):
        raise ValueError("This password reset link has already been used or revoked.")

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            raise ValueError("Invalid token type for password reset")
        email = payload.get("sub")
        if not email or not isinstance(email, str):
            raise ValueError("Token does not contain a valid user identity")
        return email
    except jwt.ExpiredSignatureError:
        raise ValueError("Password reset link has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid or malformed password reset link.")


def create_oauth_state(redirect_uri: str | None = None) -> str:
    """Create a cryptographically signed OAuth state nonce with optional redirect_uri."""
    now = datetime.now(timezone.utc)
    to_encode = {
        "nonce": uuid.uuid4().hex,
        "type": "oauth_state",
        "redirect_uri": redirect_uri,
        "iat": now.timestamp(),
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_oauth_state(state: str) -> dict | None:
    """Validate signature and decode OAuth state claims."""
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") == "oauth_state":
            return payload
        return None
    except Exception:
        return None


def verify_oauth_state(state: str) -> bool:
    """Verify validity and signature of OAuth state token."""
    return decode_oauth_state(state) is not None


def create_stream_ticket(user: User, expires_delta: timedelta | None = None) -> str:
    """Create a 60-second single-use JWT stream ticket for SSE, WebSocket, and file preview URLs."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(seconds=60))
    to_encode = {
        "sub": user.email,
        "type": "stream_ticket",
        "purpose": "stream_ticket",
        "jti": str(uuid.uuid4()),
        "iat": now.timestamp(),
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)




