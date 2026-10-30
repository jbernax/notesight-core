"""
MusicXML Sanitizer Service
Fixes structural inconsistencies, homr OMR edge cases, and invalid MusicXML constructs
that cause Verovio segfaults (C++ core dumps) or OpenSheetMusicDisplay render crashes.
"""

import copy
import logging
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET

from app.services.page_text import sanitize_xml_string

logger = logging.getLogger(__name__)


def _note_pitch_key(note_elem: ET.Element) -> tuple[str, int, int] | None:
    """Return (step, alter_int, octave_int) for a pitched <note>, or None if rest/unpitched."""
    if note_elem.find("rest") is not None:
        return None
    pitch = note_elem.find("pitch")
    if pitch is None:
        return None
    step = (pitch.findtext("step") or "").strip()
    if not step:
        return None
    alter_text = (pitch.findtext("alter") or "0").strip()
    octave_text = (pitch.findtext("octave") or "4").strip()
    try:
        alter_val = int(float(alter_text))
        octave_val = int(octave_text)
    except ValueError:
        return None
    return (step, alter_val, octave_val)


def _ensure_tie_on_note(note_elem: ET.Element, tie_type: str) -> None:
    """Ensure <tie type=tie_type/> and <notations><tied type=tie_type/></notations> exist on note."""
    existing_ties = [t for t in note_elem.findall("tie") if t.get("type") == tie_type]
    if not existing_ties:
        tie_el = ET.Element("tie", type=tie_type)
        children = list(note_elem)
        insert_idx = len(children)
        for idx, ch in enumerate(children):
            if ch.tag in ("duration", "pitch", "rest"):
                insert_idx = idx + 1
            elif ch.tag in ("voice", "type", "dot", "accidental", "stem", "staff", "beam", "notations", "lyric"):
                break
        note_elem.insert(insert_idx, tie_el)

    notations = note_elem.find("notations")
    if notations is None:
        notations = ET.SubElement(note_elem, "notations")
    existing_tied = [t for t in notations.findall("tied") if t.get("type") == tie_type]
    if not existing_tied:
        ET.SubElement(notations, "tied", type=tie_type)


def _cleanup_empty_notations(note_elem: ET.Element) -> None:
    """Remove any empty <notations> elements from note_elem."""
    for notations in list(note_elem.findall("notations")):
        if len(notations) == 0:
            note_elem.remove(notations)


def convert_same_pitch_slurs_to_ties(root: ET.Element) -> int:
    """
    Convert 2-note <slur type="start"/> -> <slur type="stop"/> pairs on immediately
    consecutive notes of identical pitch in the same (part, staff, voice) stream into
    proper MusicXML <tie> and <tied> elements.

    homr's vocabulary lacks tieStart/tieStop tokens and emits ties as slurs between
    adjacent notes of the same pitch.

    Returns:
        Number of slur pairs converted to ties.
    """
    converted_pairs = 0

    for part in root.findall(".//part"):
        streams: dict[tuple[str, str], list[ET.Element]] = {}
        for measure in part.findall("measure"):
            for note in measure.findall("note"):
                if note.find("grace") is not None or note.find("chord") is not None:
                    continue
                staff = (note.findtext("staff") or "1").strip()
                voice = (note.findtext("voice") or "1").strip()
                streams.setdefault((staff, voice), []).append(note)

        for stream_notes in streams.values():
            for idx in range(len(stream_notes) - 1):
                note_a = stream_notes[idx]
                note_b = stream_notes[idx + 1]
                pitch_a = _note_pitch_key(note_a)
                pitch_b = _note_pitch_key(note_b)
                if pitch_a is None or pitch_a != pitch_b:
                    continue

                notations_a = note_a.find("notations")
                notations_b = note_b.find("notations")
                if notations_a is None or notations_b is None:
                    continue

                start_slur = notations_a.find("slur[@type='start']")
                stop_slur = notations_b.find("slur[@type='stop']")
                if start_slur is None or stop_slur is None:
                    continue

                notations_a.remove(start_slur)
                notations_b.remove(stop_slur)
                _ensure_tie_on_note(note_a, "start")
                _ensure_tie_on_note(note_b, "stop")
                converted_pairs += 1

    return converted_pairs


def prune_unmatched_slurs(root: ET.Element) -> int:
    """
    Remove orphaned <slur type="stop"/> without an open start, duplicate nested
    unnumbered <slur type="start"/> whose predecessor was never closed, and unclosed
    <slur type="start"/> remaining at the end of a (part, staff, voice) stream.

    Returns:
        Number of unmatched slur elements removed.
    """
    pruned = 0

    for part in root.findall(".//part"):
        streams: dict[tuple[str, str], list[ET.Element]] = {}
        for measure in part.findall("measure"):
            for note in measure.findall("note"):
                if note.find("grace") is not None:
                    continue
                staff = (note.findtext("staff") or "1").strip()
                voice = (note.findtext("voice") or "1").strip()
                streams.setdefault((staff, voice), []).append(note)

        for stream_notes in streams.values():
            open_slur_note: ET.Element | None = None
            open_slur_notations: ET.Element | None = None
            open_slur_elem: ET.Element | None = None

            for note in stream_notes:
                for notations in list(note.findall("notations")):
                    # Process stop slurs first so a note can close a prior slur and start a new one
                    for stop_slur in list(notations.findall("slur[@type='stop']")):
                        if open_slur_elem is not None:
                            open_slur_note = None
                            open_slur_notations = None
                            open_slur_elem = None
                        else:
                            notations.remove(stop_slur)
                            pruned += 1

                    for start_slur in list(notations.findall("slur[@type='start']")):
                        if open_slur_elem is not None and open_slur_notations is not None:
                            open_slur_notations.remove(open_slur_elem)
                            if open_slur_note is not None:
                                _cleanup_empty_notations(open_slur_note)
                            pruned += 1
                        open_slur_note = note
                        open_slur_notations = notations
                        open_slur_elem = start_slur

                _cleanup_empty_notations(note)

            if open_slur_elem is not None and open_slur_notations is not None:
                open_slur_notations.remove(open_slur_elem)
                if open_slur_note is not None:
                    _cleanup_empty_notations(open_slur_note)
                pruned += 1

    return pruned


_ATTRIBUTES_CHILD_ORDER: dict[str, int] = {
    "footnote": 0,
    "level": 1,
    "divisions": 2,
    "key": 3,
    "time": 4,
    "staves": 5,
    "part-symbol": 6,
    "instruments": 7,
    "clef": 8,
    "staff-details": 9,
    "transpose": 10,
    "directive": 11,
    "measure-style": 12,
}

_BARLINE_CHILD_ORDER: dict[str, int] = {
    "bar-style": 0,
    "footnote": 1,
    "level": 2,
    "wavy-line": 3,
    "segno": 4,
    "coda": 5,
    "fermata": 6,
    "ending": 7,
    "repeat": 8,
}


def consolidate_measure_attributes(root: ET.Element) -> int:
    """
    Merge multiple <attributes> blocks within the same <measure> into a single
    canonical <attributes> element with XSD-ordered children.

    homr emits a first <attributes> with <divisions> and a second <attributes>
    with <key>, <time>, and <clef>, which previously caused downstream passes
    inspecting only measure.find("attributes") to think <time> was missing.
    """
    merged_count = 0
    singleton_tags = {"divisions", "key", "time", "staves", "part-symbol", "instruments"}

    for measure in root.findall(".//part/measure"):
        attrs = measure.findall("attributes")
        if not attrs:
            continue

        primary = attrs[0]
        if len(attrs) > 1:
            for extra in attrs[1:]:
                for child in list(extra):
                    if child.tag in singleton_tags:
                        existing = primary.find(child.tag)
                        if existing is not None:
                            primary.remove(existing)
                    elif child.tag == "clef":
                        c_num = child.get("number", "1")
                        for old_clef in list(primary.findall("clef")):
                            if old_clef.get("number", "1") == c_num:
                                primary.remove(old_clef)
                    primary.append(child)
                measure.remove(extra)
                merged_count += 1

        children = list(primary)
        sorted_children = sorted(children, key=lambda c: _ATTRIBUTES_CHILD_ORDER.get(c.tag, 99))
        if children != sorted_children:
            primary[:] = sorted_children

    return merged_count


def _order_barline_children(barline: ET.Element) -> None:
    """Sort children of a <barline> element according to MusicXML XSD order."""
    children = list(barline)
    sorted_children = sorted(children, key=lambda c: _BARLINE_CHILD_ORDER.get(c.tag, 99))
    if children != sorted_children:
        barline[:] = sorted_children


def sanitize_barlines_and_repeats(root: ET.Element) -> int:
    """
    Normalize <barline> elements in every measure:
      - Forward repeats (<repeat direction="forward"/>) must be on <barline location="left">
        with <bar-style>heavy-light</bar-style> at the start of the measure.
      - Backward repeats (<repeat direction="backward"/>) must be on <barline location="right">
        with <bar-style>light-heavy</bar-style> at the end of the measure.
      - Duplicate <barline> elements at the same location in a measure are merged.
      - Children inside <barline> are ordered (<bar-style>, <ending>, <repeat>).
    """
    corrections = 0

    for measure in root.findall(".//part/measure"):
        barlines = list(measure.findall("barline"))
        if not barlines:
            continue

        for bl in barlines:
            repeats = bl.findall("repeat")
            has_fwd = any(r.get("direction") == "forward" for r in repeats)
            has_bwd = any(r.get("direction") == "backward" for r in repeats)

            if has_fwd and not has_bwd:
                if bl.get("location") != "left":
                    bl.set("location", "left")
                    corrections += 1
                if bl.find("bar-style") is None:
                    bs = ET.Element("bar-style")
                    bs.text = "heavy-light"
                    bl.insert(0, bs)
                    corrections += 1
            elif has_bwd and not has_fwd:
                if bl.get("location") != "right":
                    bl.set("location", "right")
                    corrections += 1
                if bl.find("bar-style") is None:
                    bs = ET.Element("bar-style")
                    bs.text = "light-heavy"
                    bl.insert(0, bs)
                    corrections += 1

        # Merge multiple barlines with the same location ("left" or "right")
        by_loc: dict[str, ET.Element] = {}
        for bl in list(measure.findall("barline")):
            loc = bl.get("location") or "right"
            bl.set("location", loc)
            if loc not in by_loc:
                by_loc[loc] = bl
            else:
                target = by_loc[loc]
                for child in list(bl):
                    if child.tag == "bar-style" and target.find("bar-style") is not None:
                        continue
                    if child.tag == "repeat" and any(
                        r.get("direction") == child.get("direction") for r in target.findall("repeat")
                    ):
                        continue
                    if child.tag == "ending" and any(
                        e.get("type") == child.get("type") and e.get("number") == child.get("number")
                        for e in target.findall("ending")
                    ):
                        continue
                    target.append(child)
                measure.remove(bl)
                corrections += 1

        # Order children and position left barline before notes and right barline at end
        for loc, bl in by_loc.items():
            _order_barline_children(bl)
            children = list(measure)
            if loc == "left":
                first_note_idx = next(
                    (i for i, ch in enumerate(children) if ch.tag in ("note", "backup", "forward")),
                    len(children),
                )
                curr_idx = children.index(bl)
                if curr_idx > first_note_idx:
                    measure.remove(bl)
                    measure.insert(first_note_idx, bl)
                    corrections += 1
            elif loc == "right":
                if children[-1] is not bl:
                    measure.remove(bl)
                    measure.append(bl)
                    corrections += 1

    return corrections


def sanitize_measure_rests_and_durations(root: ET.Element) -> int:
    """
    Ensure every <part> has an <attributes> element in measure 1 with divisions & time,
    and every <note> (especially <rest measure="yes"/>) has a valid duration and type.
    Prevents OpenSheetMusicDisplay crashes ("The provided duration is not valid: u").
    """
    corrections = consolidate_measure_attributes(root)
    parts = root.findall(".//part")
    if not parts:
        return corrections

    # 1. Discover consensus divisions, time signature, and key from the score
    global_div = 8
    global_beats = 4
    global_beat_type = 4
    global_key = None
    has_any_attr = False
    for p in parts:
        m1 = p.find("measure")
        if m1 is not None:
            for attr in m1.findall("attributes"):
                has_any_attr = True
                div_text = attr.findtext("divisions")
                if div_text and div_text.isdigit():
                    global_div = int(div_text)
                b_text = attr.findtext("time/beats")
                bt_text = attr.findtext("time/beat-type")
                if b_text and b_text.isdigit() and bt_text and bt_text.isdigit():
                    global_beats = int(b_text)
                    global_beat_type = int(bt_text)
                k = attr.find("key")
                if k is not None and global_key is None:
                    global_key = k

    # 2. Check each part for missing attributes in measure 1 if score defines attributes
    if has_any_attr:
        for p in parts:
            measures = p.findall("measure")
            if not measures:
                continue
            m1 = measures[0]
            m1_attr = m1.find("attributes")
            if m1_attr is None:
                m1_attr = ET.Element("attributes")
                div_el = ET.SubElement(m1_attr, "divisions")
                div_el.text = str(global_div)
                time_el = ET.SubElement(m1_attr, "time")
                b_el = ET.SubElement(time_el, "beats")
                b_el.text = str(global_beats)
                bt_el = ET.SubElement(time_el, "beat-type")
                bt_el.text = str(global_beat_type)
                if global_key is not None:
                    m1_attr.append(copy.deepcopy(global_key))
                m1.insert(0, m1_attr)
            else:
                if m1_attr.find("divisions") is None:
                    div_el = ET.Element("divisions")
                    div_el.text = str(global_div)
                    m1_attr.insert(0, div_el)
                if m1_attr.find("time") is None:
                    time_el = ET.SubElement(m1_attr, "time")
                    b_el = ET.SubElement(time_el, "beats")
                    b_el.text = str(global_beats)
                    bt_el = ET.SubElement(time_el, "beat-type")
                    bt_el.text = str(global_beat_type)
                if m1_attr.find("key") is None and global_key is not None:
                    m1_attr.append(copy.deepcopy(global_key))
                consolidate_measure_attributes(root)

    # 3. Process every measure and note in every part
    type_duration_map = {
        "whole": 4.0,
        "half": 2.0,
        "quarter": 1.0,
        "eighth": 0.5,
        "16th": 0.25,
        "32nd": 0.125,
        "64th": 0.0625,
        "128th": 0.03125,
    }

    for p in parts:
        curr_div = global_div
        curr_beats = global_beats
        curr_beat_type = global_beat_type

        for m in p.findall("measure"):
            for attr in m.findall("attributes"):
                div_text = attr.findtext("divisions")
                if div_text and div_text.isdigit():
                    curr_div = int(div_text)
                b_text = attr.findtext("time/beats")
                bt_text = attr.findtext("time/beat-type")
                if b_text and b_text.isdigit() and bt_text and bt_text.isdigit():
                    curr_beats = int(b_text)
                    curr_beat_type = int(bt_text)

            measure_full_dur = max(1, int(curr_div * 4 * curr_beats / curr_beat_type))

            for note in m.findall("note"):
                rest = note.find("rest")
                dur = note.find("duration")
                grace = note.find("grace")
                chord = note.find("chord")
                is_measure_rest = rest is not None and rest.get("measure") == "yes"

                if is_measure_rest:
                    dur_text = (dur.text or "").strip() if dur is not None else ""
                    if not dur_text or dur_text == "0":
                        if dur is None:
                            dur = ET.Element("duration")
                            ins_idx = 1 if (note.find("pitch") is not None or rest is not None) else 0
                            note.insert(ins_idx, dur)
                        dur.text = str(measure_full_dur)
                        corrections += 1
                    if note.find("type") is None:
                        t_elem = ET.SubElement(note, "type")
                        t_elem.text = "whole"
                        corrections += 1
                    if note.find("voice") is None:
                        v_elem = ET.SubElement(note, "voice")
                        v_elem.text = "1"
                        corrections += 1
                elif grace is None:
                    # Regular note or non-measure rest
                    dur_text = (dur.text or "").strip() if dur is not None else ""
                    if not dur_text or dur_text == "0":
                        note_type = (note.findtext("type") or "").strip().lower()
                        if note_type in type_duration_map:
                            computed_dur = max(1, int(curr_div * type_duration_map[note_type]))
                        else:
                            computed_dur = max(1, curr_div)
                        if dur is None:
                            dur = ET.Element("duration")
                            ins_idx = 1 if (note.find("pitch") is not None or rest is not None) else 0
                            note.insert(ins_idx, dur)
                        dur.text = str(computed_dur)
                        corrections += 1

                    if note.find("voice") is None and chord is None:
                        v_elem = ET.SubElement(note, "voice")
                        v_elem.text = "1"
                        corrections += 1

    return corrections


def sanitize_musicxml_tree(root: ET.Element) -> int:
    """
    Sanitize an in-memory ElementTree root of a MusicXML document.
    Fixes:
      1. Invalid <chord/> elements immediately following a <rest/> note.
      2. Invalid <chord/> elements that appear as the first note in a measure or voice.
      3. Discrepancies in voice or staff between chord notes and their base note.
      4. Same-pitch 2-note slurs emitted by homr converted to proper <tie>/<tied> elements.
      5. Orphaned/unclosed <slur> elements pruned.
      6. Missing divisions or durations, and whole-measure rests without duration (preventing OSMD crash).
      7. Autotags voices (S, A, T, B) and instruments (Piano) and applies autobeaming.
    
    Returns:
        Number of corrections made.
    """
    from app.services.voice_autotagger import autotag_musicxml_tree
    from app.services.autobeamer import autobeam_musicxml_tree

    autotag_musicxml_tree(root)
    corrections = 0

    for part in root.findall(".//part"):
        for measure in part.findall("measure"):
            # Track previous note per voice/staff to detect invalid chords
            prev_note_is_rest = False
            prev_note_exists = False
            prev_staff = None

            for elem in list(measure):
                if elem.tag == "backup" or elem.tag == "forward":
                    # Time displacement elements reset immediate chord sequence
                    prev_note_exists = False
                    prev_note_is_rest = False
                    continue

                if elem.tag != "note":
                    continue

                is_rest = elem.find("rest") is not None
                chord_elem = elem.find("chord")
                staff_elem = elem.find("staff")
                curr_staff = staff_elem.text if staff_elem is not None else "1"

                if chord_elem is not None:
                    # In MusicXML, a chord note cannot follow a rest,
                    # cannot be the first note in a measure/sequence,
                    # and must belong to the same staff as the base note.
                    should_remove_chord = (
                        not prev_note_exists
                        or prev_note_is_rest
                        or (prev_staff is not None and curr_staff != prev_staff)
                    )

                    if should_remove_chord:
                        elem.remove(chord_elem)
                        corrections += 1
                        logger.debug(
                            "Removed invalid <chord/> following rest or boundary in measure %s",
                            measure.get("number")
                        )

                prev_note_exists = True
                prev_note_is_rest = is_rest
                prev_staff = curr_staff

    ties_converted = convert_same_pitch_slurs_to_ties(root)
    corrections += ties_converted

    slurs_pruned = prune_unmatched_slurs(root)
    corrections += slurs_pruned

    # Fix any missing durations or measure rests lacking duration (prevents OSMD "The provided duration is not valid: u")
    rests_and_durs_fixed = sanitize_measure_rests_and_durations(root)
    corrections += rests_and_durs_fixed

    # Normalize forward/backward repeat barline locations and child ordering
    barlines_fixed = sanitize_barlines_and_repeats(root)
    corrections += barlines_fixed

    # Apply automatic beaming to any unbeamed eighth/16th/shorter notes
    beams_added = autobeam_musicxml_tree(root)
    corrections += beams_added

    # Sanitize all text, tail, and attribute values for strict XML 1.0 validity
    text_fixed = sanitize_tree_text_nodes(root)
    corrections += text_fixed

    return corrections


def sanitize_tree_text_nodes(root: ET.Element) -> int:
    """Sanitize all text, tail, and attribute values in an ElementTree to be strictly valid XML 1.0."""
    fixed = 0
    for elem in root.iter():
        if elem.text:
            s_text = sanitize_xml_string(elem.text)
            if s_text != elem.text:
                elem.text = s_text
                fixed += 1
        if elem.tail:
            s_tail = sanitize_xml_string(elem.tail)
            if s_tail != elem.tail:
                elem.tail = s_tail
                fixed += 1
        for k, v in list(elem.attrib.items()):
            s_v = sanitize_xml_string(v)
            if s_v != v:
                elem.attrib[k] = s_v
                fixed += 1
    return fixed


def sanitize_musicxml_string(xml_content: str) -> tuple[str, int]:
    """
    Sanitize a MusicXML string and ensure standard XML header is present.

    Returns:
        Tuple of (sanitized_xml_string, corrections_count).
    """
    cleaned = sanitize_xml_string(xml_content.strip())
    if not cleaned:
        return xml_content, 0

    try:
        root = dET.fromstring(cleaned)
    except Exception as exc:
        logger.warning("Could not parse XML string for sanitization: %s", exc)
        return xml_content, 0

    corrections = sanitize_musicxml_tree(root)

    # Serialize back to UTF-8 XML string with standard declaration
    result_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return result_bytes.decode("utf-8"), corrections


def sanitize_musicxml_file(file_path: Path) -> int:
    """
    Sanitize a MusicXML file in-place on disk.
    Self-heals invalid XML tokens before or upon parsing.

    Returns:
        Number of corrections made.
    """
    if not file_path.exists():
        return 0

    try:
        tree = dET.parse(file_path)
    except (ET.ParseError, Exception) as exc:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        sanitized_text = sanitize_xml_string(raw_text)
        if sanitized_text != raw_text:
            file_path.write_text(sanitized_text, encoding="utf-8")
            tree = dET.parse(file_path)
        else:
            raise

    root = tree.getroot()
    corrections = sanitize_musicxml_tree(root)

    if corrections > 0 or not file_path.read_text(encoding="utf-8", errors="ignore").startswith("<?xml"):
        tree.write(file_path, encoding="utf-8", xml_declaration=True)
        logger.info("Sanitized %s: applied %d correction(s)", file_path.name, corrections)

    return corrections
