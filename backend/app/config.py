import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_files() -> None:
    """Load variables from .env.local and .env files if present and not already set."""
    candidate_paths = [
        BASE_DIR.parent / ".env.local",
        BASE_DIR.parent / ".env",
        BASE_DIR / ".env.local",
        BASE_DIR / ".env",
    ]
    for env_path in candidate_paths:
        if not env_path.is_file():
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass


_load_env_files()


def _normalize_db_url(url: str | None) -> str | None:
    if not url:
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


class Settings:
    """Application configuration loaded from environment variables."""

    # Standardized on PostgreSQL 18 for complete dev/prod parity
    DATABASE_URL: str = (
        _normalize_db_url(os.getenv("DATABASE_URL"))
        or "postgresql+psycopg://omr_user:omr_password@localhost:5432/omr_db"
    )
    DATABASE_URL_UNPOOLED: str | None = _normalize_db_url(os.getenv("DATABASE_URL_UNPOOLED"))
    NEON_BRANCH: str | None = os.getenv("NEON_BRANCH")
    AUTO_MIGRATE: bool = os.getenv("AUTO_MIGRATE", "true").lower() in ("1", "true")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
    CELERY_ALWAYS_EAGER: bool = os.getenv("CELERY_ALWAYS_EAGER", "true").lower() in ("1", "true")

    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "storage" / "uploads")))
    RESULTS_DIR: Path = Path(os.getenv("RESULTS_DIR", str(BASE_DIR / "storage" / "results")))
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

    # Security: Secret key for JWT signing loaded from environment
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-insecure-secret-key-for-local-development-only")
    ACCESS_TOKEN_EXPIRE_HOURS: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Environment (development, testing, production)
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

    # Security Hardening: Rate Limiting & DoS Protection
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("1", "true")
    AUTH_RATE_LIMIT_PER_MINUTE: int = int(
        os.getenv(
            "AUTH_RATE_LIMIT_PER_MINUTE",
            "60" if os.getenv("ENVIRONMENT", "development").lower() in ("development", "test", "testing") else "5"
        )
    )
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = int(
        os.getenv(
            "UPLOAD_RATE_LIMIT_PER_MINUTE",
            "60" if os.getenv("ENVIRONMENT", "development").lower() in ("development", "test", "testing") else "10"
        )
    )

    # Guest Sandbox Limits & Protections
    ENABLE_GUEST_UPLOADS: bool = os.getenv("ENABLE_GUEST_UPLOADS", "false").lower() in ("1", "true")
    GUEST_UPLOAD_MAX_BYTES: int = int(os.getenv("GUEST_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MB
    GUEST_MAX_PAGES: int = int(os.getenv("GUEST_MAX_PAGES", "1"))
    GUEST_RATE_LIMIT: int = int(os.getenv("GUEST_RATE_LIMIT", "5"))
    GUEST_RATE_LIMIT_WINDOW: int = int(os.getenv("GUEST_RATE_LIMIT_WINDOW", "3600"))
    GUEST_JOB_RETENTION_HOURS: int = int(os.getenv("GUEST_JOB_RETENTION_HOURS", "2"))

    # Security Hardening: Decompression Bomb & Resource Limits
    FILE_VALIDATION_ENABLED: bool = os.getenv("FILE_VALIDATION_ENABLED", "true").lower() in ("1", "true")
    MAX_IMAGE_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "100000000"))  # 100 Megapixels
    MAX_IMAGE_DIMENSION: int = int(os.getenv("MAX_IMAGE_DIMENSION", "10000"))  # 10,000 px max width/height
    MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "200"))
    ENABLE_SECURITY_HEADERS: bool = os.getenv("ENABLE_SECURITY_HEADERS", "true").lower() in ("1", "true")

    # Storage Layer (Local vs Cloudflare R2 / AWS S3 vs Google Cloud Storage)
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local").lower()
    STORAGE_DIR: Path = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage")))
    S3_ENDPOINT_URL: str | None = os.getenv("S3_ENDPOINT_URL")
    S3_ACCESS_KEY_ID: str | None = os.getenv("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY: str | None = os.getenv("S3_SECRET_ACCESS_KEY")
    S3_REGION_NAME: str = os.getenv("S3_REGION_NAME", "auto")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "notesight-scores")
    GCS_BUCKET_NAME: str = os.getenv("GCS_BUCKET_NAME", "notesight-scores")
    GCS_PROJECT_ID: str | None = os.getenv("GCS_PROJECT_ID")
    GOOGLE_APPLICATION_CREDENTIALS: str | None = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # Stability & Resource Caps
    MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(50 * 1024 * 1024)))  # 50MB
    OMR_TIMEOUT_SECONDS: int = int(os.getenv("OMR_TIMEOUT_SECONDS", "300"))  # 300s limit on subprocess execution per page
    SSE_MAX_DURATION_SECONDS: int = int(os.getenv("SSE_MAX_DURATION_SECONDS", "900"))  # 15 min max duration for active SSE stream
    UPLOAD_RETENTION_DAYS: int = int(os.getenv("UPLOAD_RETENTION_DAYS", "7"))  # Prune raw uploads after 7 days
    # CORS Configuration Hardening: Default to explicit origins & guaranteed Capacitor mobile schemes
    _RAW_CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://127.0.0.1:8080,https://localhost,capacitor://localhost",
    )
    _PARSED_ORIGINS = [
        o.strip().strip("\"'")
        for o in re.split(r"[,;|\s]+", _RAW_CORS_ORIGINS)
        if o.strip().strip("\"'")
    ]
    _BASELINE_ORIGINS = [
        "https://localhost",
        "capacitor://localhost",
        "http://localhost",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]
    CORS_ORIGINS: list[str] = list(dict.fromkeys(_PARSED_ORIGINS + _BASELINE_ORIGINS))

    # Quota & Tier System Settings (Starter, Pro, Virtuoso)
    STARTER_STORAGE_MB: int = int(os.getenv("STARTER_STORAGE_MB", "30"))
    PRO_STORAGE_MB: int = int(os.getenv("PRO_STORAGE_MB", "300"))
    VIRTUOSO_STORAGE_MB: int = int(os.getenv("VIRTUOSO_STORAGE_MB", os.getenv("MAESTRO_STORAGE_MB", "500")))
    MAESTRO_STORAGE_MB: int = VIRTUOSO_STORAGE_MB

    STARTER_MONTHLY_PAGES: int = int(os.getenv("STARTER_MONTHLY_PAGES", "100"))
    PRO_MONTHLY_PAGES: int = int(os.getenv("PRO_MONTHLY_PAGES", "500"))
    VIRTUOSO_MONTHLY_PAGES: int = int(os.getenv("VIRTUOSO_MONTHLY_PAGES", os.getenv("MAESTRO_MONTHLY_PAGES", "2000")))
    MAESTRO_MONTHLY_PAGES: int = VIRTUOSO_MONTHLY_PAGES

    # Stripe Billing & Payment Configuration
    STRIPE_SECRET_KEY: str | None = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY: str | None = os.getenv("STRIPE_PUBLISHABLE_KEY")
    STRIPE_WEBHOOK_SECRET: str | None = os.getenv("STRIPE_WEBHOOK_SECRET")
    STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "")
    STRIPE_VIRTUOSO_PRICE_ID: str = os.getenv("STRIPE_VIRTUOSO_PRICE_ID", "")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:8080")

    # Transactional Email Service Configuration
    EMAIL_BACKEND: str = os.getenv("EMAIL_BACKEND", "console").lower()  # console, smtp, resend, mock
    SMTP_HOST: str = os.getenv("SMTP_HOST", "localhost")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "1025"))
    SMTP_USERNAME: str | None = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "false").lower() in ("1", "true")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "NoteSight <noreply@localhost>")
    CONTACT_EMAIL: str = os.getenv("CONTACT_EMAIL", "admin@localhost")
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "admin@localhost")
    RESEND_API_KEY: str | None = os.getenv("RESEND_API_KEY")
    REQUIRE_EMAIL_VERIFICATION: bool = os.getenv("REQUIRE_EMAIL_VERIFICATION", "true").lower() in ("1", "true")

    # Google OAuth 2.0 Social Authentication
    GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str | None = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", f"{FRONTEND_URL}/auth/google/callback")



settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

