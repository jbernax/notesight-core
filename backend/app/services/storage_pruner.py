import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Job, JobStatus
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


def prune_expired_uploads(
    retention_days: int = 7,
    db: Session | None = None,
) -> dict[str, Any]:
    """Prune raw uploaded scores older than retention threshold and clean up orphaned temporary directories.

    Preserves generated MusicXML results in RESULTS_DIR permanently so user scores and playback are unaffected.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    storage_service = get_storage_service()
    files_pruned = 0
    dirs_pruned = 0
    bytes_freed = 0

    try:
        # 1. Prune raw uploads for completed or failed jobs older than retention window
        expired_jobs = (
            db.query(Job)
            .filter(
                Job.created_at < cutoff,
                Job.file_path.isnot(None),
                Job.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]),
            )
            .all()
        )

        for job in expired_jobs:
            if job.file_path:
                try:
                    file_p = Path(job.file_path)
                    file_size = 0
                    if file_p.is_file():
                        file_size = file_p.stat().st_size
                        bytes_freed += file_size
                    deleted = storage_service.delete_file(job.file_path)
                    if deleted:
                        files_pruned += 1
                        job.file_size_bytes = max(0, (job.file_size_bytes or 0) - file_size)
                except Exception as exc:
                    logger.warning("Failed to delete expired raw file %s: %s", job.file_path, exc)

                job.file_path = None

        db.commit()

        # 2. Prune orphaned _pages intermediate directories older than 1 hour
        upload_dir = settings.UPLOAD_DIR
        now_ts = time.time()
        one_hour_sec = 3600

        if upload_dir.exists():
            for entry in upload_dir.iterdir():
                if entry.is_dir() and entry.name.endswith("_pages"):
                    try:
                        mtime = entry.stat().st_mtime
                        if (now_ts - mtime) > one_hour_sec:
                            dir_size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                            shutil.rmtree(entry, ignore_errors=True)
                            bytes_freed += dir_size
                            dirs_pruned += 1
                            logger.info("Cleaned orphaned page extraction dir: %s (%d bytes)", entry.name, dir_size)
                    except Exception as exc:
                        logger.warning("Failed to inspect/remove page directory %s: %s", entry, exc)

        # 3. Prune expired unclaimed guest jobs (user_id is None) older than retention threshold
        guest_hours = getattr(settings, "GUEST_JOB_RETENTION_HOURS", 2)
        guest_cutoff = datetime.now(timezone.utc) - timedelta(hours=guest_hours)
        expired_guest_jobs = (
            db.query(Job)
            .filter(
                Job.user_id.is_(None),
                Job.created_at < guest_cutoff,
            )
            .all()
        )
        for g_job in expired_guest_jobs:
            for p in (g_job.file_path, g_job.result_file_path, g_job.raw_prediction_path):
                if p:
                    try:
                        storage_service.delete_file(p)
                    except Exception:
                        pass
            db.delete(g_job)
            files_pruned += 1

        db.commit()

        logger.info(
            "Storage pruning completed: %d raw files pruned, %d temp dirs removed, %d bytes freed (%.2f MB)",
            files_pruned,
            dirs_pruned,
            bytes_freed,
            bytes_freed / (1024 * 1024),
        )

        return {
            "files_pruned": files_pruned,
            "dirs_pruned": dirs_pruned,
            "bytes_freed": bytes_freed,
            "bytes_freed_mb": round(bytes_freed / (1024 * 1024), 2),
        }

    finally:
        if owns_session:
            db.close()


def reap_stale_processing_jobs(
    db: Session | None = None,
    max_age_minutes: int = 30,
) -> int:
    """Transition jobs stuck in JobStatus.PROCESSING beyond max_age_minutes to JobStatus.FAILED."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    try:
        stale_jobs = (
            db.query(Job)
            .filter(
                Job.status == JobStatus.PROCESSING,
                Job.updated_at < cutoff,
            )
            .all()
        )
        reaped_count = 0
        for job in stale_jobs:
            job.status = JobStatus.FAILED
            job.error_message = (
                f"Job timed out and was reaped after remaining in processing state for over {max_age_minutes} minutes without progress."
            )
            job.updated_at = datetime.now(timezone.utc)
            reaped_count += 1
            logger.warning("Reaped stale processing job %s (stuck since %s)", job.id, job.updated_at)

        if reaped_count > 0:
            db.commit()
        return reaped_count
    finally:
        if owns_session:
            db.close()

