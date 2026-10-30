import asyncio
import hashlib
import json
import logging
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
import redis.asyncio as aioredis

from app.services.job_reconciliation import reconcile_stale_jobs, INTERRUPTED_JOB_ERROR_MSG

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import Job, JobStatus, User
from app.schemas import (
    ClaimScoreRequest,
    GuestJobResponse,
    JobRenameRequest,
    JobResponse,
    JobUpdate,
    RhythmIssueResponse,
    ScoreCreate,
    ScoreUrlImportRequest,
    ScoreValidationResponse,
)
from app.tasks import process_score
from app.services.url_downloader import download_file_from_url
from app.auth import get_current_user, get_user_from_token_str
from app.services.storage import get_storage_service
from app.services.musicxml_sanitizer import sanitize_musicxml_string
from app.services.rhythm_validator import validate_musicxml_rhythms
from app.services.rate_limiter import rate_limit
from app.services.file_security import validate_uploaded_file_safety
from app.services.quota import (
    get_tier_config,
    get_user_storage_bytes,
    inspect_upload_pages,
    record_deleted_job_pages,
    validate_upload_quota,
)
from app.api.helpers import (
    build_content_disposition_headers,
    resolve_sample_file,
    save_upload_file_safely,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scores"])


def _resolve_storage_service():
    try:
        import app.api.routes as routes_module
        return getattr(routes_module, "get_storage_service", get_storage_service)()
    except Exception:
        return get_storage_service()


def _resolve_process_score():
    try:
        import app.api.routes as routes_module
        return getattr(routes_module, "process_score", process_score)
    except Exception:
        return process_score


# Concurrency guard: limit in-process OMR inference to 1 heavy compute task per container
# This protects container memory from OOM while allowing Uvicorn to serve 80 concurrent HTTP requests.
_omr_lock = threading.Semaphore(1)


def _execute_eager_omr_task(proc, job_id_str: str) -> None:
    """Execute OMR inference synchronously in eager mode within active HTTP request.
    
    This keeps the Cloud Run request lifecycle active, ensuring GCP allocates 100% CPU
    under request-based billing (cpu-throttling: true) and scales to 0 when idle ($0.00 compute).
    """
    with _omr_lock:
        proc(job_id_str)


@router.post(
    "/guest/upload",
    response_model=GuestJobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(limit=settings.GUEST_RATE_LIMIT, window_seconds=settings.GUEST_RATE_LIMIT_WINDOW, scope="ip"))],
)
@router.post(
    "/scores/guest-upload",
    response_model=GuestJobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(limit=settings.GUEST_RATE_LIMIT, window_seconds=settings.GUEST_RATE_LIMIT_WINDOW, scope="ip"))],
)
def upload_guest_score(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> GuestJobResponse:
    """Accept an uploaded score from an unauthenticated visitor, strictly enforcing 1-page and size limits."""
    if not settings.ENABLE_GUEST_UPLOADS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest trial uploads are currently disabled. Please create a free account or sign in to transcribe sheet music.",
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename",
        )

    safe_filename = Path(file.filename).name
    extension = Path(safe_filename).suffix.lower()

    if extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{extension}'. Allowed: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}",
        )

    job_id = uuid.uuid4()
    stored_filename = f"{job_id}_{safe_filename}"
    target_path = settings.UPLOAD_DIR / stored_filename

    # Save uploaded bytes securely with bounded size check (max GUEST_UPLOAD_MAX_BYTES)
    content_hash = save_upload_file_safely(file, target_path, settings.GUEST_UPLOAD_MAX_BYTES)
    file_size = target_path.stat().st_size

    # Enforce strict 1-page ceiling for guest sandbox
    page_count = inspect_upload_pages(target_path)
    if page_count > settings.GUEST_MAX_PAGES:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Guest test upload is limited to {settings.GUEST_MAX_PAGES} page(s). "
                f"Your file has {page_count} pages. Create a free account to scan multi-page scores!"
            ),
        )

    # Security Hardening: Validate genuine magic bytes and bounds
    try:
        validate_uploaded_file_safety(target_path, extension)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise

    storage_service = _resolve_storage_service()
    if settings.STORAGE_BACKEND in ("s3", "gcs"):
        storage_key = f"uploads/{stored_filename}"
        with open(target_path, "rb") as f:
            storage_service.save_file(storage_key, f)
        stored_file_ref = storage_key
    else:
        stored_file_ref = str(target_path)

    guest_token = secrets.token_urlsafe(32)

    # Deduplication cache hit check
    cached_job = (
        db.query(Job)
        .filter(
            Job.content_hash == content_hash,
            Job.status == JobStatus.COMPLETED,
            Job.result_file_path.isnot(None),
        )
        .order_by(Job.created_at.desc())
        .first()
    )

    if cached_job:
        source_ref = (
            cached_job.raw_prediction_path
            if (cached_job.raw_prediction_path and storage_service.exists(cached_job.raw_prediction_path))
            else cached_job.result_file_path
        )
        if source_ref and storage_service.exists(source_ref):
            new_result_path = settings.RESULTS_DIR / f"{job_id}.musicxml"
            cached_source = storage_service.get_local_path(source_ref)
            shutil.copyfile(cached_source, new_result_path)

            new_result_size = new_result_path.stat().st_size if new_result_path.exists() else 0
            if settings.STORAGE_BACKEND in ("s3", "gcs"):
                new_result_key = f"results/{job_id}.musicxml"
                with open(new_result_path, "rb") as f:
                    storage_service.save_file(new_result_key, f)
                stored_result_ref = new_result_key
                try:
                    new_result_path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                stored_result_ref = str(new_result_path)

            total_job_size = file_size + new_result_size
            job = Job(
                id=job_id,
                user_id=None,
                guest_token=guest_token,
                status=JobStatus.COMPLETED,
                original_filename=safe_filename,
                file_path=stored_file_ref,
                result_file_path=stored_result_ref,
                content_hash=content_hash,
                page_count=cached_job.page_count or page_count,
                file_size_bytes=total_job_size,
                processing_time_seconds=0.0,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            return GuestJobResponse.model_validate(job)

    job = Job(
        id=job_id,
        user_id=None,
        guest_token=guest_token,
        status=JobStatus.PENDING,
        original_filename=safe_filename,
        file_path=stored_file_ref,
        content_hash=content_hash,
        page_count=page_count,
        file_size_bytes=file_size,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    proc = _resolve_process_score()
    if not settings.CELERY_ALWAYS_EAGER:
        proc.delay(str(job.id))
    else:
        _execute_eager_omr_task(proc, str(job.id))
        db.refresh(job)

    return GuestJobResponse.model_validate(job)


@router.get("/guest/{job_id}", response_model=GuestJobResponse)
@router.get("/scores/guest/{job_id}", response_model=GuestJobResponse)
def get_guest_job_status(
    job_id: str,
    token: str = Query(..., description="Guest access token"),
    db: Session = Depends(get_db),
) -> GuestJobResponse:
    """Retrieve status of an unauthenticated guest score job."""
    sample = resolve_sample_file(job_id)
    if sample:
        return GuestJobResponse(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            status=JobStatus.COMPLETED,
            original_filename=sample.name,
            guest_token=token,
            result_file_path=str(sample),
            page_count=1,
            error_message=None,
        )

    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID '{job_id}' not found")

    job = db.query(Job).filter(Job.id == parsed_id, Job.guest_token == token).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Guest score job not found or invalid token")

    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
        if job.updated_at and job.updated_at < stale_threshold:
            job.status = JobStatus.FAILED
            job.error_message = INTERRUPTED_JOB_ERROR_MSG
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(job)

    return GuestJobResponse.model_validate(job)


@router.get("/guest/{job_id}/download")
@router.get("/scores/guest/{job_id}/download")
def download_guest_musicxml(
    job_id: str,
    token: str = Query(..., description="Guest access token"),
    db: Session = Depends(get_db),
):
    """Serve MusicXML for in-browser OSMD rendering of a completed guest score."""
    sample = resolve_sample_file(job_id)
    if sample:
        return FileResponse(
            path=str(sample),
            media_type="application/vnd.recordare.musicxml+xml",
            filename=f"{sample.stem}.musicxml",
        )

    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID '{job_id}' not found")

    job = db.query(Job).filter(Job.id == parsed_id, Job.guest_token == token).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Guest score job not found or invalid token")

    if job.status != JobStatus.COMPLETED or not job.result_file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Score processing is not yet completed")

    storage_service = _resolve_storage_service()
    if not storage_service.exists(job.result_file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result file not found in storage")

    local_path = storage_service.get_local_path(job.result_file_path)
    return FileResponse(
        path=str(local_path),
        media_type="application/vnd.recordare.musicxml+xml",
        filename=f"{Path(job.original_filename).stem}.musicxml",
    )


@router.post("/guest/{job_id}/claim", response_model=JobResponse)
@router.post("/scores/guest/{job_id}/claim", response_model=JobResponse)
def claim_guest_score(
    job_id: str,
    payload: ClaimScoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Transfer an anonymous guest score into the authenticated user's library."""
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID '{job_id}' not found")

    job = db.query(Job).filter(Job.id == parsed_id, Job.guest_token == payload.guest_token).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Score not found or invalid claim token")

    if job.user_id is not None:
        if job.user_id == current_user.id:
            return JobResponse.model_validate(job)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Score has already been claimed by another user")

    # Validate user's storage quota
    tier_cfg = get_tier_config(current_user.tier)
    current_storage = get_user_storage_bytes(current_user.id, db)
    if current_storage + job.file_size_bytes > tier_cfg.storage_limit_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE if hasattr(status, "HTTP_413_CONTENT_TOO_LARGE") else 413,
            detail=f"Storage quota exceeded. Your {tier_cfg.display_name} plan has insufficient space to save this score.",
        )

    # Transfer ownership and clear guest token
    job.user_id = current_user.id
    job.guest_token = None
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.post(
    "/upload",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(scope="user"))],
)
@router.post(
    "/jobs/upload",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(scope="user"))],
)
def upload_score(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> JobResponse:
    """Accept an uploaded score (PDF/image) and queue it as a pending OMR job, with instant deduplication caching."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename",
        )

    safe_filename = Path(file.filename).name
    extension = Path(safe_filename).suffix.lower()

    if extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{extension}'. Allowed: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}",
        )

    job_id = uuid.uuid4()
    stored_filename = f"{job_id}_{safe_filename}"
    target_path = settings.UPLOAD_DIR / stored_filename

    # Save uploaded bytes securely with bounded size check and compute SHA-256
    content_hash = save_upload_file_safely(file, target_path, settings.MAX_UPLOAD_SIZE_BYTES)
    file_size = target_path.stat().st_size

    # Validate upload against user tier limits (storage capacity, page count, monthly usage)
    try:
        page_count = validate_upload_quota(current_user, file_size, target_path, db)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise

    # Security Hardening: Validate genuine magic bytes and decompression/resource bounds
    try:
        validate_uploaded_file_safety(target_path, extension)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise

    storage_service = _resolve_storage_service()
    if settings.STORAGE_BACKEND in ("s3", "gcs"):
        storage_key = f"uploads/{stored_filename}"
        with open(target_path, "rb") as f:
            storage_service.save_file(storage_key, f)
        stored_file_ref = storage_key
    else:
        stored_file_ref = str(target_path)

    # Check for deduplication cache hit (existing completed job with valid result file)
    cached_job = (
        db.query(Job)
        .filter(
            Job.content_hash == content_hash,
            Job.status == JobStatus.COMPLETED,
            Job.result_file_path.isnot(None),
        )
        .order_by(Job.created_at.desc())
        .first()
    )

    if cached_job:
        # Cross-tenant data isolation: If cached job belongs to another user,
        # we strictly use the baseline raw prediction (if available) so that User A's private manual edits are never leaked to User B.
        source_ref = (
            cached_job.raw_prediction_path
            if (cached_job.user_id != current_user.id and cached_job.raw_prediction_path and storage_service.exists(cached_job.raw_prediction_path))
            else cached_job.result_file_path
        )
        if source_ref and storage_service.exists(source_ref):
            # Cache hit: duplicate result file to keep job lifecycle independent
            new_result_path = settings.RESULTS_DIR / f"{job_id}.musicxml"
            cached_source = storage_service.get_local_path(source_ref)
            shutil.copyfile(cached_source, new_result_path)

        new_result_size = new_result_path.stat().st_size if new_result_path.exists() else 0

        if settings.STORAGE_BACKEND in ("s3", "gcs"):
            new_result_key = f"results/{job_id}.musicxml"
            with open(new_result_path, "rb") as f:
                storage_service.save_file(new_result_key, f)
            stored_result_ref = new_result_key
            try:
                new_result_path.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            stored_result_ref = str(new_result_path)

        total_job_size = file_size + new_result_size

        job = Job(
            id=job_id,
            user_id=current_user.id,
            status=JobStatus.COMPLETED,
            original_filename=safe_filename,
            file_path=stored_file_ref,
            result_file_path=stored_result_ref,
            content_hash=content_hash,
            page_count=cached_job.page_count or page_count,
            file_size_bytes=total_job_size,
            processing_time_seconds=0.0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return JobResponse.model_validate(job)

    # Cache miss: persist job as pending and dispatch background inference
    job = Job(
        id=job_id,
        user_id=current_user.id,
        status=JobStatus.PENDING,
        original_filename=safe_filename,
        file_path=stored_file_ref,
        content_hash=content_hash,
        page_count=page_count,
        file_size_bytes=file_size,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch asynchronous background task
    proc = _resolve_process_score()
    if not settings.CELERY_ALWAYS_EAGER:
        proc.delay(str(job.id))
    else:
        _execute_eager_omr_task(proc, str(job.id))
        db.refresh(job)

    return JobResponse.model_validate(job)


@router.post(
    "/import-url",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(scope="user"))],
)
@router.post(
    "/scores/import-url",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(scope="user"))],
)
@router.post(
    "/jobs/import-url",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(scope="user"))],
)
async def import_score_from_url(
    background_tasks: BackgroundTasks,
    payload: ScoreUrlImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Download a score from a public web URL, validate safety & quotas, and queue for OMR processing."""
    # Download file safely into staging directory with SSRF protection
    temp_path, inferred_name, file_size = await download_file_from_url(payload.url, settings.UPLOAD_DIR)

    safe_filename = payload.title.strip() if payload.title and payload.title.strip() else inferred_name
    extension = Path(inferred_name).suffix.lower()

    # Ensure clean extension on filename
    if not safe_filename.lower().endswith(extension):
        safe_filename = f"{safe_filename}{extension}"

    job_id = uuid.uuid4()
    stored_filename = f"{job_id}_{Path(safe_filename).name}"
    target_path = settings.UPLOAD_DIR / stored_filename

    # Move from temp download path to target path
    shutil.move(str(temp_path), str(target_path))

    # Compute content hash (SHA-256)
    hasher = hashlib.sha256()
    with open(target_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    content_hash = hasher.hexdigest()

    # Validate upload against user tier limits (storage capacity, page count, monthly usage)
    try:
        page_count = validate_upload_quota(current_user, file_size, target_path, db)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise

    # Security Hardening: Validate genuine magic bytes and decompression/resource bounds
    try:
        validate_uploaded_file_safety(target_path, extension)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise

    storage_service = _resolve_storage_service()
    if settings.STORAGE_BACKEND in ("s3", "gcs"):
        storage_key = f"uploads/{stored_filename}"
        with open(target_path, "rb") as f:
            storage_service.save_file(storage_key, f)
        stored_file_ref = storage_key
    else:
        stored_file_ref = str(target_path)

    # Check for deduplication cache hit
    cached_job = (
        db.query(Job)
        .filter(
            Job.content_hash == content_hash,
            Job.status == JobStatus.COMPLETED,
            Job.result_file_path.isnot(None),
        )
        .order_by(Job.created_at.desc())
        .first()
    )

    if cached_job:
        source_ref = (
            cached_job.raw_prediction_path
            if (cached_job.user_id != current_user.id and cached_job.raw_prediction_path and storage_service.exists(cached_job.raw_prediction_path))
            else cached_job.result_file_path
        )
        if source_ref and storage_service.exists(source_ref):
            new_result_path = settings.RESULTS_DIR / f"{job_id}.musicxml"
            cached_source = storage_service.get_local_path(source_ref)
            shutil.copyfile(cached_source, new_result_path)

        new_result_size = new_result_path.stat().st_size if new_result_path.exists() else 0

        if settings.STORAGE_BACKEND in ("s3", "gcs"):
            new_result_key = f"results/{job_id}.musicxml"
            with open(new_result_path, "rb") as f:
                storage_service.save_file(new_result_key, f)
            stored_result_ref = new_result_key
            try:
                new_result_path.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            stored_result_ref = str(new_result_path)

        total_job_size = file_size + new_result_size

        job = Job(
            id=job_id,
            user_id=current_user.id,
            status=JobStatus.COMPLETED,
            original_filename=safe_filename,
            file_path=stored_file_ref,
            result_file_path=stored_result_ref,
            content_hash=content_hash,
            page_count=cached_job.page_count or page_count,
            file_size_bytes=total_job_size,
            processing_time_seconds=0.0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return JobResponse.model_validate(job)

    # Cache miss: persist job as pending and dispatch background inference
    job = Job(
        id=job_id,
        user_id=current_user.id,
        status=JobStatus.PENDING,
        original_filename=safe_filename,
        file_path=stored_file_ref,
        content_hash=content_hash,
        page_count=page_count,
        file_size_bytes=file_size,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch asynchronous background task
    proc = _resolve_process_score()
    if not settings.CELERY_ALWAYS_EAGER:
        proc.delay(str(job.id))
    else:
        _execute_eager_omr_task(proc, str(job.id))
        db.refresh(job)

    return JobResponse.model_validate(job)


@router.post("/jobs/create", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_custom_score(
    score_data: ScoreCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Create a new score from scratch and save directly into the user's library."""
    title = score_data.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score title cannot be empty",
        )

    raw_xml = score_data.musicxml.strip()
    if not raw_xml:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MusicXML content cannot be empty",
        )

    try:
        import defusedxml.ElementTree as ET
    except ImportError:
        import xml.etree.ElementTree as ET

    try:
        ET.fromstring(raw_xml)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MusicXML structure: {exc}",
        )

    sanitized_xml, _ = sanitize_musicxml_string(raw_xml)
    xml_bytes = sanitized_xml.encode("utf-8")
    file_size = len(xml_bytes)

    # Check storage quota
    tier_cfg = get_tier_config(current_user.tier)
    used_bytes = get_user_storage_bytes(current_user.id, db)
    if used_bytes + file_size > tier_cfg.storage_limit_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Storage quota exceeded for tier '{tier_cfg.name}'. Please upgrade your subscription to save more scores.",
        )

    job_id = uuid.uuid4()
    storage_service = _resolve_storage_service()
    settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    local_result_path = settings.RESULTS_DIR / f"{job_id}.musicxml"

    with open(local_result_path, "wb") as f:
        f.write(xml_bytes)

    if settings.STORAGE_BACKEND in ("s3", "gcs"):
        storage_key = f"results/{job_id}.musicxml"
        with open(local_result_path, "rb") as f:
            storage_service.save_file(storage_key, f)
        stored_result_ref = storage_key
        try:
            local_result_path.unlink(missing_ok=True)
        except Exception:
            pass
    else:
        stored_result_ref = str(local_result_path)

    safe_filename = f"{title}.musicxml" if not title.lower().endswith((".musicxml", ".xml")) else title

    job = Job(
        id=job_id,
        user_id=current_user.id,
        status=JobStatus.COMPLETED,
        original_filename=safe_filename,
        file_path=None,
        result_file_path=stored_result_ref,
        page_count=1,
        file_size_bytes=file_size,
        processing_time_seconds=0.0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.get("/jobs", response_model=list[JobResponse])
def list_user_jobs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[JobResponse]:
    """Retrieve all recognition jobs for the current authenticated user, ordered newest first with optional pagination."""
    reconcile_stale_jobs(db, user_id=current_user.id)
    jobs = (
        db.query(Job)
        .filter(Job.user_id == current_user.id)
        .order_by(Job.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [JobResponse.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> JobResponse:
    """Retrieve the current processing state and details of a job by ID."""
    sample = resolve_sample_file(job_id)
    if sample:
        return JobResponse(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            status=JobStatus.COMPLETED,
            original_filename="Twinkle_Twinkle_Little_Star.musicxml",
            result_file_path=str(sample),
            error_message=None,
        )

    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == parsed_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Reconcile if job has stalled in processing/pending for longer than stale threshold
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
        if job.updated_at and job.updated_at < stale_threshold:
            job.status = JobStatus.FAILED
            job.error_message = INTERRUPTED_JOB_ERROR_MSG
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(job)

    return JobResponse.model_validate(job)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobResponse,
    dependencies=[Depends(rate_limit(scope="user"))],
)
def retry_failed_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force retry even if job is currently marked as processing/pending"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Retry a failed or stalled recognition job using the preserved uploaded file."""
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == parsed_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if job.status == JobStatus.COMPLETED and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is already completed and cannot be retried.",
        )

    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING) and not force:
        stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
        if job.updated_at and job.updated_at >= stale_threshold:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job is currently processing. If it appears stalled, you can retry after 5 minutes or use force=true.",
            )

    storage_service = _resolve_storage_service()
    if not job.file_path or not storage_service.exists(job.file_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Original uploaded file is no longer available in storage. Please upload the score again.",
        )

    # Reset job state to PENDING and clear error message
    job.status = JobStatus.PENDING
    job.error_message = None
    job.processing_time_seconds = None
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    # Re-dispatch background inference
    proc = _resolve_process_score()
    if not settings.CELERY_ALWAYS_EAGER:
        proc.delay(str(job.id))
    else:
        _execute_eager_omr_task(proc, str(job.id))
        db.refresh(job)

    return JobResponse.model_validate(job)


def get_current_user_from_stream(
    token: str | None = Query(None),
    authorization: str | None = Header(None),
) -> User:
    """Authenticate stream connections via ?token= query parameter or Authorization header."""
    raw_token = token
    if not raw_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    with SessionLocal() as db:
        user = get_user_from_token_str(raw_token, db, allow_stream_ticket=True)
        db.expunge(user)
        return user


def _verify_stream_job_ownership(job_id_str: str, user_id: uuid.UUID) -> dict[str, Any]:
    """Verify job existence and ownership in a short-lived synchronous database session."""
    try:
        parsed_id = uuid.UUID(job_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id_str}' not found",
        )

    with SessionLocal() as db:
        job = db.query(Job).filter(Job.id == parsed_id, Job.user_id == user_id).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id_str}' not found",
            )
        return {
            "id": str(job.id),
            "status": job.status,
            "page_count": job.page_count,
            "processing_time_seconds": job.processing_time_seconds,
            "error_message": job.error_message,
        }


@router.get("/jobs/{job_id}/stream")
async def stream_job_events(
    job_id: str,
    current_user: User = Depends(get_current_user_from_stream),
) -> StreamingResponse:
    """Stream real-time job lifecycle events via Server-Sent Events (SSE). Non-blocking async implementation."""
    job_info = await run_in_threadpool(_verify_stream_job_ownership, job_id, current_user.id)
    channel_name = f"job:{job_id}"

    async def async_event_generator():
        # 1. If job is already in terminal state, yield immediately and exit
        if job_info["status"] in (JobStatus.COMPLETED, JobStatus.FAILED):
            payload = {
                "id": job_info["id"],
                "status": job_info["status"].value,
                "page_count": job_info["page_count"],
                "processing_time_seconds": job_info["processing_time_seconds"],
                "error_message": job_info["error_message"],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            return

        initial_payload = {
            "id": job_info["id"],
            "status": job_info["status"].value,
            "page": 0,
            "total_pages": job_info["page_count"] or 1,
        }
        yield f"data: {json.dumps(initial_payload)}\n\n"

        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(channel_name)
        except Exception as exc:
            logger.warning("Could not connect to Redis PubSub for async SSE stream: %s", exc)
            return

        try:
            start_time = time.time()
            max_duration = getattr(settings, "SSE_MAX_DURATION_SECONDS", 900)
            last_ping = start_time
            while time.time() - start_time < max_duration:
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                        timeout=1.5,
                    )
                except asyncio.TimeoutError:
                    msg = None

                if msg and msg["type"] == "message":
                    raw_data = str(msg["data"])
                    yield f"data: {raw_data}\n\n"
                    try:
                        parsed = json.loads(raw_data)
                        if parsed.get("status") in (JobStatus.COMPLETED.value, JobStatus.FAILED.value):
                            break
                    except Exception:
                        pass
                else:
                    now = time.time()
                    if now - last_ping >= 15.0:
                        yield ": ping\n\n"
                        last_ping = now
                await asyncio.sleep(0.05)
        finally:
            try:
                await pubsub.unsubscribe(channel_name)
                if hasattr(pubsub, "aclose"):
                    await pubsub.aclose()
                elif hasattr(pubsub, "close"):
                    await pubsub.close()
                if hasattr(r, "aclose"):
                    await r.aclose()
                elif hasattr(r, "close"):
                    await r.close()
            except Exception:
                pass

    return StreamingResponse(
        async_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sync_musicxml_title(xml_text: str, new_title: str) -> str:
    """Updates or sets <work-title> and <movement-title> in MusicXML string."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)

        work = root.find("work")
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        work_title = work.find("work-title")
        if work_title is None:
            work_title = ET.SubElement(work, "work-title")
        work_title.text = new_title

        mov_title = root.find("movement-title")
        if mov_title is not None:
            mov_title.text = new_title

        for credit in root.findall("credit"):
            ctype = credit.find("credit-type")
            if ctype is not None and ctype.text and ctype.text.strip().lower() == "title":
                cwords = credit.find("credit-words")
                if cwords is not None:
                    cwords.text = new_title

        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    except Exception:
        import re
        if re.search(r"<work-title>[^<]*</work-title>", xml_text):
            xml_text = re.sub(r"<work-title>[^<]*</work-title>", f"<work-title>{new_title}</work-title>", xml_text)
        elif "<work>" in xml_text:
            xml_text = xml_text.replace("<work>", f"<work><work-title>{new_title}</work-title>", 1)
        if re.search(r"<movement-title>[^<]*</movement-title>", xml_text):
            xml_text = re.sub(r"<movement-title>[^<]*</movement-title>", f"<movement-title>{new_title}</movement-title>", xml_text)
        return xml_text


@router.patch("/jobs/{job_id}/rename", response_model=JobResponse)
def rename_job(
    job_id: str,
    payload: JobRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Rename a score job, updating original_filename and synchronizing the MusicXML title."""
    try:
        val_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == val_uuid, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    new_title = payload.title.strip()
    if not new_title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score title cannot be empty",
        )

    orig_ext = Path(job.original_filename).suffix
    if not orig_ext:
        orig_ext = ".musicxml"

    clean_stem = new_title
    if clean_stem.lower().endswith(orig_ext.lower()):
        clean_stem = clean_stem[:-len(orig_ext)]
    clean_stem = clean_stem.strip()
    if not clean_stem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score title cannot be empty",
        )

    safe_filename = "".join(c for c in clean_stem if c.isalnum() or c in (" ", "-", "_", "(", ")", ".")).strip()
    if not safe_filename:
        safe_filename = "Score"
    job.original_filename = f"{safe_filename}{orig_ext}"

    # Also synchronize the MusicXML file title if completed
    storage_service = _resolve_storage_service()
    if job.status == JobStatus.COMPLETED and job.result_file_path and storage_service.exists(job.result_file_path):
        try:
            target_path = storage_service.get_local_path(job.result_file_path)
            if target_path.exists():
                xml_text = target_path.read_text(encoding="utf-8")
                updated_xml = _sync_musicxml_title(xml_text, safe_filename)
                target_path.write_text(updated_xml, encoding="utf-8")
                if settings.STORAGE_BACKEND in ("s3", "gcs"):
                    with open(target_path, "rb") as f:
                        storage_service.save_file(job.result_file_path, f)
        except Exception as exc:
            logger.warning("Could not synchronize MusicXML title for job %s: %s", job_id, exc)

    # Invalidate cached derived exports (.pdf, .mid) so downloads use new title
    if job.result_file_path:
        target_path = storage_service.get_local_path(job.result_file_path)
        for ext in (".pdf", ".mid"):
            cand = target_path.with_suffix(ext)
            if cand.exists():
                cand.unlink(missing_ok=True)
            if settings.STORAGE_BACKEND in ("s3", "gcs"):
                cloud_cand = Path(job.result_file_path).with_suffix(ext)
                storage_service.delete_file(str(cloud_cand))

    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.put("/jobs/{job_id}", response_model=JobResponse)
def update_job_score(
    job_id: str,
    job_update: JobUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Update an existing completed job's MusicXML score with user edits and invalidate cached exports."""
    try:
        val_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == val_uuid, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if job.status != JobStatus.COMPLETED or not job.result_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a score whose transcription is not completed",
        )

    if job_update.title and job_update.title.strip():
        new_title = job_update.title.strip()
        orig_ext = Path(job.original_filename).suffix or ".musicxml"
        if new_title.lower().endswith(orig_ext.lower()):
            new_title = new_title[:-len(orig_ext)].strip()
        safe_filename = "".join(c for c in new_title if c.isalnum() or c in (" ", "-", "_", "(", ")", ".")).strip()
        if safe_filename:
            job.original_filename = f"{safe_filename}{orig_ext}"

    if job_update.musicxml is None:
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return JobResponse.model_validate(job)

    raw_xml = job_update.musicxml.strip()
    if not raw_xml:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MusicXML content cannot be empty",
        )

    try:
        import defusedxml.ElementTree as ET
    except ImportError:
        import xml.etree.ElementTree as ET

    try:
        ET.fromstring(raw_xml)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MusicXML structure: {exc}",
        )

    sanitized_xml, _ = sanitize_musicxml_string(raw_xml)
    sanitized_bytes = len(sanitized_xml.encode("utf-8"))
    storage_service = _resolve_storage_service()

    # Calculate net delta for storage quota and accounting
    old_xml_bytes = 0
    if storage_service.exists(job.result_file_path):
        try:
            old_xml_bytes = len(storage_service.read_bytes(job.result_file_path))
        except Exception:
            old_xml_bytes = 0

    net_delta = sanitized_bytes - old_xml_bytes
    if net_delta > 0:
        tier_cfg = get_tier_config(current_user.tier)
        current_used = get_user_storage_bytes(current_user.id, db)
        if current_used + net_delta > tier_cfg.storage_limit_bytes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "STORAGE_QUOTA_EXCEEDED",
                    "message": f"Storage limit of {tier_cfg.storage_limit_mb} MB exceeded. Please upgrade your subscription tier.",
                    "storage_limit_mb": tier_cfg.storage_limit_mb,
                    "current_usage_bytes": current_used,
                },
            )

    target_path = storage_service.get_local_path(job.result_file_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Capture original raw prediction before overwriting for active learning telemetry
    original_raw_xml = ""
    if job.raw_prediction_path and storage_service.exists(job.raw_prediction_path):
        try:
            original_raw_xml = storage_service.read_bytes(job.raw_prediction_path).decode("utf-8")
        except Exception:
            pass
    elif target_path.exists():
        try:
            original_raw_xml = target_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # Ensure baseline raw prediction is preserved if not already set
    if not job.raw_prediction_path and original_raw_xml:
        raw_key = f"results/{job.id}_raw.musicxml"
        try:
            storage_service.save_bytes(raw_key, original_raw_xml.encode("utf-8"))
            job.raw_prediction_path = raw_key
        except Exception:
            pass

    # Record training triplet if user opted into anonymous model improvement telemetry
    if current_user.allow_omr_telemetry and original_raw_xml:
        from app.services.telemetry_service import record_user_correction
        try:
            record_user_correction(
                db=db,
                job=job,
                raw_xml=original_raw_xml,
                corrected_xml=sanitized_xml,
                user_id=current_user.id,
            )
        except Exception as exc:
            logger.warning("Active learning telemetry capture skipped due to error: %s", exc)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(sanitized_xml)

    if settings.STORAGE_BACKEND in ("s3", "gcs"):
        with open(target_path, "rb") as f:
            storage_service.save_file(job.result_file_path, f)

    # Invalidate cached derived exports (.pdf, .mid)
    for ext in (".pdf", ".mid"):
        cand = target_path.with_suffix(ext)
        if cand.exists():
            cand.unlink(missing_ok=True)
        if settings.STORAGE_BACKEND in ("s3", "gcs"):
            cloud_cand = Path(job.result_file_path).with_suffix(ext)
            storage_service.delete_file(str(cloud_cand))

    if job.file_size_bytes is not None:
        job.file_size_bytes = max(0, job.file_size_bytes + net_delta)
    else:
        job.file_size_bytes = sanitized_bytes
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a recognition job and its associated files from disk."""
    try:
        val_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == val_uuid, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    storage_service = _resolve_storage_service()

    # Clean up uploaded input file if present
    if job.file_path:
        storage_service.delete_file(job.file_path)

    # Clean up result files (musicxml, pdf, midi) if present
    if job.result_file_path:
        storage_service.delete_file(job.result_file_path)
        rpath = Path(job.result_file_path)
        for ext in (".pdf", ".mid"):
            cand = rpath.with_suffix(ext)
            storage_service.delete_file(str(cand))

    # Clean up raw baseline prediction file if present
    if job.raw_prediction_path:
        storage_service.delete_file(job.raw_prediction_path)

    # Preserve historical monthly page processing usage so cleaning up the library doesn't decrease monthly quota
    if job.status == JobStatus.COMPLETED and job.page_count:
        created_at = job.created_at or datetime.now(timezone.utc)
        record_deleted_job_pages(
            user_id=current_user.id,
            created_at=created_at,
            page_count=job.page_count,
            db=db,
        )

    db.delete(job)
    db.commit()
    return None


@router.get("/jobs/{job_id}/validation", response_model=ScoreValidationResponse)
def get_job_rhythm_validation(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScoreValidationResponse:
    """Validate measure rhythms and return detection confidence report for a completed job."""
    sample = resolve_sample_file(job_id)
    if sample:
        issues = validate_musicxml_rhythms(sample)
        total_m = 2
        try:
            import defusedxml.ElementTree as ET
            tree = ET.parse(sample)
            total_m = len(tree.getroot().findall(".//part[1]/measure"))
        except Exception:
            pass
        return ScoreValidationResponse(
            job_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            total_measures=max(1, total_m),
            invalid_measures_count=len(issues),
            issues=[RhythmIssueResponse(**issue.to_dict()) for issue in issues],
        )

    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID '{job_id}' not found")

    job = db.query(Job).filter(Job.id == parsed_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID '{job_id}' not found")

    if job.status != JobStatus.COMPLETED or not job.result_file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job is not completed yet")

    storage_service = _resolve_storage_service()
    if not storage_service.exists(job.result_file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result file not found in storage")

    local_path = storage_service.get_local_path(job.result_file_path)
    issues = validate_musicxml_rhythms(local_path)

    try:
        import defusedxml.ElementTree as ET
        tree = ET.parse(local_path)
        total_m = len(tree.getroot().findall(".//part[1]/measure"))
    except Exception:
        total_m = len(issues)

    return ScoreValidationResponse(
        job_id=job.id,
        total_measures=max(1, total_m),
        invalid_measures_count=len(issues),
        issues=[RhythmIssueResponse(**issue.to_dict()) for issue in issues],
    )


@router.get("/jobs/{job_id}/original")
def get_job_original_file(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_stream),
):
    """Retrieve the original uploaded sheet music document (PDF or image) for side-by-side review."""
    if job_id.lower() in (
        "sample-bach",
        "bach",
        "sample-prelude",
        "prelude",
        "sample-classical",
        "classical",
        "sample-beethoven",
        "beethoven",
        "sample-twinkle",
        "twinkle",
    ):
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        is_bach = "bach" in job_id.lower() or "prelude" in job_id.lower()
        is_beethoven = "beethoven" in job_id.lower() or "ode" in job_id.lower()
        if is_bach:
            candidate = project_root / "sample_scores" / "bach_prelude.pdf"
            media_type = "application/pdf"
        elif is_beethoven:
            candidate = project_root / "sample_scores" / "beethoven_ode_to_joy.png"
            media_type = "image/png"
        else:
            candidate = project_root / "sample_scores" / "twinkle.pdf"
            media_type = "application/pdf"

        if not candidate.exists():
            candidate = project_root / "sample_scores" / "twinkle.pdf"
            media_type = "application/pdf"

        if candidate.exists():
            return FileResponse(
                path=str(candidate),
                media_type=media_type,
                filename=candidate.name,
            )

    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID '{job_id}' not found")

    job = db.query(Job).filter(Job.id == parsed_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This score does not have an original uploaded document (it may have been created from scratch)",
        )

    storage_service = _resolve_storage_service()
    if not storage_service.exists(job.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file not found in storage",
        )

    ext = Path(job.original_filename).suffix.lower()
    media_type = "application/pdf" if ext == ".pdf" else "image/png" if ext == ".png" else "image/jpeg" if ext in (".jpg", ".jpeg") else "application/octet-stream"

    # Stream original file directly to support secure iframe embedding without private keys or third-party redirects
    stream = storage_service.open_stream(job.file_path)
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers=build_content_disposition_headers(job.original_filename, "inline"),
    )
