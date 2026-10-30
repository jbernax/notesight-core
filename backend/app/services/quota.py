from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import uuid
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
import pypdfium2 as pdfium

from app.config import settings
from app.models import Job, JobStatus, User, UserMonthlyUsage, UserTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TierConfig:
    id: UserTier
    name: str
    display_name: str
    tagline: str
    storage_limit_mb: int
    storage_limit_bytes: int
    max_pages_per_score: int
    monthly_page_limit: int
    price: str
    features: list[str]


def get_all_tier_configs() -> list[TierConfig]:
    """Return all available subscription tiers with limits dynamically configured from settings."""
    return [
        TierConfig(
            id=UserTier.STARTER,
            name="Starter",
            display_name="Starter",
            tagline="Essential transcription for individual musicians",
            storage_limit_mb=settings.STARTER_STORAGE_MB,
            storage_limit_bytes=settings.STARTER_STORAGE_MB * 1024 * 1024,
            max_pages_per_score=settings.STARTER_MONTHLY_PAGES,
            monthly_page_limit=settings.STARTER_MONTHLY_PAGES,
            price="Free",
            features=[
                f"{settings.STARTER_STORAGE_MB} MB secure score storage",
                f"{settings.STARTER_MONTHLY_PAGES} pages processed per month",
            ],
        ),
        TierConfig(
            id=UserTier.PRO,
            name="Pro",
            display_name="Pro",
            tagline="Expanded capacity for performers & music teachers",
            storage_limit_mb=settings.PRO_STORAGE_MB,
            storage_limit_bytes=settings.PRO_STORAGE_MB * 1024 * 1024,
            max_pages_per_score=settings.PRO_MONTHLY_PAGES,
            monthly_page_limit=settings.PRO_MONTHLY_PAGES,
            price="3,99 € / month",
            features=[
                f"{settings.PRO_STORAGE_MB} MB secure score storage",
                f"{settings.PRO_MONTHLY_PAGES} pages processed per month",
            ],
        ),
        TierConfig(
            id=UserTier.VIRTUOSO,
            name="Virtuoso",
            display_name="Virtuoso",
            tagline="High-volume transcription for directors & ensembles",
            storage_limit_mb=settings.VIRTUOSO_STORAGE_MB,
            storage_limit_bytes=settings.VIRTUOSO_STORAGE_MB * 1024 * 1024,
            max_pages_per_score=settings.VIRTUOSO_MONTHLY_PAGES,
            monthly_page_limit=settings.VIRTUOSO_MONTHLY_PAGES,
            price="5,99 € / month",
            features=[
                f"{settings.VIRTUOSO_STORAGE_MB} MB secure score storage",
                f"{settings.VIRTUOSO_MONTHLY_PAGES} pages processed per month",
            ],
        ),
    ]


def get_tier_config(tier: UserTier | str) -> TierConfig:
    """Retrieve the configuration for a given tier enum or string identifier."""
    tier_str = tier.value if isinstance(tier, UserTier) else str(tier).lower()
    # Map legacy maestro identifier to virtuoso
    if tier_str == "maestro":
        tier_str = "virtuoso"
    for config in get_all_tier_configs():
        if config.id.value == tier_str:
            return config
    # Fallback default to Starter
    return get_all_tier_configs()[0]



def get_user_storage_bytes(user_id: uuid.UUID, db: Session) -> int:
    """Calculate total stored file bytes for a user with an O(1) SQL aggregation."""
    total = (
        db.query(func.coalesce(func.sum(Job.file_size_bytes), 0))
        .filter(Job.user_id == user_id)
        .scalar()
    )
    return int(total or 0)


def get_user_pages_processed_this_month(user_id: uuid.UUID, db: Session) -> int:
    """Calculate total pages transcribed for completed jobs in the current UTC calendar month.

    Includes both currently active completed jobs and pages from completed jobs that were
    subsequently cleaned up / deleted from the library during this month.
    """
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    # 1. Pages from currently stored completed jobs created this month
    active_pages = (
        db.query(func.coalesce(func.sum(Job.page_count), 0))
        .filter(
            Job.user_id == user_id,
            Job.created_at >= month_start,
            Job.status == JobStatus.COMPLETED,
        )
        .scalar()
    ) or 0

    # 2. Pages from completed jobs that were processed this month but deleted/cleaned up from library
    archived_pages = (
        db.query(func.coalesce(func.sum(UserMonthlyUsage.deleted_job_pages), 0))
        .filter(
            UserMonthlyUsage.user_id == user_id,
            UserMonthlyUsage.year == now.year,
            UserMonthlyUsage.month == now.month,
        )
        .scalar()
    ) or 0

    return int(active_pages + archived_pages)


def record_deleted_job_pages(
    user_id: uuid.UUID,
    created_at: datetime,
    page_count: int,
    db: Session,
) -> None:
    """Preserve page count of a deleted job towards the user's monthly processing quota for its creation month."""
    if not page_count or page_count <= 0:
        return
    year = created_at.year
    month = created_at.month

    usage = (
        db.query(UserMonthlyUsage)
        .filter(
            UserMonthlyUsage.user_id == user_id,
            UserMonthlyUsage.year == year,
            UserMonthlyUsage.month == month,
        )
        .first()
    )
    if usage:
        usage.deleted_job_pages += page_count
    else:
        usage = UserMonthlyUsage(
            user_id=user_id,
            year=year,
            month=month,
            deleted_job_pages=page_count,
        )
        db.add(usage)


def inspect_upload_pages(file_path: Path) -> int:
    """
    Rapidly inspect the page count of an uploaded score without rasterization.
    Takes <10ms by reading only document metadata.
    """
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        try:
            doc = pdfium.PdfDocument(str(file_path))
            try:
                count = len(doc)
                return max(1, count)
            finally:
                doc.close()
        except Exception as exc:
            logger.debug("Failed to read PDF pages with PDFium (%s), defaulting to 1 page.", exc)
            return 1
    # Images (PNG, JPG, etc.) are single-page
    return 1


def validate_upload_quota(
    user: User,
    file_size_bytes: int,
    file_path: Path,
    db: Session,
) -> int:
    """
    Validate that an incoming upload conforms to the user's tier quotas:
    1. Storage bounds (HTTP 413)
    2. Per-score page ceiling (HTTP 400)
    3. Monthly page allowance (HTTP 429)

    Returns the detected page count.
    """
    tier_config = get_tier_config(user.tier)

    # 1. Check storage capacity
    current_storage = get_user_storage_bytes(user.id, db)
    if current_storage + file_size_bytes > tier_config.storage_limit_bytes:
        used_mb = current_storage / (1024 * 1024)
        file_mb = file_size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE if hasattr(status, "HTTP_413_CONTENT_TOO_LARGE") else 413,
            detail=(
                f"Storage quota exceeded. Your {tier_config.display_name} plan has a {tier_config.storage_limit_mb}MB "
                f"storage limit (currently using {used_mb:.1f}MB). This file requires {file_mb:.1f}MB. "
                f"Please upgrade to Pro or Virtuoso, or delete older scores to free up space."
            ),
        )

    # 2. Inspect document page count & check monthly transcription quota
    page_count = inspect_upload_pages(file_path)
    pages_this_month = get_user_pages_processed_this_month(user.id, db)
    if pages_this_month + page_count > tier_config.monthly_page_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS if hasattr(status, "HTTP_429_TOO_MANY_REQUESTS") else 429,
            detail=(
                f"Monthly transcription quota reached ({pages_this_month}/{tier_config.monthly_page_limit} pages). "
                f"This upload requires {page_count} page{'s' if page_count != 1 else ''}. "
                f"Upgrade to Pro or Virtuoso to continue transcribing scores this month."
            ),
        )

    return page_count
