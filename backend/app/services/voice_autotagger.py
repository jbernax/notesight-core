"""
Voice & Piano Autotagging Service for NoteSight.
Automatically identifies, standardizes, and tags musical voices (Soprano, Alto,
Tenor, Bass, Baritone, Mezzo-Soprano) and instruments (Piano, Organ, etc.)
from score text abbreviations, MusicXML structures, clef arrangements, and staves.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import xml.etree.ElementTree as ET

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceTagInfo:
    tag: str  # Short tag/abbreviation: "S", "A", "T", "B", "Bar", "MS", "Pno", "Org", "V"
    name: str  # Canonical voice/instrument name: "Soprano", "Alto", "Tenor", "Bass", "Piano", etc.
    display_name: str  # User-friendly label: "S - Soprano", "Pno - Piano", etc.
    family: str  # "vocal" | "keyboard" | "instrumental"
    midi_program: int  # Standard General MIDI program (1-indexed: 1=Acoustic Grand Piano, 53=Choir Aahs)
    default_sound: str  # Synthesizer preset id: "piano", "strings", "synth"


# Standard Voice and Instrument Definitions
TAG_SOPRANO = VoiceTagInfo(
    tag="S",
    name="Soprano",
    display_name="S - Soprano",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_ALTO = VoiceTagInfo(
    tag="A",
    name="Alto",
    display_name="A - Alto",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_TENOR = VoiceTagInfo(
    tag="T",
    name="Tenor",
    display_name="T - Tenor",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_BASS = VoiceTagInfo(
    tag="B",
    name="Bass",
    display_name="B - Bass",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_BARITONE = VoiceTagInfo(
    tag="Bar",
    name="Barítono",
    display_name="Bar - Barítono",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_MEZZO = VoiceTagInfo(
    tag="MS",
    name="Mezzo-Soprano",
    display_name="MS - Mezzo-Soprano",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_VOICE = VoiceTagInfo(
    tag="V",
    name="Voice",
    display_name="V - Voice",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_CHOIR = VoiceTagInfo(
    tag="SATB",
    name="Choir (SATB)",
    display_name="SATB - Choir",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_DESCANT = VoiceTagInfo(
    tag="Desc",
    name="Descant",
    display_name="Desc - Descant",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_SOLO = VoiceTagInfo(
    tag="Solo",
    name="Solo",
    display_name="Solo - Solo",
    family="vocal",
    midi_program=53,
    default_sound="strings",
)

TAG_PIANO = VoiceTagInfo(
    tag="Pno",
    name="Piano",
    display_name="Pno - Piano",
    family="keyboard",
    midi_program=1,
    default_sound="piano",
)

TAG_ORGAN = VoiceTagInfo(
    tag="Org",
    name="Organ",
    display_name="Org - Organ",
    family="keyboard",
    midi_program=20,
    default_sound="synth",
)

TAG_VIOLIN = VoiceTagInfo(
    tag="Vln",
    name="Violin",
    display_name="Vln - Violin",
    family="instrumental",
    midi_program=41,
    default_sound="strings",
)

TAG_CELLO = VoiceTagInfo(
    tag="Vc",
    name="Cello",
    display_name="Vc - Cello",
    family="instrumental",
    midi_program=43,
    default_sound="strings",
)

TAG_FLUTE = VoiceTagInfo(
    tag="Fl",
    name="Flute",
    display_name="Fl - Flute",
    family="instrumental",
    midi_program=74,
    default_sound="synth",
)


# Normalized lookup map: clean lowercase string -> VoiceTagInfo
ALIAS_LOOKUP: dict[str, VoiceTagInfo] = {
    # Soprano aliases
    "s": TAG_SOPRANO,
    "sop": TAG_SOPRANO,
    "soprano": TAG_SOPRANO,
    "sopranos": TAG_SOPRANO,
    "canto": TAG_SOPRANO,
    "treble": TAG_SOPRANO,
    "diskant": TAG_SOPRANO,
    # Alto aliases
    "a": TAG_ALTO,
    "alt": TAG_ALTO,
    "alto": TAG_ALTO,
    "altos": TAG_ALTO,
    "contralto": TAG_ALTO,
    "c": TAG_ALTO,
    # Tenor aliases
    "t": TAG_TENOR,
    "ten": TAG_TENOR,
    "tenor": TAG_TENOR,
    "tenors": TAG_TENOR,
    "tenore": TAG_TENOR,
    # Bass aliases
    "b": TAG_BASS,
    "bas": TAG_BASS,
    "bass": TAG_BASS,
    "basses": TAG_BASS,
    "basso": TAG_BASS,
    "bajo": TAG_BASS,
    "bajos": TAG_BASS,
    "bao": TAG_BASS,
    "baja": TAG_BASS,
    # Baritone aliases
    "bar": TAG_BARITONE,
    "barit": TAG_BARITONE,
    "baritone": TAG_BARITONE,
    "baritones": TAG_BARITONE,
    "barítono": TAG_BARITONE,
    "baritono": TAG_BARITONE,
    "barítonos": TAG_BARITONE,
    "baritonos": TAG_BARITONE,
    # Mezzo-Soprano aliases
    "ms": TAG_MEZZO,
    "mz": TAG_MEZZO,
    "mezzo": TAG_MEZZO,
    "mezzosoprano": TAG_MEZZO,
    # General voice
    "v": TAG_VOICE,
    "voc": TAG_VOICE,
    "vocal": TAG_VOICE,
    "voice": TAG_VOICE,
    "voices": TAG_VOICE,
    "solo": TAG_SOLO,
    "sol": TAG_SOLO,
    "soloist": TAG_SOLO,
    "descant": TAG_DESCANT,
    "desc": TAG_DESCANT,
    "duet": TAG_DESCANT,
    "satb": TAG_CHOIR,
    "choir": TAG_CHOIR,
    "choral": TAG_CHOIR,
    "chorus": TAG_CHOIR,
    # Piano aliases
    "p": TAG_PIANO,
    "pno": TAG_PIANO,
    "pf": TAG_PIANO,
    "piano": TAG_PIANO,
    "pianos": TAG_PIANO,
    "pianoforte": TAG_PIANO,
    "kbd": TAG_PIANO,
    "keyboard": TAG_PIANO,
    "klavier": TAG_PIANO,
    "clavier": TAG_PIANO,
    "acc": TAG_PIANO,
    "accomp": TAG_PIANO,
    "accompaniment": TAG_PIANO,
    # Organ aliases
    "org": TAG_ORGAN,
    "organ": TAG_ORGAN,
    "organo": TAG_ORGAN,
    "orgue": TAG_ORGAN,
    # Other instruments
    "vln": TAG_VIOLIN,
    "violin": TAG_VIOLIN,
    "vc": TAG_CELLO,
    "cello": TAG_CELLO,
    "violoncello": TAG_CELLO,
    "fl": TAG_FLUTE,
    "flute": TAG_FLUTE,
}


def normalize_token(text: str) -> str:
    """Strip punctuation (dots, colons, brackets, quotes) and normalize whitespace/casing."""
    if not text:
        return ""
    # Strip common punctuation around voice abbreviations (e.g. "S.", "T:", "Pno.", "[A]")
    cleaned = re.sub(r"[^\w\s]", "", text).lower().strip()
    return cleaned


def resolve_voice_tag(text: str) -> VoiceTagInfo | None:
    """
    Resolve an arbitrary score label, abbreviation, or part name to a VoiceTagInfo.
    Handles variants like "S", "S.", "S:", "Soprano 1", "Pno.", "Piano", "T 1", etc.
    """
    if not text or not text.strip():
        return None

    raw_clean = normalize_token(text)
    if not raw_clean:
        return None

    # 1. Exact alias match
    if raw_clean in ALIAS_LOOKUP:
        return ALIAS_LOOKUP[raw_clean]

    # 2. Numbered voice variants (e.g. "S 1", "S1", "Soprano 1", "Tenor 2", "Bass 1")
    m = re.match(r"^([a-z]+)\s*(\d+|i|ii|iii|iv)$", raw_clean)
    if m:
        base_token = m.group(1)
        suffix = m.group(2).upper()
        if base_token in ALIAS_LOOKUP:
            base_info = ALIAS_LOOKUP[base_token]
            num_str = suffix
            if suffix == "I":
                num_str = "1"
            elif suffix == "II":
                num_str = "2"
            elif suffix == "III":
                num_str = "3"
            elif suffix == "IV":
                num_str = "4"
            tag_num = f"{base_info.tag}{num_str}"
            name_num = f"{base_info.name} {num_str}"
            return VoiceTagInfo(
                tag=tag_num,
                name=name_num,
                display_name=f"{tag_num} - {name_num}",
                family=base_info.family,
                midi_program=base_info.midi_program,
                default_sound=base_info.default_sound,
            )

    # 3. Check if text contains descant/duet/choir/solo keywords
    if any(k in raw_clean for k in ["descant", "duet"]):
        return TAG_DESCANT
    if "solo" in raw_clean:
        return TAG_SOLO
    if any(k in raw_clean for k in ["choir", "satb", "choral", "chorus", "cappella"]):
        return TAG_CHOIR

    # 4. Check if text contains piano/keyboard keywords
    if any(k in raw_clean for k in ["piano", "pianoforte", "klavier", "clavier", "keyboard"]):
        return TAG_PIANO

    # 5. Check if text contains soprano/alto/tenor/bass keywords
    if "soprano" in raw_clean:
        return TAG_SOPRANO
    if "contralto" in raw_clean or "alto" in raw_clean:
        return TAG_ALTO
    if "tenor" in raw_clean:
        return TAG_TENOR
    if "baritone" in raw_clean or "baritono" in raw_clean:
        return TAG_BARITONE
    if "bass" in raw_clean or "basso" in raw_clean:
        return TAG_BASS

    return None


def get_heuristic_voice_tags(
    parts_count: int,
    clef_signs: list[list[str]] | None = None,
    staves_counts: list[int] | None = None,
    part_names: list[str] | None = None,
) -> list[VoiceTagInfo]:
    """
    Generate standard voice/instrument tags based on parts count, clefs, and staves heuristics.
    Covers SATB choral ensembles, Choir + Piano, Piano solo, Duets, Trios.
    """
    if parts_count <= 0:
        return []

    # Heuristic for 1 part with 2 staves (Grand Staff) -> Piano
    if parts_count == 1:
        if staves_counts and staves_counts[0] >= 2:
            return [TAG_PIANO]
        return [TAG_PIANO]  # Default single-staff fallback is Piano / Music

    # Heuristic for 2 parts
    if parts_count == 2:
        if staves_counts and len(staves_counts) >= 2:
            # Descant/Solo + 2-staff Choir
            if staves_counts[0] == 1 and staves_counts[1] >= 2:
                p0_name = part_names[0].lower() if part_names and len(part_names) > 0 else ""
                p0_is_desc = any(k in p0_name for k in ["desc", "duet", "solo", "voice"])
                return [TAG_DESCANT if p0_is_desc else TAG_VOICE, TAG_CHOIR]
            if staves_counts[0] >= 2 and staves_counts[1] == 1:
                p1_name = part_names[1].lower() if part_names and len(part_names) > 1 else ""
                p1_is_desc = any(k in p1_name for k in ["desc", "duet", "solo", "voice"])
                return [TAG_CHOIR, TAG_DESCANT if p1_is_desc else TAG_VOICE]

        # If second part is grand staff (Piano) -> Voice + Piano
        if (
            (staves_counts and len(staves_counts) >= 2 and staves_counts[1] >= 2)
            or (part_names and len(part_names) >= 2 and resolve_voice_tag(part_names[1]) == TAG_PIANO)
        ):
            return [TAG_VOICE, TAG_PIANO]
        # Check clefs if available
        if clef_signs and len(clef_signs) >= 2:
            first_clef = clef_signs[0][0] if clef_signs[0] else "G"
            second_clef = clef_signs[1][0] if clef_signs[1] else "F"
            if first_clef == "G" and second_clef == "F":
                return [TAG_SOPRANO, TAG_BASS]
        return [TAG_SOPRANO, TAG_ALTO]

    # Heuristic for 3 parts -> SAB (Soprano, Alto, Bass)
    if parts_count == 3:
        if clef_signs and len(clef_signs) >= 3:
            c3 = clef_signs[2][0] if clef_signs[2] else "F"
            if c3 == "F":
                return [TAG_SOPRANO, TAG_ALTO, TAG_BASS]
        return [TAG_SOPRANO, TAG_ALTO, TAG_BASS]

    # Heuristic for 4 parts -> Canonical SATB
    if parts_count == 4:
        return [TAG_SOPRANO, TAG_ALTO, TAG_TENOR, TAG_BASS]

    # Heuristic for 5 parts -> SATB + Piano or SSATB (Solo + SATB)
    if parts_count == 5:
        is_5th_piano = (
            (staves_counts and len(staves_counts) >= 5 and staves_counts[4] >= 2)
            or (clef_signs and len(clef_signs) >= 5 and len(clef_signs[4]) >= 2 and set(clef_signs[4]) == {"G", "F"})
            or (part_names and len(part_names) >= 5 and resolve_voice_tag(part_names[4]) == TAG_PIANO)
        )

        if is_5th_piano:
            return [TAG_SOPRANO, TAG_ALTO, TAG_TENOR, TAG_BASS, TAG_PIANO]

        # Check if part 0 is explicitly Solo/Descant while parts 1..4 are Soprano, Alto, Tenor, Bass
        p0_tag = resolve_voice_tag(part_names[0]) if part_names and len(part_names) > 0 else None
        p1_tag = resolve_voice_tag(part_names[1]) if part_names and len(part_names) > 1 else None
        if p0_tag in (TAG_SOLO, TAG_DESCANT) or (p0_tag == TAG_SOPRANO and p1_tag == TAG_SOPRANO):
            return [TAG_SOLO, TAG_SOPRANO, TAG_ALTO, TAG_TENOR, TAG_BASS]

        # SSATB
        s1 = VoiceTagInfo("S1", "Soprano 1", "S1 - Soprano 1", "vocal", 53, "strings")
        s2 = VoiceTagInfo("S2", "Soprano 2", "S2 - Soprano 2", "vocal", 53, "strings")
        return [s1, s2, TAG_ALTO, TAG_TENOR, TAG_BASS]

    # Heuristic for 6 parts -> SSATBB or SATBarB + Piano / Solo + SATB + Piano
    if parts_count == 6:
        is_6th_piano = (
            (staves_counts and len(staves_counts) >= 6 and staves_counts[5] >= 2)
            or (clef_signs and len(clef_signs) >= 6 and len(clef_signs[5]) >= 2 and set(clef_signs[5]) == {"G", "F"})
            or (part_names and len(part_names) >= 6 and resolve_voice_tag(part_names[5]) == TAG_PIANO)
        )
        if is_6th_piano:
            p3_tag = resolve_voice_tag(part_names[3]) if part_names and len(part_names) > 3 else None
            p4_tag = resolve_voice_tag(part_names[4]) if part_names and len(part_names) > 4 else None
            p0_tag = resolve_voice_tag(part_names[0]) if part_names and len(part_names) > 0 else None
            if p3_tag == TAG_BARITONE or p4_tag == TAG_BARITONE:
                return [TAG_SOPRANO, TAG_ALTO, TAG_TENOR, TAG_BARITONE, TAG_BASS, TAG_PIANO]
            if p0_tag in (TAG_SOLO, TAG_DESCANT):
                return [TAG_SOLO, TAG_SOPRANO, TAG_ALTO, TAG_TENOR, TAG_BASS, TAG_PIANO]
            if clef_signs and len(clef_signs) >= 5:
                first_5_clefs = [c[0] if c else "" for c in clef_signs[:5]]
                if first_5_clefs == ["G", "G", "G", "F", "F"]:
                    return [TAG_SOPRANO, TAG_ALTO, TAG_TENOR, TAG_BARITONE, TAG_BASS, TAG_PIANO]
            s1 = VoiceTagInfo("S1", "Soprano 1", "S1 - Soprano 1", "vocal", 53, "strings")
            s2 = VoiceTagInfo("S2", "Soprano 2", "S2 - Soprano 2", "vocal", 53, "strings")
            return [s1, s2, TAG_ALTO, TAG_TENOR, TAG_BASS, TAG_PIANO]

        s1 = VoiceTagInfo("S1", "Soprano 1", "S1 - Soprano 1", "vocal", 53, "strings")
        s2 = VoiceTagInfo("S2", "Soprano 2", "S2 - Soprano 2", "vocal", 53, "strings")
        b1 = VoiceTagInfo("B1", "Bass 1", "B1 - Bass 1", "vocal", 53, "strings")
        b2 = VoiceTagInfo("B2", "Bass 2", "B2 - Bass 2", "vocal", 53, "strings")
        return [s1, s2, TAG_ALTO, TAG_TENOR, b1, b2]

    # Generic fallback
    return [
        VoiceTagInfo(f"P{i+1}", f"Part {i+1}", f"P{i+1} - Part {i+1}", "vocal", 53, "strings")
        for i in range(parts_count)
    ]


def autotag_musicxml_tree(root: ET.Element) -> int:
    """
    Enrich and autotag all <score-part> elements in a MusicXML document tree.
    Sets/standardizes:
      - <part-name>: Full name (e.g. "Soprano", "Alto", "Tenor", "Bass", "Piano")
      - <part-abbreviation>: Short tag (e.g. "S", "A", "T", "B", "Pno")
      - <score-instrument>: Instrument name
      - <midi-instrument>: Standard MIDI program (e.g. 1 for Piano, 53 for Choir)

    Returns:
        Number of score-parts updated.
    """
    score_parts = root.findall(".//part-list/score-part")
    if not score_parts:
        return 0

    parts_count = len(score_parts)

    # Inspect each part's staves and clefs to aid heuristic matching
    clef_signs_per_part: list[list[str]] = []
    staves_per_part: list[int] = []

    for sp in score_parts:
        pid = sp.get("id")
        part_elem = root.find(f".//part[@id='{pid}']")
        staves_count = 1
        clefs: list[str] = []

        if part_elem is not None:
            # Check staves
            staves_elem = part_elem.find(".//attributes/staves")
            if staves_elem is not None and staves_elem.text:
                try:
                    staves_count = int(staves_elem.text.strip())
                except ValueError:
                    staves_count = 1

            # Check clef signs
            for clef_elem in part_elem.findall(".//attributes/clef"):
                sign_elem = clef_elem.find("sign")
                if sign_elem is not None and sign_elem.text:
                    clefs.append(sign_elem.text.strip().upper())

        staves_per_part.append(staves_count)
        clef_signs_per_part.append(clefs)

    raw_part_names = [(sp.findtext("part-name") or "").strip() for sp in score_parts]

    heuristic_defaults = get_heuristic_voice_tags(
        parts_count,
        clef_signs=clef_signs_per_part,
        staves_counts=staves_per_part,
        part_names=raw_part_names,
    )

    updated_count = 0

    for idx, sp in enumerate(score_parts):
        curr_name_el = sp.find("part-name")
        curr_abbr_el = sp.find("part-abbreviation")

        curr_name_text = curr_name_el.text.strip() if curr_name_el is not None and curr_name_el.text else ""
        curr_abbr_text = curr_abbr_el.text.strip() if curr_abbr_el is not None and curr_abbr_el.text else ""

        # Check if already has a recognizable voice/instrument
        resolved_info = (
            resolve_voice_tag(curr_name_text)
            or resolve_voice_tag(curr_abbr_text)
        )

        pid = sp.get("id") or f"P{idx + 1}"
        part_elem = root.find(f".//part[@id='{pid}']")
        has_lyrics = len(part_elem.findall(".//lyric")) > 0 if part_elem is not None else False

        other_parts_have_vocal = any(
            (resolve_voice_tag(raw_part_names[o_idx]) and resolve_voice_tag(raw_part_names[o_idx]).family == "vocal")
            or (o_idx < len(heuristic_defaults) and heuristic_defaults[o_idx].family == "vocal")
            for o_idx in range(len(score_parts)) if o_idx != idx
        )

        curr_is_explicit_piano = (
            resolved_info == TAG_PIANO
            and bool(curr_name_text)
            and re.match(r"^(part\s*\d+|p\d+|music|staff\s*\d+|voice(\s*\d+)?)$", curr_name_text.lower().strip()) is None
        )

        # If name is generic (e.g. "Music", "Part 1", "P1", "Voice") or empty, use heuristic
        is_generic = (
            not curr_name_text
            or resolved_info == TAG_VOICE
            or (resolved_info == TAG_PIANO and not curr_is_explicit_piano and has_lyrics and not other_parts_have_vocal)
            or re.match(r"^(part\s*\d+|p\d+|music|staff\s*\d+|voice(\s*\d+)?)$", curr_name_text.lower().strip()) is not None
        )

        if not resolved_info or is_generic:
            if has_lyrics and not other_parts_have_vocal and (idx < len(staves_per_part) and staves_per_part[idx] >= 2):
                resolved_info = TAG_CHOIR
            elif idx < len(heuristic_defaults):
                resolved_info = heuristic_defaults[idx]
                if has_lyrics and resolved_info == TAG_PIANO and not other_parts_have_vocal:
                    resolved_info = TAG_CHOIR if (idx < len(staves_per_part) and staves_per_part[idx] >= 2) else TAG_VOICE

        if not resolved_info:
            continue

        # 1. Update <part-name>
        if curr_name_el is None:
            curr_name_el = ET.SubElement(sp, "part-name")
        curr_name_el.text = resolved_info.name

        # 2. Update <part-abbreviation>
        if curr_abbr_el is None:
            # Place <part-abbreviation> right after <part-name>
            insert_idx = list(sp).index(curr_name_el) + 1 if curr_name_el in list(sp) else len(list(sp))
            curr_abbr_el = ET.Element("part-abbreviation")
            sp.insert(insert_idx, curr_abbr_el)
        curr_abbr_el.text = resolved_info.tag

        # 3. Update or create <score-instrument>
        pid = sp.get("id") or f"P{idx + 1}"
        inst_id = f"{pid}-I1"
        score_inst = sp.find("score-instrument")
        if score_inst is None:
            score_inst = ET.SubElement(sp, "score-instrument", id=inst_id)
        inst_name = score_inst.find("instrument-name")
        if inst_name is None:
            inst_name = ET.SubElement(score_inst, "instrument-name")
        inst_name.text = resolved_info.name

        # 4. Update or create <midi-instrument>
        midi_inst = sp.find("midi-instrument")
        if midi_inst is None:
            midi_inst = ET.SubElement(sp, "midi-instrument", id=inst_id)
        midi_prog = midi_inst.find("midi-program")
        if midi_prog is None:
            midi_prog = ET.SubElement(midi_inst, "midi-program")
        midi_prog.text = str(resolved_info.midi_program)

        updated_count += 1

    return updated_count


def autotag_musicxml_file(xml_path: Path) -> int:
    """Parse, autotag, and write back a MusicXML file."""
    if not xml_path.exists():
        return 0
    try:
        tree = dET.parse(xml_path)
        root = tree.getroot()
        count = autotag_musicxml_tree(root)
        if count > 0:
            tree.write(xml_path, encoding="utf-8", xml_declaration=True)
            logger.info("Autotagged %d parts in %s", count, xml_path.name)
        return count
    except Exception as exc:
        logger.warning("Could not autotag MusicXML file %s: %s", xml_path, exc)
        return 0
