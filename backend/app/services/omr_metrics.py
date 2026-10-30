"""
Alignment-based accuracy metrics for comparing OMR output against ground-truth MusicXML.

Each part is reduced to a canonical sequence of note tokens (ordered by measure, staff,
onset and pitch, so voice numbering, chord order and <divisions> do not matter). The OMR
sequence is aligned to the ground truth with a weighted edit distance, and every metric is
derived from that single alignment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import numpy as np

from app.services.voice_autotagger import resolve_voice_tag

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET

_STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_REST = "rest"


@dataclass(frozen=True)
class NoteToken:
    measure: int
    staff: int
    onset: Fraction
    pitch: str  # e.g. "C#4", or "rest"
    midi: int  # -1 for rests
    duration: Fraction  # in quarter notes
    lyric: str

    @property
    def pitch_class(self) -> int:
        return self.midi % 12 if self.midi >= 0 else -1


@dataclass
class PartData:
    name: str
    tokens: list[NoteToken]
    measure_count: int
    fifths: str
    time_signature: str


@dataclass
class PartComparison:
    gt_name: str
    omr_name: str
    gt_tokens: int
    omr_tokens: int
    exact_matches: int
    pitch_correct: int
    rhythm_correct: int
    octave_errors: int
    edit_distance: int
    lyric_total: int
    lyric_correct: int
    name_match: bool
    gt_measures: int
    omr_measures: int


@dataclass
class ScoreComparison:
    note_precision: float
    note_recall: float
    note_f1: float
    pitch_accuracy: float
    rhythm_accuracy: float
    symbol_error_rate: float
    octave_errors: int
    lyric_accuracy: float
    lyric_total: int
    part_name_accuracy: float
    measure_count_match: bool
    key_match: bool
    time_match: bool
    gt_part_count: int
    omr_part_count: int
    parts: list[PartComparison] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compare_scores(gt_path: Path, omr_path: Path) -> ScoreComparison:
    """Compare an OMR MusicXML file against its ground truth and return aggregate metrics."""
    gt_parts = parse_parts(gt_path)
    omr_parts = parse_parts(omr_path)

    comparisons: list[PartComparison] = []
    for idx in range(max(len(gt_parts), len(omr_parts))):
        gt = gt_parts[idx] if idx < len(gt_parts) else None
        omr = omr_parts[idx] if idx < len(omr_parts) else None
        comparisons.append(_compare_part(gt, omr))

    gt_total = sum(c.gt_tokens for c in comparisons)
    omr_total = sum(c.omr_tokens for c in comparisons)
    exact = sum(c.exact_matches for c in comparisons)
    precision = _ratio(exact, omr_total)
    recall = _ratio(exact, gt_total)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    lyric_total = sum(c.lyric_total for c in comparisons)
    paired = [c for c in comparisons if c.gt_tokens or c.gt_name]

    return ScoreComparison(
        note_precision=precision,
        note_recall=recall,
        note_f1=f1,
        pitch_accuracy=_ratio(sum(c.pitch_correct for c in comparisons), gt_total),
        rhythm_accuracy=_ratio(sum(c.rhythm_correct for c in comparisons), gt_total),
        symbol_error_rate=_ratio(sum(c.edit_distance for c in comparisons), gt_total),
        octave_errors=sum(c.octave_errors for c in comparisons),
        lyric_accuracy=_ratio(sum(c.lyric_correct for c in comparisons), lyric_total) if lyric_total else 1.0,
        lyric_total=lyric_total,
        part_name_accuracy=_ratio(sum(c.name_match for c in paired), len(paired)),
        measure_count_match=all(c.gt_measures == c.omr_measures for c in paired),
        key_match=_first_attr_match(gt_parts, omr_parts, "fifths"),
        time_match=_first_attr_match(gt_parts, omr_parts, "time_signature"),
        gt_part_count=len(gt_parts),
        omr_part_count=len(omr_parts),
        parts=comparisons,
    )


def parse_parts(xml_path: Path) -> list[PartData]:
    """Parse a MusicXML file into canonical per-part token sequences."""
    root = dET.parse(xml_path).getroot()
    names = {sp.get("id"): (sp.findtext("part-name") or "").strip() for sp in root.iter("score-part")}
    return [_parse_part(part, names.get(part.get("id"), "")) for part in root.findall("part")]


def _parse_part(part: ET.Element, name: str) -> PartData:
    divisions = Fraction(1)
    fifths = "0"
    time_signature = "N/A"
    tokens: list[NoteToken] = []
    measures = part.findall("measure")

    for m_idx, measure in enumerate(measures):
        cursor = Fraction(0)
        last_onset = Fraction(0)
        for elem in measure:
            if elem.tag == "attributes":
                div = elem.findtext("divisions")
                if div and div.strip().isdigit() and int(div) > 0:
                    divisions = Fraction(int(div))
                key_fifths = elem.findtext("key/fifths")
                if key_fifths is not None and fifths == "0" and not tokens:
                    fifths = key_fifths.strip()
                beats, beat_type = elem.findtext("time/beats"), elem.findtext("time/beat-type")
                if beats and beat_type and time_signature == "N/A":
                    time_signature = f"{beats.strip()}/{beat_type.strip()}"
            elif elem.tag in ("backup", "forward"):
                delta = _duration(elem, divisions)
                cursor += -delta if elem.tag == "backup" else delta
            elif elem.tag == "note":
                if elem.find("grace") is not None:
                    continue
                duration = _duration(elem, divisions)
                onset = last_onset if elem.find("chord") is not None else cursor
                if elem.find("chord") is None:
                    last_onset = cursor
                    cursor += duration
                pitch, midi = _pitch(elem)
                staff_text = elem.findtext("staff")
                tokens.append(
                    NoteToken(
                        measure=m_idx,
                        staff=int(staff_text) if staff_text and staff_text.isdigit() else 1,
                        onset=onset,
                        pitch=pitch,
                        midi=midi,
                        duration=duration,
                        lyric=_lyric(elem),
                    )
                )

    tokens.sort(key=lambda t: (t.measure, t.staff, t.onset, t.midi))
    return PartData(name=name, tokens=tokens, measure_count=len(measures), fifths=fifths, time_signature=time_signature)


def _duration(elem: ET.Element, divisions: Fraction) -> Fraction:
    text = elem.findtext("duration")
    if not text or not text.strip().lstrip("-").isdigit():
        return Fraction(0)
    return Fraction(int(text.strip())) / divisions


def _pitch(note: ET.Element) -> tuple[str, int]:
    pitch = note.find("pitch")
    if pitch is None:
        return _REST, -1
    step = (pitch.findtext("step") or "C").strip().upper()
    octave = int((pitch.findtext("octave") or "4").strip())
    alter_text = pitch.findtext("alter")
    alter = int(round(float(alter_text))) if alter_text else 0
    accidental = {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}.get(alter, "")
    midi = 12 * (octave + 1) + _STEP_SEMITONES.get(step, 0) + alter
    return f"{step}{accidental}{octave}", midi


def _lyric(note: ET.Element) -> str:
    lyric = note.find("lyric")
    if lyric is None:
        return ""
    return normalise_lyric(lyric.findtext("text") or "")


def normalise_lyric(text: str) -> str:
    """Lower-case and strip punctuation so 'Glo-' and 'glo' compare equal."""
    return re.sub(r"[^\w']", "", text.lower().replace("’", "'"))


def _canonical_part_name(name: str) -> str:
    info = resolve_voice_tag(name)
    return info.name.lower() if info else name.strip().lower()


def _substitution_cost(a: NoteToken, b: NoteToken) -> float:
    if a.measure != b.measure and abs(a.measure - b.measure) > 1:
        return 1.5  # Discourage aligning notes from distant measures
    same_pitch = a.midi == b.midi
    same_rhythm = a.duration == b.duration
    if same_pitch and same_rhythm:
        return 0.0
    if same_pitch or same_rhythm:
        return 0.5
    return 1.0


def align_tokens(gt: list[NoteToken], omr: list[NoteToken]) -> list[tuple[int | None, int | None]]:
    """Weighted Levenshtein alignment. Returns (gt_index, omr_index) pairs; None marks a gap."""
    n, m = len(gt), len(omr)
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = float(i)
    for j in range(1, m + 1):
        cost[0][j] = float(j)
    for i in range(1, n + 1):
        row, prev, g = cost[i], cost[i - 1], gt[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j] + 1.0, row[j - 1] + 1.0, prev[j - 1] + _substitution_cost(g, omr[j - 1]))

    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + _substitution_cost(gt[i - 1], omr[j - 1]):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1.0:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def _compare_part(gt: PartData | None, omr: PartData | None) -> PartComparison:
    gt_tokens = gt.tokens if gt else []
    omr_tokens = omr.tokens if omr else []
    exact = pitch_ok = rhythm_ok = octave_err = edits = lyric_ok = 0

    for gi, oi in align_tokens(gt_tokens, omr_tokens):
        if gi is None or oi is None:
            edits += 1
            continue
        g, o = gt_tokens[gi], omr_tokens[oi]
        same_pitch = g.midi == o.midi
        same_rhythm = g.duration == o.duration
        pitch_ok += same_pitch
        rhythm_ok += same_rhythm
        if same_pitch and same_rhythm:
            exact += 1
        else:
            edits += 1
        if not same_pitch and g.midi >= 0 and o.midi >= 0 and g.pitch_class == o.pitch_class:
            octave_err += 1
        if g.lyric and g.lyric == o.lyric:
            lyric_ok += 1

    gt_name = gt.name if gt else ""
    omr_name = omr.name if omr else ""
    return PartComparison(
        gt_name=gt_name,
        omr_name=omr_name,
        gt_tokens=len(gt_tokens),
        omr_tokens=len(omr_tokens),
        exact_matches=exact,
        pitch_correct=pitch_ok,
        rhythm_correct=rhythm_ok,
        octave_errors=octave_err,
        edit_distance=edits,
        lyric_total=sum(1 for t in gt_tokens if t.lyric),
        lyric_correct=lyric_ok,
        name_match=bool(gt and omr) and _canonical_part_name(gt_name) == _canonical_part_name(omr_name),
        gt_measures=gt.measure_count if gt else 0,
        omr_measures=omr.measure_count if omr else 0,
    )


def _first_attr_match(gt_parts: list[PartData], omr_parts: list[PartData], attr: str) -> bool:
    if not gt_parts:
        return True
    if not omr_parts:
        return False
    return bool(getattr(gt_parts[0], attr) == getattr(omr_parts[0], attr))


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0
