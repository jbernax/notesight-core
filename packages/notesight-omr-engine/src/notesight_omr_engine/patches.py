"""
Runtime safety patches for homr.staff_parsing.

Prevents OpenCV cv2.resize zero-dimension assertions and inverted/negative
staff bounding-box regions when processing degraded or tightly spaced scans.

Licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later).
"""

from __future__ import annotations

from typing import Any
import cv2
import numpy as np


def safe_calculate_region(staff: Any, regions: Any) -> np.ndarray:
    """Calculate staff bounding region with guaranteed positive width and height."""
    x_min = staff.min_x - 2 * staff.average_unit_size
    x_max = staff.max_x + 2 * staff.average_unit_size
    y_min = max(
        staff.min_y - 4 * staff.average_unit_size,
        regions.get_start_of_closest_staff_above(staff.min_y),
    )
    y_max = min(
        staff.max_y + 4 * staff.average_unit_size,
        regions.get_start_of_closest_staff_below(staff.max_y),
    )
    if y_max <= y_min:
        y_min = staff.min_y - 4 * staff.average_unit_size
        y_max = max(y_min + 1, staff.max_y + 4 * staff.average_unit_size)
    if x_max <= x_min:
        x_min = staff.min_x
        x_max = max(x_min + 1, staff.max_x + 2 * staff.average_unit_size)
    return np.array([int(x_min), int(y_min), max(int(x_min) + 1, int(x_max)), max(int(y_min) + 1, int(y_max))])


def safe_get_tr_omr_canvas_size(
    image_shape: tuple[int, ...],
    margin_top: int = 0,
    margin_bottom: int = 0,
    max_height: int = 192,
    max_width: int = 1280,
) -> np.ndarray:
    """Compute TrOMR target canvas dimensions while clamping zero/negative inputs to >= 1 px."""
    try:
        from homr.transformer.configs import default_config
        max_height = int(default_config.max_height)
        max_width = int(default_config.max_width)
    except Exception:
        pass

    tr_omr_max_height_with_margin = max(1, max_height - margin_top - margin_bottom)
    tr_omr_ratio = float(tr_omr_max_height_with_margin) / float(max(1, max_width))

    height, width = image_shape[:2]
    safe_height = max(1, int(height))
    safe_width = max(1, int(width))

    if safe_height / safe_width > tr_omr_ratio:
        new_shape = [
            max(1, int(safe_width / safe_height * tr_omr_max_height_with_margin)),
            tr_omr_max_height_with_margin,
        ]
    else:
        new_shape = [
            max_width,
            max(1, int(safe_height / safe_width * max_width)),
        ]
    return np.array(new_shape)


def safe_center_image_on_canvas(
    image: np.ndarray,
    canvas_size: np.ndarray,
    margin_top: int = 0,
    margin_bottom: int = 0,
) -> np.ndarray:
    """Center a cropped staff image on a fixed TrOMR canvas without failing on empty slices."""
    import homr.staff_parsing as sp

    tr_omr_max_height = int(sp.tr_omr_max_height)
    tr_omr_max_width = int(sp.tr_omr_max_width)
    is_grayscale = image.ndim == 2 or (image.ndim == 3 and image.shape[2] == 1)

    if is_grayscale:
        new_image = np.full((tr_omr_max_height, tr_omr_max_width), 255, dtype=np.uint8)
    else:
        new_image = np.full((tr_omr_max_height, tr_omr_max_width, 3), 255, dtype=np.uint8)

    if image.shape[0] <= 0 or image.shape[1] <= 0:
        return new_image

    safe_target = (
        min(tr_omr_max_width, max(1, int(canvas_size[0]))),
        min(tr_omr_max_height, max(1, int(canvas_size[1]))),
    )
    resized = cv2.resize(image, safe_target)

    x_offset = 0
    tr_omr_max_height_with_margin = tr_omr_max_height - margin_top - margin_bottom
    y_offset = max(0, (tr_omr_max_height_with_margin - resized.shape[0]) // 2 + margin_top)

    end_y = min(tr_omr_max_height, y_offset + resized.shape[0])
    end_x = min(tr_omr_max_width, x_offset + resized.shape[1])
    new_image[y_offset:end_y, x_offset:end_x] = resized[: end_y - y_offset, : end_x - x_offset]
    return new_image


def smart_select_grandstaffs(self: Any, brace_dot: list[Any]) -> list[Any]:
    """
    Select GrandStaff pairs with musical engraving awareness.
    1. Filter out tall choral/system brackets that span > 2 staves (e.g. a 4-staff SATB bracket
       below a solo staff in a 5-staff system), preventing false GrandStaff merges of [0, 1].
    2. In 3-staff systems (e.g. Solo/Descant + Choir accompaniment, or Voice + Piano),
       the uppermost staff (index 0) is the solo/descant vocal line and the lower two staves
       (indices 1 & 2) form the accompaniment / choral grandstaff.
    """
    try:
        from homr.model import MultiStaff

        if len(self.staffs) == 3:
            # Check if there is any brace/bracket touching the accompaniment pair [1, 2]
            best_sc_12 = max(
                (self._score_brace_with_staff_pair(sym, self.staffs[1], self.staffs[2]) for sym in brace_dot),
                default=0.0,
            )
            if best_sc_12 > 0:
                return [MultiStaff.GrandStaffPair([1, 2], best_sc_12)]
    except Exception:
        pass

    pair_scores = []
    num_staffs = len(self.staffs)
    for i in range(num_staffs - 1):
        # In >= 4-staff systems (e.g., SATB, SSATB, Solo + SATB, SA + Piano),
        # upper/middle pairs (i < num_staffs - 2) are vocal staves (which may have
        # divisi sub-brackets like [S1, S2]) and must never be merged into a 2-staff GrandStaff.
        if num_staffs >= 4 and i < num_staffs - 2:
            continue

        upper = self.staffs[i]
        lower = self.staffs[i + 1]
        pair_span = max(1.0, float(lower.max_y - upper.min_y))
        pair_mid_y = float(upper.min_y + lower.max_y) / 2.0

        valid_scores: list[float] = []
        for symbol in brace_dot:
            sym_h = float(symbol.size[1])
            sym_cy = float(symbol.center[1])
            # A true 2-staff GrandStaff brace fits the 2-staff span and is centered on the pair.
            # A choral/system bracket spanning >= 3 staves is much taller or centered elsewhere.
            if num_staffs >= 4:
                if sym_h > pair_span * 1.35:
                    continue
                if abs(sym_cy - pair_mid_y) > pair_span * 0.28:
                    continue
            sc = self._score_brace_with_staff_pair(symbol, upper, lower)
            if sc > 0:
                valid_scores.append(sc)

        best_score = max(valid_scores, default=0.0)
        if best_score > 0:
            pair_scores.append(self.GrandStaffPair([i, i + 1], best_score))

    result = []
    used_staff_index: set[int] = set()
    for pair in sorted(pair_scores, key=lambda p: p.get_score(), reverse=True):
        if any(index in used_staff_index for index in pair.get_index()):
            continue
        result.append(pair)
        used_staff_index.update(pair.get_index())
    return result


def safe_build_repeat(barline_symbol: Any, xml: Any) -> None:
    """
    Build a MusicXML <repeat> element with valid barline location and <bar-style>.

    Fixes upstream homr bug where repeatStart is attached to a right-hand barline
    without <bar-style>, which breaks forward repeats in MusicXML 4.0 and OSMD.
    """
    import musicxml.xmlelement.xmlelement as mxl

    if len(xml.get_children_of_type(mxl.XMLRepeat)) > 0:
        return

    rhythm = getattr(barline_symbol, "rhythm", "")
    is_forward = rhythm == "repeatStart"
    if is_forward:
        xml.location = "left"
        style_value = "heavy-light"
        direction = "forward"
    else:
        xml.location = "right"
        style_value = "light-heavy"
        direction = "backward"

    if len(xml.get_children_of_type(mxl.XMLBarStyle)) == 0:
        xml.add_child(mxl.XMLBarStyle(value_=style_value))

    repeat = mxl.XMLRepeat()
    repeat._set_attributes({"direction": direction})
    xml.add_child(repeat)


def sanitize_courtesy_signature_tokens(voices: list[list[Any]]) -> int:
    """
    Remove spurious notes/rests/barlines hallucinated between a courtesy key/time signature
    at the end of a staff (following a section-ending barline) and the terminating 'newline'.

    In sheet music engraving, courtesy key or time signatures placed at the very end of a
    system indicate the meter/key of the NEXT system; no musical notes ever follow a courtesy
    signature on that staff. TrOMR can mistake the courtesy signature accidentals or trailing
    whitespace for notes, generating orphan measures that cause cross-voice delays.
    """
    removed_total = 0
    for voice in voices:
        idx = 0
        while idx < len(voice):
            try:
                nl_idx = next(i for i in range(idx, len(voice)) if getattr(voice[i], "rhythm", "") == "newline")
            except StopIteration:
                nl_idx = len(voice)

            sig_idx = None
            bar_idx = None
            for j in range(nl_idx - 1, max(idx - 1, nl_idx - 8), -1):
                rhythm = getattr(voice[j], "rhythm", "")
                if rhythm.startswith("keySignature_") or rhythm.startswith("timeSignature_"):
                    sig_idx = j
                    for k in range(sig_idx - 1, max(idx - 1, sig_idx - 4), -1):
                        r_k = getattr(voice[k], "rhythm", "")
                        if "barline" in r_k or "repeat" in r_k:
                            bar_idx = k
                            break
                    break

            if sig_idx is not None and bar_idx is not None and bar_idx < sig_idx:
                spurious_count = nl_idx - (sig_idx + 1)
                if spurious_count > 0:
                    del voice[sig_idx + 1 : nl_idx]
                    removed_total += spurious_count
                    nl_idx = sig_idx + 1

            idx = nl_idx + 1

    return removed_total


def apply_homr_safety_patches() -> bool:
    """Bind runtime safety functions onto homr modules in memory."""
    try:
        import homr.model as hm
        import homr.music_xml_generator as mxg
        import homr.staff_parsing as sp

        sp._calculate_region = safe_calculate_region  # type: ignore[attr-defined]
        sp.get_tr_omr_canvas_size = safe_get_tr_omr_canvas_size  # type: ignore[assignment]
        sp.center_image_on_canvas = safe_center_image_on_canvas  # type: ignore[assignment]
        hm.MultiStaff._select_grandstaffs = smart_select_grandstaffs  # type: ignore[assignment]
        mxg.build_repeat = safe_build_repeat  # type: ignore[assignment]
        return True
    except Exception:
        return False

