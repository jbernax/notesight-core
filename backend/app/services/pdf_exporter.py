import io
import logging
import os
from pathlib import Path
try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET
import cairosvg
import pypdf
import verovio

from app.services.musicxml_sanitizer import sanitize_musicxml_tree

logger = logging.getLogger(__name__)

# Ensure Verovio resource path points to its bundled font resources (Bravura, Leipzig)
_verovio_data = os.path.join(os.path.dirname(verovio.__file__), "data")
if os.path.exists(_verovio_data):
    verovio.setDefaultResourcePath(_verovio_data)


def export_musicxml_to_pdf(
    musicxml_input: Path | str,
    output_pdf_path: Path,
    page_width: int = 2100,
    page_height: int = 2970,
    scale: int = 40,
) -> Path:
    """
    Engrave and convert MusicXML content into a standardized multi-page vector PDF.

    Args:
        musicxml_input: File path or raw XML string containing MusicXML.
        output_pdf_path: Path where the resulting PDF will be saved.
        page_width: Page width in tenths of millimeters (default 2100 for A4 width).
        page_height: Page height in tenths of millimeters (default 2970 for A4 height).
        scale: Engraving scale percentage.

    Returns:
        Path to the generated PDF document.
    """
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    tk = verovio.toolkit()
    if os.path.exists(_verovio_data):
        tk.setResourcePath(_verovio_data)

    tk.setOptions({
        "inputFrom": "musicxml",
        "pageWidth": page_width,
        "pageHeight": page_height,
        "scale": scale,
        "adjustPageHeight": 0,
        "breaks": "auto",
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
        raise ValueError(f"Failed to parse MusicXML data for PDF export: {exc}") from exc

    if not loaded:
        raise ValueError("Failed to parse MusicXML data for PDF export.")

    page_count = tk.getPageCount()
    if page_count < 1:
        raise ValueError("No notation pages generated from MusicXML.")

    writer = pypdf.PdfWriter()
    for page_idx in range(1, page_count + 1):
        svg_content = tk.renderToSVG(page_idx)
        page_pdf_bytes = cairosvg.svg2pdf(bytestring=svg_content.encode("utf-8"), unsafe=False)
        if not isinstance(page_pdf_bytes, bytes):
            raise ValueError("Failed to convert SVG page to PDF bytes.")
        reader = pypdf.PdfReader(io.BytesIO(page_pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    with open(output_pdf_path, "wb") as out_f:
        writer.write(out_f)

    logger.info("Successfully exported MusicXML to PDF (%d pages): %s", page_count, output_pdf_path)
    return output_pdf_path

