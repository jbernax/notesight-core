"""
Unified Lyrics and Voice Part Extraction Service for NoteSight OMR.

Extracts voice names (Soprano, Alto, Tenor, Bass, Piano) and song lyrics
from sheet music pages using layout geometry and OCR/PDF text extraction.
Handles both vector PDFs and scanned image scores with RapidOCR fallback.
"""

from __future__ import annotations

from collections import Counter
import logging
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET

import numpy as np

from app.services.page_text import PageWord, clean_word_text, extract_page_words
from app.services.score_layout import PageLayout, StaffBox
from app.services.voice_autotagger import ALIAS_LOOKUP, autotag_musicxml_tree, resolve_voice_tag

logger = logging.getLogger(__name__)

# Backwards-compatible alias map for voice detection
KNOWN_VOICE_NAMES = {k: v.name for k, v in ALIAS_LOOKUP.items()}

DYNAMIC_MARKINGS = {
    "p", "pp", "ppp", "f", "ff", "fff", "mf", "mp", "sfz", "cresc", "dim", "fp", "rfz", "fz"
}

NON_LYRIC_KEYWORDS = {
    "by", "words", "music", "arranged", "approx", "performance", "time", "solo", "tutti",
    "chorus", "verse", "refrain", "intro", "coda", "fine", "da", "capo", "dal", "segno",
    "rit", "rall", "accel", "molto", "poco", "sempre", "div", "unis",
    "tempo", "slower", "faster", "rubato", "allegro", "andante", "adagio",
    "moderato", "presto", "lento", "vivace", "ritardando", "accelerando",
    "cresc", "crescendo", "dim", "diminuendo", "staccato", "legato",
    "rehearsal", "only", "divisi", "cappella"
}

# Common lyric vocabulary for decompounding OCR-merged English tokens (e.g. "Wouldyouknow", "myname")
_COMMON_LYRIC_WORDS: set[str] = {
    "a", "all", "am", "an", "and", "are", "as", "at", "be", "been", "belong", "but", "by",
    "call", "can", "can't", "carry", "cause", "'cause", "come", "could", "cry", "day", "days",
    "deep", "did", "do", "does", "don't", "doodoo", "doo", "dah", "bah", "doom", "down", "dream",
    "dreams", "each", "end", "even", "ever", "every", "eye", "eyes", "face", "fall", "far",
    "feel", "find", "fly", "for", "free", "from", "give", "go", "god", "gone", "good", "grace",
    "hand", "hands", "has", "have", "he", "heal", "hear", "heart", "hearts", "heav", "heaven",
    "help", "her", "here", "high", "him", "his", "hold", "home", "hope", "how", "i", "i'll",
    "i'm", "if", "in", "into", "is", "it", "it's", "joy", "just", "keep", "knees", "know",
    "land", "last", "lead", "leave", "left", "let", "life", "light", "like", "live", "long",
    "look", "lord", "lost", "love", "lovers", "make", "man", "may", "me", "might", "mind",
    "mine", "more", "must", "my", "name", "near", "need", "never", "new", "night", "nights",
    "no", "not", "now", "of", "oh", "on", "once", "one", "only", "open", "or", "our", "out",
    "over", "pain", "past", "peace", "place", "please", "pray", "rain", "reach", "rest", "right",
    "rise", "road", "run", "sad", "safe", "same", "save", "saw", "say", "see", "seem", "set",
    "shall", "she", "shine", "show", "sing", "sky", "sleep", "slow", "so", "some", "iffer",
    "song", "soon", "soul", "sound", "stand", "star", "stars", "stay", "still", "stop", "strong",
    "sun", "sweet", "take", "tears", "tell", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "thing", "things", "think", "this", "those", "though", "through",
    "time", "to", "today", "together", "told", "too", "touch", "true", "trust", "try", "turn",
    "two", "under", "until", "up", "upon", "us", "voice", "wait", "walk", "want", "warm", "was",
    "watch", "water", "way", "we", "weep", "well", "were", "what", "when", "where", "which",
    "while", "white", "who", "whole", "why", "wide", "will", "wind", "wings", "with", "within",
    "without", "word", "words", "world", "would", "wounds", "year", "years", "yes", "yet", "you",
    "your", "yours",
}


def disambiguate_names(names: list[str]) -> list[str]:
    """Append index numbers to duplicate voice names, or Solo + SATB for 5-part S-S-A-T-B."""
    if len(names) == 5 and names == ["Soprano", "Soprano", "Alto", "Tenor", "Bass"]:
        return ["Solo", "Soprano", "Alto", "Tenor", "Bass"]
    counts = Counter(names)
    if not any(c > 1 for c in counts.values()):
        return names
    seen: Counter[str] = Counter()
    result = []
    for n in names:
        if counts[n] > 1:
            seen[n] += 1
            result.append(f"{n} {seen[n]}")
        else:
            result.append(n)
    return result


def _clean_word(text: str) -> str:
    """Strip Private Use Area unicode glyphs used by music engraving fonts."""
    return clean_word_text(text)


def _is_lyric_word(word_text: str) -> bool:
    """Return True if a token represents song lyrics rather than dynamics, tempo, or metadata."""
    cw = clean_word_text(word_text)
    if not cw:
        return False
    lower = cw.lower().strip()
    lower_nopunct = re.sub(r"[^\w]", "", lower)
    if not lower_nopunct:
        return False
    if lower in DYNAMIC_MARKINGS or lower_nopunct in DYNAMIC_MARKINGS:
        return False
    if lower in KNOWN_VOICE_NAMES or resolve_voice_tag(cw) is not None:
        return False
    if lower in NON_LYRIC_KEYWORDS or lower_nopunct in NON_LYRIC_KEYWORDS:
        return False
    # Filter non-Latin single-character OCR artifacts (e.g. Greek rho/theta from whole-note/fermata)
    if len(lower_nopunct) == 1 and ord(lower_nopunct[0]) > 0x024F:
        return False
    # Filter isolated single consonant OCR noise (like 'y' from eighth rest)
    if len(lower_nopunct) == 1 and lower_nopunct not in ("a", "i", "o"):
        return False
    # Pure numbers (measure numbers, page numbers)
    if re.match(r"^\d+$", lower_nopunct):
        return False
    # Tempo/expression markings (e.g. '= ca. 60', 'Allegro', 'rubato', 'rit.', 'tempo', 'Slower')
    if re.search(
        r"[=\(\)]|ca\.|rubato|allegro|andante|adagio|vivace|largo|presto|hymn|moderato|rit\.|rall\.|accel\.|tempo|slower|faster",
        lower,
    ):
        return False
    return True


def _split_concatenated_token(token: str) -> list[str]:
    """
    Decompound a single space-free OCR token that may contain:
      1. Comma-joined words (e.g. 'Now,wouldyouknowmy' -> 'Now,', 'wouldyouknowmy')
      2. CamelCase joins (e.g. "'causeI" -> "'cause", "I", "Isaw" -> "I", "saw", "Dahbah" -> "Dah", "bah")
      3. Repeated scat syllables (e.g. 'doodoodoodoodoo' -> ['doo', 'doo', 'doo', 'doo', 'doo'])
      4. Concatenated common lyric words (e.g. 'Wouldyouknow' -> ['Would', 'you', 'know'],
         'wouldyouhelpmestand' -> ['would', 'you', 'help', 'me', 'stand'],
         'hereinheav' -> ['here', 'in', 'heav'], 'Nomoretears' -> ['No', 'more', 'tears']).
    """
    if not token:
        return []

    # 1. Split after internal commas (e.g. "Now,wouldyou" -> "Now,", "wouldyou")
    if "," in token and not token.endswith(","):
        parts: list[str] = []
        for sub in re.split(r"(?<=,)", token):
            if sub:
                parts.extend(_split_concatenated_token(sub))
        return parts

    # 2. Split camelCase boundaries (e.g. "'causeI" -> "'cause", "I", "Isaw" -> "I", "saw")
    camel_parts = re.split(r"(?<=[a-z])(?=[A-Z])|(?<=I)(?=[a-z]{2,})", token)
    if len(camel_parts) > 1:
        res_camel: list[str] = []
        for cp in camel_parts:
            res_camel.extend(_split_concatenated_token(cp))
        return res_camel

    # Preserve leading/trailing punctuation
    m_punct = re.match(r"^(['\"“”‘’]?)([A-Za-z']+)([,\.\?\!;:]*)$", token)
    if not m_punct:
        return [token]

    lead_p, core, trail_p = m_punct.group(1), m_punct.group(2), m_punct.group(3)
    lower_core = core.lower()

    # 3. Scat syllable repetitions (e.g. doodoodoo, doodooddoodoodoo, dahbah)
    if lower_core == "oop":
        return [("Doo" if core[0].isupper() else "doo") + trail_p]
    if re.fullmatch(r"(?:dood|doo|do|oop|oo)+", lower_core) and len(lower_core) >= 4:
        # Count 'doo' / 'do' units
        scat_matches = re.findall(r"dood|doo|do|oop|oo", lower_core)
        if len(scat_matches) > 1:
            out_scat = []
            for idx, sm in enumerate(scat_matches):
                val = "doo" if sm in ("dood", "doo", "do", "oop", "oo") else sm
                if idx == 0 and core[0].isupper():
                    val = val.capitalize()
                out_scat.append(val)
            return out_scat

    if lower_core == "dahbah":
        return ["Dah" if core[0].isupper() else "dah", "bah" + trail_p]

    # If already a known single word, keep as-is
    if lower_core in _COMMON_LYRIC_WORDS or (lead_p + lower_core) in _COMMON_LYRIC_WORDS:
        return [token]

    # 4. Dynamic programming segmentation into known lyric words
    n = len(lower_core)
    dp: list[list[str] | None] = [None] * (n + 1)
    dp[0] = []

    for i in range(n):
        if dp[i] is None:
            continue
        for j in range(i + 1, n + 1):
            sub_w = lower_core[i:j]
            # Avoid splitting into arbitrary 1-letter words except 'i' or 'a'
            if len(sub_w) == 1 and sub_w not in ("i", "a"):
                continue
            if sub_w in _COMMON_LYRIC_WORDS:
                candidate = dp[i] + [ core[i:j] ]  # type: ignore[operator]
                if dp[j] is None or len(candidate) < len(dp[j]):  # type: ignore[arg-type]
                    dp[j] = candidate

    segmented = dp[n]
    if segmented and len(segmented) > 1:
        segmented[0] = lead_p + segmented[0]
        segmented[-1] = segmented[-1] + trail_p
        return segmented

    return [token]


def _word_to_syllables(word_text: str) -> list[tuple[str, str]]:
    """
    Split a word or multi-word phrase (e.g. 'sanc-tu-ar-y', 'heart', or OCR-grouped 'To heal the wounds')
    into a list of (syllable, syllabic_type) tuples.
    Guarantees no multi-word phrases or OCR-concatenated words are emitted as a single syllable.
    """
    cleaned = clean_word_text(word_text)
    if not cleaned:
        return []

    words = [w.strip() for w in cleaned.split() if w.strip()]
    if not words:
        return []

    res: list[tuple[str, str]] = []
    for w in words:
        if not _is_lyric_word(w):
            continue

        raw_parts = [p.strip() for p in re.split(r"[_\-]+", w) if p.strip()]
        if not raw_parts:
            continue

        has_leading = w.startswith("-") or w.startswith("_")
        has_trailing = w.endswith("-") or w.endswith("_")

        # Decompound each hyphen-delimited segment in case OCR merged prior words onto a hyphenated word
        # (e.g. 'hereinheav-en' -> raw_parts=['hereinheav', 'en'] -> ['here', 'in', 'heav'] + ['en'])
        expanded_parts: list[tuple[str, bool, bool]] = []
        for idx, p in enumerate(raw_parts):
            is_first = idx == 0
            is_last = idx == len(raw_parts) - 1
            sub_tokens = _split_concatenated_token(p)
            for s_idx, st in enumerate(sub_tokens):
                if len(raw_parts) == 1 and not _is_lyric_word(st):
                    continue
                # Only the first sub-token of the first raw_part inherits has_leading;
                # only the last sub-token of a raw_part connects across the hyphen!
                st_lead = (has_leading if is_first else True) if s_idx == 0 else False
                st_trail = (has_trailing if is_last else True) if s_idx == len(sub_tokens) - 1 else False
                expanded_parts.append((st, st_lead, st_trail))

        for st, st_lead, st_trail in expanded_parts:
            if st_lead and st_trail:
                res.append((st, "middle"))
            elif st_lead:
                res.append((st, "end"))
            elif st_trail:
                res.append((st, "begin"))
            else:
                res.append((st, "single"))

    return res


def _cluster_words_into_lines(words: list[PageWord], line_threshold: float | None = None) -> list[list[PageWord]]:
    """
    Cluster words within a staff band into separate horizontal lines/verses ordered top-to-bottom.
    Uses an adaptive vertical threshold derived from median word height (~9-10px at 300 DPI) so
    closely stacked verses (e.g. 14-15px apart) are cleanly separated into distinct verse lines.
    """
    if not words:
        return []
    if line_threshold is None:
        heights = [max(4.0, w.y1 - w.y0) for w in words]
        median_h = float(np.median(heights)) if heights else 16.0
        line_threshold = max(7.5, min(11.0, median_h * 0.55))

    sorted_words = sorted(words, key=lambda w: w.mid_y)
    lines: list[list[PageWord]] = []
    current_line = [sorted_words[0]]
    current_y = sorted_words[0].mid_y
    for w in sorted_words[1:]:
        if abs(w.mid_y - current_y) <= line_threshold:
            current_line.append(w)
            current_y = sum(x.mid_y for x in current_line) / len(current_line)
        else:
            lines.append(sorted(current_line, key=lambda x: x.mid_x))
            current_line = [w]
            current_y = w.mid_y
    if current_line:
        lines.append(sorted(current_line, key=lambda x: x.mid_x))
    return lines


def extract_lyrics_and_voices(
    image_input: Path | np.ndarray,
    layout: PageLayout | None = None,
    pdf_path: Path | None = None,
    page_index: int = 0,
    fallback_voices: list[str] | None = None,
    dpi: int = 300,
) -> tuple[dict[int, list[ Any ]], list[str]]:
    """
    Extract song lyrics and voice names for a page using score layout and OCR text.

    Args:
        image_input: Page image path or loaded BGR image.
        layout: PageLayout object from OMR containing detected staves and systems.
        pdf_path: Optional source PDF file for vector text extraction.
        page_index: 0-indexed page number in the source PDF.
        fallback_voices: Inherited voice names from preceding pages.
        dpi: Target DPI for coordinates.

    Returns:
        tuple of:
          - dict mapping part/voice index -> list of lyric syllables (or system-scoped dict)
          - list of detected voice names (e.g. ['Soprano', 'Alto', 'Tenor', 'Bass'])
    """
    # 1. Extract all text words on the page (from PDF text layer or RapidOCR)
    words = extract_page_words(image_input, pdf_path=pdf_path, page_index=page_index, dpi=dpi)

    # 2. If score layout is available from homr, use layout-guided association
    if layout is not None and not layout.is_empty:
        detected_part_voices: dict[int, str] = {}
        all_part_indices = sorted(list({s.part for sys_ in layout.systems for s in sys_.staves}))
        num_parts = len(all_part_indices)

        # Detect voice names from the first system on this page
        first_system = layout.systems[0]
        sys_left = min(s.min_x for s in first_system.staves)

        # Voice labels are located along the left margin
        left_words = [w for w in words if w.mid_x < sys_left + 45 and resolve_voice_tag(w.text) is not None]

        for staff in first_system.staves:
            s_mid = (staff.min_y + staff.max_y) / 2.0
            matching = [w for w in left_words if abs(w.mid_y - s_mid) <= max(45.0, staff.height * 0.9)]
            if staff.is_grandstaff:
                choral_tags = {resolve_voice_tag(w.text) for w in matching if resolve_voice_tag(w.text) is not None}
                vocal_tags = [t for t in choral_tags if t is not None and t.family == "vocal"]
                from app.services.voice_autotagger import TAG_PIANO
                has_piano_label = any(t == TAG_PIANO for t in choral_tags)
                if has_piano_label:
                    detected_part_voices[staff.part] = "Piano"
                elif len(vocal_tags) >= 2 or any(t.name in ("Choir (SATB)", "Soprano", "Alto", "Tenor", "Bass") for t in vocal_tags):
                    detected_part_voices[staff.part] = "Choir (SATB)"
                elif matching:
                    closest = min(matching, key=lambda w: abs(w.mid_y - s_mid))
                    info = resolve_voice_tag(closest.text)
                    if info:
                        detected_part_voices[staff.part] = info.name
                else:
                    # Check if there are lyric words inside the grand staff inter-staff gap
                    gap_top = staff.min_y + 0.28 * staff.height
                    gap_bottom = staff.max_y - 0.28 * staff.height
                    has_gap_lyrics = any(
                        gap_top <= w.mid_y <= gap_bottom
                        and (staff.min_x - 35.0) <= w.mid_x <= (staff.max_x + 35.0)
                        and _is_lyric_word(w.text)
                        for w in words
                    )
                    detected_part_voices[staff.part] = "Choir (SATB)" if has_gap_lyrics else "Piano"
            elif matching:
                closest = min(matching, key=lambda w: abs(w.mid_y - s_mid))
                info = resolve_voice_tag(closest.text)
                if info:
                    detected_part_voices[staff.part] = info.name

        # Check subsequent systems for any parts not yet detected
        for subsequent_sys in layout.systems[1:]:
            if len(detected_part_voices) == num_parts:
                break
            sub_left = min(s.min_x for s in subsequent_sys.staves)
            sub_left_words = [w for w in words if w.mid_x < sub_left + 45 and resolve_voice_tag(w.text) is not None]
            for staff in subsequent_sys.staves:
                if staff.part in detected_part_voices:
                    continue
                s_mid = (staff.min_y + staff.max_y) / 2.0
                matching = [w for w in sub_left_words if abs(w.mid_y - s_mid) <= max(45.0, staff.height * 0.9)]
                if matching:
                    closest = min(matching, key=lambda w: abs(w.mid_y - s_mid))
                    info = resolve_voice_tag(closest.text)
                    if info:
                        detected_part_voices[staff.part] = info.name

        voice_names: list[str] = []
        if len(detected_part_voices) == num_parts:
            raw_names = [detected_part_voices[p] for p in range(num_parts)]
            voice_names = disambiguate_names(raw_names)
        elif detected_part_voices and fallback_voices and len(fallback_voices) == num_parts:
            # Preserve all newly detected voice names, filling only genuinely missing slots from fallback_voices
            raw_names = [
                detected_part_voices[p] if p in detected_part_voices else fallback_voices[p]
                for p in range(num_parts)
            ]
            voice_names = disambiguate_names(raw_names)
        elif fallback_voices and len(fallback_voices) == num_parts:
            voice_names = fallback_voices
        elif detected_part_voices:
            raw_names = [detected_part_voices.get(p, f"Part {p + 1}") for p in range(num_parts)]
            voice_names = disambiguate_names(raw_names)
        elif fallback_voices:
            voice_names = fallback_voices
        elif page_index > 0 and pdf_path:
            # Check page 0 for voice names
            _, voice_names = extract_lyrics_and_voices_from_pdf(pdf_path, 0)

        # Extract lyrics below each staff, keeping both a flat list (for backwards compatibility)
        # and per-system Verse 1 / Verse 2 lists so system boundaries never drift
        lyrics_by_voice: dict[Any, Any] = {p: [] for p in range(num_parts)}
        systems_by_voice: dict[int, list[dict[int, list[tuple[str, str]]]]] = {
            p: [{} for _ in range(len(layout.systems))] for p in range(num_parts)
        }

        for sys_idx, system in enumerate(layout.systems):
            for s_idx, staff in enumerate(system.staves):
                p_idx = staff.part
                # Skip piano parts for lyrics if vocal parts exist
                is_piano_part = detected_part_voices.get(p_idx) == "Piano" or staff.is_grandstaff
                if is_piano_part and any(v != "Piano" for v in detected_part_voices.values()):
                    continue

                if staff.is_grandstaff:
                    # In a grand staff (short score hymnal or choral piece), lyrics typically sit
                    # in the inter-staff gap between the upper (treble) and lower (bass) staves.
                    gap_top = staff.min_y + 0.28 * staff.height
                    gap_bottom = staff.max_y - 0.28 * staff.height
                    inter_words = [
                        w for w in words
                        if gap_top <= w.mid_y <= gap_bottom
                        and (staff.min_x - 35.0) <= w.mid_x <= (staff.max_x + 35.0)
                        and _is_lyric_word(w.text)
                    ]
                    band_top = staff.max_y - 2.0
                    next_staff = layout.staff_below(sys_idx, s_idx)
                    if next_staff is not None and next_staff.min_y > staff.max_y:
                        band_bottom = min(next_staff.min_y - 4.0, staff.max_y + max(75.0, staff.height * 1.6))
                    else:
                        band_bottom = staff.max_y + min(85.0, staff.height * 1.4)
                    below_words = [
                        w for w in words
                        if band_top <= w.mid_y <= band_bottom
                        and (staff.min_x - 35.0) <= w.mid_x <= (staff.max_x + 35.0)
                        and _is_lyric_word(w.text)
                    ]
                    band_words = inter_words if len(inter_words) >= len(below_words) else below_words
                else:
                    band_top = staff.max_y - 2.0
                    next_staff = layout.staff_below(sys_idx, s_idx)
                    if next_staff is not None and next_staff.min_y > staff.max_y:
                        band_bottom = min(next_staff.min_y - 4.0, staff.max_y + max(75.0, staff.height * 1.6))
                    else:
                        band_bottom = staff.max_y + min(85.0, staff.height * 1.4)

                    band_words = [
                        w for w in words
                        if band_top <= w.mid_y <= band_bottom
                        and (staff.min_x - 35.0) <= w.mid_x <= (staff.max_x + 35.0)
                        and _is_lyric_word(w.text)
                    ]
                lines = _cluster_words_into_lines(band_words)
                if not lines:
                    continue

                if len(lines) == 1:
                    v1_sylls: list[tuple[str, str]] = []
                    for w in lines[0]:
                        v1_sylls.extend(_word_to_syllables(w.text))
                    lyrics_by_voice[p_idx].extend(v1_sylls)
                    systems_by_voice[p_idx][sys_idx][1] = v1_sylls
                else:
                    l1, l2 = lines[0], lines[1]
                    last_x = max(w.x1 for w in l1)
                    shared = [w for w in l2 if w.x0 > last_x + 15]
                    v1_words = l1 + shared
                    v1_sylls = []
                    for w in v1_words:
                        v1_sylls.extend(_word_to_syllables(w.text))
                    lyrics_by_voice[p_idx].extend(v1_sylls)
                    systems_by_voice[p_idx][sys_idx][1] = v1_sylls

                    # Extract Verse 2 words (the non-shared portion of l2)
                    v2_words = [w for w in l2 if w.x0 <= last_x + 15]
                    if v2_words:
                        v2_sylls: list[tuple[str, str]] = []
                        for w in v2_words:
                            v2_sylls.extend(_word_to_syllables(w.text))
                        if v2_sylls:
                            systems_by_voice[p_idx][sys_idx][2] = v2_sylls

        lyrics_by_voice["__systems__"] = systems_by_voice
        return lyrics_by_voice, voice_names

    # 3. Fallback: if no layout is provided, attempt vector PDF extraction if available
    if pdf_path is not None and pdf_path.exists():
        return extract_lyrics_and_voices_from_pdf(pdf_path, page_index, fallback_voices=fallback_voices)

    return {}, fallback_voices or []


def extract_lyrics_and_voices_from_pdf(
    pdf_path: Path,
    page_index: int,
    fallback_voices: list[str] | None = None,
) -> tuple[dict[int, list[str | tuple[str, str]]], list[str]]:
    """Legacy helper for vector PDF extraction, now using OCR fallback if text layer is empty."""
    h_lines: list[tuple[float, float, float]] = []
    words: list[tuple[float, float, float, float, str]] = []
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
        from app.services.page_text import extract_pdf_raw_words

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            if page_index < 0 or page_index >= len(doc):
                return {}, fallback_voices or []
            page = doc[page_index]
            try:
                _, h_pt = page.get_size()
                words = extract_pdf_raw_words(page)
                # 1. Detect horizontal staff line clusters from PDF path objects
                for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_PATH]):
                    left, bottom, right, top = obj.get_bounds()
                    y_top = h_pt - top
                    y_bot = h_pt - bottom
                    if abs(y_bot - y_top) < 2.0 and abs(right - left) > 60:
                        h_lines.append(((y_top + y_bot) / 2.0, left, right))
            finally:
                page.close()
        finally:
            doc.close()
    except Exception as exc:
        logger.warning("Failed to inspect PDF with pypdfium2: %s", exc)
        return {}, fallback_voices or []


    ys = sorted(list(set(round(h[0], 1) for h in h_lines)))
    staffs = []
    if ys:
        current = [ys[0]]
        for y in ys[1:]:
            if y - current[-1] < 12:
                current.append(y)
            else:
                if len(current) >= 4:
                    staffs.append((current[0], current[-1]))
                current = [y]
        if len(current) >= 4:
            staffs.append((current[0], current[-1]))

    # 2. Detect voice labels along the left margin (x < 75 pt)
    raw_labels = [
        w for w in words if w[0] < 75 and resolve_voice_tag(w[4]) is not None
    ]
    raw_labels = sorted(raw_labels, key=lambda w: w[1])

    staff_labels = []
    for s_top, s_bottom in staffs:
        s_mid = (s_top + s_bottom) / 2
        m = [w for w in raw_labels if abs((w[1] + w[3]) / 2 - s_mid) < 30]
        if m:
            info = resolve_voice_tag(m[0][4])
            staff_labels.append(info.name if info else None)
        else:
            staff_labels.append(None)

    system_voices = []
    for idx, lbl in enumerate(staff_labels):
        if lbl is not None:
            if idx > 0 and lbl == staff_labels[0]:
                break
            system_voices.append(lbl)
        elif system_voices:
            break

    if system_voices:
        voice_names = disambiguate_names(system_voices)
    elif fallback_voices:
        voice_names = fallback_voices
    elif page_index > 0:
        _, voice_names = extract_lyrics_and_voices_from_pdf(pdf_path, 0)
    else:
        voice_names = []

    if not staffs:
        return {}, voice_names

    num_voices = len(voice_names) if voice_names else 1
    lyrics_by_voice: dict[int, list[str | tuple[str, str]]] = {i: [] for i in range(num_voices)}
    for s_idx, (s_top, s_bottom) in enumerate(staffs):
        v_idx = s_idx % num_voices
        next_top = staffs[s_idx + 1][0] if s_idx + 1 < len(staffs) else s_bottom + 80
        lyric_y0 = s_bottom + 2
        lyric_y1 = min(next_top - 5, s_bottom + 65)

        band = [w for w in words if lyric_y0 <= (w[1] + w[3]) / 2 <= lyric_y1]
        band = sorted(band, key=lambda w: w[0])

        for w in band:
            sylls = _word_to_syllables(w[4])
            lyrics_by_voice[v_idx].extend(sylls)

    return lyrics_by_voice, voice_names


def extract_lyrics_from_image(image_path: Path) -> tuple[dict[int, list[str | tuple[str, str]]], list[str]]:
    """Legacy helper: extract lyrics from a raster image."""
    words = extract_page_words(image_path)
    lyrics: list[str | tuple[str, str]] = []
    for w in words:
        sylls = _word_to_syllables(w.text)
        lyrics.extend(sylls)
    return ({0: lyrics} if lyrics else {}), []


def _attach_syllable_to_note(note: ET.Element, syll_item: Any, verse_number: int = 1) -> None:
    """Attach a single <lyric number=verse_number> element to a note."""
    if isinstance(syll_item, (tuple, list)) and len(syll_item) >= 2:
        syll_text = str(syll_item[0])
        syllabic_type = str(syll_item[1])
    else:
        syll_text = str(syll_item)
        syllabic_type = "single"

    syll_text = clean_word_text(syll_text)
    if not syll_text:
        return

    lyric = ET.SubElement(note, "lyric")
    lyric.set("number", str(verse_number))
    if syllabic_type in ("begin", "middle", "end", "single"):
        syl_el = ET.SubElement(lyric, "syllabic")
        syl_el.text = syllabic_type
    text_elem = ET.SubElement(lyric, "text")
    text_elem.text = syll_text


def _is_lyric_eligible_note(note: ET.Element) -> bool:
    """Return True if a note is a primary sounding note that should receive a lyric syllable."""
    is_rest = note.find("rest") is not None
    is_chord = note.find("chord") is not None
    is_grace = note.find("grace") is not None
    if is_rest or is_chord or is_grace:
        return False
    voice_text = (note.findtext("voice") or "1").strip()
    if voice_text != "1":
        return False
    ties = note.findall("tie")
    tie_types = [t.get("type") for t in ties]
    if not tie_types:
        tied_notations = note.findall(".//notations/tied")
        tie_types = [t.get("type") for t in tied_notations]
    is_tied_continuation = "stop" in tie_types and "start" not in tie_types
    return not is_tied_continuation


def enrich_musicxml_with_lyrics(
    musicxml_path: Path,
    lyrics_by_voice: dict[Any, Any],
    voice_names: list[str] | None = None,
) -> Path:
    """
    Enrich an existing MusicXML file with extracted lyrics and voice names.
    Supports syllabic tagging (<syllabic>begin/middle/end/single</syllabic>),
    system-scoped alignment (preventing cross-system drift), and multi-verse lyrics.
    """
    if not musicxml_path.exists():
        return musicxml_path

    try:
        tree = dET.parse(musicxml_path)
        root = tree.getroot()

        # 1. Update part names if voice names are known
        if voice_names:
            score_parts = root.findall(".//part-list/score-part")
            for idx, sp in enumerate(score_parts):
                if idx < len(voice_names):
                    pname = sp.find("part-name")
                    if pname is not None:
                        pname.text = voice_names[idx]
                    else:
                        pn = ET.SubElement(sp, "part-name")
                        pn.text = voice_names[idx]

        systems_map: dict[int, list[dict[int, list[tuple[str, str]]]]] | None = lyrics_by_voice.get("__systems__")

        # 2. Attach lyrics to sounding notes for each part and sanitize existing multi-word lyrics
        parts = root.findall(".//part")
        for p_idx, part in enumerate(parts):
            measures = part.findall("measure")
            # Group measures into systems using <print new-system="yes"/>
            system_measure_groups: list[list[ET.Element]] = [[]]
            for m in measures:
                if m.find("print[@new-system='yes']") is not None and system_measure_groups[-1]:
                    system_measure_groups.append([])
                system_measure_groups[-1].append(m)

            part_systems = systems_map.get(p_idx) if systems_map else None

            if part_systems and len(part_systems) == len(system_measure_groups):
                # System-scoped attachment: each system's syllables align strictly to that system's notes
                for sys_idx, sys_measures in enumerate(system_measure_groups):
                    verse_dict = part_systems[sys_idx]
                    v1_sylls = verse_dict.get(1) or []
                    v2_sylls = verse_dict.get(2) or []
                    v1_idx = 0
                    v2_idx = 0
                    for measure in sys_measures:
                        for note in measure.findall("note"):
                            if not _is_lyric_eligible_note(note):
                                continue
                            existing_lyric = note.find("lyric")
                            if existing_lyric is None:
                                if v1_idx < len(v1_sylls):
                                    _attach_syllable_to_note(note, v1_sylls[v1_idx], verse_number=1)
                                    v1_idx += 1
                                if v2_idx < len(v2_sylls):
                                    _attach_syllable_to_note(note, v2_sylls[v2_idx], verse_number=2)
                                    v2_idx += 1
                            else:
                                text_elem = existing_lyric.find("text")
                                if text_elem is not None and text_elem.text and " " in text_elem.text.strip():
                                    tokens = text_elem.text.strip().split()
                                    if tokens:
                                        text_elem.text = clean_word_text(tokens[0])
            else:
                # Fallback flat attachment across the page
                syllables = lyrics_by_voice.get(p_idx) or []
                syll_idx = 0
                for measure in measures:
                    for note in measure.findall("note"):
                        if not _is_lyric_eligible_note(note):
                            continue
                        existing_lyric = note.find("lyric")
                        if existing_lyric is None:
                            if syll_idx < len(syllables):
                                _attach_syllable_to_note(note, syllables[syll_idx], verse_number=1)
                                syll_idx += 1
                        else:
                            # Sanitize existing lyric text if it contains multiple words jammed into a single note
                            text_elem = existing_lyric.find("text")
                            if text_elem is not None and text_elem.text and " " in text_elem.text.strip():
                                tokens = text_elem.text.strip().split()
                                if tokens:
                                    text_elem.text = clean_word_text(tokens[0])

        # 3. Autotag voices, abbreviations, and piano instruments
        autotag_musicxml_tree(root)

        tree.write(musicxml_path, encoding="utf-8", xml_declaration=True)
        logger.info("Enriched %s with lyrics and autotagged voices", musicxml_path.name)
    except Exception as exc:
        logger.error("Failed to enrich MusicXML with lyrics: %s", exc)

    return musicxml_path
