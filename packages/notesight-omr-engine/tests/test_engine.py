from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import numpy as np
import pytest

from notesight_omr_engine import __version__
from notesight_omr_engine.cli import main as cli_main
from notesight_omr_engine.patches import (
    apply_homr_safety_patches,
    safe_calculate_region,
    safe_get_tr_omr_canvas_size,
)
from notesight_omr_engine.runner import transcribe_image


def test_package_has_zero_proprietary_backend_imports() -> None:
    """Verify no module in notesight_omr_engine imports anything from NoteSight's app package."""
    pkg_root = Path(__file__).resolve().parents[1] / "src" / "notesight_omr_engine"
    py_files = list(pkg_root.glob("*.py"))
    assert len(py_files) >= 4

    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app."), f"Forbidden import {alias.name} in {py_file}"
                    assert alias.name != "app", f"Forbidden import {alias.name} in {py_file}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app."), f"Forbidden import {node.module} in {py_file}"
                assert node.module != "app", f"Forbidden import {node.module} in {py_file}"


def test_safe_calculate_region_handles_inverted_bounds() -> None:
    """Ensure safe_calculate_region never returns inverted y_max <= y_min or x_max <= x_min."""
    fake_staff = SimpleNamespace(
        min_x=100.0,
        max_x=90.0,  # inverted x
        min_y=200.0,
        max_y=210.0,
        average_unit_size=5.0,
    )
    fake_regions = SimpleNamespace(
        get_start_of_closest_staff_above=lambda y: 250.0,  # forces y_min > y_max before guard
        get_start_of_closest_staff_below=lambda y: 180.0,
    )

    coords = safe_calculate_region(fake_staff, fake_regions)
    assert coords.shape == (4,)
    x_min, y_min, x_max, y_max = coords
    assert x_max > x_min
    assert y_max > y_min


def test_safe_get_tr_omr_canvas_size_handles_zero_dimensions() -> None:
    """Ensure zero-height or zero-width image slices never produce 0-pixel resize targets."""
    size_zero_h = safe_get_tr_omr_canvas_size((0, 500, 3))
    assert size_zero_h[0] >= 1
    assert size_zero_h[1] >= 1

    size_zero_w = safe_get_tr_omr_canvas_size((120, 0, 3))
    assert size_zero_w[0] >= 1
    assert size_zero_w[1] >= 1


def test_apply_homr_safety_patches_is_idempotent() -> None:
    """Verify runtime patching of homr.staff_parsing succeeds and is idempotent."""
    assert apply_homr_safety_patches() is True
    assert apply_homr_safety_patches() is True


def test_transcribe_image_writes_layout_json_and_filters_narrow_staffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify transcribe_image captures staff layout coordinates and filters narrow ossia fragments."""
    import homr.main as homr_main
    import homr.staff_detection as staff_detection
    import homr.staff_parsing as staff_parsing

    full_img = np.zeros((1000, 800, 3), dtype=np.uint8)
    # Simulate autocrop slicing [y: 50..950, x: 40..740]
    cropped_img = full_img[50:950, 40:740]

    wide_staff_1 = SimpleNamespace(min_x=10, max_x=650, min_y=100, max_y=150, is_grandstaff=False)
    wide_staff_2 = SimpleNamespace(min_x=10, max_x=650, min_y=250, max_y=300, is_grandstaff=True)
    narrow_fragment = SimpleNamespace(min_x=10, max_x=80, min_y=400, max_y=420, is_grandstaff=False)

    monkeypatch.setattr(homr_main, "autocrop", lambda img: cropped_img)
    monkeypatch.setattr(
        staff_detection,
        "detect_staff",
        lambda *args, **kwargs: [wide_staff_1, wide_staff_2, narrow_fragment],
    )
    monkeypatch.setattr(
        staff_parsing,
        "_ensure_same_number_of_staffs",
        lambda staffs, image: [SimpleNamespace(staffs=staffs)],
    )
    monkeypatch.setattr(homr_main, "parse_staffs", lambda debug, staffs, image, *a, **kw: [])

    def fake_process_image(image_path_str: str, config: Any, xml_args: Any) -> None:
        cropped = homr_main.autocrop(full_img)
        detected = homr_main.detect_staff(cropped)
        homr_main.parse_staffs(False, detected, cropped)
        Path(image_path_str).with_suffix(".musicxml").write_text("<score-partwise/>", encoding="utf-8")

    monkeypatch.setattr(homr_main, "process_image", fake_process_image)

    img_file = tmp_path / "page_1.png"
    img_file.write_bytes(b"fake_png")

    xml_out = transcribe_image(img_file, filter_narrow_staffs=True)
    assert xml_out == img_file.with_suffix(".musicxml")
    assert xml_out.exists()

    layout_file = img_file.with_suffix(".layout.json")
    assert layout_file.exists()
    layout_data = json.loads(layout_file.read_text(encoding="utf-8"))
    assert "systems" in layout_data
    assert len(layout_data["systems"]) == 1
    staves = layout_data["systems"][0]["staves"]
    # The narrow fragment (width 70 < 0.4 * 640) must have been filtered out
    assert len(staves) == 2
    assert staves[0]["part"] == 0
    assert staves[0]["min_x"] == pytest.approx(40.0 + 10.0)
    assert staves[0]["min_y"] == pytest.approx(50.0 + 100.0)
    assert staves[1]["part"] == 1
    assert staves[1]["is_grandstaff"] is True


def test_cli_version_and_transcribe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CLI entrypoint supports --version and image transcription."""
    assert isinstance(__version__, str) and len(__version__) > 0
    assert cli_main(["--version"]) == 0

    img_file = tmp_path / "score.png"
    img_file.write_bytes(b"fake")

    called_with: list[tuple[Path, bool]] = []

    def fake_transcribe(path: Path, filter_narrow_staffs: bool = False) -> Path:
        called_with.append((path, filter_narrow_staffs))
        out = path.with_suffix(".musicxml")
        out.write_text("<score-partwise/>", encoding="utf-8")
        path.with_suffix(".layout.json").write_text('{"systems": []}', encoding="utf-8")
        return out

    monkeypatch.setattr("notesight_omr_engine.cli.transcribe_image", fake_transcribe)
    rc = cli_main(["--filter-narrow-staffs", str(img_file)])
    assert rc == 0
    assert called_with == [(img_file, True)]


def test_smart_select_grandstaffs_preserves_5_staff_solo_plus_satb() -> None:
    """Verify 5-staff Solo + SATB systems with a Soprano sub-bracket on [0, 1] and 4-staff SATB bracket do not merge [0, 1]."""
    from notesight_omr_engine.patches import smart_select_grandstaffs

    staffs = [
        SimpleNamespace(min_x=170.0, max_x=1750.0, min_y=189.0, max_y=260.0, average_unit_size=14.5),
        SimpleNamespace(min_x=170.0, max_x=1750.0, min_y=422.0, max_y=498.0, average_unit_size=14.5),
        SimpleNamespace(min_x=170.0, max_x=1750.0, min_y=627.0, max_y=703.0, average_unit_size=14.5),
        SimpleNamespace(min_x=170.0, max_x=1750.0, min_y=833.0, max_y=907.0, average_unit_size=14.5),
        SimpleNamespace(min_x=170.0, max_x=1750.0, min_y=1040.0, max_y=1114.0, average_unit_size=14.5),
    ]
    braces = [
        SimpleNamespace(center=(145.5, 342.5), size=(9.0, 325.0)),   # [S1, S2] sub-bracket on [0, 1]
        SimpleNamespace(center=(158.0, 768.0), size=(10.0, 740.0)),  # 4-staff SATB bracket on [1..4]
        SimpleNamespace(center=(171.5, 651.5), size=(5.0, 941.0)),   # 5-staff left barline on [0..4]
    ]

    class FakeMultiStaff:
        class GrandStaffPair:
            def __init__(self, idx: list[int], score: float) -> None:
                self.idx = idx
                self.score = score

            def get_score(self) -> float:
                return self.score

            def get_index(self) -> list[int]:
                return self.idx

        def __init__(self) -> None:
            self.staffs = staffs

        def _score_brace_with_staff_pair(self, sym: Any, upper: Any, lower: Any) -> float:
            sym_min_y = sym.center[1] - sym.size[1] / 2.0
            sym_max_y = sym.center[1] + sym.size[1] / 2.0
            overlap = min(sym_max_y, lower.max_y) - max(sym_min_y, upper.min_y)
            return max(0.0, overlap - 20.0) if overlap > sym.size[1] * 0.5 else 0.0

    ms = FakeMultiStaff()
    pairs = smart_select_grandstaffs(ms, braces)
    assert pairs == []


def test_safe_build_repeat_sets_left_and_right_locations_with_bar_style() -> None:
    """Verify safe_build_repeat emits forward repeat on left barline with heavy-light and backward on right with light-heavy."""
    import musicxml.xmlelement.xmlelement as mxl
    from homr.transformer.vocabulary import EncodedSymbol
    from notesight_omr_engine.patches import safe_build_repeat

    fwd_barline = mxl.XMLBarline(location="right")
    safe_build_repeat(EncodedSymbol("repeatStart"), fwd_barline)
    assert fwd_barline.location == "left"
    fwd_xml = fwd_barline.to_string()
    assert 'location="left"' in fwd_xml
    assert "<bar-style>heavy-light</bar-style>" in fwd_xml
    assert '<repeat direction="forward"' in fwd_xml

    bwd_barline = mxl.XMLBarline(location="right")
    safe_build_repeat(EncodedSymbol("repeatEnd"), bwd_barline)
    assert bwd_barline.location == "right"
    bwd_xml = bwd_barline.to_string()
    assert 'location="right"' in bwd_xml
    assert "<bar-style>light-heavy</bar-style>" in bwd_xml
    assert '<repeat direction="backward"' in bwd_xml


def test_sanitize_courtesy_signature_tokens_removes_trailing_notes() -> None:
    """Verify sanitize_courtesy_signature_tokens strips hallucinated notes after courtesy signature before newline."""
    from homr.transformer.vocabulary import EncodedSymbol
    from notesight_omr_engine.patches import sanitize_courtesy_signature_tokens

    voice_with_ghost = [
        EncodedSymbol("clef_G2"),
        EncodedSymbol("note_4 C4"),
        EncodedSymbol("doublebarline"),
        EncodedSymbol("keySignature_4"),
        EncodedSymbol("note_4. B3"),
        EncodedSymbol("barline"),
        EncodedSymbol("newline"),
        EncodedSymbol("note_4 G4"),
        EncodedSymbol("barline"),
        EncodedSymbol("newline"),
    ]

    removed = sanitize_courtesy_signature_tokens([voice_with_ghost])
    assert removed == 2
    rhythms = [s.rhythm for s in voice_with_ghost]
    assert rhythms == [
        "clef_G2",
        "note_4 C4",
        "doublebarline",
        "keySignature_4",
        "newline",
        "note_4 G4",
        "barline",
        "newline",
    ]


def test_sanitize_courtesy_signature_tokens_leaves_normal_signatures_untouched() -> None:
    """Ensure mid-measure or line-initial key/time signatures followed by music are preserved."""
    from homr.transformer.vocabulary import EncodedSymbol
    from notesight_omr_engine.patches import sanitize_courtesy_signature_tokens

    normal_voice = [
        EncodedSymbol("clef_G2"),
        EncodedSymbol("keySignature_1"),
        EncodedSymbol("note_4 C4"),
        EncodedSymbol("barline"),
        EncodedSymbol("note_4 D4"),
        EncodedSymbol("barline"),
        EncodedSymbol("newline"),
    ]

    removed = sanitize_courtesy_signature_tokens([normal_voice])
    assert removed == 0
    assert len(normal_voice) == 7


