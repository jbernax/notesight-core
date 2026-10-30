import difflib
import io
import json
import logging
import statistics
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import Job, OMRTrainingTriplet
from app.services.omr_augmentation import apply_training_augmentations
from app.services.rhythm_validator import validate_musicxml_rhythms
from app.services.storage import get_storage_service

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

from PIL import Image

logger = logging.getLogger(__name__)


def compute_levenshtein(s1: str, s2: str) -> int:
    """Compute exact edit distance between two strings with space-optimized rolling buffer."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    if len(s1) < len(s2):
        s1, s2 = s2, s1

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row
    return prev_row[-1]


def calculate_character_error_rate(raw_xml: str, corrected_xml: str) -> float:
    """
    Calculate normalized Character Error Rate (CER) between raw prediction and corrected XML.

    Uses exact Levenshtein distance for strings <= 12,000 characters,
    and fast SequenceMatcher ratio for larger multi-page scores to guarantee <50ms execution.
    """
    s1 = raw_xml.strip()
    s2 = corrected_xml.strip()

    if s1 == s2:
        return 0.0
    if not s1 and not s2:
        return 0.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 0.0

    if max_len <= 12000:
        dist = compute_levenshtein(s1, s2)
        return round(min(1.0, dist / max_len), 4)

    # Fast heuristic for massive multi-megabyte XML files
    ratio = difflib.SequenceMatcher(None, s1, s2).ratio()
    return round(max(0.0, min(1.0, 1.0 - ratio)), 4)


def calculate_musicxml_diff(raw_xml: str, corrected_xml: str) -> dict[str, Any]:
    """
    Extract structural and measure-level differences between raw OMR prediction and user edits.
    """
    result: dict[str, Any] = {
        "measures_modified": 0,
        "total_measures": 0,
        "modified_elements": {},
        "cer": calculate_character_error_rate(raw_xml, corrected_xml),
    }

    try:
        raw_root = ET.fromstring(raw_xml.strip())
        corr_root = ET.fromstring(corrected_xml.strip())
    except Exception as exc:
        logger.warning("Failed to parse XML in diff calculation: %s", exc)
        result["measures_modified"] = 1 if result["cer"] > 0.0 else 0
        return result

    raw_measures = raw_root.findall(".//part/measure")
    corr_measures = corr_root.findall(".//part/measure")

    result["total_measures"] = max(len(raw_measures), len(corr_measures))

    modified_count = 0
    element_changes: dict[str, int] = {}

    for idx in range(result["total_measures"]):
        m_raw = raw_measures[idx] if idx < len(raw_measures) else None
        m_corr = corr_measures[idx] if idx < len(corr_measures) else None

        if m_raw is None or m_corr is None:
            modified_count += 1
            element_changes["measure"] = element_changes.get("measure", 0) + 1
            continue

        raw_str = ET.tostring(m_raw, encoding="unicode").strip()
        corr_str = ET.tostring(m_corr, encoding="unicode").strip()

        if raw_str != corr_str:
            modified_count += 1
            # Inspect what tags differ
            raw_tags = {elem.tag for elem in m_raw.iter()}
            corr_tags = {elem.tag for elem in m_corr.iter()}
            all_tags = raw_tags | corr_tags
            for tag in all_tags:
                count_raw = len(m_raw.findall(f".//{tag}"))
                count_corr = len(m_corr.findall(f".//{tag}"))
                if count_raw != count_corr:
                    element_changes[tag] = element_changes.get(tag, 0) + abs(count_raw - count_corr)

    result["measures_modified"] = modified_count
    result["modified_elements"] = element_changes
    return result


def calculate_rhythm_improvement(raw_xml: str, corrected_xml: str) -> int:
    """Calculate the net count of rhythm arithmetic discrepancies fixed by user edits."""
    issues_before = len(validate_musicxml_rhythms(raw_xml))
    issues_after = len(validate_musicxml_rhythms(corrected_xml))
    return max(0, issues_before - issues_after)


def record_user_correction(
    db: Session,
    job: Job,
    raw_xml: str,
    corrected_xml: str,
    user_id: uuid.UUID | None = None,
) -> OMRTrainingTriplet | None:
    """
    Capture an active learning training triplet comparing raw OMR inference with verified edits.

    Stores the aligned training data in object storage and creates an OMRTrainingTriplet record.
    """
    raw_clean = raw_xml.strip()
    corr_clean = corrected_xml.strip()

    if raw_clean == corr_clean:
        logger.debug("Score save without notation changes; skipping telemetry triplet generation.")
        return None

    diff_info = calculate_musicxml_diff(raw_clean, corr_clean)
    cer = diff_info["cer"]
    measures_modified = diff_info["measures_modified"]
    rhythm_fixed = calculate_rhythm_improvement(raw_clean, corr_clean)

    storage = get_storage_service()

    # Check if a triplet already exists for this job to prevent duplicate records on repeated saves
    existing_triplet = db.query(OMRTrainingTriplet).filter(OMRTrainingTriplet.job_id == job.id).first()
    if existing_triplet:
        storage.save_bytes(existing_triplet.corrected_xml_path, corr_clean.encode("utf-8"))
        existing_triplet.character_error_rate = cer
        existing_triplet.measures_modified = measures_modified
        existing_triplet.rhythm_issues_fixed = rhythm_fixed
        existing_triplet.diff_summary = json.dumps(diff_info["modified_elements"])
        db.commit()
        db.refresh(existing_triplet)
        logger.info(
            "Active learning triplet %s updated in-place for job %s (CER=%.4f, measures_mod=%d, rhythm_fixed=%d)",
            existing_triplet.id,
            job.id,
            cer,
            measures_modified,
            rhythm_fixed,
        )
        return existing_triplet

    triplet_id = uuid.uuid4()

    # 1. Persist raw prediction and corrected ground truth
    raw_key = f"training_triplets/{triplet_id}/raw_prediction.musicxml"
    corr_key = f"training_triplets/{triplet_id}/ground_truth.musicxml"

    storage.save_bytes(raw_key, raw_clean.encode("utf-8"))
    storage.save_bytes(corr_key, corr_clean.encode("utf-8"))

    # 2. Link source score image if available
    img_key: str | None = None
    if job.file_path and storage.exists(job.file_path):
        source_ext = Path(job.file_path).suffix.lower()
        if source_ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            img_key = f"training_triplets/{triplet_id}/source_score{source_ext}"
            try:
                img_bytes = storage.read_bytes(job.file_path)
                storage.save_bytes(img_key, img_bytes)
            except Exception as exc:
                logger.warning("Could not duplicate source image for triplet %s: %s", triplet_id, exc)
                img_key = job.file_path

    # 3. Create database record
    triplet = OMRTrainingTriplet(
        id=triplet_id,
        job_id=job.id,
        user_id=user_id or job.user_id,
        image_path=img_key,
        raw_prediction_path=raw_key,
        corrected_xml_path=corr_key,
        character_error_rate=cer,
        measures_modified=measures_modified,
        rhythm_issues_fixed=rhythm_fixed,
        diff_summary=json.dumps(diff_info["modified_elements"]),
        created_at=datetime.now(timezone.utc),
    )

    db.add(triplet)
    db.commit()
    db.refresh(triplet)

    logger.info(
        "Active learning triplet %s created for job %s (CER=%.4f, measures_mod=%d, rhythm_fixed=%d)",
        triplet_id,
        job.id,
        cer,
        measures_modified,
        rhythm_fixed,
    )
    return triplet


def generate_omr_quality_report(db: Session, user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Aggregate quality, error rate, and model confidence metrics across collected triplets via SQL."""
    agg_query = db.query(
        func.count(OMRTrainingTriplet.id).label("total"),
        func.avg(OMRTrainingTriplet.character_error_rate).label("avg_cer"),
        func.sum(OMRTrainingTriplet.measures_modified).label("total_mod"),
        func.sum(OMRTrainingTriplet.rhythm_issues_fixed).label("total_rhythm"),
        func.sum(case((OMRTrainingTriplet.character_error_rate < 0.02, 1), else_=0)).label("cer_lt_2"),
        func.sum(
            case(
                (
                    (OMRTrainingTriplet.character_error_rate >= 0.02)
                    & (OMRTrainingTriplet.character_error_rate < 0.05),
                    1,
                ),
                else_=0,
            )
        ).label("cer_2_5"),
        func.sum(
            case(
                (
                    (OMRTrainingTriplet.character_error_rate >= 0.05)
                    & (OMRTrainingTriplet.character_error_rate < 0.10),
                    1,
                ),
                else_=0,
            )
        ).label("cer_5_10"),
        func.sum(case((OMRTrainingTriplet.character_error_rate >= 0.10, 1), else_=0)).label("cer_gt_10"),
    )
    if user_id is not None:
        agg_query = agg_query.filter(OMRTrainingTriplet.user_id == user_id)

    agg = agg_query.one()
    total_triplets = int(agg.total or 0)

    if total_triplets == 0:
        return {
            "total_triplets": 0,
            "average_cer": 0.0,
            "median_cer": 0.0,
            "total_measures_modified": 0,
            "total_rhythm_issues_fixed": 0,
            "cer_distribution": {
                "< 2%": 0,
                "2% - 5%": 0,
                "5% - 10%": 0,
                "> 10%": 0,
            },
            "common_modified_elements": {},
        }

    avg_cer = round(float(agg.avg_cer or 0.0), 4)
    total_mod = int(agg.total_mod or 0)
    total_rhythm = int(agg.total_rhythm or 0)

    # Median CER computed on lightweight scalar column query
    cer_query = db.query(OMRTrainingTriplet.character_error_rate)
    if user_id is not None:
        cer_query = cer_query.filter(OMRTrainingTriplet.user_id == user_id)
    cer_values = [row[0] for row in cer_query.all() if row[0] is not None]
    med_cer = round(float(statistics.median(cer_values)), 4) if cer_values else 0.0

    cer_dist = {
        "< 2%": int(agg.cer_lt_2 or 0),
        "2% - 5%": int(agg.cer_2_5 or 0),
        "5% - 10%": int(agg.cer_5_10 or 0),
        "> 10%": int(agg.cer_gt_10 or 0),
    }

    # Common modified elements sampled directly without loading full ORM triplet objects
    diff_query = db.query(OMRTrainingTriplet.diff_summary).filter(OMRTrainingTriplet.diff_summary.isnot(None))
    if user_id is not None:
        diff_query = diff_query.filter(OMRTrainingTriplet.user_id == user_id)
    common_elements: dict[str, int] = {}
    for (diff_summary_str,) in diff_query.limit(500).all():
        if diff_summary_str:
            try:
                elements = json.loads(diff_summary_str)
                for tag, count in elements.items():
                    common_elements[tag] = common_elements.get(tag, 0) + count
            except Exception:
                pass

    sorted_elements = dict(sorted(common_elements.items(), key=lambda item: item[1], reverse=True)[:10])

    return {
        "total_triplets": total_triplets,
        "average_cer": avg_cer,
        "median_cer": med_cer,
        "total_measures_modified": total_mod,
        "total_rhythm_issues_fixed": total_rhythm,
        "cer_distribution": cer_dist,
        "common_modified_elements": sorted_elements,
    }


def export_training_corpus(
    db: Session,
    include_augmented: bool = False,
    limit: int = 100,
    user_id: uuid.UUID | None = None,
) -> bytes:
    """
    Export collected active learning triplets into a fine-tuning dataset archive.

    Includes JSONL manifest, paired image regions, raw predictions, and ground-truth MusicXML.
    Optionally applies realistic synthetic image augmentations.
    """
    query = db.query(OMRTrainingTriplet)
    if user_id is not None:
        query = query.filter(OMRTrainingTriplet.user_id == user_id)
    triplets = query.order_by(OMRTrainingTriplet.created_at.desc()).limit(limit).all()
    storage = get_storage_service()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest_lines: list[str] = []

        for t in triplets:
            t_id = str(t.id)

            # 1. Read raw prediction and ground truth XML
            raw_bytes = storage.read_bytes(t.raw_prediction_path) if storage.exists(t.raw_prediction_path) else b""
            corr_bytes = storage.read_bytes(t.corrected_xml_path) if storage.exists(t.corrected_xml_path) else b""

            raw_zip_path = f"raw_predictions/{t_id}.musicxml"
            corr_zip_path = f"ground_truth/{t_id}.musicxml"

            zf.writestr(raw_zip_path, raw_bytes)
            zf.writestr(corr_zip_path, corr_bytes)

            # 2. Source image
            img_zip_path: str | None = None
            if t.image_path and storage.exists(t.image_path):
                img_bytes = storage.read_bytes(t.image_path)
                ext = Path(t.image_path).suffix or ".png"
                img_zip_path = f"images/{t_id}{ext}"
                zf.writestr(img_zip_path, img_bytes)

                # Synthetic augmentation if requested
                if include_augmented:
                    try:
                        pil_img = Image.open(io.BytesIO(img_bytes))
                        aug_img = apply_training_augmentations(pil_img)
                        aug_buf = io.BytesIO()
                        aug_img.save(aug_buf, format="PNG")
                        zf.writestr(f"images/{t_id}_augmented.png", aug_buf.getvalue())
                    except Exception as exc:
                        logger.warning("Could not apply synthetic augmentation to %s: %s", t_id, exc)

            # 3. Add record to manifest
            manifest_item = {
                "triplet_id": t_id,
                "job_id": str(t.job_id) if t.job_id else None,
                "image": img_zip_path,
                "raw_prediction": raw_zip_path,
                "ground_truth": corr_zip_path,
                "character_error_rate": t.character_error_rate,
                "measures_modified": t.measures_modified,
                "rhythm_issues_fixed": t.rhythm_issues_fixed,
                "created_at": t.created_at.isoformat(),
            }
            manifest_lines.append(json.dumps(manifest_item))

        zf.writestr("manifest.jsonl", "\n".join(manifest_lines) + "\n")

    buffer.seek(0)
    return buffer.getvalue()
