import logging
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Job, User, UserTier
from app.schemas import (
    AccountDeletionRequest,
    ChangePasswordRequest,
    LegalTermsResponse,
    LegalTermsSection,
    QuotaPagesInfo,
    QuotaStorageInfo,
    TierDetail,
    UpdateTierRequest,
    UserProfileResponse,
    UserProfileUpdate,
    UserQuotaResponse,
)
from app.auth import (
    get_current_user,
    get_password_hash,
    validate_password,
    verify_password,
)
from app.services.audit_logger import log_security_event
from app.services.quota import (
    get_all_tier_configs,
    get_tier_config,
    get_user_pages_processed_this_month,
    get_user_storage_bytes,
)
from app.services.storage import get_storage_service
from app.services.token_blacklist import token_blacklist

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.get("/legal/terms", response_model=LegalTermsResponse)
def get_legal_terms() -> LegalTermsResponse:
    """Retrieve current NoteSight Terms of Service, Acceptable Use, and Sheet Music Copyright Policy."""
    return LegalTermsResponse(
        version="2026.1-copyright",
        effective_date="October 2026",
        title="NoteSight Terms of Service & Sheet Music Copyright Compliance",
        summary="By registering an account and using NoteSight, you agree to these Terms. NoteSight provides neural optical music recognition and playback tools solely for lawful, authorized, or public domain musical works.",
        sections=[
            LegalTermsSection(
                title="1. Lawful Use & Sheet Music Copyright Authorization",
                content="You affirm, represent, and warrant that you either own the copyright, possess an explicit license from the copyright owner, or are transcribing musical scores that reside in the public domain or qualify under statutory fair use in your jurisdiction. NoteSight strictly prohibits unauthorized copying, digitization, or reproduction of copyrighted sheet music without authorization."
            ),
            LegalTermsSection(
                title="2. Acceptable Use Policy & Prevention of Piracy",
                content="You agree not to use NoteSight to digitize, upload, export, or distribute sheet music in any manner that infringes on third-party intellectual property rights. Any attempt to use NoteSight to bypass digital rights management (DRM), mass-scrape protected score catalogs, or facilitate illegal score sharing will result in immediate termination of the account and potential reporting to rightsholders."
            ),
            LegalTermsSection(
                title="3. User Representations & Age Requirement",
                content="You must be at least 13 years of age (or the applicable age of digital consent in your jurisdiction) to register an account. You agree to provide accurate, current, and complete registration information."
            ),
            LegalTermsSection(
                title="4. Optional Billing & Subscription Tiers",
                content="Access to basic NoteSight OMR processing is available under our free Starter plan without requiring billing or payment information. Should you choose to upgrade to a paid tier (Virtuoso or Maestro), payments are processed securely via Stripe. Billing information is optional until a paid subscription is selected."
            ),
            LegalTermsSection(
                title="5. Disclaimer of Warranties & AI Transcription Limitations",
                content="Neural optical music recognition produces algorithmic estimations of musical notation. NoteSight provides score transcription on an 'as is' and 'as available' basis. Users are advised to review and verify transcribed notation before performance, publishing, or commercial use."
            ),
            LegalTermsSection(
                title="6. Open-Source Attribution & OMR Engine Source Availability",
                content="NoteSight's optical music recognition inference is powered by the standalone open-source package notesight-omr-engine (built on homr), licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-or-later) and executed as an isolated CLI subprocess. In accordance with AGPL-3.0 Section 13, the complete Corresponding Source code for notesight-omr-engine is publicly available at packages/notesight-omr-engine. Server-side PDF rendering and engraving utilize pypdfium2 (Apache-2.0/BSD-3-Clause), pypdf (BSD-3-Clause), Verovio (LGPL-3.0), and CairoSVG (LGPL-3.0); browser notation rendering uses OpenSheetMusicDisplay (BSD-3-Clause)."
            )
        ]
    )



@router.get("/user/profile", response_model=UserProfileResponse)
def get_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Retrieve full user profile details, legal acceptance record, and optional billing summary."""
    billing_name = current_user.billing_customer.billing_name if current_user.billing_customer else None
    billing_country = current_user.billing_customer.billing_country if current_user.billing_customer else None
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name or "",
        birthdate=current_user.birthdate,
        musical_role=current_user.musical_role,
        country=current_user.country,
        bio=current_user.bio,
        is_verified=current_user.is_verified,
        oauth_provider=current_user.oauth_provider,
        avatar_url=current_user.avatar_url,
        email_notifications_enabled=current_user.email_notifications_enabled,
        allow_omr_telemetry=current_user.allow_omr_telemetry,
        totp_enabled=current_user.totp_enabled,
        tier=current_user.tier,
        terms_accepted=current_user.terms_accepted,
        terms_accepted_at=current_user.terms_accepted_at,
        terms_version=current_user.terms_version,
        created_at=current_user.created_at,
        has_billing_customer=current_user.billing_customer is not None,
        billing_name=billing_name,
        billing_country=billing_country,
    )


@router.patch("/user/profile", response_model=UserProfileResponse)
def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Update user personal and musical profile settings."""
    if profile_data.full_name is not None:
        cleaned_name = profile_data.full_name.strip()
        if len(cleaned_name) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full name must be at least 2 characters")
        current_user.full_name = cleaned_name
    if profile_data.birthdate is not None:
        current_user.birthdate = profile_data.birthdate
    if profile_data.musical_role is not None:
        current_user.musical_role = profile_data.musical_role.strip() or None
    if profile_data.country is not None:
        current_user.country = profile_data.country.strip() or None
    if profile_data.bio is not None:
        current_user.bio = profile_data.bio.strip() or None
    if profile_data.avatar_url is not None:
        current_user.avatar_url = profile_data.avatar_url.strip() or None
    if profile_data.email_notifications_enabled is not None:
        current_user.email_notifications_enabled = profile_data.email_notifications_enabled
    if profile_data.allow_omr_telemetry is not None:
        current_user.allow_omr_telemetry = profile_data.allow_omr_telemetry

    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)
    return get_user_profile(current_user=current_user, db=db)


@router.post("/user/change-password", status_code=status.HTTP_200_OK)
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Securely update the authenticated user's password."""
    if current_user.hashed_password is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password modification is not available for accounts registered through Google OAuth.",
        )
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    if data.current_password == data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )
    try:
        validate_password(data.new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    current_user.hashed_password = get_password_hash(data.new_password)
    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()
    token_blacklist.revoke_all_user_tokens(current_user.email)
    log_security_event("auth.password_changed", user_id=current_user.email, status="SUCCESS")
    return {"message": "Password updated successfully"}


@router.delete("/user/account", status_code=status.HTTP_200_OK)
def delete_user_account(
    data: AccountDeletionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Permanently delete the user's account and all associated score files and records (GDPR Right to Erasure).
    Requires current password verification for password accounts; OAuth users verify via active session.
    """
    if current_user.hashed_password is not None:
        if not data.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required to confirm account deletion.",
            )
        if not verify_password(data.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incorrect password verification.",
            )

    storage_service = get_storage_service()

    # 1. Clean up all storage files for the user's jobs
    user_jobs = db.query(Job).filter(Job.user_id == current_user.id).all()
    for j in user_jobs:
        if j.file_path:
            storage_service.delete_file(j.file_path)
        if j.result_file_path:
            storage_service.delete_file(j.result_file_path)
            rpath = Path(j.result_file_path)
            for ext in (".pdf", ".mid"):
                storage_service.delete_file(str(rpath.with_suffix(ext)))
        if j.raw_prediction_path:
            storage_service.delete_file(j.raw_prediction_path)

    # 2. Invalidate user tokens in blacklist
    user_email = current_user.email
    user_id_str = str(current_user.id)
    token_blacklist.revoke_all_user_tokens(user_email)
    token_blacklist.revoke_all_user_tokens(user_id_str)

    # 3. Log security event
    log_security_event("user.account_deleted", user_id=user_email, status="SUCCESS")

    # 4. Delete user record (cascades to jobs, annotations, shares, usage, customer)
    db.delete(current_user)
    db.commit()

    return {"status": "success", "message": "Account and all associated data permanently deleted"}


def build_user_quota_response(user: User, db: Session) -> UserQuotaResponse:
    from app.services.billing_service import sync_and_expire_subscription
    from app.schemas import SubscriptionInfo
    from app.models import BillingCustomer, Subscription

    sub = sync_and_expire_subscription(user, db)
    if not sub:
        customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == user.id).first()
        if customer:
            sub = (
                db.query(Subscription)
                .filter(Subscription.customer_id == customer.id)
                .order_by(Subscription.created_at.desc())
                .first()
            )

    sub_info: SubscriptionInfo | None = None
    is_grace_period_active = False
    if sub:
        from app.services.billing_service import _ensure_utc
        now = datetime.now(timezone.utc)
        sub_info = SubscriptionInfo(
            id=str(sub.id),
            tier=sub.tier.value,
            status=sub.status.value,
            current_period_start=_ensure_utc(sub.current_period_start).isoformat(),
            current_period_end=_ensure_utc(sub.current_period_end).isoformat(),
            cancel_at_period_end=sub.cancel_at_period_end,
            pending_tier=sub.pending_tier.value if sub.pending_tier else None,
            downgrade_scheduled_at=_ensure_utc(sub.downgrade_scheduled_at).isoformat() if sub.downgrade_scheduled_at else None,
        )
        is_grace_period_active = bool(sub.cancel_at_period_end and _ensure_utc(sub.current_period_end) > now)

    tier_config = get_tier_config(user.tier)
    used_bytes = get_user_storage_bytes(user.id, db)
    used_mb = round(used_bytes / (1024 * 1024), 2)
    percent_used = (
        round((used_bytes / tier_config.storage_limit_bytes) * 100, 1)
        if tier_config.storage_limit_bytes > 0
        else 0.0
    )

    pages_month = get_user_pages_processed_this_month(user.id, db)
    remaining_pages = max(0, tier_config.monthly_page_limit - pages_month)

    all_tiers = [
        TierDetail(
            id=t.id,
            name=t.name,
            display_name=t.display_name,
            tagline=t.tagline,
            storage_limit_mb=t.storage_limit_mb,
            max_pages_per_score=t.max_pages_per_score,
            monthly_page_limit=t.monthly_page_limit,
            price=t.price,
            features=t.features,
        )
        for t in get_all_tier_configs()
    ]

    return UserQuotaResponse(
        user_id=user.id,
        email=user.email,
        tier=user.tier,
        tier_name=tier_config.display_name,
        storage=QuotaStorageInfo(
            used_bytes=used_bytes,
            used_mb=used_mb,
            limit_bytes=tier_config.storage_limit_bytes,
            limit_mb=tier_config.storage_limit_mb,
            percent_used=min(100.0, percent_used),
        ),
        pages=QuotaPagesInfo(
            max_per_score=tier_config.max_pages_per_score,
            processed_this_month=pages_month,
            monthly_limit=tier_config.monthly_page_limit,
            remaining_this_month=remaining_pages,
        ),
        available_tiers=all_tiers,
        subscription=sub_info,
        is_grace_period_active=is_grace_period_active,
    )


@router.get("/user/quota", response_model=UserQuotaResponse)
def get_current_user_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserQuotaResponse:
    """Retrieve current subscription tier, storage quota usage, page allowances, and catalog of plans."""
    return build_user_quota_response(current_user, db)


@router.post("/user/tier", response_model=UserQuotaResponse)
@router.patch("/user/tier", response_model=UserQuotaResponse)
def update_user_tier(
    tier_data: UpdateTierRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserQuotaResponse:
    """Update user subscription tier (self-service downgrade to starter with grace period, or upgrade in mock mode)."""
    from app.services.billing_service import is_stripe_configured, schedule_subscription_downgrade, TIER_RANKS

    requested_tier = UserTier.VIRTUOSO if tier_data.tier == UserTier.MAESTRO else tier_data.tier
    current_tier = UserTier.VIRTUOSO if current_user.tier == UserTier.MAESTRO else current_user.tier

    # If this is a downgrade from a paid tier, do not strip benefits immediately: schedule it!
    if TIER_RANKS.get(requested_tier, 0) < TIER_RANKS.get(current_tier, 0):
        schedule_subscription_downgrade(current_user, requested_tier, db)
        return build_user_quota_response(current_user, db)

    # Direct upgrades require Stripe checkout if live payments are configured
    if requested_tier != UserTier.STARTER and (is_stripe_configured() or settings.ENVIRONMENT in ("production", "prod")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direct tier upgrades are disabled when payment processing is active. Please upgrade via /api/billing/create-checkout-session.",
        )

    current_user.tier = requested_tier
    db.commit()
    db.refresh(current_user)
    return build_user_quota_response(current_user, db)
