import io
import logging
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OMRTrainingTriplet, User
from app.schemas import (
    OMRQualityReportResponse,
    OMRTrainingTripletResponse,
)
from app.auth import get_current_user
from app.services.telemetry_service import (
    generate_omr_quality_report,
    export_training_corpus,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["training"])


@router.get("/training/quality-report", response_model=OMRQualityReportResponse)
def get_omr_quality_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OMRQualityReportResponse:
    """Retrieve aggregate conversion quality and active learning telemetry statistics (scoped to user)."""
    report = generate_omr_quality_report(db, user_id=current_user.id)
    return OMRQualityReportResponse(**report)


@router.get("/training/triplets", response_model=list[OMRTrainingTripletResponse])
def get_training_triplets(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OMRTrainingTripletResponse]:
    """List captured training triplets for active learning inspection (scoped to user)."""
    triplets = (
        db.query(OMRTrainingTriplet)
        .filter(OMRTrainingTriplet.user_id == current_user.id)
        .order_by(OMRTrainingTriplet.created_at.desc())
        .limit(limit)
        .all()
    )
    return [OMRTrainingTripletResponse.model_validate(t) for t in triplets]


@router.get("/training/dataset/export")
def export_training_dataset(
    include_augmented: bool = Query(default=False, description="Apply synthetic document augmentations (folds, bleeds, noise) to exported images"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export collected training triplets as a standalone ZIP fine-tuning dataset archive with JSONL manifest (scoped to user)."""
    zip_bytes = export_training_corpus(db=db, include_augmented=include_augmented, limit=limit, user_id=current_user.id)
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="notesight_omr_training_corpus.zip"',
            "Content-Length": str(len(zip_bytes)),
        },
    )
