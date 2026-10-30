import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, JobStatus, ScoreAnnotation, ScoreShare, User
from app.schemas import (
    PublicSharedScoreResponse,
    ScoreAnnotationCreate,
    ScoreAnnotationResponse,
    ScoreAnnotationUpdate,
    ScoreForkResponse,
    ScoreShareCreate,
    ScoreShareResponse,
)
from app.auth import get_current_user, get_optional_current_user
from app.services.quota import get_tier_config, get_user_storage_bytes
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["collaboration"])


@router.post("/jobs/{job_id}/share", response_model=ScoreShareResponse)
def create_or_update_score_share(
    job_id: str,
    share_in: ScoreShareCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScoreShareResponse:
    """Create or update a public share link for a user's score job."""
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
            detail="Cannot share a score whose transcription is not completed",
        )

    share = db.query(ScoreShare).filter(ScoreShare.job_id == job.id).first()
    expires_at = None
    if share_in.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=share_in.expires_days)

    if share:
        share.allow_playback = share_in.allow_playback
        share.allow_fork = share_in.allow_fork
        share.is_active = True
        share.expires_at = expires_at
    else:
        share = ScoreShare(
            job_id=job.id,
            user_id=current_user.id,
            share_token=secrets.token_urlsafe(32),
            allow_playback=share_in.allow_playback,
            allow_fork=share_in.allow_fork,
            is_active=True,
            expires_at=expires_at,
        )
        db.add(share)

    db.commit()
    db.refresh(share)

    return ScoreShareResponse(
        id=share.id,
        job_id=share.job_id,
        share_token=share.share_token,
        share_url=f"/score/share/{share.share_token}",
        embed_url=f"/score/embed/{share.share_token}",
        allow_playback=share.allow_playback,
        allow_fork=share.allow_fork,
        is_active=share.is_active,
        view_count=share.view_count,
        expires_at=share.expires_at,
        created_at=share.created_at,
    )


@router.get("/jobs/{job_id}/share", response_model=ScoreShareResponse)
def get_score_share(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScoreShareResponse:
    """Retrieve active share link settings for a user's score job."""
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

    share = db.query(ScoreShare).filter(ScoreShare.job_id == job.id).first()
    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No share link configured for this score",
        )

    return ScoreShareResponse(
        id=share.id,
        job_id=share.job_id,
        share_token=share.share_token,
        share_url=f"/score/share/{share.share_token}",
        embed_url=f"/score/embed/{share.share_token}",
        allow_playback=share.allow_playback,
        allow_fork=share.allow_fork,
        is_active=share.is_active,
        view_count=share.view_count,
        expires_at=share.expires_at,
        created_at=share.created_at,
    )


@router.delete("/jobs/{job_id}/share")
def revoke_score_share(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Revoke public share link for a score."""
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

    share = db.query(ScoreShare).filter(ScoreShare.job_id == job.id).first()
    if share:
        db.delete(share)
        db.commit()

    return {"status": "success", "message": "Share link revoked"}


@router.get("/scores/share/{token}", response_model=PublicSharedScoreResponse)
def get_public_shared_score(
    token: str,
    db: Session = Depends(get_db),
) -> PublicSharedScoreResponse:
    """Public endpoint: Retrieve a shared score's metadata and MusicXML content."""
    share = db.query(ScoreShare).filter(ScoreShare.share_token == token, ScoreShare.is_active == True).first()  # noqa: E712
    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared score not found or share link has been revoked",
        )

    if share.expires_at and share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This score share link has expired",
        )

    job = db.query(Job).filter(Job.id == share.job_id).first()
    if not job or not job.result_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Score data not found",
        )

    storage = get_storage_service()
    try:
        xml_bytes = storage.read_bytes(job.result_file_path)
        musicxml_content = xml_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to read MusicXML for shared score %s: %s", job.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load shared score content",
        )

    share.view_count += 1
    db.commit()

    author_name = "Musician"
    if job.owner:
        author_name = job.owner.full_name or job.owner.email.split("@")[0]

    title = Path(job.original_filename).stem
    for suffix in ["_synth", "_omr", "_processed", "_stitched"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)]

    return PublicSharedScoreResponse(
        share_token=share.share_token,
        title=title,
        author_name=author_name,
        musicxml=musicxml_content,
        allow_playback=share.allow_playback,
        allow_fork=share.allow_fork,
        view_count=share.view_count,
        created_at=share.created_at,
    )


@router.post("/scores/share/{token}/fork", response_model=ScoreForkResponse)
def fork_shared_score(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScoreForkResponse:
    """Fork/clone a publicly shared score into the authenticated user's library."""
    share = db.query(ScoreShare).filter(ScoreShare.share_token == token, ScoreShare.is_active == True).first()  # noqa: E712
    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared score not found or share link has been revoked",
        )

    if not share.allow_fork:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cloning and forking are disabled for this shared score by the author",
        )

    if share.expires_at and share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This score share link has expired",
        )

    source_job = db.query(Job).filter(Job.id == share.job_id).first()
    if not source_job or not source_job.result_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Score data not found",
        )

    storage = get_storage_service()
    xml_bytes = storage.read_bytes(source_job.result_file_path)

    tier_cfg = get_tier_config(current_user.tier)
    used_bytes = get_user_storage_bytes(current_user.id, db)
    if used_bytes + len(xml_bytes) > tier_cfg.storage_limit_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Storage quota exceeded for tier '{tier_cfg.name}'. Please upgrade your subscription to save more scores.",
        )

    clean_source_title = Path(source_job.original_filename).stem
    fork_title = f"Fork of {clean_source_title}.musicxml"
    new_job_id = uuid.uuid4()
    result_key = f"{new_job_id}_{fork_title}"
    storage.save_bytes(result_key, xml_bytes)

    forked_job = Job(
        id=new_job_id,
        user_id=current_user.id,
        status=JobStatus.COMPLETED,
        original_filename=fork_title,
        result_file_path=result_key,
        file_size_bytes=len(xml_bytes),
        page_count=source_job.page_count or 1,
    )
    db.add(forked_job)
    db.commit()
    db.refresh(forked_job)

    return ScoreForkResponse(
        forked_job_id=forked_job.id,
        title=fork_title,
        message="Score successfully cloned to your NoteSight Score Library",
    )


@router.get("/jobs/{job_id}/annotations", response_model=list[ScoreAnnotationResponse])
def get_job_annotations(
    job_id: str,
    share_token: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> list[ScoreAnnotationResponse]:
    """Retrieve annotations for a score. Accessible to owner or via active share token."""
    try:
        val_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == val_uuid).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    is_authorized = False
    if current_user and job.user_id == current_user.id:
        is_authorized = True
    elif share_token:
        share = db.query(ScoreShare).filter(
            ScoreShare.job_id == job.id,
            ScoreShare.share_token == share_token,
            ScoreShare.is_active == True,  # noqa: E712
        ).first()
        if share:
            is_authorized = True

    if not is_authorized and not current_user:
        if job.user_id is None:
            is_authorized = True

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view annotations for this score",
        )

    annotations = (
        db.query(ScoreAnnotation)
        .filter(ScoreAnnotation.job_id == job.id)
        .order_by(ScoreAnnotation.measure_number.asc(), ScoreAnnotation.created_at.asc())
        .all()
    )
    return [ScoreAnnotationResponse.model_validate(a) for a in annotations]


@router.post("/jobs/{job_id}/annotations", response_model=ScoreAnnotationResponse)
def create_score_annotation(
    job_id: str,
    annotation_in: ScoreAnnotationCreate,
    share_token: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> ScoreAnnotationResponse:
    """Create a new annotation on a measure. Requires score ownership or active share access."""
    try:
        val_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    job = db.query(Job).filter(Job.id == val_uuid).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    is_authorized = False
    if current_user and job.user_id == current_user.id:
        is_authorized = True
    elif share_token:
        share = db.query(ScoreShare).filter(
            ScoreShare.job_id == job.id,
            ScoreShare.share_token == share_token,
            ScoreShare.is_active == True,  # noqa: E712
        ).first()
        if share and (not share.expires_at or share.expires_at > datetime.now(timezone.utc)):
            is_authorized = True

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to add annotations to this score",
        )

    author_name = "Musician"
    user_id = None
    if current_user:
        author_name = current_user.full_name or current_user.email.split("@")[0]
        user_id = current_user.id
    elif share_token:
        author_name = "Student"

    annotation = ScoreAnnotation(
        job_id=job.id,
        user_id=user_id,
        author_name=author_name,
        measure_number=annotation_in.measure_number,
        staff_index=annotation_in.staff_index,
        annotation_type=annotation_in.annotation_type,
        content=annotation_in.content,
        color=annotation_in.color,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)

    return ScoreAnnotationResponse.model_validate(annotation)


@router.patch("/jobs/{job_id}/annotations/{annotation_id}", response_model=ScoreAnnotationResponse)
def update_score_annotation(
    job_id: str,
    annotation_id: str,
    annotation_update: ScoreAnnotationUpdate,
    share_token: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> ScoreAnnotationResponse:
    """Update content, color, or resolved status of an annotation. Requires score owner or author permissions."""
    try:
        val_job_uuid = uuid.UUID(job_id)
        val_ann_uuid = uuid.UUID(annotation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid UUID")

    job = db.query(Job).filter(Job.id == val_job_uuid).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    annotation = db.query(ScoreAnnotation).filter(
        ScoreAnnotation.id == val_ann_uuid,
        ScoreAnnotation.job_id == val_job_uuid,
    ).first()
    if not annotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")

    is_authorized = False
    if current_user and (job.user_id == current_user.id or annotation.user_id == current_user.id):
        is_authorized = True
    elif share_token and annotation.user_id is None:
        # Guests with share link may only modify anonymous annotations created in shared sessions
        share = db.query(ScoreShare).filter(
            ScoreShare.job_id == job.id,
            ScoreShare.share_token == share_token,
            ScoreShare.is_active == True,  # noqa: E712
        ).first()
        if share and (not share.expires_at or share.expires_at > datetime.now(timezone.utc)):
            is_authorized = True

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this annotation",
        )

    if annotation_update.content is not None:
        annotation.content = annotation_update.content
    if annotation_update.annotation_type is not None:
        annotation.annotation_type = annotation_update.annotation_type
    if annotation_update.color is not None:
        annotation.color = annotation_update.color
    if annotation_update.is_resolved is not None:
        annotation.is_resolved = annotation_update.is_resolved

    db.commit()
    db.refresh(annotation)
    return ScoreAnnotationResponse.model_validate(annotation)


@router.delete("/jobs/{job_id}/annotations/{annotation_id}")
def delete_score_annotation(
    job_id: str,
    annotation_id: str,
    share_token: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, str]:
    """Delete an annotation. Strictly requires score owner or annotation author permissions."""
    try:
        val_job_uuid = uuid.UUID(job_id)
        val_ann_uuid = uuid.UUID(annotation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid UUID")

    job = db.query(Job).filter(Job.id == val_job_uuid).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    annotation = db.query(ScoreAnnotation).filter(
        ScoreAnnotation.id == val_ann_uuid,
        ScoreAnnotation.job_id == val_job_uuid,
    ).first()
    if not annotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")

    is_authorized = False
    if current_user and (job.user_id == current_user.id or (annotation.user_id is not None and annotation.user_id == current_user.id)):
        is_authorized = True

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this annotation",
        )

    db.delete(annotation)
    db.commit()
    return {"status": "success", "message": "Annotation deleted"}
