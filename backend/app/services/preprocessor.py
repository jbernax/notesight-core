from enum import Enum
import logging
from pathlib import Path
import re
from typing import Any
import cv2
import numpy as np
from PIL import Image
import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
PDF_EXTENSIONS = {".pdf"}


class PageType(str, Enum):
    MUSIC_SCORE = "music_score"
    COVER_OR_TITLE = "cover_or_title"
    TEXT_OR_COMMENTARY = "text_or_commentary"
    BLANK = "blank"



def extract_score_pages(file_path: Path, output_dir: Path, dpi: int = 300) -> list[Path]:
    """
    Extract individual pages of a sheet music score into normalized PNG images.

    Args:
        file_path: Path to the input PDF or image score.
        output_dir: Directory where extracted page PNGs will be stored.
        dpi: Resolution for PDF rendering (default 300 for crisp notation).

    Returns:
        List of Paths to the generated PNG images, ordered by page number.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = file_path.suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return _extract_from_pdf(file_path, output_dir, dpi)
    elif suffix in IMAGE_EXTENSIONS:
        return _extract_from_image(file_path, output_dir)
    else:
        raise ValueError(f"Unsupported file format '{suffix}'. Expected PDF or image.")


def detect_halftone_dither(gray: np.ndarray) -> bool:
    """
    Detect whether dark ink strokes are filled with halftone dithering dots or fax raster voids.
    Calculates micro-void density inside dark strokes: tiny white holes completely enclosed by ink.
    """
    ink = (gray < 140).astype(np.uint8) * 255
    ink_px = max(1, cv2.countNonZero(ink))
    if ink_px < 500:
        return False
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(255 - ink, connectivity=4)
    if num_labels <= 1:
        return False
    tiny_holes = int(np.sum((stats[1:, cv2.CC_STAT_AREA] >= 1) & (stats[1:, cv2.CC_STAT_AREA] <= 14)))
    metric = 1000.0 * tiny_holes / float(ink_px)
    return metric >= 2.0


def remove_halftone_dithering(gray: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    """
    Fill halftone dithering voids inside solid noteheads and stems while preserving
    genuine hollow half-notes and whole-notes.
    """
    ink = (gray < 140).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    closed_ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k)
    return 255 - closed_ink


def _extract_from_pdf(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    extracted_paths: list[Path] = []
    # 72 points per inch in PDF coordinate space
    target_scale = dpi / 72.0
    # For high-res dither analysis and smooth antialiasing, render at 600 DPI if targeting 300 DPI
    render_scale = max(target_scale, 600.0 / 72.0) if dpi == 300 else target_scale

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_number in range(len(doc)):
            page = doc[page_number]
            try:
                bitmap = page.render(scale=render_scale)
                arr = bitmap.to_numpy()
                is_bgra = arr.shape[2] == 4
                gray = cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY if is_bgra else cv2.COLOR_BGR2GRAY)
                dithered = detect_halftone_dither(gray)
                if dithered:
                    k_size = 5 if render_scale >= (500.0 / 72.0) else 3
                    gray = remove_halftone_dithering(gray, kernel_size=k_size)
                    logger.info("PDF page %d: detected and removed halftone dithering", page_number + 1)

                if render_scale != target_scale:
                    target_w = max(1, int(round(arr.shape[1] * (target_scale / render_scale))))
                    target_h = max(1, int(round(arr.shape[0] * (target_scale / render_scale))))
                    gray = cv2.resize(gray, (target_w, target_h), interpolation=cv2.INTER_AREA)

                page_file = output_dir / f"page_{page_number + 1}.png"
                cv2.imwrite(str(page_file), cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
                extracted_paths.append(page_file)
            finally:
                page.close()
    finally:
        doc.close()

    return extracted_paths


def _extract_from_image(image_path: Path, output_dir: Path) -> list[Path]:
    page_file = output_dir / "page_1.png"
    with Image.open(image_path) as img:
        # Convert to RGB to normalize paletted or grayscale images
        rgb_img = img.convert("RGB")
        rgb_img.save(page_file, "PNG")
    return [page_file]


SKEW_SEARCH_RANGE_DEG = 15.0
SKEW_MAX_ANALYSIS_SIDE = 1500
# Peak projection sharpness must beat the unrotated page by this factor to trust a non-zero angle
SKEW_MIN_SHARPNESS_GAIN = 1.15


def _to_gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()


def _binarize_ink(gray: np.ndarray) -> np.ndarray:
    """
    Binarize ink as white-on-black, robust to faint/grey scans.

    Combines global Otsu (solid dark ink) with a local adaptive threshold that
    keeps light-grey staff lines Otsu would drop on low-contrast photocopies.
    """
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    return cv2.bitwise_or(otsu, adaptive)


def _projection_sharpness(binary: np.ndarray, angle: float) -> float:
    """Score how sharply ink rows peak after rotating by `angle` (horizontal staff lines peak hardest)."""
    h, w = binary.shape[:2]
    rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    rotated = cv2.warpAffine(binary, rot, (w, h), flags=cv2.INTER_NEAREST)
    row_profile = rotated.sum(axis=1, dtype=np.float64)
    return float(np.var(np.diff(row_profile)))


def _best_projection_angle(binary: np.ndarray, candidates: np.ndarray) -> tuple[float, float]:
    scores = [_projection_sharpness(binary, float(a)) for a in candidates]
    best = int(np.argmax(scores))
    return float(candidates[best]), scores[best]


def detect_staff_skew_angle(image: np.ndarray) -> float:
    """
    Detect the predominant skew angle of staff lines in sheet music.

    Uses a projection-profile search: the page is binarized, rotated over a range
    of candidate angles, and the angle whose row-ink profile peaks most sharply
    (staff lines perfectly horizontal) wins. Unlike line-segment detectors, this
    does not require lines to already be near-horizontal, and it tolerates faint ink.

    Args:
        image: BGR or Grayscale uint8 numpy array.

    Returns:
        Rotation angle in degrees to pass to `deskew_image`. Returns 0.0 if no
        dominant skew is detected.
    """
    gray = _to_gray(image)
    h, w = gray.shape[:2]
    if h < 20 or w < 20:
        return 0.0

    binary = _binarize_ink(gray)
    if cv2.countNonZero(binary) == 0:
        return 0.0

    scale = min(1.0, SKEW_MAX_ANALYSIS_SIDE / float(max(h, w)))
    if scale < 1.0:
        binary = cv2.resize(binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    coarse_angle, _ = _best_projection_angle(
        binary, np.arange(-SKEW_SEARCH_RANGE_DEG, SKEW_SEARCH_RANGE_DEG + 0.01, 0.5)
    )
    fine_angle, fine_score = _best_projection_angle(
        binary, np.arange(coarse_angle - 0.5, coarse_angle + 0.51, 0.1)
    )

    baseline_score = _projection_sharpness(binary, 0.0)
    if baseline_score <= 0.0 or fine_score < baseline_score * SKEW_MIN_SHARPNESS_GAIN:
        return 0.0

    return round(fine_angle, 2)


def deskew_image(image: np.ndarray, angle: float) -> np.ndarray:
    """
    Rotate image to correct staff line skew, filling newly exposed borders with white.

    Args:
        image: BGR or Grayscale image array.
        angle: Skew angle in degrees detected by detect_staff_skew_angle.

    Returns:
        Deskewed image array.
    """
    if abs(angle) < 0.2:
        return image

    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    # Rotate by the angle to bring slanted lines back to 0 degrees horizontal
    rot_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    border_val = (255, 255, 255) if image.ndim == 3 else 255

    deskewed = cv2.warpAffine(
        image,
        rot_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_val,
    )
    return deskewed


def normalize_illumination(image: np.ndarray) -> np.ndarray:
    """
    Normalize non-uniform lighting, paper grain, and scanner shadows.

    Uses macro-scale background estimation via downscaled morphological filtering
    to flatten paper yellowing and corner gradients without attenuating notation contrast.

    Args:
        image: BGR or Grayscale image array.

    Returns:
        Illumination-corrected image array.
    """
    is_color = image.ndim == 3
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if is_color else image.copy()

    # Clean digital safeguard: if background is already uniform white with near-zero std
    bright_pixels = gray[gray >= 240]
    if bright_pixels.size > (gray.size * 0.45) and float(np.std(bright_pixels)) < 5.0:
        return image

    h, w = gray.shape[:2]
    # Macro background estimation using downscaled morphological filtering
    scale = max(0.125, min(0.5, 800.0 / max(h, w)))
    small_w = max(10, int(w * scale))
    small_h = max(10, int(h * scale))
    small = cv2.resize(gray, (small_w, small_h), interpolation=cv2.INTER_AREA)

    # Dilation kernel proportional to staff height (~60px at full res -> ~15-20px on small)
    k_size = max(9, int(35 * scale) | 1)
    bg_small = cv2.morphologyEx(
        small, cv2.MORPH_DILATE, cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
    )
    # Median blur to eliminate remaining notehead artifacts
    blur_k = max(9, int(45 * scale) | 1)
    bg_small = cv2.medianBlur(bg_small, blur_k)

    bg = cv2.resize(bg_small, (w, h), interpolation=cv2.INTER_LINEAR)
    bg = np.maximum(bg, 1)

    # Normalize image by background field: (gray / bg) * 255
    normalized = np.clip(cv2.divide(gray, bg, scale=255), 0, 255).astype(np.uint8)

    if is_color:
        return cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
    return normalized


CONTRAST_PAPER_PERCENTILE = 60.0
# Pixels this much darker than paper count as ink
CONTRAST_INK_MARGIN = 25.0
CONTRAST_INK_PERCENTILE = 10.0
# Below this ink level the darkest strokes are already near-black: no stretch needed
CONTRAST_CLEAN_INK_MAX = 60


def enhance_contrast(image: np.ndarray) -> np.ndarray:
    """
    Stretch faint, washed-out scans so ink approaches black and paper becomes white.

    Maps the typical ink level to 0 and the paper level to 255. Pages whose
    ink is already near-black (clean digital renders, good scans) are returned unchanged.

    Args:
        image: BGR or Grayscale image array (ideally illumination-normalized).

    Returns:
        Contrast-enhanced image array with the same shape and channel layout.
    """
    is_color = image.ndim == 3
    gray = _to_gray(image)

    paper_level = float(np.percentile(gray, CONTRAST_PAPER_PERCENTILE))
    ink_pixels = gray[gray < paper_level - CONTRAST_INK_MARGIN]
    if ink_pixels.size == 0:
        return image
    ink_level = float(np.percentile(ink_pixels, CONTRAST_INK_PERCENTILE))
    if ink_level <= CONTRAST_CLEAN_INK_MAX:
        return image

    lut = np.clip((np.arange(256, dtype=np.float32) - ink_level) * 255.0 / (paper_level - ink_level), 0, 255)
    stretched = cv2.LUT(gray, lut.astype(np.uint8))

    if is_color:
        return cv2.cvtColor(stretched, cv2.COLOR_GRAY2BGR)
    return stretched


def crop_page_borders(image: np.ndarray, padding: int = 20) -> np.ndarray:
    """
    Detect and crop pitch-black scanner margins, page binder edges, or photo backgrounds.

    Args:
        image: BGR or Grayscale image array.
        padding: Safe pixel padding inside the detected content boundary.

    Returns:
        Cropped image array or original if no solid dark border was found.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]

    # Calculate average brightness along edge profiles
    row_means = np.mean(gray, axis=1)
    col_means = np.mean(gray, axis=0)

    # Find regions where mean brightness is above dark border threshold (> 40)
    valid_rows = np.where(row_means >= 40)[0]
    valid_cols = np.where(col_means >= 40)[0]

    if len(valid_rows) == 0 or len(valid_cols) == 0:
        return image

    top = max(0, int(valid_rows[0]) - padding)
    bottom = min(h, int(valid_rows[-1]) + 1 + padding)
    left = max(0, int(valid_cols[0]) - padding)
    right = min(w, int(valid_cols[-1]) + 1 + padding)

    # Ensure cropped area represents at least 40% of page height and width
    if (bottom - top) >= (h * 0.4) and (right - left) >= (w * 0.4):
        # Only crop if we are actually cutting away outer dark bands
        if top > 0 or bottom < h or left > 0 or right < w:
            return image[top:bottom, left:right]

    return image


def classify_score_page(
    image_input: np.ndarray | Path, dpi: int = 300
) -> tuple[PageType, dict[str, Any]]:
    """
    Analyze a document page image to determine if it contains musical score staves
    or is a non-music page (cover, title, text/commentary, or blank).

    Args:
        image_input: Page image array (BGR/Gray) or Path to image.
        dpi: Target image resolution in DPI (defaults to 300).

    Returns:
        Tuple of (PageType, telemetry_dict).
    """
    if isinstance(image_input, (str, Path)):
        img = cv2.imread(str(image_input))
        if img is None:
            return PageType.BLANK, {"is_score": False, "error": "cannot_read_image"}
    else:
        img = image_input

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    h, w = gray.shape[:2]

    # 1. Blank page detection
    dark_pixels = np.sum(gray < 220)
    ink_ratio = float(dark_pixels) / float(gray.size)
    if ink_ratio < 0.003:
        return PageType.BLANK, {
            "is_score": False,
            "page_type": PageType.BLANK.value,
            "ink_ratio": round(ink_ratio, 4),
            "staff_count": 0,
        }

    # 2. Staff line candidate extraction via morphological horizontal opening
    kernel_len = max(20, int(w * 0.04))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    bin_inv = _binarize_ink(gray)
    horiz = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, kernel)

    # Connected components along horizontal lines
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(horiz, connectivity=8)
    min_line_width = int(w * 0.15)
    max_line_height = max(5, int(25 * (dpi / 300.0)))
    line_candidates = [
        s for s in stats[1:]
        if s[cv2.CC_STAT_WIDTH] >= min_line_width and s[cv2.CC_STAT_HEIGHT] <= max_line_height
    ]

    y_centers = sorted([int(s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT] / 2.0) for s in line_candidates])

    # Cluster closely overlapping line segments
    merged_y: list[int] = []
    if y_centers:
        cur = [y_centers[0]]
        for y in y_centers[1:]:
            if y - cur[-1] <= 3:
                cur.append(y)
            else:
                merged_y.append(int(np.mean(cur)))
                cur = [y]
        merged_y.append(int(np.mean(cur)))

    # 3. Detect 5-line staff patterns (uniform interline staff space Sp in [10, 65] px)
    expected_min_sp = max(8, int(10 * (dpi / 300.0)))
    expected_max_sp = max(25, int(65 * (dpi / 300.0)))

    staves: list[list[int]] = []
    i = 0
    while i <= len(merged_y) - 5:
        group = merged_y[i : i + 5]
        diffs = np.diff(group)
        med = float(np.median(diffs))
        if expected_min_sp <= med <= expected_max_sp and np.all(np.abs(diffs - med) <= max(4, med * 0.35)):
            staves.append(group)
            i += 5
        else:
            i += 1

    # 4. Classification determination
    is_score = len(staves) >= 1 or len(line_candidates) >= 15
    if is_score:
        page_type = PageType.MUSIC_SCORE
    else:
        # Distinguish cover/title page from dense prose/commentary
        # Cover pages typically have high title font sizes and lower total text block counts
        page_type = PageType.COVER_OR_TITLE

    telemetry = {
        "page_type": page_type.value,
        "is_score": is_score,
        "staff_clusters": len(staves),
        "line_candidates": len(line_candidates),
        "ink_ratio": round(ink_ratio, 4),
    }
    return page_type, telemetry


def extract_cover_metadata(image_input: np.ndarray | Path) -> dict[str, str]:
    """
    Extract high-level musical metadata (title, composer, arranger, voicing)
    from a cover page using OCR.
    """
    img = cv2.imread(str(image_input)) if isinstance(image_input, (str, Path)) else image_input
    if img is None:
        return {}

    try:
        from app.services.page_text import get_ocr_engine
        ocr = get_ocr_engine()
        if ocr is None:
            return {}
        res = ocr(img)
    except Exception as exc:
        logger.warning("Could not run OCR for cover metadata extraction: %s", exc)
        return {}

    raw_txts = getattr(res, "txts", None)
    if not raw_txts or not isinstance(raw_txts, (list, tuple)):
        return {}

    txts = [t.strip() for t in raw_txts if isinstance(t, str) and t.strip()]
    metadata: dict[str, str] = {}

    for t in txts:
        low = t.lower()
        if any(p in low for p in ["words and music by", "composed by", "music by", "words by"]):
            cleaned = re.sub(
                r"^(words and music by|composed by|music by|words by)\s*:?\s*",
                "",
                t,
                flags=re.IGNORECASE,
            ).strip()
            if cleaned and "composer" not in metadata:
                metadata["composer"] = cleaned
        elif "arranged by" in low or "arr." in low:
            cleaned = re.sub(r"^(arranged by|arr\.)\s*:?\s*", "", t, flags=re.IGNORECASE).strip()
            if cleaned and "arranger" not in metadata:
                metadata["arranger"] = cleaned
        elif any(v in low for v in ["satb", "ssaa", "ttbb", "sab", "2-part", "choir", "a cappella", "piano vocal"]):
            if "voicing" not in metadata:
                cleaned_voicing = re.sub(
                    r"(us\s*\$[\d\.]+|[\d\.]+\s*eur|[\$£€]\d+[\.\d]*)",
                    "",
                    t,
                    flags=re.IGNORECASE,
                ).strip()
                metadata["voicing"] = cleaned_voicing

    # Title detection: look for prominent title string
    for t in txts:
        if re.match(r"^[0-9]+$", t) or "$" in t or "SATB" in t.upper() or "Words and Music" in t or "Arranged" in t:
            continue
        if len(t) > 2 and all(p not in t.upper() for p in ["HAL", "CORPORATION", "ROAD", "MILWAUKEE", "DISTRIBUTED"]):
            metadata["title"] = t
            break

    return metadata


def extract_first_page_header_metadata(
    image_path: Path,
    layout: Any | None = None,
    pdf_path: Path | None = None,
    page_index: int = 0,
) -> dict[str, str]:
    """
    Extract title, composer, and arranger metadata from the header area above the first
    system on the first music score page when no standalone cover page is present.
    """
    if layout is None or getattr(layout, "is_empty", True) or not getattr(layout, "systems", None):
        return {}

    first_sys = layout.systems[0]
    if not first_sys.staves:
        return {}

    top_staff = first_sys.staves[0]
    sp = max(6.0, top_staff.line_spacing)
    header_max_y = top_staff.min_y - 2.0 * sp
    if header_max_y <= 10.0:
        return {}

    try:
        from app.services.page_text import extract_page_words

        all_words = extract_page_words(image_path, pdf_path=pdf_path, page_index=page_index)
    except Exception as exc:
        logger.debug("First-page header metadata extraction skipped: %s", exc)
        return {}

    header_words = [w for w in all_words if w.mid_y < header_max_y and w.text.strip()]
    if not header_words:
        return {}

    # 1. Group words into horizontal rows by mid_y proximity, then sort each row left-to-right by x0
    by_y = sorted(header_words, key=lambda w: w.mid_y)
    rows: list[list[Any]] = []
    for w in by_y:
        w_h = max(8.0, w.y1 - w.y0)
        placed_row = False
        for row in rows:
            row_mid_y = float(np.median([rw.mid_y for rw in row]))
            row_h = float(np.median([max(8.0, rw.y1 - rw.y0) for rw in row]))
            if abs(w.mid_y - row_mid_y) <= 0.55 * max(w_h, row_h):
                row.append(w)
                placed_row = True
                break
        if not placed_row:
            rows.append([w])

    # 2. Within each row (sorted left-to-right), split into phrases when horizontal gap is large
    phrases: list[list[Any]] = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        curr_phrase: list[Any] = [row[0]]
        for w in row[1:]:
            last_w = curr_phrase[-1]
            w_h = max(8.0, w.y1 - w.y0)
            last_h = max(8.0, last_w.y1 - last_w.y0)
            x_gap = w.x0 - last_w.x1
            h_ratio = max(w_h, last_h) / max(1.0, min(w_h, last_h))
            if x_gap <= 110.0 and h_ratio <= 1.45:
                curr_phrase.append(w)
            else:
                phrases.append(curr_phrase)
                curr_phrase = [w]
        phrases.append(curr_phrase)

    sys_min_x = first_sys.min_x
    sys_max_x = first_sys.max_x
    sys_width = max(1.0, sys_max_x - sys_min_x)
    sys_mid_x = 0.5 * (sys_min_x + sys_max_x)

    phrase_infos: list[dict[str, Any]] = []
    for phrase in phrases:
        phrase.sort(key=lambda w: w.x0)
        text = " ".join(w.text.strip() for w in phrase).strip()
        x0 = min(w.x0 for w in phrase)
        x1 = max(w.x1 for w in phrase)
        y0 = min(w.y0 for w in phrase)
        y1 = max(w.y1 for w in phrase)
        avg_h = float(np.median([w.y1 - w.y0 for w in phrase]))
        phrase_infos.append(
            {
                "text": text,
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "mid_x": 0.5 * (x0 + x1),
                "height": avg_h,
            }
        )

    phrase_infos.sort(key=lambda p: (p["y0"], p["x0"]))
    metadata: dict[str, str] = {}

    arr_re = re.compile(
        r"^(?:arranged\s+by|arr\.?|arm\.?|armonizaci[oó]n|harmonized\s+by|adapt\.?)\s*:?\s*(.+)$",
        re.IGNORECASE,
    )
    comp_re = re.compile(
        r"^(?:words\s+and\s+music\s+by|composed\s+by|music\s+by|m[uú]sica|letra\s+y\s+m[uú]sica)\s*:?\s*(.+)$",
        re.IGNORECASE,
    )

    used_indices: set[int] = set()
    for idx, p in enumerate(phrase_infos):
        txt = p["text"]
        m_arr = arr_re.match(txt)
        if m_arr:
            val = m_arr.group(1).strip()
            if val and "arranger" not in metadata:
                metadata["arranger"] = val
                used_indices.add(idx)
            continue
        m_comp = comp_re.match(txt)
        if m_comp:
            val = m_comp.group(1).strip()
            if val and "composer" not in metadata:
                metadata["composer"] = val
                used_indices.add(idx)
            continue

    # Right-aligned header lines (x0 > sys_mid_x + 0.1 * sys_width) without explicit prefix -> composer
    for idx, p in enumerate(phrase_infos):
        if idx in used_indices:
            continue
        if p["x0"] > sys_mid_x + 0.1 * sys_width and p["x1"] > sys_max_x - 8.0 * sp:
            txt = p["text"]
            if len(txt) > 2 and not re.match(r"^[0-9]+$", txt) and "composer" not in metadata:
                metadata["composer"] = txt
                used_indices.add(idx)

    # Centered prominent lines -> title
    centered_candidates = [
        p
        for idx, p in enumerate(phrase_infos)
        if idx not in used_indices
        and abs(p["mid_x"] - sys_mid_x) <= 0.25 * sys_width
        and len(p["text"]) >= 2
        and not re.match(r"^[0-9]+$", p["text"])
    ]
    if centered_candidates:
        max_h = max(p["height"] for p in centered_candidates)
        title_lines = [
            p["text"]
            for p in centered_candidates
            if p["height"] >= 0.72 * max_h
        ]
        if title_lines:
            metadata["title"] = " ".join(title_lines)

    return metadata


def preprocess_page(img: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Normalize a raw page image so staves are horizontal, uncropped by dark margins,
    evenly lit, and high-contrast.

    Steps:
      1. Detect staff line skew and deskew.
      2. Crop dark scanner margins and binder shadows.
      3. Normalize illumination and remove shadows.
      4. Stretch contrast of faint, washed-out scans.

    Args:
        img: Raw BGR or Grayscale page image.

    Returns:
        Tuple of (preprocessed image, telemetry_dict).
    """
    orig_h, orig_w = img.shape[:2]

    skew_angle = detect_staff_skew_angle(img)
    deskewed = deskew_image(img, skew_angle)

    cropped = crop_page_borders(deskewed, padding=20)

    illuminated = normalize_illumination(cropped)
    enhanced = enhance_contrast(illuminated)

    gray_for_dither = _to_gray(enhanced)
    dither_detected = detect_halftone_dither(gray_for_dither)
    if dither_detected:
        k_size = 5 if max(enhanced.shape[:2]) >= 3000 else 3
        cleaned_gray = remove_halftone_dithering(gray_for_dither, kernel_size=k_size)
        enhanced = cv2.cvtColor(cleaned_gray, cv2.COLOR_GRAY2BGR) if enhanced.ndim == 3 else cleaned_gray
        logger.info("preprocess_page: detected and removed halftone dithering (k=%d)", k_size)

    telemetry: dict[str, Any] = {
        "original_size": [orig_w, orig_h],
        "final_size": [enhanced.shape[1], enhanced.shape[0]],
        "skew_angle": skew_angle,
        "deskew_applied": abs(skew_angle) >= 0.2,
        "border_cropped": cropped.shape != deskewed.shape,
        "contrast_enhanced": enhanced is not illuminated,
        "halftone_removed": dither_detected,
        "preprocessed": True,
    }
    return enhanced, telemetry


def preprocess_image_for_omr(image_path: Path, output_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """
    Run `preprocess_page` on an image file before classification and OMR inference.

    Args:
        image_path: Path to the raw extracted page image.
        output_path: Path where the preprocessed image will be written (defaults to overwriting image_path).

    Returns:
        Tuple of (saved_path, telemetry_dict).
    """
    target_path = output_path if output_path is not None else image_path

    img = cv2.imread(str(image_path))
    if img is None:
        logger.warning("Could not read image %s with OpenCV, leaving unchanged.", image_path)
        return image_path, {"preprocessed": False, "error": "imread_failed"}

    enhanced, telemetry = preprocess_page(img)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target_path), enhanced)

    logger.info(
        "Preprocessed page %s: skew=%.2f°, cropped=%s, contrast=%s",
        image_path.name,
        telemetry["skew_angle"],
        telemetry["border_cropped"],
        telemetry["contrast_enhanced"],
    )
    return target_path, telemetry


# Alias for clarity
depurate_image_for_omr = preprocess_image_for_omr

