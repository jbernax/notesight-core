"""
Unified Score Transcription Pipeline Service.

Encapsulates the end-to-end OMR transcription pipeline:
1. Extract pages (PDF to high-res images or single image)
2. Classify and depurate pages (skip covers/blanks, extract metadata)
3. Preprocess and deskew music score pages
4. Run homr OMR inference with staff layout tracking
5. Extract lyrics and detect voice parts (PDF text layer + RapidOCR)
6. Enrich page MusicXML with lyrics and voice tags
7. Merge and stitch pages with metadata injection, voice autotagging, and consistency repairs
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable

from app.services.lyrics_extractor import (
    enrich_musicxml_with_lyrics,
    extract_lyrics_and_voices,
)
from app.services.omr import PageRecognition, recognize_page
from app.services.preprocessor import (
    PageType,
    classify_score_page,
    extract_cover_metadata,
    extract_first_page_header_metadata,
    extract_score_pages,
    preprocess_image_for_omr,
)
from app.services.stitcher import _parse_xml, merge_musicxml_files
from app.services.volta_detector import detect_and_apply_voltas

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    xml_path: Path
    page_count: int
    total_extracted_pages: int
    metadata: dict[str, str] = field(default_factory=dict)
    voice_names: list[str] = field(default_factory=list)
    skipped_pages: list[dict[str, Any]] = field(default_factory=list)


def transcribe_score(
    source_file: Path,
    output_xml_path: Path,
    work_dir: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> TranscriptionResult:
    """
    Run end-to-end score transcription on a PDF or image file.

    Args:
        source_file: Path to the input PDF or image.
        output_xml_path: Path where the merged MusicXML will be written.
        work_dir: Optional directory for intermediate page images and XMLs.
        on_progress: Optional callback function(page_done, total_music_pages).

    Returns:
        TranscriptionResult with output XML path and metadata.
    """
    if not source_file.exists():
        raise FileNotFoundError(f"Input file not found: {source_file}")

    temp_created = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="transcribe_"))
        temp_created = True
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

    pages_dir = work_dir / "pages"
    try:
        is_pdf = source_file.suffix.lower() == ".pdf"

        # 1. Extract pages
        extracted_pages = extract_score_pages(source_file, pages_dir)
        total_pages = len(extracted_pages)
        logger.info("Transcribe: extracted %d pages from %s", total_pages, source_file.name)

        # 2. Preliminary page analysis & depuration
        music_pages_to_process: list[tuple[int, Path]] = []
        cover_metadata: dict[str, str] = {}
        skipped_pages: list[dict[str, Any]] = []

        for p_idx, p_path in enumerate(extracted_pages, start=1):
            # Preprocess first: tilted / faint scans hide their staves from the classifier
            p_path, prep_telemetry = preprocess_image_for_omr(p_path)
            p_type, p_telemetry = classify_score_page(p_path)
            p_telemetry["preprocess"] = prep_telemetry
            if p_type == PageType.COVER_OR_TITLE and not cover_metadata:
                try:
                    cover_metadata = extract_cover_metadata(p_path)
                except Exception as meta_exc:
                    logger.warning("Cover metadata extraction failed: %s", meta_exc)

            if p_type == PageType.MUSIC_SCORE:
                music_pages_to_process.append((p_idx, p_path))
            else:
                skipped_pages.append({"page": p_idx, "type": p_type.value, "telemetry": p_telemetry})

        # Safeguard fallback for unusual notation
        if not music_pages_to_process:
            if total_pages == 1:
                music_pages_to_process = [(1, extracted_pages[0])]
            else:
                raise ValueError(
                    "No sheet music staves detected in document. Please verify the uploaded file contains musical score staves."
                )

        total_music_pages = len(music_pages_to_process)

        # 3. OMR inference and lyric enrichment on each validated page
        xml_pages: list[Path] = []
        score_voice_names: list[str] = []

        for seq_idx, (orig_page_num, page_img) in enumerate(music_pages_to_process, start=1):
            if on_progress:
                on_progress(seq_idx - 1, total_music_pages)

            rec = recognize_page(page_img)
            xml_page: Path = rec.xml_path if isinstance(rec, PageRecognition) else Path(rec)
            page_layout = getattr(rec, "layout", None)

            if seq_idx == 1 and page_layout is not None:
                try:
                    header_meta = extract_first_page_header_metadata(
                        page_img,
                        layout=page_layout,
                        pdf_path=source_file if is_pdf else None,
                        page_index=orig_page_num - 1,
                    )
                    for k, v in header_meta.items():
                        if v and k not in cover_metadata:
                            cover_metadata[k] = v
                except Exception as meta_exc:
                    logger.debug("First-page header metadata skipped: %s", meta_exc)

            try:
                # Ensure same-pitch slurs are converted to <tie> tags before lyric enrichment
                # so tied continuation notes do not consume lyric syllables, and detect voltas/repeats
                from app.services.musicxml_sanitizer import convert_same_pitch_slurs_to_ties
                from app.services.score_consistency import (
                    align_system_break_measures,
                    remove_empty_ghost_measures,
                )

                if xml_page.exists():
                    page_tree = _parse_xml(xml_page)
                    page_root = page_tree.getroot()
                    removed_g = remove_empty_ghost_measures(page_root)
                    aligned_sys = align_system_break_measures(page_root)
                    converted_t = convert_same_pitch_slurs_to_ties(page_root)
                    voltas_added = detect_and_apply_voltas(
                        page_root,
                        image_path=page_img,
                        layout=page_layout,
                        pdf_path=source_file if is_pdf else None,
                        page_index=orig_page_num - 1,
                    )
                    if removed_g > 0 or aligned_sys > 0 or converted_t > 0 or voltas_added > 0:
                        page_tree.write(xml_page, encoding="utf-8", xml_declaration=True)

                lyrics_by_voice, voice_names = extract_lyrics_and_voices(
                    page_img,
                    layout=page_layout,
                    pdf_path=source_file if is_pdf else None,
                    page_index=orig_page_num - 1,
                    fallback_voices=score_voice_names,
                )
                if voice_names and (not score_voice_names or len(voice_names) > len(score_voice_names)):
                    score_voice_names = voice_names

                if lyrics_by_voice or voice_names:
                    enrich_musicxml_with_lyrics(xml_page, lyrics_by_voice, voice_names)
            except Exception as exc:
                logger.warning("Lyric extraction skipped on page %d: %s", orig_page_num, exc)

            xml_pages.append(xml_page)

            if on_progress:
                on_progress(seq_idx, total_music_pages)

        # 4. Merge all pages into final output
        output_xml_path.parent.mkdir(parents=True, exist_ok=True)
        merge_musicxml_files(xml_pages, output_xml_path, metadata=cover_metadata or None)

        return TranscriptionResult(
            xml_path=output_xml_path,
            page_count=total_music_pages,
            total_extracted_pages=total_pages,
            metadata=cover_metadata,
            voice_names=score_voice_names,
            skipped_pages=skipped_pages,
        )

    finally:
        if temp_created and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
