import copy
import shutil
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = None

from app.services.page_text import sanitize_xml_string


def _parse_xml(path: Path) -> Any:
    parser = dET if dET is not None else ET
    try:
        return parser.parse(str(path))
    except (ET.ParseError, Exception) as exc:
        raw_text = Path(path).read_text(encoding="utf-8", errors="replace")
        sanitized_text = sanitize_xml_string(raw_text)
        if sanitized_text != raw_text:
            Path(path).write_text(sanitized_text, encoding="utf-8")
            return parser.parse(str(path))
        raise


from app.services.musicxml_sanitizer import sanitize_musicxml_tree
from app.services.score_consistency import (
    align_system_break_measures,
    remove_empty_ghost_measures,
    repair_score_consistency,
)
from app.services.voice_autotagger import autotag_musicxml_tree


def _extract_active_attributes(part: ET.Element) -> tuple[int, int, int, ET.Element | None]:
    """Find current divisions, beats, beat-type, and attributes template from a part."""
    div = 8
    beats = 4
    beat_type = 4
    attr_template = None
    for m in part.findall("measure"):
        attr = m.find("attributes")
        if attr is not None:
            if attr_template is None:
                attr_template = attr
            div_t = attr.findtext("divisions")
            if div_t and div_t.isdigit():
                div = int(div_t)
            b_t = attr.findtext("time/beats")
            bt_t = attr.findtext("time/beat-type")
            if b_t and b_t.isdigit() and bt_t and bt_t.isdigit():
                beats = int(b_t)
                beat_type = int(bt_t)
    return div, beats, beat_type, attr_template


def _create_padded_measure(
    parent_part: ET.Element,
    measure_num: int,
    divisions: int = 8,
    beats: int = 4,
    beat_type: int = 4,
    attributes_elem: ET.Element | None = None,
) -> ET.Element:
    """Create a fully compliant whole-measure rest note with attributes, duration, voice, and type."""
    pad_m = ET.SubElement(parent_part, "measure", number=str(measure_num))
    if attributes_elem is not None:
        pad_m.append(copy.deepcopy(attributes_elem))
    note_elem = ET.SubElement(pad_m, "note")
    ET.SubElement(note_elem, "rest", measure="yes")
    meas_dur = int(divisions * 4 * beats / max(1, beat_type))
    dur_elem = ET.SubElement(note_elem, "duration")
    dur_elem.text = str(max(1, meas_dur))
    voice_elem = ET.SubElement(note_elem, "voice")
    voice_elem.text = "1"
    type_elem = ET.SubElement(note_elem, "type")
    type_elem.text = "whole"
    return pad_m


def inject_score_metadata(root: ET.Element, metadata: dict[str, str] | None) -> None:
    """Inject title, composer, arranger, and voicing metadata into MusicXML root."""
    if not metadata:
        return

    title = metadata.get("title")
    composer = metadata.get("composer")
    arranger = metadata.get("arranger")

    if title:
        work = root.find("work")
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        work_title = work.find("work-title")
        if work_title is None:
            work_title = ET.SubElement(work, "work-title")
        work_title.text = title

        mov_title = root.find("movement-title")
        if mov_title is not None:
            mov_title.text = title

    if composer or arranger:
        ident = root.find("identification")
        if ident is None:
            ident = ET.Element("identification")
            insert_idx = 1 if root.find("work") is not None else 0
            root.insert(insert_idx, ident)

        if composer:
            comp_elem = ident.find("creator[@type='composer']")
            if comp_elem is None:
                comp_elem = ET.SubElement(ident, "creator", type="composer")
            comp_elem.text = composer

        if arranger:
            arr_elem = ident.find("creator[@type='arranger']")
            if arr_elem is None:
                arr_elem = ET.SubElement(ident, "creator", type="arranger")
            arr_elem.text = arranger


def _extract_part_signature(part: ET.Element) -> tuple[int, tuple[str, ...]]:
    """Extract (staves_count, unique_clefs_tuple) for structural part alignment across pages."""
    staves_text = part.findtext(".//attributes/staves", "1")
    try:
        staves = int(staves_text.strip())
    except Exception:
        staves = 1
    raw_clefs = [
        c.findtext("sign", "").strip().upper()
        for c in part.findall(".//attributes/clef")
        if c.findtext("sign")
    ]
    # Deduplicate consecutive identical clefs unless this is a multi-staff part
    clefs: tuple[str, ...]
    if staves == 1 and raw_clefs:
        clefs = (raw_clefs[0],)
    else:
        seen: list[str] = []
        for c in raw_clefs:
            if not seen or c != seen[-1] or len(seen) < staves:
                seen.append(c)
        clefs = tuple(seen[: max(1, staves)])
    return (staves, clefs)


def _align_page_parts(
    base_parts: list[ET.Element],
    next_parts: list[ET.Element],
    base_root: ET.Element | None = None,
    next_root: ET.Element | None = None,
) -> dict[int, ET.Element | None]:
    """
    Map each index in next_parts to its corresponding base_part in base_parts,
    or None if next_parts[idx] is a newly entering part.
    """
    base_sigs = [_extract_part_signature(bp) for bp in base_parts]
    next_sigs = [_extract_part_signature(np) for np in next_parts]

    if len(base_parts) == len(next_parts) and base_sigs == next_sigs:
        return {i: base_parts[i] for i in range(len(next_parts))}

    # Special case: Next page introduces 1 or more upper Solo/Descant staves above an existing ensemble
    # (e.g., Page 1 has 4 staves [S, A, T, B] with clefs [G, G, G, F] and Page 6 has 5 staves [Solo, S, A, T, B]
    # with clefs [G, G, G, G, F]). Suffix alignment matches next_parts[offset:] -> base_parts[0..N].
    if len(next_parts) > len(base_parts):
        offset = len(next_parts) - len(base_parts)
        if next_sigs[offset:] == base_sigs:
            mapping_suffix: dict[int, ET.Element | None] = {}
            for i in range(offset):
                mapping_suffix[i] = None
            for i in range(len(base_parts)):
                mapping_suffix[offset + i] = base_parts[i]
            return mapping_suffix

    # Special case: Previous page had an upper Solo/Descant staff that drops out on the next page
    if len(base_parts) > len(next_parts):
        offset = len(base_parts) - len(next_parts)
        if base_sigs[offset:] == next_sigs:
            return {i: base_parts[offset + i] for i in range(len(next_parts))}

    mapping: dict[int, ET.Element | None] = {}
    used_base: set[int] = set()

    base_tags: list[str | None] = []
    next_tags: list[str | None] = []

    # Pass 0: Match by canonical voice tag when both roots have explicit non-generic part-names
    if base_root is not None and next_root is not None:
        from app.services.voice_autotagger import resolve_voice_tag, TAG_VOICE, TAG_PIANO
        for bp in base_parts:
            bid = bp.get("id")
            bsp = base_root.find(f".//score-part[@id='{bid}']") if bid else None
            bname = (bsp.findtext("part-name") or "").strip() if bsp is not None else ""
            btag = resolve_voice_tag(bname)
            base_tags.append(btag.tag if btag and btag not in (TAG_VOICE, TAG_PIANO) else None)

        for np in next_parts:
            nid = np.get("id")
            nsp = next_root.find(f".//score-part[@id='{nid}']") if nid else None
            nname = (nsp.findtext("part-name") or "").strip() if nsp is not None else ""
            ntag = resolve_voice_tag(nname)
            next_tags.append(ntag.tag if ntag and ntag not in (TAG_VOICE, TAG_PIANO) else None)

        # Match from bottom to top so choral bass/tenor/alto/soprano anchor before upper solo
        for np_idx in range(len(next_parts) - 1, -1, -1):
            nt_tag = next_tags[np_idx]
            if not nt_tag:
                continue
            for bp_idx in range(len(base_parts) - 1, -1, -1):
                if bp_idx not in used_base and base_tags[bp_idx] == nt_tag and next_sigs[np_idx] == base_sigs[bp_idx]:
                    mapping[np_idx] = base_parts[bp_idx]
                    used_base.add(bp_idx)
                    break

    # Pass 1: exact signature match (staves count and clefs)
    for np_idx, np in enumerate(next_parts):
        if np_idx in mapping:
            continue
        np_sig = next_sigs[np_idx]
        for bp_idx, bp in enumerate(base_parts):
            if bp_idx not in used_base and base_sigs[bp_idx] == np_sig:
                if base_tags and next_tags and bp_idx < len(base_tags) and np_idx < len(next_tags):
                    b_t = base_tags[bp_idx]
                    n_t = next_tags[np_idx]
                    if b_t and n_t and b_t != n_t:
                        continue
                mapping[np_idx] = bp
                used_base.add(bp_idx)
                break

    # Pass 2: staves count match for remaining parts
    for np_idx, np in enumerate(next_parts):
        if np_idx in mapping:
            continue
        np_staves = next_sigs[np_idx][0]
        for bp_idx, bp in enumerate(base_parts):
            if bp_idx not in used_base and base_sigs[bp_idx][0] == np_staves:
                mapping[np_idx] = bp
                used_base.add(bp_idx)
                break

    for np_idx in range(len(next_parts)):
        if np_idx not in mapping:
            mapping[np_idx] = None

    return mapping


def merge_musicxml_files(
    xml_paths: list[Path], output_path: Path, metadata: dict[str, str] | None = None
) -> Path:
    """
    Merge multiple MusicXML files (e.g. from different pages) into a single score.
    Supports single-part and multi-part (e.g. SATB choral) scores with parallel measure numbering.

    Args:
        xml_paths: Ordered list of paths to single-page MusicXML files.
        output_path: Path where the merged MusicXML will be written.
        metadata: Optional dictionary of score metadata (title, composer, arranger) to inject.

    Returns:
        Path to the merged MusicXML file.
    """
    if not xml_paths:
        raise ValueError("At least one MusicXML file is required to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(xml_paths) == 1:
        shutil.copyfile(xml_paths[0], output_path)
        base_tree = _parse_xml(output_path)
        base_root = base_tree.getroot()
        if base_root is None:
            raise ValueError(f"Failed to parse MusicXML root from: {output_path}")
        inject_score_metadata(base_root, metadata)
        autotag_musicxml_tree(base_root)
        repair_score_consistency(base_root)
        sanitize_musicxml_tree(base_root)
        base_tree.write(output_path, encoding="utf-8", xml_declaration=True)
        return output_path

    # Parse the first page as the base document
    base_tree = _parse_xml(xml_paths[0])
    base_root = base_tree.getroot()
    if base_root is None:
        raise ValueError(f"Failed to parse base MusicXML root from: {xml_paths[0]}")
    remove_empty_ghost_measures(base_root)
    align_system_break_measures(base_root)
    base_parts = base_root.findall(".//part")

    if not base_parts:
        raise ValueError(f"No <part> element found in base MusicXML: {xml_paths[0]}")

    base_parts_map = {p.get("id"): p for p in base_parts}
    base_part_list = base_root.find(".//part-list")

    # Current maximum measure count across parts on page 1
    max_measure_num = max(len(p.findall("measure")) for p in base_parts)
    for bp in base_parts:
        bp_measures = bp.findall("measure")
        bp_div, bp_beats, bp_bt, _ = _extract_active_attributes(bp)
        for pad_num in range(len(bp_measures) + 1, max_measure_num + 1):
            _create_padded_measure(bp, pad_num, divisions=bp_div, beats=bp_beats, beat_type=bp_bt)

    for next_file in xml_paths[1:]:
        tree = _parse_xml(next_file)
        root = tree.getroot()
        if root is None:
            continue
        remove_empty_ghost_measures(root)
        align_system_break_measures(root)
        next_parts = root.findall(".//part")
        if not next_parts:
            continue

        page_max_measures = max(len(part_elem.findall("measure")) for part_elem in next_parts)
        part_alignment = _align_page_parts(base_parts, next_parts, base_root=base_root, next_root=root)
        matched_base_parts: set[ET.Element] = set()
        for idx, next_part in enumerate(next_parts):
            part_id = next_part.get("id")
            target_base_part = part_alignment.get(idx)
            if target_base_part is None:
                # Determine whether this newly entering part is an upper Solo/Descant part (idx == 0
                # while subsequent parts match base_parts) so we insert it at the top of the score
                is_upper_solo = idx == 0 and len(base_parts) >= 4 and part_alignment.get(1) is not None

                next_score_part = root.find(f".//score-part[@id='{part_id}']")
                nsp_name = (next_score_part.findtext("part-name") or "").strip() if next_score_part is not None else ""
                from app.services.voice_autotagger import resolve_voice_tag, TAG_BARITONE, TAG_PIANO, TAG_ORGAN, TAG_CHOIR
                nsp_tag = resolve_voice_tag(nsp_name)

                base_sigs_curr = [_extract_part_signature(p) for p in base_parts]
                bottom_sp = base_part_list[-1] if base_part_list is not None and len(base_part_list) > 0 else None
                bottom_name = (bottom_sp.findtext("part-name") or "").strip() if bottom_sp is not None else ""
                bottom_tag = resolve_voice_tag(bottom_name)

                has_bottom_piano = len(base_parts) > 0 and (
                    bottom_tag in (TAG_PIANO, TAG_ORGAN)
                    or (bottom_tag is not None and bottom_tag.family == "keyboard")
                    or (base_sigs_curr[-1][0] >= 2 and bottom_tag != TAG_CHOIR and "choir" not in bottom_name.lower())
                )

                insert_idx = None
                if is_upper_solo:
                    insert_idx = 0
                elif nsp_tag == TAG_BARITONE and len(base_parts) >= 4:
                    # In choral SATBarB, insert Baritone right before Bass
                    bass_idx = None
                    for b_i, bp_elem in enumerate(base_parts):
                        b_sp = base_root.find(f".//score-part[@id='{bp_elem.get('id')}']")
                        if b_sp is not None:
                            b_tag = resolve_voice_tag(b_sp.findtext("part-name") or "")
                            if b_tag and b_tag.tag == "B":
                                bass_idx = b_i
                                break
                    if bass_idx is not None:
                        insert_idx = bass_idx
                    elif has_bottom_piano:
                        insert_idx = len(base_parts) - 1
                elif has_bottom_piano and (nsp_tag is None or nsp_tag.family == "vocal"):
                    insert_idx = len(base_parts) - 1

                existing_ids = set(base_parts_map.keys()) | {p.get("id") for p in base_parts if p.get("id")}
                c_num = 1
                while f"P{c_num}" in existing_ids:
                    c_num += 1
                clean_id = f"P{c_num}"

                target_base_part = ET.Element("part", id=clean_id)
                if insert_idx is not None:
                    ref_anchor = base_parts[insert_idx]
                    dom_idx = list(base_root).index(ref_anchor) if ref_anchor in list(base_root) else len(list(base_root))
                    base_root.insert(dom_idx, target_base_part)
                    base_parts.insert(insert_idx, target_base_part)
                else:
                    base_root.append(target_base_part)
                    base_parts.append(target_base_part)
                base_parts_map[clean_id] = target_base_part

                if next_score_part is not None and base_part_list is not None:
                    new_sp = copy.deepcopy(next_score_part)
                    new_sp.set("id", clean_id)
                    if is_upper_solo:
                        pname_el = new_sp.find("part-name")
                        if pname_el is None:
                            pname_el = ET.SubElement(new_sp, "part-name")
                        pname_el.text = "Solo"
                        pabbr_el = new_sp.find("part-abbreviation")
                        if pabbr_el is not None:
                            pabbr_el.text = "Solo"
                        base_part_list.insert(0, new_sp)
                    elif insert_idx is not None and insert_idx < len(base_part_list):
                        base_part_list.insert(insert_idx, new_sp)
                    else:
                        base_part_list.append(new_sp)

                # Determine active divisions and time from primary base part
                ref_part = base_parts[1] if (is_upper_solo and len(base_parts) > 1) else base_parts[0]
                b_div, b_beats, b_bt, b_attr = _extract_active_attributes(ref_part)

                # Build initial attributes for measure 1 of this newly introduced part
                m1_attr = ET.Element("attributes")
                d_el = ET.SubElement(m1_attr, "divisions")
                d_el.text = str(b_div)
                if b_attr is not None:
                    k_el = b_attr.find("key")
                    if k_el is not None:
                        m1_attr.append(copy.deepcopy(k_el))
                t_el = ET.SubElement(m1_attr, "time")
                b_el = ET.SubElement(t_el, "beats")
                b_el.text = str(b_beats)
                bt_el = ET.SubElement(t_el, "beat-type")
                bt_el.text = str(b_bt)

                # If entering part has a clef in its definitions, carry it into measure 1
                entering_clef = next_part.find(".//attributes/clef")
                if entering_clef is not None:
                    m1_attr.append(copy.deepcopy(entering_clef))

                # If this part entered on a later page, pad prior measures with whole rests for timeline synchronization
                for prior_m in range(1, max_measure_num + 1):
                    attr_for_m = m1_attr if prior_m == 1 else None
                    _create_padded_measure(
                        target_base_part,
                        prior_m,
                        divisions=b_div,
                        beats=b_beats,
                        beat_type=b_bt,
                        attributes_elem=attr_for_m,
                    )

            matched_base_parts.add(target_base_part)
            next_measures = next_part.findall("measure")

            for m_idx, measure in enumerate(next_measures, start=1):
                measure.set("number", str(max_measure_num + m_idx))
                target_base_part.append(measure)

            # Pad if this part had fewer measures on this page than page_max_measures
            t_div, t_beats, t_bt, _ = _extract_active_attributes(target_base_part)
            for pad_idx in range(len(next_measures) + 1, page_max_measures + 1):
                _create_padded_measure(
                    target_base_part,
                    max_measure_num + pad_idx,
                    divisions=t_div,
                    beats=t_beats,
                    beat_type=t_bt,
                )

        # Pad any base_parts that were absent on this page (e.g. Solo staff resting on a 4-staff page)
        for bp in base_parts:
            if bp not in matched_base_parts:
                t_div, t_beats, t_bt, _ = _extract_active_attributes(bp)
                for pad_idx in range(1, page_max_measures + 1):
                    _create_padded_measure(
                        bp,
                        max_measure_num + pad_idx,
                        divisions=t_div,
                        beats=t_beats,
                        beat_type=t_bt,
                    )

        max_measure_num += page_max_measures

    # Inject title, composer, arranger metadata if provided
    inject_score_metadata(base_root, metadata)

    # Autotag voices, abbreviations, and piano instruments
    autotag_musicxml_tree(base_root)

    # Apply score consistency post-processing
    repair_score_consistency(base_root)

    # Sanitize merged tree to prevent Verovio segfaults and OSMD render issues
    sanitize_musicxml_tree(base_root)

    base_tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path

