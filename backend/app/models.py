import enum
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.services.totp import TotpService


class EncryptedTotpSecret(TypeDecorator):
    """Transparent authenticated symmetric encryption (Fernet) for TOTP secret with legacy plaintext fallback."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return value
        return TotpService.encrypt_secret(value)

    def process_result_value(self, value, dialect):
        if not value:
            return value
        return TotpService.decrypt_secret(value)


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UserTier(str, enum.Enum):
    STARTER = "starter"
    PRO = "pro"
    VIRTUOSO = "virtuoso"
    MAESTRO = "maestro"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    TRIALING = "trialing"



class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    musical_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(EncryptedTotpSecret, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    totp_backup_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    allow_omr_telemetry: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terms_version: Mapped[str | None] = mapped_column(String(50), nullable=True, default="2026.1-copyright")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    tier: Mapped[UserTier] = mapped_column(
        SQLEnum(UserTier, name="usertier", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=UserTier.STARTER,
        server_default="starter",
    )

    jobs = relationship("Job", back_populates="owner", cascade="all, delete-orphan")
    billing_customer = relationship("BillingCustomer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    monthly_usages = relationship("UserMonthlyUsage", back_populates="user", cascade="all, delete-orphan")
    shared_scores = relationship("ScoreShare", back_populates="user", cascade="all, delete-orphan")
    annotations = relationship("ScoreAnnotation", back_populates="author")


class Job(Base):
    """Represents an optical music recognition processing job."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_id_created_at", "user_id", "created_at"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, name="jobstatus", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_prediction_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Forward-compatible telemetry, quota and deduplication fields
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    processing_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    guest_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner = relationship("User", back_populates="jobs")
    training_triplets = relationship("OMRTrainingTriplet", back_populates="job", cascade="all, delete-orphan")
    shares = relationship("ScoreShare", back_populates="job", cascade="all, delete-orphan")
    annotations = relationship("ScoreAnnotation", back_populates="job", cascade="all, delete-orphan")


class BillingCustomer(Base):
    """Represents a customer profile linked to an external payment processor (Stripe)."""

    __tablename__ = "billing_customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="billing_customer")
    subscriptions = relationship("Subscription", back_populates="customer", cascade="all, delete-orphan")


class Subscription(Base):
    """Represents an active or historic subscription record."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_customer_id_status", "customer_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billing_customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    stripe_price_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tier: Mapped[UserTier] = mapped_column(
        SQLEnum(UserTier, name="usertier", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SQLEnum(SubscriptionStatus, name="subscriptionstatus", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
        index=True,
    )
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_tier: Mapped[UserTier | None] = mapped_column(
        SQLEnum(UserTier, name="usertier", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )
    downgrade_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    customer = relationship("BillingCustomer", back_populates="subscriptions")


class ProcessedWebhookEvent(Base):
    """Guarantees at-most-once processing of payment webhooks for idempotency."""

    __tablename__ = "processed_webhook_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class UserMonthlyUsage(Base):
    """Tracks cumulative monthly processed page volume independently of library score retention."""

    __tablename__ = "user_monthly_usage"
    __table_args__ = (
        Index("ix_user_monthly_usage_user_year_month", "user_id", "year", "month", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_job_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    user = relationship("User", back_populates="monthly_usages")


class OMRTrainingTriplet(Base):
    """Represents an active learning training triplet linking source image, raw prediction, and ground truth."""

    __tablename__ = "omr_training_triplets"
    __table_args__ = (
        Index("ix_omr_training_triplets_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_prediction_path: Mapped[str] = mapped_column(String(512), nullable=False)
    corrected_xml_path: Mapped[str] = mapped_column(String(512), nullable=False)
    character_error_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0", nullable=False)
    measures_modified: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rhythm_issues_fixed: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    diff_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    job = relationship("Job", back_populates="training_triplets")


class ScoreShare(Base):
    """Represents a publicly accessible share link for a score with permission flags."""

    __tablename__ = "score_shares"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_score_shares_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    share_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    allow_playback: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    allow_fork: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job = relationship("Job", back_populates="shares")
    user = relationship("User", back_populates="shared_scores")


class ScoreAnnotation(Base):
    """Represents a teacher or student annotation (comment, fingering, note) pinned to a measure."""

    __tablename__ = "score_annotations"
    __table_args__ = (
        Index("ix_score_annotations_job_id_measure", "job_id", "measure_number"),
        Index("ix_score_annotations_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_name: Mapped[str] = mapped_column(String(100), nullable=False, default="Musician", server_default="Musician")
    measure_number: Mapped[int] = mapped_column(Integer, nullable=False)
    staff_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    annotation_type: Mapped[str] = mapped_column(String(50), default="comment", server_default="comment", nullable=False)
    content: Mapped[str] = mapped_column(String(1000), nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#6366f1", server_default="#6366f1", nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job = relationship("Job", back_populates="annotations")
    author = relationship("User", back_populates="annotations")

