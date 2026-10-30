import base64
import logging
import os
from pathlib import Path
try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET
import verovio

from app.services.musicxml_sanitizer import sanitize_musicxml_tree

logger = logging.getLogger(__name__)

# Ensure Verovio resource path points to its bundled font resources if available
_verovio_data = os.path.join(os.path.dirname(verovio.__file__), "data")
if os.path.exists(_verovio_data):
    verovio.setDefaultResourcePath(_verovio_data)


def musicxml_to_midi_bytes(musicxml_input: Path | str) -> bytes:
    """
    Render MusicXML content into raw Standard MIDI File (SMF) bytes.

    Args:
        musicxml_input: File path or raw XML string containing MusicXML.

    Returns:
        Raw bytes representing a Standard MIDI File (starting with b'MThd').
    """
    tk = verovio.toolkit()
    if os.path.exists(_verovio_data):
        tk.setResourcePath(_verovio_data)

    tk.setOptions({
        "inputFrom": "musicxml",
    })

    # Validate and sanitize MusicXML before passing to Verovio to prevent C++ segfaults
    try:
        if isinstance(musicxml_input, Path):
            if not musicxml_input.exists():
                raise FileNotFoundError(f"MusicXML file not found: {musicxml_input}")
            tree = ET.parse(musicxml_input)
            sanitize_musicxml_tree(tree.getroot())
            xml_str = ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True).decode("utf-8")
            loaded = tk.loadData(xml_str)
        else:
            root = ET.fromstring(musicxml_input)
            sanitize_musicxml_tree(root)
            xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
            loaded = tk.loadData(xml_str)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse MusicXML data for MIDI export: {exc}") from exc

    if not loaded:
        raise ValueError("Failed to load MusicXML data for MIDI export into Verovio.")

    b64_midi = tk.renderToMIDI()
    if not b64_midi:
        raise ValueError("Verovio produced empty MIDI data for the provided score.")

    midi_bytes = base64.b64decode(b64_midi)
    if not midi_bytes.startswith(b"MThd"):
        raise ValueError("Generated MIDI data is missing valid MIDI file header.")

    return midi_bytes


def export_musicxml_to_midi(
    musicxml_input: Path | str,
    output_midi_path: Path,
) -> Path:
    """
    Render and export MusicXML content to a Standard MIDI File on disk.

    Args:
        musicxml_input: File path or raw XML string containing MusicXML.
        output_midi_path: Path where the resulting .mid file will be saved.

    Returns:
        Path to the saved MIDI document.
    """
    output_midi_path.parent.mkdir(parents=True, exist_ok=True)
    midi_bytes = musicxml_to_midi_bytes(musicxml_input)

    with open(output_midi_path, "wb") as f:
        f.write(midi_bytes)

    logger.info("Successfully exported MusicXML to MIDI (%d bytes): %s", len(midi_bytes), output_midi_path)
    return output_midi_path
