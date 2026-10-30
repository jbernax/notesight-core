"""
Score Consistency and Musical Plausibility Post-Processing Service.

Applies domain-specific post-processing to OMR output trees:
1. Tenor clef & octave alignment: fixes homr transcribing tenor G8 clef as G2,
   shifting tenor octaves to true sounding pitch and adding <clef-octave-change>-1.
2. Key and time signature consensus voting: resolves isolated misread signatures
   across parallel parts in multi-voice choral and orchestral systems.
3. Rhythm repair: ensures arithmetic consistency with time signatures.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import logging
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET

import numpy as np

from app.services.voice_autotagger import resolve_voice_tag

logger = logging.getLogger(__name__)

# Standard quarter-note duration to (MusicXML note <type>, dot_count) mapping
_QUARTER_FRACTION_TO_TYPE: dict[Fraction, tuple[str, int]] = {
    Fraction(1, 16): ("64th", 0),
    Fraction(3, 32): ("64th", 1),
    Fraction(1, 8): ("32nd", 0),
    Fraction(3, 16): ("32nd", 1),
    Fraction(1, 4): ("16th", 0),
    Fraction(3, 8): ("16th", 1),
    Fraction(1, 2): ("eighth", 0),
    Fraction(3, 4): ("eighth", 1),
    Fraction(7, 8): ("eighth", 2),
    Fraction(1, 1): ("quarter", 0),
    Fraction(3, 2): ("quarter", 1),
    Fraction(7, 4): ("quarter", 2),
    Fraction(2, 1): ("half", 0),
    Fraction(3, 1): ("half", 1),
    Fraction(7, 2): ("half", 2),
    Fraction(4, 1): ("whole", 0),
    Fraction(6, 1): ("whole", 1),
}


def remove_empty_ghost_measures(root: ET.Element) -> int:
    """
    Remove spurious noteless <measure> elements (e.g. produced by homr when double
    barlines or courtesy time signatures appear at system boundaries) and renumber
    remaining measures sequentially 1..N per part.

    Any <print>, <attributes>, or <direction> children inside a removed ghost measure
    are carried forward into the following measure so system breaks and clefs are preserved.

    Returns:
        Number of ghost measures removed across all parts.
    """
    removed_count = 0
    parts = root.findall(".//part")

    for part in parts:
        measures = part.findall("measure")
        if len(measures) <= 1:
            continue

        idx = 0
        while idx < len(measures):
            m = measures[idx]
            has_notes = m.find("note") is not None or m.find("forward") is not None
            if not has_notes and len(measures) > 1:
                if idx + 1 < len(measures):
                    next_m = measures[idx + 1]
                    carry_elems = [
                        child
                        for child in list(m)
                        if child.tag in ("print", "attributes", "direction")
                    ]
                    for insert_pos, child in enumerate(carry_elems):
                        if child.tag == "print" and next_m.find("print") is not None:
                            continue
                        next_m.insert(insert_pos, deepcopy(child))
                part.remove(m)
                measures.pop(idx)
                removed_count += 1
            else:
                idx += 1

        for new_num, m in enumerate(part.findall("measure"), start=1):
            m.set("number", str(new_num))

    return removed_count


def align_system_break_measures(root: ET.Element) -> int:
    """
    Synchronize system-break measure boundaries across parallel parts in multi-part scores.

    In choral and orchestral scores, section-ending double barlines (light-light, light-heavy)
    or repeats are often followed by courtesy key/time signatures at the end of the system.
    TrOMR frequently misinterprets courtesy accidentals as notes, creating an orphan measure
    in some parts between the double barline and the newline (<print new-system="yes"/>).
    This causes parallel voices to slip out of sync by 1 or more measures.

    This function identifies measure indices where parallel parts disagree on a system break
    and prunes the spurious orphan boundary measures, carrying forward any courtesy attributes
    (such as key signatures) into the new system.

    Returns:
        Number of orphan boundary measures removed across all parts.
    """
    parts = root.findall(".//part")
    if not parts or len(parts) < 2:
        return 0

    removed_total = 0
    part_measures = [p.findall("measure") for p in parts]
    max_m = max(len(ms) for ms in part_measures)
    m_idx = 0
    last_agreed_break = 0

    while m_idx < max_m:
        part_measures = [p.findall("measure") for p in parts]
        min_m = min(len(ms) for ms in part_measures)
        if m_idx >= min_m:
            break

        curr_measures = [ms[m_idx] for ms in part_measures]
        has_sys_break = [
            m.find("print[@new-system='yes']") is not None or m.find("print[@new-page='yes']") is not None
            for m in curr_measures
        ]

        if all(has_sys_break):
            last_agreed_break = m_idx
            m_idx += 1
            continue

        if any(has_sys_break) and not all(has_sys_break):
            # Case 1: Orphan boundary measure right at m_idx (e.g. courtesy ghost measure after double barline)
            orphan_parts = []
            for p_idx, m in enumerate(curr_measures):
                if not has_sys_break[p_idx]:
                    # Check if previous measure ended with a section boundary
                    prev_m = part_measures[p_idx][m_idx - 1] if m_idx > 0 else None
                    has_prev_section_bar = False
                    if prev_m is not None:
                        bl = prev_m.find("barline[@location='right']")
                        if bl is not None:
                            bs = bl.findtext("bar-style")
                            rep = bl.find("repeat")
                            if bs in ("light-light", "light-heavy") or (rep is not None and rep.get("direction") == "backward"):
                                has_prev_section_bar = True

                    # Check if next measure has the system break for this part
                    next_m = part_measures[p_idx][m_idx + 1] if m_idx + 1 < len(part_measures[p_idx]) else None
                    has_next_sys = False
                    if next_m is not None:
                        pr = next_m.find("print")
                        if pr is not None and (pr.get("new-system") == "yes" or pr.get("new-page") == "yes"):
                            has_next_sys = True

                    # Check content of m: orphan measures have at most 1 note/rest and no lyrics
                    notes = m.findall("note")
                    has_lyrics = any(n.find("lyric") is not None for n in notes)
                    is_short_or_stray = len(notes) <= 1 and not has_lyrics

                    if has_prev_section_bar and has_next_sys and is_short_or_stray:
                        orphan_parts.append(p_idx)

            if orphan_parts:
                for p_idx in orphan_parts:
                    p_elem = parts[p_idx]
                    m_to_remove = part_measures[p_idx][m_idx]
                    next_m = part_measures[p_idx][m_idx + 1]

                    carry_elems = [
                        ch for ch in list(m_to_remove)
                        if ch.tag in ("attributes", "direction")
                    ]
                    for c_idx, ch in enumerate(carry_elems):
                        next_m.insert(c_idx, deepcopy(ch))

                    p_elem.remove(m_to_remove)
                    removed_total += 1

                for p in parts:
                    for new_num, m_el in enumerate(p.findall("measure"), start=1):
                        m_el.set("number", str(new_num))

                part_measures = [p.findall("measure") for p in parts]
                max_m = max(len(ms) for ms in part_measures)
                continue

            # Case 2: Majority of parts have system break at m_idx, minority lagging part has break at m_idx + 1
            num_with_break = sum(has_sys_break)
            if num_with_break >= len(parts) / 2:
                fixed_any = False
                for p_idx, has_b in enumerate(has_sys_break):
                    if not has_b:
                        next_has = (
                            m_idx + 1 < len(part_measures[p_idx])
                            and (
                                part_measures[p_idx][m_idx + 1].find("print[@new-system='yes']") is not None
                                or part_measures[p_idx][m_idx + 1].find("print[@new-page='yes']") is not None
                            )
                        )
                        if next_has:
                            cand_idx = None
                            for check_i in range(m_idx, last_agreed_break, -1):
                                m_cand = part_measures[p_idx][check_i]
                                notes = m_cand.findall("note")
                                has_lyr = any(n.find("lyric") is not None for n in notes)
                                is_rest = not notes or (len(notes) == 1 and notes[0].find("rest") is not None)
                                if is_rest and not has_lyr:
                                    cand_idx = check_i
                                    break
                            if cand_idx is not None:
                                p_elem = parts[p_idx]
                                m_to_remove = part_measures[p_idx][cand_idx]
                                next_m = part_measures[p_idx][cand_idx + 1]
                                carry_elems = [
                                    ch for ch in list(m_to_remove)
                                    if ch.tag in ("attributes", "direction")
                                ]
                                for c_idx, ch in enumerate(carry_elems):
                                    next_m.insert(c_idx, deepcopy(ch))
                                p_elem.remove(m_to_remove)
                                removed_total += 1
                                fixed_any = True

                if fixed_any:
                    for p in parts:
                        for new_num, m_el in enumerate(p.findall("measure"), start=1):
                            m_el.set("number", str(new_num))
                    part_measures = [p.findall("measure") for p in parts]
                    max_m = max(len(ms) for ms in part_measures)
                    continue

        m_idx += 1

    return removed_total


def fix_tenor_octave_and_clef(root: ET.Element) -> int:
    """
    Ensure vocal Tenor parts using treble clef (G2) are marked with <clef-octave-change>-1
    and their notes are shifted to true sounding pitch (octave 3-4 instead of 4-5).

    Returns:
        Number of tenor parts adjusted.
    """
    adjusted_count = 0
    score_parts = root.findall(".//part-list/score-part")

    for sp in score_parts:
        pid = sp.get("id")
        pname = (sp.findtext("part-name") or "").strip()
        pabbr = (sp.findtext("part-abbreviation") or "").strip()

        info = resolve_voice_tag(pname) or resolve_voice_tag(pabbr)
        if not info or not info.tag.startswith("T"):
            continue

        part_elem = root.find(f".//part[@id='{pid}']")
        if part_elem is None:
            continue

        # Inspect clefs in this tenor part
        g_clefs = []
        for clef in part_elem.findall(".//attributes/clef"):
            sign = clef.findtext("sign")
            line = clef.findtext("line")
            oct_change = clef.findtext("clef-octave-change")
            if sign == "G" and (line == "2" or line is None) and oct_change is None:
                g_clefs.append(clef)

        if not g_clefs:
            continue

        # Check the note pitch octaves in this part
        note_octaves: list[int] = []
        for oct_el in part_elem.findall(".//note/pitch/octave"):
            if oct_el.text and oct_el.text.strip().isdigit():
                note_octaves.append(int(oct_el.text.strip()))

        if not note_octaves:
            continue

        # If median octave is >= 4, notes were transcribed an octave too high
        median_oct = float(np.median(note_octaves))
        if median_oct >= 4.0:
            # 1. Add <clef-octave-change>-1 to all un-transposed G clefs
            for clef in g_clefs:
                oct_el = ET.SubElement(clef, "clef-octave-change")
                oct_el.text = "-1"

            # 2. Shift all pitch octaves down by 1
            for oct_el in part_elem.findall(".//note/pitch/octave"):
                if oct_el.text and oct_el.text.strip().isdigit():
                    curr_val = int(oct_el.text.strip())
                    oct_el.text = str(max(1, curr_val - 1))

            adjusted_count += 1
            logger.info("Adjusted Tenor part %s (%s): added clef-octave-change=-1 and shifted octaves down", pid, pname)

    return adjusted_count


def align_key_and_time_signatures(root: ET.Element) -> int:
    """
    Perform cross-part consensus voting for key and time signatures.
    If parallel parts in the same measure disagree, majority vote prevails.
    Also propagates mid-score key signature modulations when >= 2 parts detect a key change.

    Returns:
        Number of attributes updated.
    """
    from app.services.musicxml_sanitizer import consolidate_measure_attributes

    consolidate_measure_attributes(root)
    parts = root.findall(".//part")
    if len(parts) <= 1:
        return 0

    # Group measures by measure number
    measures_by_number: dict[str, list[ET.Element]] = {}
    for part in parts:
        for m in part.findall("measure"):
            num = m.get("number", "1")
            measures_by_number.setdefault(num, []).append(m)

    updated_count = 0

    for m_num, m_list in measures_by_number.items():
        if len(m_list) <= 1:
            continue

        # 1. Key signature consensus
        fifths_votes: list[str] = []
        for m in m_list:
            f_el = m.find(".//attributes/key/fifths")
            if f_el is not None and f_el.text:
                fifths_votes.append(f_el.text.strip())

        if fifths_votes:
            counter = Counter(fifths_votes)
            majority_fifths, majority_count = counter.most_common(1)[0]
            if majority_count > len(fifths_votes) / 2 and majority_count >= 2:
                for m in m_list:
                    f_el = m.find(".//attributes/key/fifths")
                    if f_el is not None and f_el.text and f_el.text.strip() != majority_fifths:
                        f_el.text = majority_fifths
                        updated_count += 1
                    elif f_el is None:
                        attr = m.find("attributes")
                        if attr is None:
                            attr = ET.Element("attributes")
                            insert_idx = 0
                            for idx, ch in enumerate(list(m)):
                                if ch.tag == "print":
                                    insert_idx = idx + 1
                            m.insert(insert_idx, attr)
                        key_el = attr.find("key")
                        if key_el is None:
                            key_el = ET.SubElement(attr, "key")
                        f_sub = key_el.find("fifths")
                        if f_sub is None:
                            f_sub = ET.SubElement(key_el, "fifths")
                        f_sub.text = majority_fifths
                        updated_count += 1

        # 2. Time signature consensus
        time_votes: list[tuple[str, str]] = []
        for m in m_list:
            b_el = m.find(".//attributes/time/beats")
            bt_el = m.find(".//attributes/time/beat-type")
            if b_el is not None and bt_el is not None and b_el.text and bt_el.text:
                time_votes.append((b_el.text.strip(), bt_el.text.strip()))

        if time_votes:
            counter_time = Counter(time_votes)
            (maj_b, maj_bt), maj_t_count = counter_time.most_common(1)[0]
            if maj_t_count > len(time_votes) / 2 and maj_t_count >= 2:
                for m in m_list:
                    b_el = m.find(".//attributes/time/beats")
                    bt_el = m.find(".//attributes/time/beat-type")
                    if b_el is not None and bt_el is not None and b_el.text and bt_el.text:
                        curr_b = b_el.text.strip()
                        curr_bt = bt_el.text.strip()
                        if curr_b != maj_b or curr_bt != maj_bt:
                            b_el.text = maj_b
                            bt_el.text = maj_bt
                            updated_count += 1

    consolidate_measure_attributes(root)
    return updated_count


def _get_or_create_measure_barline(measure: ET.Element, location: str) -> ET.Element:
    """Return existing <barline location=.../> in measure or create and position a new one."""
    for bl in measure.findall("barline"):
        if (bl.get("location") or "right") == location:
            return bl

    bl = ET.Element("barline", location=location)
    if location == "left":
        children = list(measure)
        insert_idx = next(
            (i for i, ch in enumerate(children) if ch.tag in ("note", "backup", "forward")),
            len(children),
        )
        measure.insert(insert_idx, bl)
    else:
        measure.append(bl)
    return bl


def align_barlines_and_repeats(root: ET.Element) -> int:
    """
    Propagate forward repeats (repeatStart), backward repeats (repeatEnd),
    volta <ending> brackets, and special barline styles across all parallel parts.

    In multi-staff systems, homr often detects repeat dots on only a subset of staves
    (e.g., 2 of 4 SATB staves on Measure 5, or 3 of 4 on Measure 14), and volta brackets
    appear only above the top staff.
    """
    from app.services.musicxml_sanitizer import (
        _order_barline_children,
        sanitize_barlines_and_repeats,
    )

    updated_count = sanitize_barlines_and_repeats(root)
    parts = root.findall(".//part")
    if len(parts) <= 1:
        return updated_count

    part_measures = [p.findall("measure") for p in parts]
    min_measures = min(len(ms) for ms in part_measures)
    if min_measures == 0:
        return updated_count

    # Pre-scan which measure indices have any forward or backward repeat or ending
    any_fwd = [False] * min_measures
    any_bwd = [False] * min_measures
    fwd_counts = [0] * min_measures
    bwd_counts = [0] * min_measures

    for m_idx in range(min_measures):
        for ms in part_measures:
            m = ms[m_idx]
            if m.find("barline[@location='left']/repeat[@direction='forward']") is not None:
                fwd_counts[m_idx] += 1
                any_fwd[m_idx] = True
            if m.find("barline[@location='right']/repeat[@direction='backward']") is not None:
                bwd_counts[m_idx] += 1
                any_bwd[m_idx] = True

    for m_idx in range(min_measures):
        m_list = [ms[m_idx] for ms in part_measures]

        # 1. Forward repeat consensus
        has_paired_bwd = any(any_bwd[j] for j in range(m_idx, min(min_measures, m_idx + 17)))
        should_have_fwd = fwd_counts[m_idx] >= 2 or (fwd_counts[m_idx] >= 1 and has_paired_bwd)
        if should_have_fwd:
            for m in m_list:
                bl = _get_or_create_measure_barline(m, "left")
                if bl.find("bar-style") is None:
                    bs = ET.Element("bar-style")
                    bs.text = "heavy-light"
                    bl.insert(0, bs)
                if bl.find("repeat[@direction='forward']") is None:
                    ET.SubElement(bl, "repeat", direction="forward")
                    _order_barline_children(bl)
                    updated_count += 1

        # 2. Backward repeat consensus
        has_paired_fwd = any(any_fwd[j] for j in range(max(0, m_idx - 16), m_idx + 1))
        should_have_bwd = bwd_counts[m_idx] >= 2 or (bwd_counts[m_idx] >= 1 and has_paired_fwd)
        if should_have_bwd:
            for m in m_list:
                bl = _get_or_create_measure_barline(m, "right")
                if bl.find("bar-style") is None:
                    bs = ET.Element("bar-style")
                    bs.text = "light-heavy"
                    bl.insert(0, bs)
                if bl.find("repeat[@direction='backward']") is None:
                    ET.SubElement(bl, "repeat", direction="backward")
                    _order_barline_children(bl)
                    updated_count += 1

        # 3. Synchronize <ending> elements across all parts for both left and right barlines
        for loc in ("left", "right"):
            ending_templates: dict[tuple[str, str], ET.Element] = {}
            for m in m_list:
                for ending in m.findall(f"barline[@location='{loc}']/ending"):
                    num = (ending.get("number") or "1").strip()
                    etype = (ending.get("type") or "start").strip()
                    if (num, etype) not in ending_templates:
                        ending_templates[(num, etype)] = ending

            for (num, etype), tmpl in ending_templates.items():
                for m in m_list:
                    bl = _get_or_create_measure_barline(m, loc)
                    existing = [
                        e
                        for e in bl.findall("ending")
                        if (e.get("number") or "1").strip() == num
                        and (e.get("type") or "").strip() == etype
                    ]
                    if not existing:
                        bl.append(deepcopy(tmpl))
                        _order_barline_children(bl)
                        updated_count += 1

        # 4. Synchronize non-repeat special right barline styles (e.g., light-heavy final bar, light-light)
        if not should_have_bwd:
            style_votes: list[str] = []
            for m in m_list:
                bs_el = m.find("barline[@location='right']/bar-style")
                if bs_el is not None and bs_el.text and bs_el.text.strip():
                    style_votes.append(bs_el.text.strip())
            if style_votes:
                maj_style, maj_s_count = Counter(style_votes).most_common(1)[0]
                if maj_s_count >= 2 and maj_s_count >= len(m_list) / 2:
                    for m in m_list:
                        bl = _get_or_create_measure_barline(m, "right")
                        bs_el = bl.find("bar-style")
                        if bs_el is None:
                            bs_el = ET.Element("bar-style")
                            bs_el.text = maj_style
                            bl.insert(0, bs_el)
                            _order_barline_children(bl)
                            updated_count += 1

    return updated_count


def _extract_primary_voice_events(
    measure: ET.Element, divisions: int
) -> tuple[list[list[ET.Element]], list[Fraction], bool]:
    """
    Extract primary voice ("1") chord-groups and their durations in quarter-note Fractions.
    Returns (event_note_groups, event_quarter_durations, has_multi_voice_backup).
    """
    has_backup = measure.find("backup") is not None or measure.find("forward") is not None
    groups: list[list[ET.Element]] = []
    durations: list[Fraction] = []

    for elem in list(measure):
        if elem.tag != "note":
            continue
        if elem.find("grace") is not None:
            continue
        voice_text = (elem.findtext("voice") or "1").strip()
        if voice_text != "1":
            continue

        if elem.find("chord") is not None:
            if groups:
                groups[-1].append(elem)
            continue

        dur_text = (elem.findtext("duration") or "0").strip()
        dur_int = int(dur_text) if dur_text.isdigit() else 0
        groups.append([elem])
        durations.append(Fraction(dur_int, max(1, divisions)))

    return groups, durations, has_backup


def _set_event_quarter_duration(
    note_group: list[ET.Element], target_q: Fraction, divisions: int
) -> bool:
    """
    Update <duration>, <type>, and <dot> on all notes in a chord group to match target_q.
    """
    new_dur_frac = target_q * divisions
    if new_dur_frac.denominator != 1 or new_dur_frac.numerator <= 0:
        return False

    new_dur_int = new_dur_frac.numerator
    type_info = _QUARTER_FRACTION_TO_TYPE.get(target_q)

    for note_el in note_group:
        dur_el = note_el.find("duration")
        if dur_el is None:
            dur_el = ET.SubElement(note_el, "duration")
        dur_el.text = str(new_dur_int)

        if type_info is not None:
            type_name, dot_count = type_info
            type_el = note_el.find("type")
            if type_el is not None:
                type_el.text = type_name
            # Rebuild <dot/> elements right after <type> or <voice>
            for old_dot in list(note_el.findall("dot")):
                note_el.remove(old_dot)
            if dot_count > 0:
                children = list(note_el)
                insert_idx = len(children)
                for idx, ch in enumerate(children):
                    if ch.tag in ("type", "voice", "duration"):
                        insert_idx = idx + 1
                for _ in range(dot_count):
                    note_el.insert(insert_idx, ET.Element("dot"))

    return True


def repair_cross_part_rhythm_outliers(root: ET.Element) -> int:
    """
    Detect and repair single-part OMR duration errors in multi-part scores using
    cross-part rhythmic consensus:
      1. Homophonic N-event template snapping: when a part's total measure duration
         disagrees with the cross-part consensus, but another part with the consensus
         duration has the exact same number of primary rhythmic events, snap the
         mismatched event durations to the reference template.
      2. Prefix/suffix spurious rest removal: when an overfilled outlier measure
         shares identical prefix and suffix events with a reference part and differs
         only by an extra rest next to a misread note in the middle, remove the
         spurious rest and snap the note duration.

    Returns:
        Number of measures repaired.
    """
    parts = root.findall(".//part")
    if len(parts) < 2:
        return 0

    part_measures = [p.findall("measure") for p in parts]
    min_measures = min(len(ms) for ms in part_measures)
    if min_measures == 0:
        return 0

    running_divs = [1 for _ in parts]
    running_expected_q = [Fraction(4, 1) for _ in parts]
    repaired_measures = 0

    for m_idx in range(min_measures):
        # Update running divisions and time signature expectations
        for p_idx, ms in enumerate(part_measures):
            m = ms[m_idx]
            for attr in m.findall("attributes"):
                div_text = (attr.findtext("divisions") or "").strip()
                if div_text.isdigit() and int(div_text) > 0:
                    running_divs[p_idx] = int(div_text)
                b_text = (attr.findtext("time/beats") or "").strip()
                bt_text = (attr.findtext("time/beat-type") or "").strip()
                if b_text.isdigit() and bt_text.isdigit() and int(bt_text) > 0:
                    running_expected_q[p_idx] = Fraction(int(b_text) * 4, int(bt_text))

        # Extract events and total duration for each part in this measure
        part_events: list[tuple[list[list[ET.Element]], list[Fraction], bool]] = []
        part_totals: list[Fraction] = []

        for p_idx, ms in enumerate(part_measures):
            groups, durs, has_backup = _extract_primary_voice_events(ms[m_idx], running_divs[p_idx])
            part_events.append((groups, durs, has_backup))
            part_totals.append(sum(durs, Fraction(0)))

        if len(set(part_totals)) <= 1:
            continue

        # Determine consensus target duration in quarter notes
        counts = Counter(q for q in part_totals if q > 0)
        if not counts:
            continue

        top_candidates = counts.most_common()
        maj_q, maj_count = top_candidates[0]
        expected_q = running_expected_q[0]

        if maj_count > len(parts) / 2 and maj_count >= 2:
            target_q = maj_q
        elif expected_q in counts and counts[expected_q] >= 2:
            target_q = expected_q
        else:
            continue

        # Reference parts that already match target_q
        ref_indices = [i for i, tot in enumerate(part_totals) if tot == target_q]

        for p_idx, tot_q in enumerate(part_totals):
            if tot_q == target_q:
                continue

            groups, durs, has_backup = part_events[p_idx]
            if has_backup or not groups:
                continue

            div = running_divs[p_idx]
            fixed_this_part = False

            # Strategy 1: Exact N-event homophonic template match against a reference part
            for r_idx in ref_indices:
                r_groups, r_durs, r_backup = part_events[r_idx]
                if not r_backup and len(r_durs) == len(durs):
                    # Verify all target durations are representable in this part's divisions
                    if all((rq * div).denominator == 1 and (rq * div).numerator > 0 for rq in r_durs):
                        for ev_idx, (grp, cur_q, ref_q) in enumerate(zip(groups, durs, r_durs)):
                            if cur_q != ref_q:
                                _set_event_quarter_duration(grp, ref_q, div)
                        fixed_this_part = True
                        break

            # Strategy 2: Prefix + suffix match where outlier has 1 extra spurious rest in the middle
            if not fixed_this_part and tot_q > target_q:
                for r_idx in ref_indices:
                    r_groups, r_durs, r_backup = part_events[r_idx]
                    if r_backup or len(durs) != len(r_durs) + 1:
                        continue

                    # Match common prefix
                    prefix_len = 0
                    while (
                        prefix_len < len(r_durs)
                        and durs[prefix_len] == r_durs[prefix_len]
                    ):
                        prefix_len += 1

                    # Match common suffix
                    suffix_len = 0
                    while (
                        suffix_len < (len(r_durs) - prefix_len)
                        and durs[len(durs) - 1 - suffix_len] == r_durs[len(r_durs) - 1 - suffix_len]
                    ):
                        suffix_len += 1

                    if prefix_len + suffix_len == len(r_durs) - 1:
                        # Outlier has 2 events at [prefix_len, prefix_len+1] corresponding to 1 ref event r_durs[prefix_len]
                        ref_mid_q = r_durs[prefix_len]
                        ev_a, ev_b = groups[prefix_len], groups[prefix_len + 1]
                        a_is_rest = ev_a[0].find("rest") is not None
                        b_is_rest = ev_b[0].find("rest") is not None
                        if a_is_rest and not b_is_rest and (ref_mid_q * div).denominator == 1:
                            part_measures[p_idx][m_idx].remove(ev_a[0])
                            _set_event_quarter_duration(ev_b, ref_mid_q, div)
                            fixed_this_part = True
                            break
                        elif b_is_rest and not a_is_rest and (ref_mid_q * div).denominator == 1:
                            part_measures[p_idx][m_idx].remove(ev_b[0])
                            _set_event_quarter_duration(ev_a, ref_mid_q, div)
                            fixed_this_part = True
                            break

            if fixed_this_part:
                repaired_measures += 1

    return repaired_measures


def _set_measure_time_signature(measure: ET.Element, beats: int, beat_type: int) -> None:
    """Insert or update <time><beats>...</beats><beat-type>...</beat-type></time> in measure."""
    time_el = measure.find(".//attributes/time")
    if time_el is not None:
        b_el = time_el.find("beats")
        if b_el is None:
            b_el = ET.SubElement(time_el, "beats")
        b_el.text = str(beats)
        bt_el = time_el.find("beat-type")
        if bt_el is None:
            bt_el = ET.SubElement(time_el, "beat-type")
        bt_el.text = str(beat_type)
        return

    attr_el = measure.find("attributes")
    if attr_el is None:
        attr_el = ET.Element("attributes")
        # Insert after <print> if present, else at index 0
        insert_idx = 0
        for idx, ch in enumerate(list(measure)):
            if ch.tag == "print":
                insert_idx = idx + 1
        measure.insert(insert_idx, attr_el)

    time_el = ET.SubElement(attr_el, "time")
    b_el = ET.SubElement(time_el, "beats")
    b_el.text = str(beats)
    bt_el = ET.SubElement(time_el, "beat-type")
    bt_el.text = str(beat_type)


def _remove_measure_time_signature(measure: ET.Element) -> bool:
    """Remove redundant <time> element from measure <attributes> if present."""
    removed = False
    for attr in list(measure.findall("attributes")):
        for time_el in list(attr.findall("time")):
            attr.remove(time_el)
            removed = True
        if len(attr) == 0:
            measure.remove(attr)
    return removed


def _is_single_whole_rest_measure(groups: list[list[ET.Element]], has_backup: bool) -> bool:
    """Return True if a measure's primary voice consists solely of a single whole rest or measure rest."""
    if has_backup or len(groups) != 1 or len(groups[0]) != 1:
        return False
    sole_note = groups[0][0]
    rest_el = sole_note.find("rest")
    if rest_el is None:
        return False
    if rest_el.get("measure") == "yes":
        return True
    note_type = (sole_note.findtext("type") or "").strip().lower()
    return note_type in ("whole", "breve", "")


def normalize_whole_measure_rests(root: ET.Element) -> int:
    """
    Convert single-event <type>whole</type> rests (emitted by homr as `rest_1` with
    4.0 quarter-note duration) into <rest measure="yes"/> snapped to the active
    time signature's measure duration (e.g., 3.0 quarter notes / 12 divisions in 6/8).

    In standard engraving, a whole rest centered in a measure denotes a full-bar rest
    in any time signature (6/8, 3/4, 2/4, etc.). Without this normalization, 3 resting
    voices during a solo in 6/8 time have duration 16 (8/8), causing downstream passes
    to falsely infer a meter change to 8/8.
    """
    parts = root.findall(".//part")
    if not parts:
        return 0

    part_measures = [p.findall("measure") for p in parts]
    min_measures = min(len(ms) for ms in part_measures)
    if min_measures == 0:
        return 0

    running_divs = [1 for _ in parts]
    active_beats = 4
    active_beat_type = 4
    normalized_count = 0

    for m_idx in range(min_measures):
        explicit_times: list[tuple[int, int]] = []
        for p_idx, ms in enumerate(part_measures):
            m = ms[m_idx]
            for attr in m.findall("attributes"):
                div_text = (attr.findtext("divisions") or "").strip()
                if div_text.isdigit() and int(div_text) > 0:
                    running_divs[p_idx] = int(div_text)
                b_text = (attr.findtext("time/beats") or "").strip()
                bt_text = (attr.findtext("time/beat-type") or "").strip()
                if b_text.isdigit() and bt_text.isdigit() and int(bt_text) > 0:
                    explicit_times.append((int(b_text), int(bt_text)))

        if explicit_times:
            (cand_b, cand_bt), cand_count = Counter(explicit_times).most_common(1)[0]
            if m_idx == 0 or cand_count >= 2 or len(parts) == 1:
                active_beats, active_beat_type = cand_b, cand_bt

        expected_q = Fraction(active_beats * 4, active_beat_type)

        # Check if non-rest parts in this measure establish a pickup or explicit meter
        non_rest_totals: list[Fraction] = []
        part_events: list[tuple[list[list[ET.Element]], list[Fraction], bool]] = []
        for p_idx, ms in enumerate(part_measures):
            groups, durs, has_backup = _extract_primary_voice_events(ms[m_idx], running_divs[p_idx])
            part_events.append((groups, durs, has_backup))
            if not _is_single_whole_rest_measure(groups, has_backup):
                tot = sum(durs, Fraction(0))
                if tot > 0:
                    non_rest_totals.append(tot)

        target_q = expected_q
        if m_idx == 0 and non_rest_totals:
            maj_non_rest_q, _ = Counter(non_rest_totals).most_common(1)[0]
            if Fraction(0) < maj_non_rest_q < expected_q:
                target_q = maj_non_rest_q

        for p_idx, (groups, durs, has_backup) in enumerate(part_events):
            if not _is_single_whole_rest_measure(groups, has_backup):
                continue

            sole_note = groups[0][0]
            rest_el = sole_note.find("rest")
            if rest_el is None:
                continue

            div = running_divs[p_idx]
            target_dur_frac = target_q * div
            if target_dur_frac.denominator != 1 or target_dur_frac.numerator <= 0:
                continue

            target_dur_int = target_dur_frac.numerator
            changed = False

            if rest_el.get("measure") != "yes":
                rest_el.set("measure", "yes")
                changed = True

            dur_el = sole_note.find("duration")
            if dur_el is None:
                dur_el = ET.SubElement(sole_note, "duration")
            if (dur_el.text or "").strip() != str(target_dur_int):
                dur_el.text = str(target_dur_int)
                changed = True

            for old_dot in list(sole_note.findall("dot")):
                sole_note.remove(old_dot)
                changed = True

            if changed:
                normalized_count += 1

    return normalized_count


def infer_and_align_measure_time_signatures(root: ET.Element) -> int:
    """
    Infer mixed-meter time signature changes (e.g. 3/4 <-> 4/4) from cross-part
    consensus measure durations and mark pickup measures (anacrusis) as implicit="yes".

    Because homr's token vocabulary (timeSignature/4) only encodes the denominator
    and uses the page-wide median duration for the numerator, single-measure meter
    changes on a page (such as 4/4 bars inside a 3/4 piece) are mislabeled by homr
    as 3/4.

    Returns:
        Number of measure time signature attributes updated.
    """
    parts = root.findall(".//part")
    if not parts:
        return 0

    part_measures = [p.findall("measure") for p in parts]
    min_measures = min(len(ms) for ms in part_measures)
    if min_measures < 2:
        return 0

    running_divs = [1 for _ in parts]
    active_beats = 4
    active_beat_type = 4
    updated_count = 0

    for m_idx in range(min_measures):
        # 1. Read any explicit divisions and time signatures on this measure
        explicit_times: list[tuple[int, int]] = []
        for p_idx, ms in enumerate(part_measures):
            m = ms[m_idx]
            for attr in m.findall("attributes"):
                div_text = (attr.findtext("divisions") or "").strip()
                if div_text.isdigit() and int(div_text) > 0:
                    running_divs[p_idx] = int(div_text)
                b_text = (attr.findtext("time/beats") or "").strip()
                bt_text = (attr.findtext("time/beat-type") or "").strip()
                if b_text.isdigit() and bt_text.isdigit() and int(bt_text) > 0:
                    explicit_times.append((int(b_text), int(bt_text)))

        if m_idx == 0 and explicit_times:
            active_beats, active_beat_type = Counter(explicit_times).most_common(1)[0][0]

        # 2. Calculate each part's actual primary voice duration in quarter notes
        part_totals: list[Fraction] = []
        active_voice_totals: list[Fraction] = []
        for p_idx, ms in enumerate(part_measures):
            groups, durs, has_backup = _extract_primary_voice_events(ms[m_idx], running_divs[p_idx])
            tot = sum(durs, Fraction(0))
            part_totals.append(tot)
            if not _is_single_whole_rest_measure(groups, has_backup) and tot > 0:
                active_voice_totals.append(tot)

        counts = Counter(q for q in part_totals if q > 0)
        if not counts:
            continue

        consensus_q, maj_count = counts.most_common(1)[0]
        if maj_count <= len(parts) / 2 and len(parts) > 1:
            continue

        active_expected_q = Fraction(active_beats * 4, active_beat_type)

        # Handle Measure 1 pickup (anacrusis)
        if m_idx == 0:
            if Fraction(0) < consensus_q < active_expected_q:
                for ms in part_measures:
                    if ms[0].get("implicit") != "yes":
                        ms[0].set("implicit", "yes")
                        updated_count += 1
            continue

        # Never infer a meter change if no active (non-whole-rest) voices support the new duration
        if consensus_q != active_expected_q:
            active_support = sum(1 for q in active_voice_totals if q == consensus_q)
            if active_support == 0 or (len(active_voice_totals) >= 2 and active_support <= len(active_voice_totals) / 2):
                continue

        # Check if consensus_q represents a valid meter change relative to active_expected_q
        beat_unit_q = Fraction(4, active_beat_type)
        beats_in_active_denom = consensus_q / beat_unit_q

        if (
            beats_in_active_denom.denominator == 1
            and 2 <= beats_in_active_denom.numerator <= 12
        ):
            inferred_beats = beats_in_active_denom.numerator
            inferred_bt = active_beat_type

            if inferred_beats != active_beats:
                # Meter changed on this measure! Set <time> across all parts
                for ms in part_measures:
                    _set_measure_time_signature(ms[m_idx], inferred_beats, inferred_bt)
                    updated_count += 1
                active_beats = inferred_beats
            else:
                # Meter did NOT change on this measure; ensure any explicit <time> matches active meter
                for ms in part_measures:
                    time_el = ms[m_idx].find(".//attributes/time")
                    if time_el is not None:
                        curr_b = (time_el.findtext("beats") or "").strip()
                        curr_bt = (time_el.findtext("beat-type") or "").strip()
                        if curr_b != str(active_beats) or curr_bt != str(active_beat_type):
                            _set_measure_time_signature(ms[m_idx], active_beats, active_beat_type)
                            updated_count += 1

    return updated_count


def repair_score_consistency(root: ET.Element) -> dict[str, int]:
    """
    Apply full suite of score consistency post-processing rules.
    """
    ghost_removed = remove_empty_ghost_measures(root)
    sys_aligned = align_system_break_measures(root)
    tenor_fixes = fix_tenor_octave_and_clef(root)
    sig_fixes = align_key_and_time_signatures(root)
    barline_fixes = align_barlines_and_repeats(root)
    rest_fixes = normalize_whole_measure_rests(root)
    rhythm_fixes = repair_cross_part_rhythm_outliers(root)
    meter_fixes = infer_and_align_measure_time_signatures(root)

    return {
        "ghost_measures_removed": ghost_removed,
        "system_breaks_aligned": sys_aligned,
        "tenor_parts_adjusted": tenor_fixes,
        "signatures_aligned": sig_fixes,
        "barlines_aligned": barline_fixes,
        "whole_rests_normalized": rest_fixes,
        "rhythm_outliers_repaired": rhythm_fixes,
        "time_signatures_inferred": meter_fixes,
    }


def repair_score_file(xml_path: Path) -> dict[str, int]:
    """Load, repair, and save a MusicXML file."""
    if not xml_path.exists():
        return {}
    try:
        tree = dET.parse(xml_path)
        root = tree.getroot()
        stats = repair_score_consistency(root)
        if any(v > 0 for v in stats.values()):
            tree.write(xml_path, encoding="utf-8", xml_declaration=True)
            logger.info("Repaired score consistency in %s: %s", xml_path.name, stats)
        return stats
    except Exception as exc:
        logger.warning("Could not repair score consistency for %s: %s", xml_path, exc)
        return {}

