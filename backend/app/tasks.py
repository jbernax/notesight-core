import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import Job, JobStatus
from app.services.event_publisher import publish_job_event
from app.services.omr import recognize_page
from app.services.preprocessor import (
    PageType,
    classify_score_page,
    extract_cover_metadata,
    extract_score_pages,
    preprocess_image_for_omr,
)
from app.services.score_pipeline import transcribe_score
from app.services.stitcher import merge_musicxml_files
from app.services.storage import get_storage_service
from app.services.storage_pruner import prune_expired_uploads

logger = logging.getLogger(__name__)


@celery_app.task(name="process_score")
def process_score(job_id_str: str) -> None:
    """Full background pipeline: Preprocess -> OMR Inference -> Lyrics Extraction -> Stitch MusicXML."""
    job_id = uuid.UUID(job_id_str)
    db = SessionLocal()
    pages_dir = settings.UPLOAD_DIR / f"{job_id}_pages"
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job %s not found in database", job_id)
            return

        start_time = datetime.now(timezone.utc)
        # 1. Update status to PROCESSING
        job.status = JobStatus.PROCESSING
        job.updated_at = start_time
        db.commit()
        publish_job_event(str(job_id), {"id": str(job_id), "status": "processing", "page": 0, "total_pages": 1})

        storage_service = get_storage_service()
        if not job.file_path or not storage_service.exists(job.file_path):
            raise FileNotFoundError(f"Uploaded file not found at: {job.file_path}")

        source_file = storage_service.get_local_path(job.file_path)
        is_pdf = source_file.suffix.lower() == ".pdf"

        # 2. Execute unified score transcription pipeline
        final_xml_path = settings.RESULTS_DIR / f"{job_id}.musicxml"

        def _on_progress(page_idx: int, total_p: int) -> None:
            publish_job_event(
                str(job_id),
                {
                    "id": str(job_id),
                    "status": "processing",
                    "page": page_idx,
                    "total_pages": total_p,
                },
            )

        transcription = transcribe_score(
            source_file,
            output_xml_path=final_xml_path,
            work_dir=pages_dir,
            on_progress=_on_progress,
        )
        total_music_pages = transcription.page_count
        total_pages = transcription.total_extracted_pages
        cover_metadata = transcription.metadata

        xml_size = final_xml_path.stat().st_size if final_xml_path.exists() else 0

        if settings.STORAGE_BACKEND in ("s3", "gcs"):
            storage_key = f"results/{job_id}.musicxml"
            with open(final_xml_path, "rb") as f:
                storage_service.save_file(storage_key, f)
            job.result_file_path = storage_key
        else:
            job.result_file_path = str(final_xml_path)

        # Preserve baseline raw prediction copy for active learning telemetry
        if final_xml_path.exists():
            raw_xml_path = settings.RESULTS_DIR / f"{job_id}_raw.musicxml"
            raw_xml_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(final_xml_path, raw_xml_path)
            if settings.STORAGE_BACKEND in ("s3", "gcs"):
                raw_storage_key = f"results/{job_id}_raw.musicxml"
                with open(raw_xml_path, "rb") as f:
                    storage_service.save_file(raw_storage_key, f)
                job.raw_prediction_path = raw_storage_key
                try:
                    raw_xml_path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                job.raw_prediction_path = str(raw_xml_path)

        # Clean up temporary local XML staging file when backed by cloud storage
        if settings.STORAGE_BACKEND in ("s3", "gcs"):
            try:
                final_xml_path.unlink(missing_ok=True)
            except Exception:
                pass

        # 5. Clean up temporary extracted page directory
        if pages_dir.exists():
            shutil.rmtree(pages_dir, ignore_errors=True)

        # 6. Mark job as COMPLETED
        elapsed_seconds = round((datetime.now(timezone.utc) - start_time).total_seconds(), 2)
        job.file_size_bytes = (job.file_size_bytes or 0) + xml_size
        job.status = JobStatus.COMPLETED
        job.error_message = None
        job.page_count = total_music_pages
        job.processing_time_seconds = elapsed_seconds
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Job %s processing completed successfully in %ss", job_id, elapsed_seconds)
        publish_job_event(str(job_id), {
            "id": str(job_id),
            "status": "completed",
            "page_count": total_music_pages,
            "total_extracted_pages": total_pages,
            "processing_time_seconds": elapsed_seconds
        })

        # 7. Deliver job completion notification if user has enabled email notifications
        try:
            if job.owner and job.owner.email and getattr(job.owner, "email_notifications_enabled", True):
                from app.services.email import build_job_completed_email, get_email_service
                score_name = (
                    cover_metadata.get("title")
                    or Path(job.original_filename).stem.replace("_", " ").title()
                )
                score_link = f"{settings.FRONTEND_URL}/studio?jobId={job.id}"
                html_b, text_b = build_job_completed_email(
                    recipient_email=job.owner.email,
                    score_title=score_name,
                    page_count=total_music_pages,
                    score_link=score_link,
                )
                get_email_service().send_email(
                    job.owner.email,
                    f"Your Score '{score_name}' is Ready!",
                    html_b,
                    text_b,
                )
        except Exception as mail_exc:
            logger.warning("Job %s: Could not send completion email notification: %s", job_id, mail_exc)

    except Exception as exc:
        logger.exception("Error while processing job %s: %s", job_id, exc)
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
        publish_job_event(str(job_id), {
            "id": str(job_id),
            "status": "failed",
            "error_message": str(exc)
        })
        raise
    finally:
        if pages_dir.exists():
            shutil.rmtree(pages_dir, ignore_errors=True)
        db.close()


@celery_app.task(name="prune_storage")
def prune_storage(retention_days: int | None = None) -> dict[str, Any]:
    """Celery task to prune raw uploads older than retention threshold and clean orphaned files."""
    days = retention_days if retention_days is not None else settings.UPLOAD_RETENTION_DAYS
    logger.info("Executing scheduled storage pruning (retention_days=%d)...", days)
    return prune_expired_uploads(retention_days=days)

