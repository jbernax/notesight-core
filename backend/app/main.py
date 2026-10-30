import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pathlib import Path
from alembic import command
from alembic.config import Config
from app.__version__ import __version__
from app.config import BASE_DIR, settings
from app.api.routes import router as api_router
from app.api.billing import router as billing_router
from app.api.collaboration_ws import router as collaboration_router
from app.api.health import router as health_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def apply_migrations() -> None:
    """Run Alembic migrations programmatically to head."""
    alembic_ini_path = BASE_DIR / "alembic.ini"
    if not alembic_ini_path.exists():
        alembic_ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"

    if not alembic_ini_path.exists():
        logger.warning("alembic.ini not found at %s. Skipping auto-migration.", alembic_ini_path)
        return

    logger.info("Executing database migrations up to head...")
    alembic_cfg = Config(str(alembic_ini_path))
    migration_url = settings.DATABASE_URL_UNPOOLED or settings.DATABASE_URL
    alembic_cfg.set_main_option("sqlalchemy.url", migration_url)

    script_loc = BASE_DIR / "alembic"
    if script_loc.exists():
        alembic_cfg.set_main_option("script_location", str(script_loc))

    is_postgres = migration_url.startswith("postgresql") or migration_url.startswith("postgres://")
    if is_postgres:
        import sqlalchemy
        from sqlalchemy import text
        lock_engine = sqlalchemy.create_engine(migration_url, isolation_level="AUTOCOMMIT")
        with lock_engine.connect() as conn:
            logger.info("Checking PostgreSQL migration advisory lock...")
            acquired = conn.execute(text("SELECT pg_try_advisory_lock(842109284);")).scalar()
            if not acquired:
                logger.info("Another worker is applying database migrations. Waiting for advisory lock...")
                conn.execute(text("SELECT pg_advisory_lock(842109284);"))
            try:
                command.upgrade(alembic_cfg, "head")
                logger.info("Database schema successfully verified/upgraded to head.")
            except Exception as exc:
                logger.exception("Database migration failed on startup: %s", exc)
                raise RuntimeError(f"Database migration failed on startup: {exc}") from exc
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(842109284);"))
    else:
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("Database schema successfully verified/upgraded to head.")
        except Exception as exc:
            logger.exception("Database migration failed on startup: %s", exc)
            raise RuntimeError(f"Database migration failed on startup: {exc}") from exc


def validate_production_security() -> None:
    """Enforce zero-trust production security guards on startup."""
    env = settings.ENVIRONMENT.lower()
    if env in ("production", "prod"):
        if (
            settings.SECRET_KEY == "dev-insecure-secret-key-for-local-development-only"
            or len(settings.SECRET_KEY) < 32
        ):
            raise RuntimeError(
                "FATAL: Insecure or insufficiently strong SECRET_KEY configured in production. "
                "SECRET_KEY must be at least 32 characters long and not the development default."
            )


def validate_cors_configuration(origins: list[str], allow_credentials: bool = True) -> None:
    """Enforce that wildcard origin cannot be combined with credentialed requests."""
    if "*" in origins and allow_credentials:
        raise RuntimeError(
            "CORS misconfiguration: Wildcard '*' in CORS_ORIGINS cannot be combined with allow_credentials=True per W3C specification."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_security()
    validate_cors_configuration(settings.CORS_ORIGINS, allow_credentials=True)
    if settings.AUTO_MIGRATE:
        apply_migrations()
    try:
        from app.services.job_reconciliation import reconcile_stale_jobs
        reconcile_stale_jobs()
    except Exception as exc:
        logger.warning("Startup job reconciliation skipped: %s", exc)
    yield


app = FastAPI(
    title="NoteSight API",
    description="Backend API for NoteSight: Sheet music recognition, transcription, and MusicXML generation",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

from app.middleware.security import SecurityHeadersMiddleware

# Security headers middleware (CSP, X-Frame-Options, X-Content-Type-Options, HSTS)
app.add_middleware(SecurityHeadersMiddleware)

# CORS middleware for secure web client communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred."},
    )


app.include_router(api_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(collaboration_router, prefix="/api")
app.include_router(health_router)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "NoteSight Backend API"}


@app.get("/docs", include_in_schema=False)
def redirect_docs():
    return RedirectResponse(url="/api/docs")


@app.get("/openapi.json", include_in_schema=False)
def redirect_openapi():
    return RedirectResponse(url="/api/openapi.json")


@app.get("/redoc", include_in_schema=False)
def redirect_redoc():
    return RedirectResponse(url="/api/redoc")

