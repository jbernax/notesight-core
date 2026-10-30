import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


@dataclass
class RhythmValidationIssue:
    measure_number: int
    time_signature: str
    expected_beats: float
    actual_beats: float
    discrepancy_beats: float
    status: str  # "underfilled" | "overfilled"
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_musicxml_rhythms(xml_source: str | Path) -> list[RhythmValidationIssue]:
    """
    Validate measure rhythmic arithmetic across a MusicXML score.

    Calculates expected measure duration based on current time signature and divisions,
    taking into account chords, grace notes, tuplets, multi-voice backups, and anacrusis
    (pickup measures).

    Args:
        xml_source: MusicXML string content or Path to a .musicxml/.xml file.

    Returns:
        List of RhythmValidationIssue for measures with arithmetic discrepancies.
    """
    issues: list[RhythmValidationIssue] = []

    try:
        if isinstance(xml_source, Path) or (isinstance(xml_source, str) and not xml_source.strip().startswith("<")):
            path = Path(xml_source)
            if not path.exists():
                logger.warning("Rhythm validation skipped: file not found: %s", path)
                return []
            tree = ET.parse(path)
            root = tree.getroot()
        else:
            root = ET.fromstring(xml_source.strip())
    except Exception as exc:
        logger.warning("Failed to parse MusicXML for rhythm validation: %s", exc)
        return []

    parts = root.findall(".//part")
    if not parts:
        return []

    for part in parts:
        current_divisions = 1
        current_beats = 4
        current_beat_type = 4

        measures = part.findall("measure")
        for m_idx, measure in enumerate(measures):
            m_number_raw = measure.get("number", str(m_idx + 1))
            try:
                m_number = int(m_number_raw)
            except ValueError:
                m_number = m_idx + 1

            # 1. Update active divisions and time signature if defined in any attributes block
            for attr_elem in measure.findall("attributes"):
                div_el = attr_elem.find("divisions")
                if div_el is not None and div_el.text and div_el.text.strip().isdigit():
                    div_val = int(div_el.text.strip())
                    if div_val > 0:
                        current_divisions = div_val

                time_el = attr_elem.find("time")
                if time_el is not None:
                    beats_el = time_el.find("beats")
                    beat_type_el = time_el.find("beat-type")
                    if beats_el is not None and beats_el.text and beats_el.text.strip().isdigit():
                        current_beats = int(beats_el.text.strip())
                    if beat_type_el is not None and beat_type_el.text and beat_type_el.text.strip().isdigit():
                        current_beat_type = int(beat_type_el.text.strip())

            # Expected duration calculation
            # In MusicXML: 1 quarter note = current_divisions
            # One beat of beat-type T = (4.0 / T) * current_divisions
            quarter_factor = 4.0 / current_beat_type
            expected_divisions = current_beats * quarter_factor * current_divisions
            expected_beats = round(current_beats * quarter_factor, 2)
            time_sig_str = f"{current_beats}/{current_beat_type}"

            # 2. Track voice duration in this measure
            voice_durations: dict[str, int] = {}

            for elem in list(measure):
                if elem.tag == "note":
                    # Ignore grace notes (duration=0) and chord notes (simultaneous with base note)
                    if elem.find("grace") is not None:
                        continue
                    if elem.find("chord") is not None:
                        continue

                    voice_el = elem.find("voice")
                    voice_id = voice_el.text.strip() if (voice_el is not None and voice_el.text) else "1"

                    dur_el = elem.find("duration")
                    dur_val = 0
                    if dur_el is not None and dur_el.text and dur_el.text.strip().isdigit():
                        dur_val = int(dur_el.text.strip())

                    voice_durations[voice_id] = voice_durations.get(voice_id, 0) + dur_val

                elif elem.tag == "forward":
                    dur_el = elem.find("duration")
                    voice_el = elem.find("voice")
                    voice_id = voice_el.text.strip() if (voice_el is not None and voice_el.text) else "1"
                    if dur_el is not None and dur_el.text and dur_el.text.strip().isdigit():
                        dur_val = int(dur_el.text.strip())
                        voice_durations[voice_id] = voice_durations.get(voice_id, 0) + dur_val

            if not voice_durations:
                continue

            # Pick the primary voice or the maximum voice duration
            actual_divisions = max(voice_durations.values())
            actual_beats = round(actual_divisions / (quarter_factor * current_divisions), 2)
            diff_divisions = actual_divisions - expected_divisions

            # Check if this is an intentional pickup measure (anacrusis)
            is_implicit = measure.get("implicit", "").lower() == "yes"
            is_pickup_candidate = (m_idx == 0 or m_number in (0, 1)) and actual_divisions < expected_divisions

            if is_implicit or (m_idx == 0 and is_pickup_candidate):
                # Valid anacrusis, not a defect
                continue

            # Tolerance of 0.05 beat to account for rounding divisions
            tolerance_divisions = 0.05 * current_divisions
            if abs(diff_divisions) > tolerance_divisions:
                discrepancy_beats = round(diff_divisions / (quarter_factor * current_divisions), 2)
                status = "overfilled" if diff_divisions > 0 else "underfilled"
                if status == "overfilled":
                    msg = (
                        f"Measure {m_number}: found {actual_beats} beats in {time_sig_str} "
                        f"(exceeds by {abs(discrepancy_beats)} beat)"
                    )
                else:
                    msg = (
                        f"Measure {m_number}: found {actual_beats} beats in {time_sig_str} "
                        f"(missing {abs(discrepancy_beats)} beat)"
                    )

                issues.append(
                    RhythmValidationIssue(
                        measure_number=m_number,
                        time_signature=time_sig_str,
                        expected_beats=expected_beats,
                        actual_beats=actual_beats,
                        discrepancy_beats=discrepancy_beats,
                        status=status,
                        message=msg,
                    )
                )

    return issues


def validate_musicxml_rhythms_dict(xml_source: str | Path) -> list[dict[str, Any]]:
    """Helper returning list of serializable dicts."""
    return [issue.to_dict() for issue in validate_musicxml_rhythms(xml_source)]
