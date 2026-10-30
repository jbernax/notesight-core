"""
MusicXML Auto-Beamer Service
Computes and injects standard Western music notation beam tags (<beam>)
into MusicXML scores where beams are missing (e.g., from OMR inference engines like homr).
"""

from fractions import Fraction
import logging
from typing import Any
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Mapping of MusicXML note types to beam levels
BEAM_TYPE_LEVELS: dict[str, int] = {
    "eighth": 1,
    "16th": 2,
    "32nd": 3,
    "64th": 4,
    "128th": 5,
}

# Ordered valid tags in MusicXML <note> schema
# <beam> must come after staff/stem/notations-preceding elements and before <notations>/<lyric>
TAGS_PRECEDING_BEAM = {
    "grace",
    "cue",
    "chord",
    "pitch",
    "unpitched",
    "rest",
    "duration",
    "tie",
    "voice",
    "type",
    "dot",
    "accidental",
    "time-modification",
    "stem",
    "notehead",
    "notehead-text",
    "staff",
}


def _calculate_beam_tags(notes_in_group: list[dict[str, Any]]) -> list[list[tuple[int, str]]]:
    """
    Given a list of note metadata dicts in a single beam group, calculate
    the beam tuples (level, beam_state) for each note.
    Beam states: 'begin', 'continue', 'end', 'forward hook', 'backward hook'.
    """
    n = len(notes_in_group)
    if n < 2:
        return [[] for _ in range(n)]

    levels = [note["level"] for note in notes_in_group]
    max_level = max(levels)
    beam_tags: list[list[tuple[int, str]]] = [[] for _ in range(n)]

    for lvl in range(1, max_level + 1):
        in_segment = False
        seg_start = -1

        for i in range(n):
            has_lvl = levels[i] >= lvl
            if has_lvl and not in_segment:
                in_segment = True
                seg_start = i
            elif not has_lvl and in_segment:
                in_segment = False
                seg_end = i - 1
                _assign_level_tags(beam_tags, lvl, seg_start, seg_end, levels)

        if in_segment:
            seg_end = n - 1
            _assign_level_tags(beam_tags, lvl, seg_start, seg_end, levels)

    return beam_tags


def _assign_level_tags(
    beam_tags: list[list[tuple[int, str]]],
    lvl: int,
    start: int,
    end: int,
    levels: list[int],
) -> None:
    """Helper to assign begin/continue/end or hook tags for a segment at a given beam level."""
    if start == end:
        # Single isolated note at level >= lvl (e.g. 16th hook beside an 8th note)
        # Determine hook direction based on adjacent notes with at least level 1
        if start > 0 and levels[start - 1] >= 1:
            beam_tags[start].append((lvl, "backward hook"))
        elif start < len(levels) - 1 and levels[start + 1] >= 1:
            beam_tags[start].append((lvl, "forward hook"))
    else:
        for i in range(start, end + 1):
            if i == start:
                beam_tags[i].append((lvl, "begin"))
            elif i == end:
                beam_tags[i].append((lvl, "end"))
            else:
                beam_tags[i].append((lvl, "continue"))


def _insert_beam_element(note_elem: ET.Element, level: int, tag_value: str) -> None:
    """Insert a <beam number="level">tag_value</beam> element at the schema-compliant index."""
    beam_elem = ET.Element("beam", number=str(level))
    beam_elem.text = tag_value

    insert_idx = len(note_elem)
    for idx, child in enumerate(list(note_elem)):
        if child.tag not in TAGS_PRECEDING_BEAM and child.tag != "beam":
            insert_idx = idx
            break

    note_elem.insert(insert_idx, beam_elem)


def autobeam_musicxml_tree(root: ET.Element) -> int:
    """
    Scan a MusicXML ElementTree and automatically inject standard metric <beam> elements
    for eighth, 16th, and shorter notes that do not currently possess beam definitions.
    
    Preserves all existing explicit beams.
    Returns total number of <beam> elements injected.
    """
    total_beams_added = 0

    for part in root.findall(".//part"):
        current_divisions = 1
        current_beats = 4
        current_beat_type = 4

        for measure in part.findall("measure"):
            # Update divisions and time signature if defined in this measure
            div_elem = measure.find(".//attributes/divisions")
            if div_elem is not None and div_elem.text and div_elem.text.strip():
                try:
                    parsed_div = int(div_elem.text.strip())
                    if parsed_div > 0:
                        current_divisions = parsed_div
                except ValueError:
                    pass

            beats_elem = measure.find(".//attributes/time/beats")
            beat_type_elem = measure.find(".//attributes/time/beat-type")
            if beats_elem is not None and beats_elem.text and beat_type_elem is not None and beat_type_elem.text:
                try:
                    parsed_beats = int(beats_elem.text.strip())
                    parsed_bt = int(beat_type_elem.text.strip())
                    if parsed_beats > 0 and parsed_bt > 0:
                        current_beats = parsed_beats
                        current_beat_type = parsed_bt
                except ValueError:
                    pass

            # Calculate beat duration in divisions
            # Compound meters (6/8, 9/8, 12/8): beat is 3 eighth notes = 1.5 quarter notes
            if current_beat_type == 8 and current_beats % 3 == 0:
                beat_duration = Fraction(current_divisions * 3, 2)
            else:
                beat_duration = Fraction(current_divisions * 4, current_beat_type)

            if beat_duration <= 0:
                beat_duration = Fraction(current_divisions, 1)

            # Timeline pass: track note onsets, voices, and staves
            clock = Fraction(0)
            voice_streams: dict[tuple[str, str], list[dict[str, Any]]] = {}
            prev_onset = Fraction(0)

            for elem in list(measure):
                if elem.tag == "backup":
                    dur_elem = elem.find("duration")
                    if dur_elem is not None and dur_elem.text:
                        try:
                            clock = max(Fraction(0), clock - Fraction(int(dur_elem.text.strip()), 1))
                        except ValueError:
                            pass
                    continue

                if elem.tag == "forward":
                    dur_elem = elem.find("duration")
                    if dur_elem is not None and dur_elem.text:
                        try:
                            clock = clock + Fraction(int(dur_elem.text.strip()), 1)
                        except ValueError:
                            pass
                    continue

                if elem.tag != "note":
                    continue

                is_chord = elem.find("chord") is not None
                is_grace = elem.find("grace") is not None
                is_rest = elem.find("rest") is not None

                dur_val = Fraction(0)
                dur_elem = elem.find("duration")
                if dur_elem is not None and dur_elem.text:
                    try:
                        dur_val = Fraction(int(dur_elem.text.strip()), 1)
                    except ValueError:
                        pass

                if is_chord:
                    onset = prev_onset
                else:
                    onset = clock
                    prev_onset = onset
                    if not is_grace:
                        clock = clock + dur_val

                # Skip chords from creating distinct beam positions (MusicXML puts beams only on base note)
                if is_chord:
                    continue

                staff_elem = elem.find("staff")
                staff_num = staff_elem.text.strip() if staff_elem is not None and staff_elem.text else "1"

                voice_elem = elem.find("voice")
                voice_num = voice_elem.text.strip() if voice_elem is not None and voice_elem.text else "1"

                type_elem = elem.find("type")
                note_type = type_elem.text.strip().lower() if type_elem is not None and type_elem.text else ""

                has_beams = elem.find("beam") is not None
                level = BEAM_TYPE_LEVELS.get(note_type, 0) if not is_rest and not is_grace else 0

                stream_key = (staff_num, voice_num)
                if stream_key not in voice_streams:
                    voice_streams[stream_key] = []

                voice_streams[stream_key].append({
                    "elem": elem,
                    "onset": onset,
                    "duration": dur_val,
                    "is_rest": is_rest,
                    "is_grace": is_grace,
                    "has_beams": has_beams,
                    "level": level,
                    "type": note_type,
                })

            # Process beaming for each staff and voice stream
            for stream in voice_streams.values():
                # Split stream into metric beats
                i = 0
                n_notes = len(stream)
                while i < n_notes:
                    note_info = stream[i]

                    # Only consider beamable notes (level >= 1, not rest, no existing beams)
                    if note_info["level"] < 1 or note_info["is_rest"] or note_info["has_beams"]:
                        i += 1
                        continue

                    # Determine which beat this note belongs to
                    beat_index = int(note_info["onset"] // beat_duration)
                    beat_start = beat_index * beat_duration
                    beat_end = beat_start + beat_duration

                    # Collect all consecutive beamable notes within this beat
                    group: list[dict[str, Any]] = []
                    j = i
                    has_preexisting_beams_in_beat = False

                    while j < n_notes:
                        curr = stream[j]
                        # If reached beyond the beat window, end group
                        if curr["onset"] >= beat_end:
                            break

                        # If rest or non-beamable note occurs within beat, it breaks contiguous beam group
                        if curr["is_rest"] or curr["level"] < 1:
                            break

                        if curr["has_beams"]:
                            has_preexisting_beams_in_beat = True
                            break

                        group.append(curr)
                        j += 1

                    # If the beat already had explicit user/OMR beams, do not overwrite or duplicate
                    if not has_preexisting_beams_in_beat and len(group) >= 2:
                        tags_per_note = _calculate_beam_tags(group)
                        for note_dict, tags in zip(group, tags_per_note):
                            for lvl, state_str in tags:
                                _insert_beam_element(note_dict["elem"], lvl, state_str)
                                total_beams_added += 1

                    i = max(i + 1, j)

    return total_beams_added
