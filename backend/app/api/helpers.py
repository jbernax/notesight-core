import hashlib
import logging
import re
from pathlib import Path
from fastapi import HTTPException, UploadFile, status

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


def safe_content_disposition_filename(filename: str) -> str:
    """Sanitize filename to prevent HTTP header injection, newlines, and escaping in Content-Disposition."""
    clean = re.sub(r'[\r\n\x00-\x1f\x7f"]', "", Path(filename).name).strip()
    return clean or "download"


def build_content_disposition_headers(filename: str, disposition: str = "attachment") -> dict[str, str]:
    """Build hardened RFC 5987 / RFC 6266 compliant Content-Disposition header dictionary."""
    from app.services.file_security import format_content_disposition
    return {"Content-Disposition": format_content_disposition(filename, disposition)}


def save_upload_file_safely(file: UploadFile, target_path: Path, max_size_bytes: int) -> str:
    """Save an UploadFile chunk-by-chunk while enforcing a strict maximum size limit and computing SHA-256."""
    chunk_size = 1024 * 1024  # 1MB chunks
    bytes_read = 0
    hasher = hashlib.sha256()
    with open(target_path, "wb") as buffer:
        while True:
            chunk = file.file.read(chunk_size)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_size_bytes:
                buffer.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE if hasattr(status, "HTTP_413_CONTENT_TOO_LARGE") else 413,
                    detail=f"File exceeds maximum allowed size of {max_size_bytes // (1024 * 1024)}MB",
                )
            hasher.update(chunk)
            buffer.write(chunk)
    return hasher.hexdigest()


def resolve_sample_file(job_id_str: str) -> Path | None:
    """Resolve sample demo scores like sample-bach, sample-prelude, or sample-twinkle to their static file paths."""
    sample_key = job_id_str.lower()

    if sample_key in ("sample-bach", "bach", "sample-prelude", "prelude", "sample-classical", "classical"):
        filename = "bach_prelude.musicxml"
    elif sample_key in ("sample-beethoven", "beethoven", "sample-ode", "ode"):
        filename = "beethoven_ode_to_joy.musicxml"
    elif sample_key in ("sample-twinkle", "twinkle", "demo-score-id"):
        filename = "twinkle.musicxml"
    else:
        return None

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        BASE_DIR / "sample_scores" / filename,
        BASE_DIR.parent / "sample_scores" / filename,
        project_root / "sample_scores" / filename,
        project_root / "frontend" / "public" / "samples" / filename,
        Path(f"sample_scores/{filename}").resolve(),
        Path(f"../sample_scores/{filename}").resolve(),
    ]
    for c in candidates:
        if c.exists():
            return c

    # Fallback if twinkle.musicxml was requested but not found: return bach_prelude.musicxml
    if filename == "twinkle.musicxml":
        for alt in (
            project_root / "sample_scores" / "bach_prelude.musicxml",
            BASE_DIR / "sample_scores" / "bach_prelude.musicxml",
        ):
            if alt.exists():
                return alt
    return None

