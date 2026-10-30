import uuid
from datetime import date, datetime, timezone
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models import JobStatus, UserTier

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)
    full_name: str = Field(..., min_length=2, max_length=255)
    birthdate: date
    terms_accepted: bool = Field(...)
    terms_version: str = "2026.1-copyright"
    musical_role: str | None = None
    country: str | None = None

    @field_validator("terms_accepted")
    @classmethod
    def validate_terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms and Conditions and Sheet Music Fair-Use Policy to register")
        return v

    @field_validator("birthdate")
    @classmethod
    def validate_age(cls, v: date) -> date:
        today = date.today()
        if v > today:
            raise ValueError("Birthdate cannot be in the future")
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 13:
            raise ValueError("You must be at least 13 years old to register an account")
        try:
            min_date = today.replace(year=today.year - 125)
        except ValueError:
            min_date = today.replace(year=today.year - 125, day=28)
        if age > 125 or v < min_date:
            raise ValueError("Birthdate cannot be more than 125 years ago")
        return v

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None
    email: str | None = None
    requires_2fa: bool = False
    temp_token: str | None = None


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    backup_codes: list[str]


class TotpVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=12)


class TotpDisableRequest(BaseModel):
    password: str = Field(..., max_length=128)
    code: str | None = Field(default=None, max_length=12)


class TotpLoginRequest(BaseModel):
    temp_token: str
    code: str = Field(..., min_length=4, max_length=16)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class RequestVerificationRequest(BaseModel):
    email: EmailStr | None = None


class AccountDeletionRequest(BaseModel):
    password: str | None = Field(default=None, max_length=128)


class OAuthGoogleCallbackRequest(BaseModel):
    code: str
    state: str | None = None


class OAuthUrlResponse(BaseModel):
    url: str


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    birthdate: date | None = None
    musical_role: str | None = None
    country: str | None = None
    bio: str | None = None
    is_verified: bool = False
    oauth_provider: str | None = None
    avatar_url: str | None = None
    email_notifications_enabled: bool = True
    allow_omr_telemetry: bool = False
    totp_enabled: bool = False
    tier: UserTier
    terms_accepted: bool
    terms_accepted_at: datetime | None = None
    terms_version: str | None = None
    created_at: datetime
    has_billing_customer: bool = False
    billing_name: str | None = None
    billing_country: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    birthdate: date | None = None
    musical_role: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=512)
    email_notifications_enabled: bool | None = None
    allow_omr_telemetry: bool | None = None

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            cleaned = v.strip().lower()
            if not (cleaned.startswith("https://") or cleaned.startswith("http://") or cleaned.startswith("/")):
                raise ValueError("Avatar URL must begin with http://, https://, or /")
            if cleaned.startswith("javascript:") or cleaned.startswith("data:") or cleaned.startswith("vbscript:"):
                raise ValueError("Unsafe avatar URL scheme is not allowed")
        return v

    @field_validator("birthdate")
    @classmethod
    def validate_birthdate_update(cls, v: date | None) -> date | None:
        if v is not None:
            today = date.today()
            if v > today:
                raise ValueError("Birthdate cannot be in the future")
            age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
            if age < 13:
                raise ValueError("You must be at least 13 years old")
            try:
                min_date = today.replace(year=today.year - 125)
            except ValueError:
                min_date = today.replace(year=today.year - 125, day=28)
            if age > 125 or v < min_date:
                raise ValueError("Birthdate cannot be more than 125 years ago")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., max_length=128)


class OptionalBillingDetailsUpdate(BaseModel):
    billing_name: str | None = Field(None, max_length=255)
    billing_email: EmailStr | None = None
    billing_country: str | None = Field(None, min_length=2, max_length=2)


class LegalTermsSection(BaseModel):
    title: str
    content: str


class LegalTermsResponse(BaseModel):
    version: str
    effective_date: str
    title: str
    summary: str
    sections: list[LegalTermsSection]


class JobResponse(BaseModel):
    """Schema representing job state returned to the client."""

    id: uuid.UUID
    status: JobStatus
    original_filename: str
    result_file_path: str | None = None
    error_message: str | None = None
    content_hash: str | None = None
    page_count: int | None = None
    file_size_bytes: int = 0
    processing_time_seconds: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class GuestJobResponse(BaseModel):
    """Schema representing an unauthenticated guest sandbox job."""

    id: uuid.UUID
    status: JobStatus
    original_filename: str
    guest_token: str
    result_file_path: str | None = None
    error_message: str | None = None
    page_count: int | None = None
    file_size_bytes: int = 0
    processing_time_seconds: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class ClaimScoreRequest(BaseModel):
    """Request payload to claim an anonymous guest score into authenticated user library."""

    guest_token: str = Field(..., min_length=16, max_length=128)


class JobUpdate(BaseModel):
    """Schema for updating an existing completed job's MusicXML content or title."""

    musicxml: str | None = Field(None, max_length=15_000_000)
    title: str | None = Field(None, max_length=255)


class JobRenameRequest(BaseModel):
    """Schema for renaming an existing score job."""

    title: str = Field(..., min_length=1, max_length=255)


class RhythmIssueResponse(BaseModel):
    """Schema representing an arithmetic discrepancy in measure duration."""

    measure_number: int
    time_signature: str
    expected_beats: float
    actual_beats: float
    discrepancy_beats: float
    status: str
    message: str


class ScoreValidationResponse(BaseModel):
    """Schema representing a score rhythm and confidence validation report."""

    job_id: uuid.UUID
    total_measures: int
    invalid_measures_count: int
    issues: list[RhythmIssueResponse]



class ScoreCreate(BaseModel):
    """Schema for creating a new score from scratch."""

    title: str = Field(..., min_length=1, max_length=255)
    composer: str | None = Field(None, max_length=255)
    musicxml: str = Field(..., min_length=10)


class ScoreUrlImportRequest(BaseModel):
    """Schema for importing and transcribing a score from a public web URL."""

    url: str = Field(..., min_length=10, max_length=2048, description="Public HTTP/HTTPS URL of the score")
    title: str | None = Field(default=None, max_length=255, description="Optional custom title for the score")


class QuotaStorageInfo(BaseModel):
    used_bytes: int
    used_mb: float
    limit_bytes: int
    limit_mb: int
    percent_used: float


class QuotaPagesInfo(BaseModel):
    max_per_score: int
    processed_this_month: int
    monthly_limit: int
    remaining_this_month: int


class TierDetail(BaseModel):
    id: UserTier
    name: str
    display_name: str
    tagline: str
    storage_limit_mb: int
    max_pages_per_score: int
    monthly_page_limit: int
    price: str
    features: list[str]


class SubscriptionInfo(BaseModel):
    id: str
    tier: str
    status: str
    current_period_start: str
    current_period_end: str
    cancel_at_period_end: bool
    pending_tier: str | None = None
    downgrade_scheduled_at: str | None = None


class UserQuotaResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    tier: UserTier
    tier_name: str
    storage: QuotaStorageInfo
    pages: QuotaPagesInfo
    available_tiers: list[TierDetail]
    subscription: SubscriptionInfo | None = None
    is_grace_period_active: bool = False


class UpdateTierRequest(BaseModel):
    tier: UserTier


class ScheduleDowngradeRequest(BaseModel):
    tier: UserTier


class CheckoutSessionRequest(BaseModel):
    tier: UserTier
    locale: str | None = Field(None, max_length=10, description="Language code for Stripe Checkout (e.g. 'en', 'es', 'de', 'fr', 'it', 'pt', 'auto')")


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class CustomerPortalRequest(BaseModel):
    locale: str | None = Field(None, max_length=10, description="Language code for Stripe Customer Portal")


class CustomerPortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    tier: str
    has_active_subscription: bool
    subscription: SubscriptionInfo | None = None
    stripe_customer_id: str | None = None
    billing_name: str | None = None
    billing_email: str | None = None
    billing_country: str | None = None


class OMRTrainingTripletResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID | None = None
    image_path: str | None = None
    raw_prediction_path: str
    corrected_xml_path: str
    character_error_rate: float
    measures_modified: int
    rhythm_issues_fixed: int
    diff_summary: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OMRQualityReportResponse(BaseModel):
    total_triplets: int
    average_cer: float
    median_cer: float
    total_measures_modified: int
    total_rhythm_issues_fixed: int
    cer_distribution: dict[str, int]
    common_modified_elements: dict[str, int]


# --- Track P8: Real-Time Collaboration & Social Sharing Schemas ---

class ScoreShareCreate(BaseModel):
    allow_playback: bool = True
    allow_fork: bool = True
    expires_days: int | None = Field(None, ge=1, le=365)


class ScoreShareUpdate(BaseModel):
    allow_playback: bool | None = None
    allow_fork: bool | None = None
    is_active: bool | None = None
    expires_days: int | None = Field(None, ge=1, le=365)


class ScoreShareResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    share_token: str
    share_url: str
    embed_url: str
    allow_playback: bool
    allow_fork: bool
    is_active: bool
    view_count: int
    expires_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicSharedScoreResponse(BaseModel):
    share_token: str
    title: str
    author_name: str
    musicxml: str
    allow_playback: bool
    allow_fork: bool
    view_count: int
    created_at: datetime


class ScoreForkResponse(BaseModel):
    forked_job_id: uuid.UUID
    title: str
    message: str


class ScoreAnnotationCreate(BaseModel):
    measure_number: int = Field(..., ge=1)
    staff_index: int = Field(0, ge=0)
    annotation_type: str = Field("comment", max_length=50)
    content: str = Field(..., min_length=1, max_length=1000)
    color: str = Field("#6366f1", max_length=20)


class ScoreAnnotationUpdate(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=1000)
    annotation_type: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=20)
    is_resolved: bool | None = None


class ScoreAnnotationResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    user_id: uuid.UUID | None
    author_name: str
    measure_number: int
    staff_index: int
    annotation_type: str
    content: str
    color: str
    is_resolved: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StreamTicketResponse(BaseModel):
    ticket: str
    token: str
    stream_ticket: str
    expires_in: int = 60


from app.schemas_ucp import (
    UCPAvailability,
    UCPBuyer,
    UCPCatalogFilters,
    UCPCatalogLookupRequest,
    UCPCatalogLookupResponse,
    UCPCatalogPriceFilter,
    UCPCatalogSearchRequest,
    UCPCatalogSearchResponse,
    UCPCheckoutSessionRequest,
    UCPCheckoutSessionResponse,
    UCPDescription,
    UCPLineItem,
    UCPLineItemDetail,
    UCPPrice,
    UCPProduct,
    UCPRecurrence,
    UCPVariant,
)




