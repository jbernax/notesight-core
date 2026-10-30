"""Aggregator router for NoteSight API domain modules.

Decomposed domain routers:
- app.api.auth: Authentication, session tokens, registration, email verification, password reset, Google OAuth.
- app.api.users: User profiles, legal terms, GDPR account deletion, password change, tier & quota management.
- app.api.scores: Score uploads, job CRUD, processing streams, MusicXML updates, rhythm validation.
- app.api.exports: MusicXML downloads, multi-page PDF generation, Standard MIDI conversion.
- app.api.collaboration: Score sharing, public score links, score forking, measure annotations.
- app.api.training: OMR active learning telemetry, quality reports, dataset export.
"""

from fastapi import APIRouter

# Import domain routers
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.scores import router as scores_router
from app.api.exports import router as exports_router
from app.api.collaboration import router as collaboration_router
from app.api.training import router as training_router

# Re-exports for test compatibility and backward compatibility
from app.tasks import process_score
from app.services.email import get_email_service
from app.services.storage import get_storage_service
from app.api.helpers import (
    build_content_disposition_headers,
    resolve_sample_file,
    safe_content_disposition_filename,
    save_upload_file_safely,
)

# Unified router aggregating all sub-domain endpoints
router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(scores_router)
router.include_router(exports_router)
router.include_router(collaboration_router)
router.include_router(training_router)

__all__ = [
    "router",
    "auth_router",
    "users_router",
    "scores_router",
    "exports_router",
    "collaboration_router",
    "training_router",
    "process_score",
    "get_email_service",
    "get_storage_service",
    "save_upload_file_safely",
    "resolve_sample_file",
    "safe_content_disposition_filename",
    "build_content_disposition_headers",
]
