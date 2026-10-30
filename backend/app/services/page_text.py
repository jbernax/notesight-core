"""
Unified page text extraction service for NoteSight OMR.

Extracts text words and bounding boxes in page pixel coordinates.
First attempts vector text extraction from PDF text layer (fast, exact).
Falls back to high-accuracy RapidOCR on raster images (for scanned scores).
Reuses a single OCR engine instance to avoid redundant model reloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_ocr_engine: Any = None


@dataclass(frozen=True)
class PageWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float = 1.0

    @property
    def mid_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def mid_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


def is_valid_xml_char(c: str) -> bool:
    """Return True if character is a valid XML 1.0 character."""
    cp = ord(c)
    if cp in (0x9, 0xA, 0xD):
        return True
    if 0x20 <= cp <= 0xD7FF:
        return True
    if 0xE000 <= cp <= 0xFFFD:
        return not (0xFDD0 <= cp <= 0xFDEF)
    if 0x10000 <= cp <= 0x10FFFF:
        return (cp & 0xFFFF) not in (0xFFFE, 0xFFFF)
    return False


def sanitize_xml_string(text: str) -> str:
    """Strip all characters that violate W3C XML 1.0 character validity."""
    if not text:
        return ""
    return "".join(c for c in text if is_valid_xml_char(c))


def clean_word_text(text: str) -> str:
    """
    Strip SMuFL, Private Use Area unicode glyphs used by music engraving fonts,
    and any non-XML characters/noncharacters (e.g. U+FFFE, control codes).
    """
    if not text:
        return ""
    cleaned = "".join(
        c for c in text
        if is_valid_xml_char(c) and not (0xE000 <= ord(c) <= 0xF8FF)
    )
    return cleaned.strip()


def get_ocr_engine() -> Any:
    """Lazy singleton for RapidOCR engine to prevent reloading weights on every page."""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception as exc:
            logger.warning("RapidOCR could not be initialized: %s", exc)
            return None
    return _ocr_engine


def extract_pdf_raw_words(page: Any) -> list[tuple[float, float, float, float, str]]:
    """
    Extract words from a pypdfium2 PdfPage in top-down PDF point coordinates (x0, y0, x1, y1, text).
    Accurately segments words based on reading order and spatial geometry to avoid concatenating
    separate vertical lines or verse stanzas where whitespace delimiters are missing.
    """
    _, h_pt = page.get_size()
    tp = page.get_textpage()
    try:
        full_text = tp.get_text_range()
        if not full_text:
            return []

        raw_words: list[tuple[float, float, float, float, str]] = []
        curr_chars: list[str] = []
        curr_boxes: list[tuple[float, float, float, float]] = []

        def _flush_word() -> None:
            if not curr_chars or not curr_boxes:
                return
            word_str = "".join(curr_chars).strip()
            if not word_str:
                return
            x0 = min(b[0] for b in curr_boxes)
            y0 = min(h_pt - b[3] for b in curr_boxes)
            x1 = max(b[2] for b in curr_boxes)
            y1 = max(h_pt - b[1] for b in curr_boxes)
            raw_words.append((float(x0), float(y0), float(x1), float(y1), word_str))

        for i in range(len(full_text)):
            c = full_text[i]
            if c.isspace():
                _flush_word()
                curr_chars.clear()
                curr_boxes.clear()
                continue

            box = tp.get_charbox(i)

            # Check for spatial discontinuity with previous character in current word
            if curr_boxes:
                prev_box = curr_boxes[-1]
                y_prev_mid = (prev_box[1] + prev_box[3]) / 2.0
                y_curr_mid = (box[1] + box[3]) / 2.0
                x_prev_right = prev_box[2]
                x_curr_left = box[0]

                # If vertical position jumps significantly or horizontal position moves backwards,
                # this belongs to a different line or verse stanza.
                if abs(y_curr_mid - y_prev_mid) > 5.0 or x_curr_left < x_prev_right - 4.0:
                    _flush_word()
                    curr_chars.clear()
                    curr_boxes.clear()

            # Handle unmapped glyphs (e.g. U+FFFE / U+FFFF produced by PDFium for missing ToUnicode CMaps)
            if c in ("\ufffe", "\uffff"):
                box_w = abs(box[2] - box[0])
                box_h = abs(box[3] - box[1])
                if box_w > 1.2 * max(0.5, box_h):
                    c = "-"
                else:
                    continue

            curr_chars.append(c)
            curr_boxes.append(box)

        _flush_word()
        return raw_words
    finally:
        tp.close()


def extract_page_words(
    image_input: Path | np.ndarray,
    pdf_path: Path | None = None,
    page_index: int = 0,
    dpi: int = 300,
) -> list[PageWord]:
    """
    Extract text words with bounding boxes in image pixel coordinates.

    Args:
        image_input: Path to the page image file or loaded numpy BGR image.
        pdf_path: Optional original PDF path to check for vector text layer.
        page_index: 0-indexed page number if pdf_path is provided.
        dpi: DPI used when rendering the PDF page to image (default 300).

    Returns:
        List of PageWord objects sorted top-down, left-to-right.
    """
    # 1. Try vector text extraction if PDF is provided
    if pdf_path is not None and pdf_path.exists():
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(pdf_path))
            try:
                if 0 <= page_index < len(doc):
                    page = doc[page_index]
                    try:
                        raw_words = extract_pdf_raw_words(page)
                    finally:
                        page.close()
                    # If the PDF contains a real text layer (more than 5 words)
                    if len(raw_words) > 5:
                        scale = dpi / 72.0
                        words: list[PageWord] = []
                        for w in raw_words:
                            cw = clean_word_text(w[4])
                            if cw:
                                words.append(
                                    PageWord(
                                        text=cw,
                                        x0=float(w[0] * scale),
                                        y0=float(w[1] * scale),
                                        x1=float(w[2] * scale),
                                        y1=float(w[3] * scale),
                                        confidence=1.0,
                                    )
                                )
                        if words:
                            words.sort(key=lambda item: (item.mid_y, item.mid_x))
                            return words
            finally:
                doc.close()
        except Exception as exc:
            logger.debug("PDF text layer extraction skipped: %s", exc)


    # 2. Fallback to RapidOCR on raster image
    ocr = get_ocr_engine()
    if ocr is None:
        return []

    try:
        if isinstance(image_input, (str, Path)):
            ocr_result = ocr(str(image_input))
        else:
            ocr_result = ocr(image_input)

        if not ocr_result:
            return []

        # RapidOCR returns RapidOCROutput dataclass (boxes, txts, scores) or tuple/list
        items: list[Any] = []
        if hasattr(ocr_result, "txts") and hasattr(ocr_result, "boxes") and hasattr(ocr_result, "scores"):
            txts = ocr_result.txts or ()
            boxes = ocr_result.boxes if ocr_result.boxes is not None else ()
            scores = ocr_result.scores or ()
            for b, t, s in zip(boxes, txts, scores):
                items.append((b, t, s))
        elif isinstance(ocr_result, (list, tuple)) and ocr_result:
            first = ocr_result[0]
            if isinstance(first, (list, tuple)):
                items = list(first)
            else:
                items = list(ocr_result)

        words = []
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            box, text, score = item[0], item[1], item[2]
            try:
                conf = float(score)
            except (ValueError, TypeError):
                conf = 0.5

            if conf < 0.4:
                continue

            cw = clean_word_text(str(text))
            if not cw:
                continue

            # box is a 4x2 array or list of points
            box_arr = np.array(box)
            words.append(
                PageWord(
                    text=cw,
                    x0=float(box_arr[:, 0].min()),
                    y0=float(box_arr[:, 1].min()),
                    x1=float(box_arr[:, 0].max()),
                    y1=float(box_arr[:, 1].max()),
                    confidence=conf,
                )
            )

        words.sort(key=lambda item: (item.mid_y, item.mid_x))
        return words
    except Exception as exc:
        logger.warning("RapidOCR extraction failed: %s", exc)
        return []
