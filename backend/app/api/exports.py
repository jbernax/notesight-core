import logging
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Job, JobStatus, User
from app.auth import get_current_user
from app.services.storage import get_storage_service
from app.services.rate_limiter import rate_limit
from app.services.pdf_exporter import export_musicxml_to_pdf
from app.services.midi_exporter import export_musicxml_to_midi
from app.services.musicxml_sanitizer import sanitize_musicxml_tree
from app.services.audit_logger import log_security_event
from app.api.helpers import (
    build_content_disposition_headers,
    resolve_sample_file,
    safe_content_disposition_filename,
    save_upload_file_safely,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["exports"])


def _resolve_storage_service():
    try:
        import app.api.routes as routes_module
        return getattr(routes_module, "get_storage_service", get_storage_service)()
    except Exception:
        return get_storage_service()


@router.get("/jobs/{job_id}/download")
@router.get("/scores/export/{job_id}/musicxml")
def download_musicxml(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Download the finalized MusicXML file for a completed job."""
    sample = resolve_sample_file(job_id)
    if sample:
        is_bach = "bach" in job_id.lower() or "prelude" in job_id.lower() or "bach_prelude" in sample.name
        is_beethoven = "beethoven" in job_id.lower() or "ode" in job_id.lower() or "ode_to_joy" in sample.name
        if is_bach:
            fname = "Johann_Sebastian_Bach_Prelude_in_C_Major_BWV_846.musicxml"
        elif is_beethoven:
            fname = "Ludwig_van_Beethoven_Ode_to_Joy.musicxml"
        else:
            fname = "Twinkle_Twinkle_Little_Star.musicxml"
        return FileResponse(
            path=str(sample),
            media_type="application/vnd.recordare.musicxml+xml",
            filename=fname,
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

    if job.status != JobStatus.COMPLETED or not job.result_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score processing is not yet completed",
        )

    storage_service = _resolve_storage_service()
    if not storage_service.exists(job.result_file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result file not found in storage",
        )

    download_name = f"{Path(job.original_filename).stem}.musicxml"

    # Local & Cloud storage (S3 / GCS / Local): Stream file directly using storage_service.open_stream.
    # Streaming ensures reliable delivery in containerized/Cloud Run environments without requiring private signing keys,
    # prevents leaking client Bearer tokens to cloud storage gateways on redirect, and avoids third-party bucket CORS barriers.
    stream = storage_service.open_stream(job.result_file_path)
    return StreamingResponse(
        stream,
        media_type="application/vnd.recordare.musicxml+xml",
        headers=build_content_disposition_headers(download_name, "attachment"),
    )


@router.get("/jobs/{job_id}/export/pdf")
@router.get("/scores/export/{job_id}/pdf")
def export_job_pdf(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export the recognized score as a printable multi-page PDF."""
    sample = resolve_sample_file(job_id)
    if sample:
        pdf_path = sample.with_suffix(".pdf")
        if not pdf_path.exists():
            export_musicxml_to_pdf(sample, pdf_path)
        is_bach = "bach" in job_id.lower() or "prelude" in job_id.lower() or "bach_prelude" in sample.name
        is_beethoven = "beethoven" in job_id.lower() or "ode" in job_id.lower() or "ode_to_joy" in sample.name
        if is_bach:
            fname = "Johann_Sebastian_Bach_Prelude_in_C_Major_BWV_846.pdf"
        elif is_beethoven:
            fname = "Ludwig_van_Beethoven_Ode_to_Joy.pdf"
        else:
            fname = "Twinkle_Twinkle_Little_Star.pdf"
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            headers=build_content_disposition_headers(fname, "attachment"),
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

    if job.status != JobStatus.COMPLETED or not job.result_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score processing is not yet completed",
        )

    storage_service = _resolve_storage_service()
    if not storage_service.exists(job.result_file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result MusicXML file not found in storage",
        )

    xml_path = storage_service.get_local_path(job.result_file_path)
    pdf_path = xml_path.with_suffix(".pdf")
    if not pdf_path.exists():
        try:
            export_musicxml_to_pdf(xml_path, pdf_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"PDF generation failed: {exc}",
            )

    download_name = f"{Path(job.original_filename).stem}.pdf"
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers=build_content_disposition_headers(download_name, "attachment"),
    )


@router.post(
    "/convert/xml-to-pdf",
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def convert_xml_to_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Directly convert an uploaded MusicXML file into a PDF (useful for batch testing)."""
    import tempfile

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must have a filename")

    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in {".musicxml", ".xml"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be .musicxml or .xml")

    temp_dir = Path(tempfile.mkdtemp())
    temp_xml = temp_dir / safe_name
    temp_pdf = temp_dir / f"{temp_xml.stem}.pdf"

    try:
        save_upload_file_safely(file, temp_xml, settings.MAX_UPLOAD_SIZE_BYTES)
        # Validate XML well-formedness before passing to external Verovio parser
        try:
            try:
                import defusedxml.ElementTree as ET
            except ImportError:
                import xml.etree.ElementTree as ET
            tree = ET.parse(str(temp_xml))
            root = tree.getroot()
        except Exception as parse_err:
            log_security_event("conversion.malformed_xml_rejected", status="FAILURE", details={"error": str(parse_err), "filename": safe_name})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed MusicXML syntax: {parse_err}",
            )

        sanitize_musicxml_tree(root)
        tree.write(str(temp_xml), encoding="utf-8", xml_declaration=True)

        export_musicxml_to_pdf(temp_xml, temp_pdf)
        log_security_event("conversion.xml_to_pdf", status="SUCCESS", details={"filename": safe_name})
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PDF rendering failed: {exc}")

    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)
    return FileResponse(
        path=str(temp_pdf),
        media_type="application/pdf",
        headers=build_content_disposition_headers(f"{temp_xml.stem}.pdf", "attachment"),
    )


@router.get("/jobs/{job_id}/export/midi")
@router.get("/scores/export/{job_id}/midi")
def export_job_midi(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export the recognized score as a downloadable Standard MIDI File (.mid)."""
    sample = resolve_sample_file(job_id)
    if sample:
        midi_path = sample.with_suffix(".mid")
        if not midi_path.exists():
            export_musicxml_to_midi(sample, midi_path)
        is_bach = "bach" in job_id.lower() or "prelude" in job_id.lower() or "bach_prelude" in sample.name
        is_beethoven = "beethoven" in job_id.lower() or "ode" in job_id.lower() or "ode_to_joy" in sample.name
        if is_bach:
            fname = "Johann_Sebastian_Bach_Prelude_in_C_Major_BWV_846.mid"
        elif is_beethoven:
            fname = "Ludwig_van_Beethoven_Ode_to_Joy.mid"
        else:
            fname = "Twinkle_Twinkle_Little_Star.mid"
        return FileResponse(
            path=str(midi_path),
            media_type="audio/midi",
            headers=build_content_disposition_headers(fname, "attachment"),
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

    if job.status != JobStatus.COMPLETED or not job.result_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score processing is not yet completed",
        )

    storage_service = _resolve_storage_service()
    if not storage_service.exists(job.result_file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result MusicXML file not found in storage",
        )

    xml_path = storage_service.get_local_path(job.result_file_path)
    midi_path = xml_path.with_suffix(".mid")
    if not midi_path.exists():
        try:
            export_musicxml_to_midi(xml_path, midi_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MIDI generation failed: {exc}",
            )

    download_name = f"{Path(job.original_filename).stem}.mid"
    return FileResponse(
        path=str(midi_path),
        media_type="audio/midi",
        headers=build_content_disposition_headers(download_name, "attachment"),
    )


@router.post(
    "/convert/xml-to-midi",
    dependencies=[Depends(rate_limit(scope="ip"))],
)
def convert_xml_to_midi(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Directly convert an uploaded MusicXML file into a Standard MIDI File (.mid)."""
    import tempfile

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must have a filename")

    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in {".musicxml", ".xml"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be .musicxml or .xml")

    temp_dir = Path(tempfile.mkdtemp())
    temp_xml = temp_dir / safe_name
    temp_midi = temp_dir / f"{temp_xml.stem}.mid"

    try:
        save_upload_file_safely(file, temp_xml, settings.MAX_UPLOAD_SIZE_BYTES)
        # Validate XML well-formedness before passing to external MIDI encoder
        try:
            try:
                import defusedxml.ElementTree as ET
            except ImportError:
                import xml.etree.ElementTree as ET
            tree = ET.parse(str(temp_xml))
            root = tree.getroot()
        except Exception as parse_err:
            log_security_event("conversion.malformed_xml_rejected", status="FAILURE", details={"error": str(parse_err), "filename": safe_name})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed MusicXML syntax: {parse_err}",
            )

        sanitize_musicxml_tree(root)
        tree.write(str(temp_xml), encoding="utf-8", xml_declaration=True)

        export_musicxml_to_midi(temp_xml, temp_midi)
        log_security_event("conversion.xml_to_midi", status="SUCCESS", details={"filename": safe_name})
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"MIDI generation failed: {exc}")

    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)
    return FileResponse(
        path=str(temp_midi),
        media_type="audio/midi",
        headers=build_content_disposition_headers(f"{temp_xml.stem}.mid", "attachment"),
    )
