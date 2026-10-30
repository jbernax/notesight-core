"""
Volta Bracket (1. / 2. Ending) Detection and MusicXML Enrichment Service.

Detects prima and seconda volta brackets above each system's top staff by combining:
  1. OpenCV morphological detection of horizontal bracket roofs with downward vertical hooks.
  2. PDF text-layer / OCR word extraction of '1.' and '2.' labels.
  3. Repeat-barline (`repeatEnd`) anchoring and system barline x-coordinate mapping.

Supports both single-measure voltas within a system (e.g. Measures 8-9 on Page 1 of
'Las Campanas de la Mezquita') and multi-measure voltas spanning a system break
(e.g. Measures 33-35 on Page 3).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import xml.etree.ElementTree as ET

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET

import cv2
import numpy as np

from app.services.musicxml_sanitizer import _order_barline_children
from app.services.page_text import PageWord, extract_page_words
from app.services.score_consistency import (
    _get_or_create_measure_barline,
    align_barlines_and_repeats,
)
from app.services.score_layout import PageLayout, SystemLayout

logger = logging.getLogger(__name__)

_VOLTA_1_RE = re.compile(r"^1[\.,:;]?$")
_VOLTA_2_RE = re.compile(r"^2[\.,:;]?$")


@dataclass(frozen=True)
class VoltaBracketCandidate:
    """Visual and/or textual evidence for a volta bracket in a system."""

    system_index: int
    x0: float
    x1: float
    y: float
    number: int | None = None
    has_left_hook: bool = False
    has_right_hook: bool = False


def _group_measures_by_system(
    part_measures: list[ET.Element], num_systems: int
) -> list[list[int]]:
    """
    Partition measure indices (0..N-1) into systems using <print new-system="yes"/> markers.
    Falls back to even partitioning if system break markers are absent or inconsistent.
    """
    total_measures = len(part_measures)
    if total_measures == 0 or num_systems <= 0:
        return []

    groups: list[list[int]] = [[]]
    for m_idx, m in enumerate(part_measures):
        if m_idx > 0:
            has_new_sys = any(
                pr.get("new-system") == "yes" or pr.get("new-page") == "yes"
                for pr in m.findall("print")
            )
            if has_new_sys:
                groups.append([])
        groups[-1].append(m_idx)

    groups = [g for g in groups if g]
    if len(groups) == num_systems:
        return groups

    # Fallback: proportional partitioning across num_systems
    fallback: list[list[int]] = []
    for sys_i in range(num_systems):
        start_i = int(round(sys_i * total_measures / num_systems))
        end_i = int(round((sys_i + 1) * total_measures / num_systems))
        if end_i > start_i:
            fallback.append(list(range(start_i, end_i)))
    return fallback


def _estimate_system_measure_spans(
    system: SystemLayout, num_measures: int
) -> list[tuple[float, float]]:
    """
    Estimate the horizontal [x_left, x_right] pixel span of each measure in `system`.
    Uses `system.barline_xs` when interior barlines match, falling back to uniform
    division after the clef/key-signature header.
    """
    if num_measures <= 0:
        return []

    sys_min_x = system.min_x
    sys_max_x = system.max_x
    sp = max(6.0, system.staves[0].line_spacing if system.staves else 12.0)

    if num_measures == 1:
        return [(sys_min_x, sys_max_x)]

    header_end_x = min(sys_max_x - 20.0, sys_min_x + 7.5 * sp)
    interior_bars = [
        bx
        for bx in system.barline_xs
        if (header_end_x + 2.0 * sp) <= bx <= (sys_max_x - 2.5 * sp)
    ]

    if len(interior_bars) == num_measures - 1:
        boundaries = [sys_min_x, *interior_bars, sys_max_x]
        return [(boundaries[i], boundaries[i + 1]) for i in range(num_measures)]

    # Uniform measure width after the clef/key header
    usable_w = max(1.0, sys_max_x - header_end_x)
    step = usable_w / float(num_measures)
    spans: list[tuple[float, float]] = []
    for i in range(num_measures):
        left_x = sys_min_x if i == 0 else header_end_x + i * step
        right_x = sys_max_x if i == num_measures - 1 else header_end_x + (i + 1) * step
        spans.append((left_x, right_x))
    return spans


def _map_x_to_system_measure(
    x: float,
    measure_indices: list[int],
    measure_spans: list[tuple[float, float]],
) -> int:
    """Map a page x-coordinate to the corresponding measure index within a system."""
    if not measure_indices:
        return 0
    if len(measure_indices) != len(measure_spans):
        return measure_indices[0]

    for m_idx, (x0, x1) in zip(measure_indices, measure_spans):
        if x0 <= x <= x1:
            return m_idx

    # Closest measure span center if outside bounds
    best_idx = min(
        range(len(measure_indices)),
        key=lambda i: abs(x - 0.5 * (measure_spans[i][0] + measure_spans[i][1])),
    )
    return measure_indices[best_idx]


def _detect_visual_brackets_in_system(
    gray: np.ndarray, system: SystemLayout, system_index: int
) -> list[VoltaBracketCandidate]:
    """
    Detect horizontal volta bracket lines with downward vertical hooks in the strip
    immediately above a system's top staff.
    """
    if not system.staves:
        return []

    top_staff = system.staves[0]
    sp = max(6.0, top_staff.line_spacing)
    img_h, img_w = gray.shape[:2]

    y_top = max(0, int(round(top_staff.min_y - 5.0 * sp)))
    y_bot = max(y_top + 1, min(img_h, int(round(top_staff.min_y - 0.3 * sp))))
    x_left = max(0, int(round(system.min_x)))
    x_right = max(x_left + 1, min(img_w, int(round(system.max_x + sp))))

    strip = gray[y_top:y_bot, x_left:x_right]
    if strip.size == 0:
        return []

    bw = (strip < 185).astype(np.uint8) * 255
    horiz_len = max(25, int(round(3.0 * sp)))
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horiz_len, 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, horiz_kernel)

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(horiz, connectivity=8)
    raw_segs: list[tuple[int, int, int, int]] = []
    min_seg_w = max(35, int(round(4.0 * sp)))
    max_seg_h = max(8, int(round(0.7 * sp)))

    for label_idx in range(1, num_labels):
        sx = int(stats[label_idx, cv2.CC_STAT_LEFT])
        sy = int(stats[label_idx, cv2.CC_STAT_TOP])
        sw = int(stats[label_idx, cv2.CC_STAT_WIDTH])
        sh = int(stats[label_idx, cv2.CC_STAT_HEIGHT])
        if sw >= min_seg_w and sh <= max_seg_h:
            raw_segs.append((sx, sy, sx + sw, sy + sh))

    if not raw_segs:
        return []

    # Sort by x0 and merge collinear horizontal segments separated by tiny gaps
    raw_segs.sort(key=lambda r: (r[0], r[1]))
    merged: list[list[int]] = []
    for sx0, sy0, sx1, sy1 in raw_segs:
        if (
            merged
            and abs(sy0 - merged[-1][1]) <= 4
            and (sx0 - merged[-1][2]) <= int(round(1.2 * sp))
        ):
            merged[-1][2] = max(merged[-1][2], sx1)
            merged[-1][1] = min(merged[-1][1], sy0)
            merged[-1][3] = max(merged[-1][3], sy1)
        else:
            merged.append([sx0, sy0, sx1, sy1])

    candidates: list[VoltaBracketCandidate] = []
    hook_check_h = max(12, int(round(1.8 * sp)))
    min_hook_rows = max(8, int(round(1.0 * sp)))

    for sx0, sy0, sx1, sy1 in merged:
        page_x0 = float(x_left + sx0)
        page_x1 = float(x_left + sx1)
        page_y = float(y_top + sy0)

        # Check downward vertical hook at left and right ends in full grayscale image
        iy0 = int(round(page_y))
        iy1 = min(img_h, iy0 + hook_check_h)
        lx0 = max(0, int(round(page_x0)) - 4)
        lx1 = min(img_w, int(round(page_x0)) + 6)
        rx0 = max(0, int(round(page_x1)) - 6)
        rx1 = min(img_w, int(round(page_x1)) + 4)

        left_patch = gray[iy0:iy1, lx0:lx1] < 185
        right_patch = gray[iy0:iy1, rx0:rx1] < 185

        left_hook_rows = int(np.sum(np.any(left_patch, axis=1))) if left_patch.size > 0 else 0
        right_hook_rows = int(np.sum(np.any(right_patch, axis=1))) if right_patch.size > 0 else 0

        has_left_hook = left_hook_rows >= min_hook_rows
        has_right_hook = right_hook_rows >= min_hook_rows

        if has_left_hook:
            candidates.append(
                VoltaBracketCandidate(
                    system_index=system_index,
                    x0=page_x0,
                    x1=page_x1,
                    y=page_y,
                    number=None,
                    has_left_hook=has_left_hook,
                    has_right_hook=has_right_hook,
                )
            )

    return candidates


def _extract_system_volta_candidates(
    image_path: Path | None,
    layout: PageLayout,
    pdf_path: Path | None = None,
    page_index: int | None = None,
) -> list[VoltaBracketCandidate]:
    """
    Combine visual OpenCV bracket candidates and OCR/PDF text labels ('1.', '2.')
    across all systems on the page.
    """
    if layout.is_empty:
        return []

    gray: np.ndarray | None = None
    if image_path is not None and image_path.exists():
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)

    words: list[PageWord] = []
    if image_path is not None and image_path.exists():
        try:
            words = extract_page_words(
                image_path, pdf_path=pdf_path, page_index=page_index if page_index is not None else 0
            )
        except Exception as exc:
            logger.debug("Could not extract page words for volta detection: %s", exc)

    all_candidates: list[VoltaBracketCandidate] = []

    for sys_idx, system in enumerate(layout.systems):
        if not system.staves:
            continue
        top_staff = system.staves[0]
        sp = max(6.0, top_staff.line_spacing)
        y_top = top_staff.min_y - 5.2 * sp
        y_bot = top_staff.min_y + 0.8 * sp

        visual_brackets = (
            _detect_visual_brackets_in_system(gray, system, sys_idx)
            if gray is not None
            else []
        )

        # Find '1.' and '2.' text labels above top staff
        text_labels: list[tuple[int, PageWord]] = []
        for w in words:
            if not (y_top <= w.mid_y <= y_bot and system.min_x <= w.mid_x <= system.max_x):
                continue
            txt = w.text.strip()
            has_dot = txt.endswith((".", ",", ":"))
            # Guard against bare measure number at far-left of system unless it has a period '1.'/'2.'
            if not has_dot and w.x0 < system.min_x + 3.5 * sp:
                continue
            if _VOLTA_1_RE.match(txt):
                text_labels.append((1, w))
            elif _VOLTA_2_RE.match(txt):
                text_labels.append((2, w))

        used_labels: set[int] = set()
        for vb in visual_brackets:
            matched_num: int | None = None
            for l_idx, (num, w) in enumerate(text_labels):
                if (vb.x0 - 1.5 * sp) <= w.mid_x <= (vb.x1 + 1.0 * sp):
                    matched_num = num
                    used_labels.add(l_idx)
                    break
            all_candidates.append(
                VoltaBracketCandidate(
                    system_index=sys_idx,
                    x0=vb.x0,
                    x1=vb.x1,
                    y=vb.y,
                    number=matched_num,
                    has_left_hook=vb.has_left_hook,
                    has_right_hook=vb.has_right_hook,
                )
            )

        # Any text label ('1.' or '2.') with explicit punctuation that didn't match a visual bracket
        for l_idx, (num, w) in enumerate(text_labels):
            if l_idx in used_labels:
                continue
            if w.text.strip().endswith((".", ",")):
                all_candidates.append(
                    VoltaBracketCandidate(
                        system_index=sys_idx,
                        x0=w.x0,
                        x1=w.x1 + 6.0 * sp,
                        y=w.y0,
                        number=num,
                        has_left_hook=True,
                        has_right_hook=(num == 1),
                    )
                )

    return all_candidates


def _add_ending_to_measure(
    part_measures: list[list[ET.Element]],
    measure_idx: int,
    location: str,
    number: int,
    ending_type: str,
) -> int:
    """Add <ending number=... type=...> to `location` barline across all parts on `measure_idx`."""
    added = 0
    num_str = str(number)
    for ms in part_measures:
        if measure_idx < 0 or measure_idx >= len(ms):
            continue
        m = ms[measure_idx]
        bl = _get_or_create_measure_barline(m, location)
        existing = [
            e
            for e in bl.findall("ending")
            if (e.get("number") or "").strip() == num_str
            and (e.get("type") or "").strip() == ending_type
        ]
        if not existing:
            ending_el = ET.SubElement(bl, "ending", number=num_str, type=ending_type)
            if ending_type == "start":
                ending_el.text = f"{num_str}."
            _order_barline_children(bl)
            added += 1
    return added


def detect_and_apply_voltas(
    root: ET.Element,
    image_path: Path | None,
    layout: PageLayout | None,
    pdf_path: Path | None = None,
    page_index: int | None = None,
) -> int:
    """
    Detect prima (`1.`) and seconda (`2.`) volta brackets on a page and inject
    MusicXML `<ending>` elements into `root` across all parts.

    Returns:
        Number of `<ending>` / `<repeat>` elements added across all parts.
    """
    if layout is None or layout.is_empty:
        return 0

    parts = root.findall(".//part")
    if not parts:
        return 0

    # Ensure existing repeat barlines are normalized and aligned across parts first
    align_barlines_and_repeats(root)

    part_measures = [p.findall("measure") for p in parts]
    min_measures = min(len(ms) for ms in part_measures)
    if min_measures == 0:
        return 0

    sys_measure_groups = _group_measures_by_system(part_measures[0][:min_measures], len(layout.systems))
    if len(sys_measure_groups) != len(layout.systems):
        return 0

    sys_spans = [
        _estimate_system_measure_spans(layout.systems[i], len(sys_measure_groups[i]))
        for i in range(len(layout.systems))
    ]

    candidates = _extract_system_volta_candidates(
        image_path=image_path,
        layout=layout,
        pdf_path=pdf_path,
        page_index=page_index,
    )
    if not candidates:
        return 0

    # Map each candidate's x0 and x1 to measure indices
    mapped: list[tuple[VoltaBracketCandidate, int, int]] = []
    for cand in candidates:
        m_indices = sys_measure_groups[cand.system_index]
        m_spans = sys_spans[cand.system_index]
        if not m_indices:
            continue
        start_m = _map_x_to_system_measure(
            cand.x0 + 12.0, m_indices, m_spans
        )
        end_m = _map_x_to_system_measure(
            max(cand.x0 + 12.0, cand.x1 - 18.0), m_indices, m_spans
        )
        if end_m < start_m:
            end_m = start_m
        mapped.append((cand, start_m, end_m))

    # Locate backward repeats (repeatEnd) across the page
    repeat_end_measures: set[int] = set()
    for m_idx in range(min_measures):
        if any(
            ms[m_idx].find("barline[@location='right']/repeat[@direction='backward']") is not None
            for ms in part_measures
        ):
            repeat_end_measures.add(m_idx)

    # Also infer repeatEnd ONLY if an explicit candidate with number=1 is immediately followed by a candidate with number=2
    for i, (cand_a, start_a, end_a) in enumerate(mapped):
        for cand_b, start_b, _ in mapped[i + 1 :]:
            if (
                cand_a.number == 1
                and cand_b.number == 2
                and start_a <= start_b - 1 <= end_a + 1
            ):
                inferred_rep = start_b - 1
                if 0 <= inferred_rep < min_measures:
                    repeat_end_measures.add(inferred_rep)

    changes = 0

    for rep_m in sorted(repeat_end_measures):
        # Find Prima Volta (1.) candidate that ends at or covers rep_m (including multi-measure across system break)
        prima_cand: tuple[VoltaBracketCandidate, int, int] | None = None
        for cand, start_m, end_m in mapped:
            if cand.number != 1:
                continue
            if start_m <= rep_m and (
                start_m <= rep_m <= end_m + 1
                or (rep_m - start_m) <= 4
            ):
                prima_cand = (cand, start_m, rep_m)
                break

        # Find Seconda Volta (2.) candidate starting at rep_m + 1
        seconda_cand: tuple[VoltaBracketCandidate, int, int] | None = None
        if rep_m + 1 < min_measures:
            for cand, start_m, end_m in mapped:
                if cand.number != 2:
                    continue
                if start_m == rep_m + 1 or abs(start_m - (rep_m + 1)) <= 1:
                    span_len = max(0, end_m - start_m)
                    seconda_cand = (cand, rep_m + 1, min(min_measures - 1, rep_m + 1 + span_len))
                    break

        # If neither cand has an explicit number (1 or 2), do not infer or apply voltas on unlabeled noise
        if prima_cand is None and seconda_cand is None:
            continue

        # If one is confirmed with an explicit number (1 or 2), allow matching an adjacent unlabeled candidate
        if prima_cand is None and seconda_cand is not None:
            for cand, start_m, end_m in mapped:
                if cand is not seconda_cand[0] and (start_m <= rep_m <= end_m + 1 or rep_m == start_m):
                    prima_cand = (cand, start_m, rep_m)
                    break
        elif prima_cand is not None and seconda_cand is None and rep_m + 1 < min_measures:
            for cand, start_m, end_m in mapped:
                if cand is not prima_cand[0] and (start_m == rep_m + 1 or abs(start_m - (rep_m + 1)) <= 1):
                    span_len = max(0, end_m - start_m)
                    seconda_cand = (cand, rep_m + 1, min(min_measures - 1, rep_m + 1 + span_len))
                    break

        # Ensure backward repeat is present across all parts on rep_m
        for ms in part_measures:
            bl = _get_or_create_measure_barline(ms[rep_m], "right")
            if bl.find("bar-style") is None:
                bs = ET.Element("bar-style")
                bs.text = "light-heavy"
                bl.insert(0, bs)
            if bl.find("repeat[@direction='backward']") is None:
                ET.SubElement(bl, "repeat", direction="backward")
                _order_barline_children(bl)
                changes += 1

        # Apply Prima Volta (1.)
        p_start = prima_cand[1] if prima_cand is not None else rep_m
        p_stop = rep_m
        changes += _add_ending_to_measure(part_measures, p_start, "left", 1, "start")
        changes += _add_ending_to_measure(part_measures, p_stop, "right", 1, "stop")

        # Apply Seconda Volta (2.) if rep_m + 1 exists on this page
        if seconda_cand is not None:
            s_start = seconda_cand[1]
            s_stop = seconda_cand[2]
            end_type = "stop" if seconda_cand[0].has_right_hook and not seconda_cand[0].has_left_hook else "discontinue"
            changes += _add_ending_to_measure(part_measures, s_start, "left", 2, "start")
            changes += _add_ending_to_measure(part_measures, s_stop, "right", 2, end_type)
        elif prima_cand is not None and (rep_m + 1) < min_measures:
            # If prima volta is confirmed on rep_m and rep_m + 1 is on the same page, check if any unclaimed bracket is on rep_m + 1
            for cand, start_m, end_m in mapped:
                if cand is not prima_cand[0] and start_m == rep_m + 1:
                    changes += _add_ending_to_measure(part_measures, rep_m + 1, "left", 2, "start")
                    changes += _add_ending_to_measure(part_measures, max(rep_m + 1, end_m), "right", 2, "discontinue")
                    break

    return changes


def enrich_musicxml_with_voltas(
    xml_path: Path,
    image_path: Path | None,
    layout: PageLayout | None,
    pdf_path: Path | None = None,
    page_index: int | None = None,
) -> int:
    """Load `xml_path`, detect and inject volta endings, and write back if modified."""
    if not xml_path.exists():
        return 0
    try:
        tree = dET.parse(xml_path)
        root = tree.getroot()
        changes = detect_and_apply_voltas(
            root=root,
            image_path=image_path,
            layout=layout,
            pdf_path=pdf_path,
            page_index=page_index,
        )
        if changes > 0:
            tree.write(xml_path, encoding="utf-8", xml_declaration=True)
            logger.info("Applied %d volta/repeat barline updates to %s", changes, xml_path.name)
        return changes
    except Exception as exc:
        logger.warning("Volta detection skipped for %s: %s", xml_path, exc)
        return 0
