import logging
from pathlib import Path
import re
from PIL import Image
import pypdf
import pypdfium2 as pdfium
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)

# Ensure Pillow strict decompression bomb limit is globally active
Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS


def detect_magic_file_type(header: bytes) -> str | None:
    """Detect file format based on initial binary magic bytes."""
    if len(header) < 4:
        return None

    # PDF signature (standard %PDF- within the first 1024 bytes)
    if b"%PDF-" in header[:1024]:
        return "pdf"

    # PNG signature: 89 50 4E 47 0D 0A 1A 0A
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    # JPEG signature: FF D8 FF
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    # TIFF signature: II* (little-endian) or MM* (big-endian)
    if header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        return "tiff"

    # BMP signature: BM (42 4D)
    if header.startswith(b"BM"):
        return "bmp"

    return None


def validate_file_magic_bytes(file_path: Path, expected_extension: str) -> None:
    """
    Validate that the file on disk possesses genuine magic bytes matching its declared extension.
    Raises HTTPException(400) if a mismatch or spoofing attempt is detected.
    """
    ext = expected_extension.lower().lstrip(".")
    ext_mapping = {
        "pdf": "pdf",
        "png": "png",
        "jpg": "jpeg",
        "jpeg": "jpeg",
        "tiff": "tiff",
        "tif": "tiff",
        "bmp": "bmp",
    }
    expected_type = ext_mapping.get(ext)
    if not expected_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format extension '.{ext}'.",
        )

    try:
        with open(file_path, "rb") as f:
            header = f.read(1024)
    except Exception as exc:
        logger.error("Failed to read header from %s: %s", file_path, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to read uploaded file header.",
        )

    detected_type = detect_magic_file_type(header)
    if detected_type != expected_type:
        logger.warning(
            "Magic byte validation mismatch for %s: expected '%s', detected '%s'",
            file_path.name,
            expected_type,
            detected_type,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File content does not match extension '.{ext}'. "
                f"Expected genuine {expected_type.upper()} binary header."
            ),
        )


def validate_image_safety(file_path: Path) -> None:
    """
    Inspect image headers to prevent decompression bomb attacks (excessive pixels or dimensions).
    """
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            if width > settings.MAX_IMAGE_DIMENSION or height > settings.MAX_IMAGE_DIMENSION:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Image dimensions ({width}x{height} px) exceed maximum allowable "
                        f"resolution of {settings.MAX_IMAGE_DIMENSION}x{settings.MAX_IMAGE_DIMENSION} px."
                    ),
                )
    except Image.DecompressionBombError as e:
        logger.warning("Decompression bomb detected in image %s: %s", file_path.name, e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image exceeds maximum allowable pixel resolution (decompression bomb protection).",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Corrupt or unreadable image %s: %s", file_path.name, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image file is corrupted or could not be decoded.",
        )


def validate_pdf_safety(file_path: Path) -> None:
    """
    Validate PDF document integrity, page limits, and page dimensions to avoid memory exhaustion.
    """
    try:
        reader = pypdf.PdfReader(str(file_path))
        if reader.is_encrypted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encrypted or password-protected PDF files cannot be processed.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to parse PDF structure %s: %s", file_path.name, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF file is corrupted or malformed.",
        )

    try:
        doc = pdfium.PdfDocument(str(file_path))
    except Exception as exc:
        err_msg = str(exc).lower()
        if "password" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encrypted or password-protected PDF files cannot be processed.",
            )
        logger.warning("Failed to open PDF %s with PDFium: %s", file_path.name, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF file is corrupted or malformed.",
        )

    try:
        page_count = len(doc)
        if page_count > settings.MAX_PDF_PAGES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"PDF document exceeds maximum limit of {settings.MAX_PDF_PAGES} pages (found {page_count}).",
            )

        if page_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF document contains zero pages.",
            )

        # Inspect all pages for abnormal dimensions (>15,000 pt)
        for i in range(page_count):
            width, height = doc.get_page_size(i)
            if width > 15000 or height > 15000:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"PDF page {i+1} dimensions ({int(width)}x{int(height)} pt) exceed safety limit.",
                )
    finally:
        doc.close()


def validate_uploaded_file_safety(file_path: Path, extension: str) -> None:
    """Comprehensive validation: magic bytes + decompression / resource bounds."""
    if not settings.FILE_VALIDATION_ENABLED:
        return
    validate_file_magic_bytes(file_path, extension)
    clean_ext = extension.lower().lstrip(".")
    if clean_ext == "pdf":
        validate_pdf_safety(file_path)
    else:
        validate_image_safety(file_path)


def format_content_disposition(filename: str, disposition: str = "attachment") -> str:
    """
    Format a hardened Content-Disposition header conforming to RFC 5987 / RFC 6266.
    Protects against HTTP header injection (CRLF splitting), unescaped double quotes,
    and non-ASCII character corruption across varied HTTP clients.

    Args:
        filename: Original suggested file name.
        disposition: 'attachment' or 'inline'.

    Returns:
        RFC 5987 compliant header string, e.g.:
        attachment; filename="score.pdf"; filename*=UTF-8''score.pdf
    """
    import urllib.parse

    # 1. Strip all control characters (CR, LF, NULL, tabs) and quotes to neutralize header injection
    sanitized = re.sub(r'[\r\n\x00-\x1f\x7f"]', "", filename).strip()
    if not sanitized:
        sanitized = "download"

    # 2. Extract base safe ASCII name for legacy HTTP/1.0 clients
    ascii_safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sanitized)
    if not ascii_safe or ascii_safe == ".":
        ascii_safe = "download"

    # 3. Percent-encode UTF-8 string per RFC 5987 (filename*=UTF-8''...)
    encoded_utf8 = urllib.parse.quote(sanitized.encode("utf-8"))

    return f'{disposition}; filename="{ascii_safe}"; filename*=UTF-8\'\'{encoded_utf8}'
