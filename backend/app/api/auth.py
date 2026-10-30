import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import (
    UserCreate,
    Token,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    RequestVerificationRequest,
    OAuthGoogleCallbackRequest,
    OAuthUrlResponse,
    TotpSetupResponse,
    TotpVerifyRequest,
    TotpDisableRequest,
    TotpLoginRequest,
    StreamTicketResponse,
)
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_email_verification_token,
    verify_email_token,
    create_password_reset_token,
    verify_password_reset_token,
    create_oauth_state,
    decode_oauth_state,
    verify_oauth_state,
    validate_password,
    get_current_user,
    get_user_from_token_str,
    oauth2_scheme,
    create_2fa_temp_token,
    verify_2fa_temp_token,
    create_stream_ticket,
)
from app.services.totp import TotpService
from app.services.email import (
    get_email_service,
    build_verification_email,
    build_password_reset_email,
)
from app.services.rate_limiter import rate_limit
from app.services.token_blacklist import token_blacklist
from app.services.audit_logger import log_security_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def _resolve_email_service():
    try:
        import app.api.routes as routes_module
        return getattr(routes_module, "get_email_service", get_email_service)()
    except Exception:
        return get_email_service()


@router.post(
    "/register",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    try:
        validate_password(user_data.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    if not user_data.terms_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must accept the Terms and Conditions and Sheet Music Fair-Use Policy to register"
        )

    # Check if email is already registered before attempting insert
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    hashed_pwd = get_password_hash(user_data.password)
    now = datetime.now(timezone.utc)
    new_user = User(
        email=user_data.email,
        hashed_password=hashed_pwd,
        full_name=user_data.full_name,
        birthdate=user_data.birthdate,
        musical_role=user_data.musical_role,
        country=user_data.country,
        is_verified=False,
        email_notifications_enabled=True,
        terms_accepted=True,
        terms_accepted_at=now,
        terms_version=user_data.terms_version or "2026.1-copyright",
        created_at=now,
        updated_at=now,
    )
    
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Dispatch email verification link upon registration
    try:
        verification_token = create_email_verification_token(new_user.email)
        verification_link = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
        html_body, text_body = build_verification_email(new_user.email, verification_link)
        _resolve_email_service().send_email(
            new_user.email,
            "Verify Your NoteSight Account",
            html_body,
            text_body,
        )
    except Exception as exc:
        logger.warning("Could not dispatch welcome verification email to %s: %s", new_user.email, exc)

    log_security_event("auth.register", user_id=new_user.email, status="SUCCESS")

    return {
        "id": str(new_user.id),
        "email": new_user.email,
        "full_name": new_user.full_name,
        "is_verified": new_user.is_verified,
        "requires_verification": True,
        "message": "Account created. Please check your email to verify your account before logging in.",
    }


@router.post(
    "/token",
    response_model=Token,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user:
        log_security_event("auth.login_failure", user_id=form_data.username, status="FAILURE", details={"reason": "user_not_found"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.hashed_password is None:
        log_security_event("auth.login_failure", user_id=form_data.username, status="FAILURE", details={"reason": "oauth_account"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account was registered using Google OAuth. Please sign in with Google.",
        )
    if not verify_password(form_data.password, user.hashed_password):
        log_security_event("auth.login_failure", user_id=form_data.username, status="FAILURE", details={"reason": "wrong_password"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_verified:
        log_security_event("auth.login_failure", user_id=form_data.username, status="FAILURE", details={"reason": "email_unverified"})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address before signing in.",
        )
    if user.totp_enabled:
        temp_token = create_2fa_temp_token(user.email)
        log_security_event("auth.2fa_challenge_issued", user_id=user.email, status="SUCCESS")
        return {
            "access_token": "",
            "refresh_token": None,
            "token_type": "bearer",
            "requires_2fa": True,
            "temp_token": temp_token,
            "email": user.email,
        }

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})
    log_security_event("auth.login_success", user_id=user.email, status="SUCCESS")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "requires_2fa": False,
        "temp_token": None,
        "email": user.email,
    }


@router.post("/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),
):
    """Revoke the current access token and invalidate user session."""
    token_blacklist.revoke_token(token)
    log_security_event("auth.logout", user_id=current_user.email, status="SUCCESS")
    return {"message": "Successfully logged out"}


@router.post(
    "/refresh-token",
    response_model=Token,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def refresh_access_token(
    data: RefreshTokenRequest | None = None,
    db: Session = Depends(get_db),
):
    """Exchange a valid refresh token for a fresh access token with Refresh Token Rotation (RTR)."""
    token_str = data.refresh_token if (data and data.refresh_token) else None
    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing refresh token. Provide via request body.",
        )

    if token_blacklist.is_token_revoked(token_str):
        log_security_event("auth.token_replay_blocked", status="BLOCKED", details={"reason": "revoked_token_replay"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token_str, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token provided is not a refresh token",
            )
        email = payload.get("sub")
        if not isinstance(email, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token subject",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User associated with token not found",
        )

    # Invalidate the consumed refresh token and issue a rotated pair
    token_blacklist.revoke_token(token_str)
    new_access_token = create_access_token(data={"sub": user.email})
    new_refresh_token = create_refresh_token(data={"sub": user.email})
    log_security_event("auth.token_rotated", user_id=user.email, status="SUCCESS")
    return {"access_token": new_access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}


@router.post(
    "/auth/request-verification",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
@router.post(
    "/request-verification",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def request_email_verification(
    data: RequestVerificationRequest | None = None,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
):
    """Send an account verification email link. Can be requested authenticated or by email."""
    target_email = None
    if authorization and authorization.startswith("Bearer "):
        try:
            curr_user = get_user_from_token_str(authorization[7:], db)
            target_email = curr_user.email
        except Exception:
            pass

    if not target_email and data and data.email:
        target_email = data.email

    if target_email:
        clean_email = target_email.strip().lower()
        if settings.RATE_LIMIT_ENABLED:
            from app.services.rate_limiter import rate_limiter
            email_key = f"ratelimit:resend_verification_email:{clean_email}"
            is_limited, retry_after = rate_limiter.is_rate_limited(email_key, limit=1, window_seconds=60)
            if is_limited:
                log_security_event(
                    "auth.resend_verification_blocked",
                    user_id=clean_email,
                    status="BLOCKED",
                    details={"retry_after": retry_after},
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Please wait {retry_after} seconds before requesting another verification email.",
                    headers={"Retry-After": str(retry_after)},
                )

        user = db.query(User).filter(User.email == target_email).first()
        if user and not user.is_verified:
            v_token = create_email_verification_token(user.email)
            v_link = f"{settings.FRONTEND_URL}/verify-email?token={v_token}"
            html_b, text_b = build_verification_email(user.email, v_link)
            _resolve_email_service().send_email(
                user.email,
                "Verify Your NoteSight Account",
                html_b,
                text_b,
            )
            log_security_event("auth.resend_verification", user_id=user.email, status="SUCCESS")

    return {"message": "Verification link dispatched if the account is unverified."}


@router.post("/auth/verify-email", status_code=status.HTTP_200_OK)
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Validate a cryptographic verification token and mark account as verified."""
    try:
        email = verify_email_token(data.token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found")

    user.is_verified = True
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Email successfully verified!"}


@router.get("/auth/verify-email")
def verify_email_link(token: str = Query(..., description="Email verification token"), db: Session = Depends(get_db)):
    """Direct browser GET link from verification emails redirecting to frontend."""
    try:
        email = verify_email_token(token)
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.is_verified = True
            user.updated_at = datetime.now(timezone.utc)
            db.commit()
            return RedirectResponse(f"{settings.FRONTEND_URL}/verify-email?status=success", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        logger.warning("Email verification GET error: %s", exc)

    return RedirectResponse(f"{settings.FRONTEND_URL}/verify-email?status=error", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Generate expiring, single-use password reset token and send email link."""
    user = db.query(User).filter(User.email == data.email).first()
    if user and user.hashed_password is not None:
        reset_token = create_password_reset_token(user.email)
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
        html_b, text_b = build_password_reset_email(user.email, reset_link)
        _resolve_email_service().send_email(
            user.email,
            "Reset Your NoteSight Password",
            html_b,
            text_b,
        )
    return {"message": "If this email is registered, a password reset link has been sent."}


@router.post(
    "/auth/reset-password",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset user password using valid cryptographic token and revoke existing sessions."""
    try:
        validate_password(data.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        email = verify_password_reset_token(data.token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found")

    user.hashed_password = get_password_hash(data.new_password)
    user.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Invalidate the used token and all previous user sessions
    token_blacklist.revoke_token(data.token)
    token_blacklist.revoke_all_user_tokens(user.email)

    return {"message": "Password successfully reset. You can now log in with your new password."}


def _is_allowed_redirect_uri(redirect_uri: str) -> bool:
    """Validate that custom redirect URI origin is in allowed CORS origins or matches FRONTEND_URL."""
    try:
        parsed = urllib.parse.urlparse(redirect_uri)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed_origins = {orig.rstrip("/") for orig in settings.CORS_ORIGINS if orig}
        if settings.FRONTEND_URL:
            allowed_origins.add(settings.FRONTEND_URL.rstrip("/"))
        return origin.rstrip("/") in allowed_origins
    except Exception:
        return False


def _handle_google_oauth_exchange(code: str, db: Session, redirect_uri: str | None = None) -> User:
    """Exchange authorization code with Google Token API and auto-provision / link User."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server.",
        )

    effective_redirect_uri = redirect_uri or settings.GOOGLE_REDIRECT_URI
    token_url = "https://oauth2.googleapis.com/token"
    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": effective_redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        token_url,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_json = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        logger.error("Google token exchange failed: %s", err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to exchange Google authorization code")
    except Exception as exc:
        logger.error("Google token exchange network error: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Network error contacting Google OAuth services")

    google_access_token = token_json.get("access_token")
    if not google_access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No access token received from Google")

    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    user_req = urllib.request.Request(
        userinfo_url,
        headers={"Authorization": f"Bearer {google_access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(user_req, timeout=10) as resp:
            user_info = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.error("Failed to fetch Google userinfo: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch Google user profile")

    google_sub = user_info.get("sub")
    email = user_info.get("email")
    email_verified = user_info.get("email_verified", True)
    full_name = user_info.get("name") or ""
    avatar_url = user_info.get("picture")

    if not google_sub or not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incomplete profile returned from Google")

    if email_verified is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google account email is not verified")

    user = db.query(User).filter(User.oauth_provider == "google", User.oauth_id == google_sub).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.oauth_provider = "google"
            user.oauth_id = google_sub
            if avatar_url and not user.avatar_url:
                user.avatar_url = avatar_url
            user.is_verified = True
            user.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(user)
            log_security_event("auth.oauth_link_account", user_id=user.email, status="SUCCESS", details={"provider": "google"})
        else:
            now = datetime.now(timezone.utc)
            user = User(
                email=email,
                hashed_password=None,
                full_name=full_name,
                is_verified=True,
                oauth_provider="google",
                oauth_id=google_sub,
                avatar_url=avatar_url,
                terms_accepted=True,
                terms_accepted_at=now,
                terms_version="2026.1-copyright",
                created_at=now,
                updated_at=now,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            log_security_event("auth.oauth_register", user_id=user.email, status="SUCCESS", details={"provider": "google"})

    return user


@router.get("/auth/google/url", response_model=OAuthUrlResponse)
def get_google_auth_url(
    redirect_uri: str | None = Query(None, description="Optional custom callback URI"),
    prompt: str | None = Query(None, description="Optional OAuth prompt behavior (default: select_account)"),
):
    """Generate and return Google OAuth authorization URL with CSRF state token."""
    chosen_redirect_uri = settings.GOOGLE_REDIRECT_URI
    if redirect_uri:
        if _is_allowed_redirect_uri(redirect_uri):
            chosen_redirect_uri = redirect_uri
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Disallowed redirect URI specified for Google OAuth flow.",
            )

    state = create_oauth_state(redirect_uri=chosen_redirect_uri)
    if not settings.GOOGLE_CLIENT_ID:
        return OAuthUrlResponse(url=f"{settings.FRONTEND_URL}/login?oauth_demo=true")

    # Default to 'select_account' so returning users can select their Google account
    # without repeatedly being forced through the consent / review screen.
    valid_prompts = {"select_account", "consent", "none"}
    effective_prompt = prompt if (prompt and prompt in valid_prompts) else "select_account"

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": chosen_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "prompt": effective_prompt,
        "state": state,
    }
    return OAuthUrlResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}")


@router.get("/auth/google/login")
def google_login_redirect(
    redirect_uri: str | None = Query(None),
    prompt: str | None = Query(None),
):
    """Direct 307 redirect to Google's OAuth 2.0 authorization screen."""
    return RedirectResponse(
        get_google_auth_url(redirect_uri=redirect_uri, prompt=prompt).url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.post("/auth/google/callback", response_model=Token)
def google_callback_post(data: OAuthGoogleCallbackRequest, db: Session = Depends(get_db)):
    """Exchange authorization code for NoteSight session tokens via API."""
    if not data.state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state token")

    state_claims = decode_oauth_state(data.state)
    if not state_claims:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state token")

    embedded_redirect_uri = state_claims.get("redirect_uri")
    user = _handle_google_oauth_exchange(data.code, db, redirect_uri=embedded_redirect_uri)
    if user.totp_enabled:
        temp_token = create_2fa_temp_token(user.email)
        log_security_event("auth.2fa_challenge_issued", user_id=user.email, status="SUCCESS", details={"provider": "google"})
        return {
            "access_token": "",
            "refresh_token": None,
            "token_type": "bearer",
            "requires_2fa": True,
            "temp_token": temp_token,
            "email": user.email,
        }

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})
    log_security_event("auth.oauth_login", user_id=user.email, status="SUCCESS", details={"provider": "google"})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "email": user.email}


@router.get("/auth/google/callback")
def google_callback_get(
    code: str = Query(..., description="Google OAuth authorization code"),
    state: str | None = Query(None, description="OAuth state nonce"),
    db: Session = Depends(get_db),
):
    """Direct browser GET callback from Google redirecting to frontend with session tokens."""
    if not state:
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?oauth_error=invalid_state",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    state_claims = decode_oauth_state(state)
    if not state_claims:
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?oauth_error=invalid_state",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    embedded_redirect_uri = state_claims.get("redirect_uri")
    try:
        user = _handle_google_oauth_exchange(code, db, redirect_uri=embedded_redirect_uri)
        frontend_base = settings.FRONTEND_URL
        if embedded_redirect_uri:
            parsed = urllib.parse.urlparse(embedded_redirect_uri)
            if parsed.scheme and parsed.netloc:
                frontend_base = f"{parsed.scheme}://{parsed.netloc}"

        if user.totp_enabled:
            temp_token = create_2fa_temp_token(user.email)
            log_security_event("auth.2fa_challenge_issued", user_id=user.email, status="SUCCESS", details={"provider": "google"})
            target_url = (
                f"{frontend_base}/login"
                f"?requires_2fa=1"
                f"&temp_token={urllib.parse.quote(temp_token)}"
                f"&email={urllib.parse.quote(user.email)}"
            )
            return RedirectResponse(target_url, status_code=status.HTTP_303_SEE_OTHER)

        access_token = create_access_token(data={"sub": user.email})
        refresh_token = create_refresh_token(data={"sub": user.email})
        log_security_event("auth.oauth_login", user_id=user.email, status="SUCCESS", details={"provider": "google"})

        target_url = (
            f"{frontend_base}/auth/google/callback"
            f"#access_token={urllib.parse.quote(access_token)}"
            f"&refresh_token={urllib.parse.quote(refresh_token)}"
            f"&email={urllib.parse.quote(user.email)}"
        )
        return RedirectResponse(target_url, status_code=status.HTTP_303_SEE_OTHER)
    except HTTPException as exc:
        logger.warning("OAuth GET callback error: %s", exc.detail)
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?oauth_error={urllib.parse.quote(str(exc.detail))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        logger.error("OAuth GET callback unhandled error: %s", exc)
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?oauth_error=unknown_error",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post(
    "/auth/2fa/setup",
    response_model=TotpSetupResponse,
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
@router.post(
    "/2fa/setup",
    response_model=TotpSetupResponse,
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
def setup_two_factor_auth(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a new uncommitted TOTP secret, backup codes, and QR code URI."""
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is already enabled. Disable it first before re-enrolling.",
        )

    secret = TotpService.generate_secret()
    backup_codes = TotpService.generate_backup_codes(count=10)
    hashed_backup_codes = [TotpService.hash_backup_code(code) for code in backup_codes]

    current_user.totp_secret = secret
    current_user.totp_backup_codes = json.dumps(hashed_backup_codes)
    db.commit()

    otpauth_uri = TotpService.generate_totp_uri(secret, current_user.email)
    log_security_event("auth.2fa_setup_initiated", user_id=current_user.email, status="SUCCESS")
    return TotpSetupResponse(
        secret=secret,
        otpauth_uri=otpauth_uri,
        backup_codes=backup_codes,
    )


@router.post(
    "/auth/2fa/verify",
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
@router.post(
    "/2fa/verify",
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
def verify_and_enable_two_factor_auth(
    data: TotpVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm a 6-digit TOTP code and activate Two-Factor Authentication."""
    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-Factor Authentication setup has not been initiated. Call /api/auth/2fa/setup first.",
        )

    is_valid = TotpService.verify_code(current_user.totp_secret, data.code, user_id=current_user.id)
    if not is_valid:
        log_security_event("auth.2fa_enable_failed", user_id=current_user.email, status="FAILURE", details={"reason": "invalid_code"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authentication code. Please check your authenticator app and try again.",
        )

    current_user.totp_enabled = True
    db.commit()
    log_security_event("auth.2fa_enabled", user_id=current_user.email, status="SUCCESS")
    return {"message": "Two-Factor Authentication successfully enabled."}


@router.post(
    "/auth/2fa/disable",
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
@router.post(
    "/2fa/disable",
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
def disable_two_factor_auth(
    data: TotpDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable Two-Factor Authentication after verifying the user's password or current TOTP code."""
    if current_user.hashed_password is not None:
        if not verify_password(data.password, current_user.hashed_password):
            log_security_event("auth.2fa_disable_failed", user_id=current_user.email, status="FAILURE", details={"reason": "invalid_password"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incorrect password.",
            )
    elif data.code and current_user.totp_secret:
        if not TotpService.verify_code(current_user.totp_secret, data.code, user_id=current_user.id):
            log_security_event("auth.2fa_disable_failed", user_id=current_user.email, status="FAILURE", details={"reason": "invalid_code"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid authentication code.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password or authentication code required to disable 2FA.",
        )

    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.totp_backup_codes = None
    db.commit()
    log_security_event("auth.2fa_disabled", user_id=current_user.email, status="SUCCESS")
    return {"message": "Two-Factor Authentication successfully disabled."}


@router.post(
    "/auth/2fa/login",
    response_model=Token,
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
@router.post(
    "/2fa/login",
    response_model=Token,
    dependencies=[Depends(rate_limit(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60, scope="ip"))],
)
def login_with_two_factor_auth(
    data: TotpLoginRequest,
    db: Session = Depends(get_db),
):
    """Complete login using a temporary 2FA token and either a 6-digit TOTP or an 8-character backup recovery code."""
    email = verify_2fa_temp_token(data.temp_token)
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.totp_enabled or not user.totp_secret:
        log_security_event("auth.2fa_login_failed", user_id=email, status="FAILURE", details={"reason": "2fa_not_active"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-Factor Authentication is not enabled for this account.",
        )

    clean_code = data.code.strip()
    is_valid = False
    used_backup = False

    if len(clean_code.replace(" ", "").replace("-", "")) == 6 and clean_code.replace(" ", "").replace("-", "").isdigit():
        is_valid = TotpService.verify_code(user.totp_secret, clean_code, user_id=user.id)

    if not is_valid and user.totp_backup_codes:
        try:
            stored_hashes = json.loads(user.totp_backup_codes)
            matched, updated_hashes = TotpService.verify_and_consume_backup_code(clean_code, stored_hashes)
            if matched:
                is_valid = True
                used_backup = True
                user.totp_backup_codes = json.dumps(updated_hashes)
                db.commit()
        except Exception as e:
            logger.error("Failed to parse or verify backup codes: %s", e)

    if not is_valid:
        fail_count = TotpService.record_temp_token_failure(data.temp_token)
        if fail_count >= 5:
            token_blacklist.revoke_token(data.temp_token)
            log_security_event("auth.2fa_temp_token_invalidated", user_id=email, status="BLOCKED", details={"reason": "too_many_failed_attempts"})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Too many failed attempts. Temporary token invalidated, please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        log_security_event("auth.2fa_login_failed", user_id=email, status="FAILURE", details={"reason": "invalid_code", "attempt": fail_count})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication code or backup recovery code.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_blacklist.revoke_token(data.temp_token)

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})
    log_security_event(
        "auth.2fa_login_success",
        user_id=user.email,
        status="SUCCESS",
        details={"used_backup_code": used_backup},
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "requires_2fa": False,
        "temp_token": None,
        "email": user.email,
    }


@router.post(
    "/auth/stream-ticket",
    response_model=StreamTicketResponse,
    dependencies=[Depends(rate_limit(scope="user"))],
)
@router.post(
    "/stream-ticket",
    response_model=StreamTicketResponse,
    dependencies=[Depends(rate_limit(scope="user"))],
)
def issue_stream_ticket(
    current_user: User = Depends(get_current_user),
):
    """Issue a 60-second single-use stream ticket for SSE, WebSocket, and file preview URLs."""
    ticket = create_stream_ticket(current_user)
    return StreamTicketResponse(
        ticket=ticket,
        token=ticket,
        stream_ticket=ticket,
        expires_in=60,
    )

