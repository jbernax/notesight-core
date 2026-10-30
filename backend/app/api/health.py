import logging
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

START_TIME = time.time()


@router.get("/live", status_code=status.HTTP_200_OK)
def liveness_probe() -> dict[str, Any]:
    """
    Kubernetes/container liveness probe.
    Returns 200 immediately to confirm the application event loop and HTTP server are responsive.
    """
    return {
        "status": "ok",
        "service": "notesight-backend",
        "uptime_seconds": round(time.time() - START_TIME, 2),
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
def readiness_probe(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Readiness probe verifying that core dependencies (PostgreSQL, Redis, Storage) are available.
    Returns 200 if ready to serve user traffic, or 503 if any mandatory dependency fails.
    """
    checks: dict[str, Any] = {
        "database": False,
        "redis": False,
        "storage": False,
    }
    healthy = True

    # 1. Database connectivity check
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        logger.warning("Readiness probe database check failed: %s", exc)
        checks["database"] = False
        healthy = False

    # 2. Redis connectivity check
    try:
        import redis
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2.0)
        r.ping()
        r.close()
        checks["redis"] = True
    except Exception as exc:
        logger.warning("Readiness probe Redis check failed: %s", exc)
        # Redis is considered degraded rather than fatal in dev/test, but tracked
        checks["redis"] = False
        if settings.ENVIRONMENT == "production":
            healthy = False

    # 3. Storage directory write check
    try:
        test_file = settings.UPLOAD_DIR / f".health_check_{int(time.time())}"
        test_file.write_text("ok")
        test_file.unlink(missing_ok=True)
        checks["storage"] = True
    except Exception as exc:
        logger.warning("Readiness probe storage directory check failed: %s", exc)
        checks["storage"] = False
        healthy = False

    if not healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "checks": checks},
        )

    return {
        "status": "ready",
        "service": "notesight-backend",
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "checks": checks,
    }
