"""
Job Reconciliation Service for NoteSight OMR.

Detects and recovers orphaned processing jobs that were interrupted due to
container restarts, OOM terminations, or worker disconnections.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, JobStatus

logger = logging.getLogger(__name__)

DEFAULT_STALE_JOB_THRESHOLD_MINUTES = 15
INTERRUPTED_JOB_ERROR_MSG = (
    "Processing was interrupted (server restart or timeout). You can safely retry this score."
)


def reconcile_stale_jobs(
    db: Session | None = None,
    max_age_minutes: int = DEFAULT_STALE_JOB_THRESHOLD_MINUTES,
    user_id: uuid.UUID | None = None,
) -> list[Job]:
    """
    Find jobs stuck in PROCESSING (or PENDING) older than max_age_minutes and transition them to FAILED.

    This ensures that jobs aborted by container crashes or SIGKILL do not remain in an infinite
    processing spinner, and unblocks them so users can trigger a retry.
    """
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    reconciled_jobs: list[Job] = []

    try:
        query = db.query(Job).filter(
            Job.status.in_([JobStatus.PROCESSING, JobStatus.PENDING]),
            Job.updated_at < cutoff,
        )
        if user_id is not None:
            query = query.filter(Job.user_id == user_id)

        stale_jobs = query.all()
        for job in stale_jobs:
            logger.warning(
                "Reconciling stale job %s (%s) last updated at %s (cutoff: %s)",
                job.id,
                job.original_filename,
                job.updated_at,
                cutoff,
            )
            job.status = JobStatus.FAILED
            job.error_message = INTERRUPTED_JOB_ERROR_MSG
            job.updated_at = datetime.now(timezone.utc)
            reconciled_jobs.append(job)

        if reconciled_jobs:
            db.commit()
            for job in reconciled_jobs:
                db.refresh(job)
            logger.info("Successfully reconciled %d stale job(s) to FAILED state.", len(reconciled_jobs))

        return reconciled_jobs
    except Exception as exc:
        logger.exception("Failed to reconcile stale jobs: %s", exc)
        if db:
            db.rollback()
        return []
    finally:
        if owns_session and db:
            db.close()
