from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

from app.config import settings
from app.services.score_layout import PageLayout

logger = logging.getLogger(__name__)


def get_omr_engine_bin() -> str:
    """Find the standalone notesight-omr executable in the current Python virtual environment or PATH."""
    venv_bin = Path(sys.executable).parent / "notesight-omr"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("notesight-omr")
    if found:
        return found
    return "notesight-omr"


# Backward-compatible alias
get_homr_bin = get_omr_engine_bin

# Fallback minimal MusicXML used if OMR_MOCK_INFERENCE / HOMR_MOCK_INFERENCE is set in testing
MOCK_MUSICXML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1">
      <part-name>Music</part-name>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
  </part>
</score-partwise>
"""


@dataclass(frozen=True)
class PageRecognition(os.PathLike[str]):
    """Result of OMR on one page: the MusicXML file and the staff layout it was read from."""

    xml_path: Path
    layout: PageLayout = field(default_factory=PageLayout)

    def __fspath__(self) -> str:
        return str(self.xml_path)

    def __str__(self) -> str:
        return str(self.xml_path)

    @property
    def name(self) -> str:
        return self.xml_path.name

    def exists(self) -> bool:
        return self.xml_path.exists()


def recognize_page(image_path: Path) -> PageRecognition:
    """
    Run Optical Music Recognition on a single page image via the standalone notesight-omr CLI.

    Args:
        image_path: Path to the input page image.

    Returns:
        PageRecognition with the generated .musicxml path and the detected staff layout.
    """
    expected_output = image_path.with_suffix(".musicxml")

    # If running in test mode with mock inference requested
    mock_flag = os.getenv("OMR_MOCK_INFERENCE", os.getenv("HOMR_MOCK_INFERENCE", "false")).lower()
    if mock_flag in ("1", "true"):
        expected_output.write_text(MOCK_MUSICXML_TEMPLATE, encoding="utf-8")
        return PageRecognition(xml_path=expected_output)

    logger.info("Starting OMR inference via standalone notesight-omr on: %s", image_path)

    # Execute standalone notesight-omr CLI in an isolated subprocess with bounded execution timeout
    cmd = [get_omr_engine_bin(), str(image_path)]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["ONNXRUNTIME_DISABLE_THREAD_AFFINITY"] = "1"
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.OMR_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("OMR inference timed out on %s after %ds", image_path, settings.OMR_TIMEOUT_SECONDS)
        raise TimeoutError(f"OMR inference timed out after {settings.OMR_TIMEOUT_SECONDS} seconds") from exc

    if result.returncode != 0:
        logger.error("OMR inference failed on %s: %s", image_path, result.stderr)
        raise RuntimeError(f"homr inference failed: {result.stderr.strip()}")

    if not expected_output.exists():
        raise FileNotFoundError(f"Expected OMR output file not found: {expected_output}")

    layout = PageLayout.load(image_path.with_suffix(".layout.json"))
    logger.info("Successfully generated MusicXML: %s (%d systems)", expected_output, len(layout.systems))
    return PageRecognition(xml_path=expected_output, layout=layout)

