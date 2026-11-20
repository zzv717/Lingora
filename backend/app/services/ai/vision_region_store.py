"""Persistence for exercise regions and manual crop corrections.

The AI box is only a proposal. This module is the single place that decides how a
proposal becomes a stored region, and how a human correction takes priority over it:

* region boxes are always stored normalized (0..1), never in OCR/PDF pixels;
* ``apply_correction`` overwrites the region (``source="manual"``), hides its
  confidence penalty, links the box to the saved exercise, and writes an audit row;
* the audit rows are the raw material for later accuracy analysis;
* nothing here creates answer keys, grades or student progress.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import Exercise, VisionExerciseRegion, VisionRegionCorrection
from app.services.ai.vision_regions import (
    box_area,
    clamp_bbox,
    overlap_ratio,
    pad_bbox,
    sequence_issues,
    validate_regions,
)

log = logging.getLogger("lingora.vision.regions.store")

CONTINUATION_GAP = 0.35  # a continuation box must be near the page edge
PAGE_EDGE = 0.80


def _payload(region: VisionExerciseRegion) -> dict[str, Any]:
    return {
        "id": region.id, "page": region.page_number, "number": region.number,
        "title": region.title, "bbox": list(region.bbox or []),
        "original_bbox": list(region.original_bbox or []) or None,
        "source": region.source, "confidence": region.confidence,
        "needs_review": region.needs_review,
        "continues_from_previous_page": region.continues_from_previous_page,
        "continues_on_next_page": region.continues_on_next_page,
        "continued_from_region_id": region.continued_from_region_id,
        "flags": list(region.flags or []), "exercise_id": region.exercise_id,
        "provider": region.provider, "model": region.model,
    }


def page_regions(db: Session, book_id: str, page: int, include_manual: bool = True) -> list[dict[str, Any]]:
    query = select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book_id, VisionExerciseRegion.page_number == page)
    if not include_manual:
        query = query.where(VisionExerciseRegion.source != "manual")
    rows = list(db.scalars(query.order_by(VisionExerciseRegion.order_index)))
    return [_payload(row) for row in rows]


def all_regions(db: Session, book_id: str) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book_id).order_by(
        VisionExerciseRegion.page_number, VisionExerciseRegion.order_index)))
    return [_payload(row) for row in rows]


def _link_continuations(regions: list[VisionExerciseRegion]) -> None:
    """Link a box that starts at the top of a page to the previous page's last box."""
    by_page: dict[int, list[VisionExerciseRegion]] = {}
    for region in regions:
        by_page.setdefault(region.page_number, []).append(region)
    previous: list[VisionExerciseRegion] | None = None
    for page in sorted(by_page):
        current = sorted(by_page[page], key=lambda r: r.bbox[1])
        if previous:
            last = previous[-1]
            first = current[0]
            same_number = first.number and first.number == last.number
            near_edge = first.bbox[1] <= CONTINUATION_GAP and last.bbox[3] >= PAGE_EDGE
            if (first.continues_from_previous_page or same_number) and near_edge:
                first.continued_from_region_id = last.id
                first.flags = sorted(set(list(first.flags or []) + ["continued_from_previous_page"]))
        previous = current


def _resolve_exercises(db: Session, book_id: str, page: int, regions: list[dict[str, Any]]) -> dict[int, str]:
    """Map region index -> saved exercise id, only for unambiguous printed numbers."""
    rows = list(db.scalars(select(Exercise).where(
        Exercise.book_id == book_id, Exercise.page_number == page,
        Exercise.detection == "vision").order_by(Exercise.order_index)))
    if not rows:
        return {}
    by_ref: dict[str, list[Exercise]] = {}
    for row in rows:
        number = (row.ref or "").replace("Exercise", "").strip()
        by_ref.setdefault(number, []).append(row)
    mapping: dict[int, str] = {}
    for index, region in enumerate(regions):
        matches = by_ref.get(region["number"] or "", [])
        if len(matches) == 1:
            mapping[index] = matches[0].id
    return mapping


def save_page_regions(db: Session, book, page: int, exercises: list[dict[str, Any]],
                      provider: str = "", model: str = "", image_sha256: str = "") -> list[dict[str, Any]]:
    """Store (or refresh) the AI regions of one page. Manual boxes are never overwritten."""
    manual = {row.number for row in db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book.id, VisionExerciseRegion.page_number == page,
        VisionExerciseRegion.source == "manual"))}
    existing = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book.id, VisionExerciseRegion.page_number == page,
        VisionExerciseRegion.source != "manual")))
    for row in existing:
        db.delete(row)
    db.flush()
    kept = [dict(item) for item in exercises if (item.get("number") or "") not in manual]
    kept, _ = validate_regions(kept) if kept else ([], [])
    linkable: list[VisionExerciseRegion] = []
    first_index = 0
    if kept:
        first_index = int(db.scalar(select(func.coalesce(func.max(VisionExerciseRegion.order_index), -1)).where(
            VisionExerciseRegion.book_id == book.id,
            VisionExerciseRegion.page_number < page)) or -1) + 1
    links = _resolve_exercises(db, book.id, page, kept)
    for offset, item in enumerate(kept):
        row = VisionExerciseRegion(
            book_id=book.id, page_number=page, order_index=first_index + offset,
            number=item.get("number") or "", title=(item.get("title") or "")[:300],
            bbox=list(item["bbox"]), original_bbox=item.get("original_bbox") or list(item["bbox"]),
            source="manual" if item.get("source") == "manual" else "ai",
            confidence=float(item.get("confidence") or 0.0),
            needs_review=True,
            continues_from_previous_page=bool(item.get("continues_from_previous_page")),
            continues_on_next_page=bool(item.get("continues_on_next_page")),
            flags=list(item.get("flags") or []), provider=provider, model=model,
            image_sha256=image_sha256, exercise_id=links.get(offset),
        )
        db.add(row)
        linkable.append(row)
    db.flush()
    rows = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book.id).order_by(
        VisionExerciseRegion.page_number, VisionExerciseRegion.order_index)))
    _link_continuations(rows)
    db.commit()
    return page_regions(db, book.id, page)


def library_warnings(db: Session, book_id: str) -> list[str]:
    """Real issues for the review UI: gaps/duplicates and low confidence after a correction pass."""
    rows = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book_id).order_by(VisionExerciseRegion.order_index)))
    if not rows:
        return []
    warnings: list[str] = []
    for issue in sequence_issues([row.number for row in rows if row.number]):
        if issue.startswith("duplicate:"):
            warnings.append(f"Mashq raqamlari takrorlanadi ({issue.split(':', 1)[1]}).")
        elif issue.startswith("gap:"):
            warnings.append(f"Mashq raqamlari orasida uzilish bor ({issue.split(':', 1)[1]}).")
    unchecked = sum(1 for row in rows if row.source == "ai" and row.needs_review)
    if unchecked:
        warnings.append(f"{unchecked} ta mashq qirqimi hali tasdiqlanmagan.")
    return warnings


def region_for_user(db: Session, user_id: str, region_id: str) -> VisionExerciseRegion:
    """Ownership check: another user's region is indistinguishable from a missing one."""
    region = db.get(VisionExerciseRegion, region_id)
    if not region:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    from app.models import Book

    book = db.get(Book, region.book_id)
    if not book or book.user_id != user_id:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    return region


def apply_correction(db: Session, user_id: str, region_id: str, bbox: Any,
                     note: str = "") -> dict[str, Any]:
    """Save a human box for one exercise; it takes priority over the AI result."""
    region = region_for_user(db, user_id, region_id)
    box = clamp_bbox(bbox)
    if box is None or box[2] - box[0] < 0.01 or box[3] - box[1] < 0.01:
        raise ApiError("INVALID_BBOX", "Qirqim chegarasi noto'g'ri: sahifa ichida tanlang.", 422)
    if box_area(box) > 0.98:
        raise ApiError("INVALID_BBOX", "Qirqim butun sahifani egallay olmaydi.", 422)
    siblings = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == region.book_id,
        VisionExerciseRegion.page_number == region.page_number,
        VisionExerciseRegion.id != region.id)))
    clash = next((s for s in siblings if overlap_ratio(list(s.bbox), box) > 0.10), None)
    if clash:
        raise ApiError(
            "REGION_OVERLAP",
            f"Bu chegara {clash.number or 'boshqa'} mashq bilan ustma-ust tushadi. Chegarani tuzatib qayta saqlang.",
            422, {"conflict_region_id": clash.id})

    previous_source, previous_bbox = region.source, list(region.bbox or [])
    region.bbox = box
    region.source = "manual"
    region.needs_review = False
    region.confidence = 1.0
    region.flags = sorted(set(list(region.flags or []) + ["manually_corrected"]))
    if region.exercise_id:
        exercise = db.get(Exercise, region.exercise_id)
        if exercise:
            # The exercise row keeps a normalized copy for readers that only load exercises.
            exercise.bbox = {"mode": "normalized", "page": region.page_number,
                             "bbox": [round(v, 5) for v in pad_bbox(box)], "source": "manual"}
    db.add(VisionRegionCorrection(
        user_id=user_id, book_id=region.book_id, region_id=region.id,
        exercise_id=region.exercise_id, page_number=region.page_number, number=region.number,
        previous_source=previous_source, previous_bbox=previous_bbox,
        corrected_bbox=box, note=(note or "")[:300]))
    db.commit()
    log.info("Region %s corrected on page %s (book %s)", region.id, region.page_number, region.book_id)
    return _payload(region)


def create_manual_region(db: Session, user_id: str, book, page: int, number: str,
                         bbox: Any, note: str = "") -> dict[str, Any]:
    """Add a box the model missed (the reviewer draws it on the page)."""
    box = clamp_bbox(bbox)
    if box is None:
        raise ApiError("INVALID_BBOX", "Qirqim chegarasi noto'g'ri: sahifa ichida tanlang.", 422)
    if not 1 <= page <= book.page_count:
        raise ApiError("INVALID_PAGE_SELECTION", "Sahifa raqami kitob oralig'ida emas.", 422)
    siblings = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book.id, VisionExerciseRegion.page_number == page)))
    clash = next((s for s in siblings if overlap_ratio(list(s.bbox), box) > 0.10), None)
    if clash:
        raise ApiError("REGION_OVERLAP",
                       f"Bu chegara {clash.number or 'boshqa'} mashq bilan ustma-ust tushadi.", 422,
                       {"conflict_region_id": clash.id})
    order = int(db.scalar(select(func.coalesce(func.max(VisionExerciseRegion.order_index), -1)).where(
        VisionExerciseRegion.book_id == book.id)) or -1) + 1
    region = VisionExerciseRegion(
        book_id=book.id, page_number=page, order_index=order, number=(number or "")[:16],
        title="", bbox=box, original_bbox=None, source="manual", confidence=1.0,
        needs_review=False, flags=["manually_corrected"])
    db.add(region)
    db.flush()
    db.add(VisionRegionCorrection(
        user_id=user_id, book_id=book.id, region_id=region.id, page_number=page,
        number=region.number, previous_source="none", previous_bbox=[],
        corrected_bbox=box, note=(note or "")[:300]))
    db.commit()
    return _payload(region)


def delete_region(db: Session, user_id: str, region_id: str) -> dict[str, Any]:
    region = region_for_user(db, user_id, region_id)
    db.add(VisionRegionCorrection(
        user_id=user_id, book_id=region.book_id, region_id=None, exercise_id=region.exercise_id,
        page_number=region.page_number, number=region.number, previous_source=region.source,
        previous_bbox=list(region.bbox or []), corrected_bbox=[], note="deleted"))
    db.delete(region)
    db.commit()
    return {"deleted": True}


def correction_stats(db: Session, book_id: str) -> dict[str, Any]:
    """How much the AI result was corrected — the basis for later accuracy analysis."""
    rows = list(db.scalars(select(VisionExerciseRegion).where(VisionExerciseRegion.book_id == book_id)))
    logs = list(db.scalars(select(VisionRegionCorrection).where(
        VisionRegionCorrection.book_id == book_id).order_by(VisionRegionCorrection.created_at.desc())))
    return {
        "regions": len(rows),
        "manual": sum(1 for row in rows if row.source == "manual"),
        "low_confidence": sum(1 for row in rows if row.source == "ai" and row.confidence < 0.7),
        "corrections": len(logs),
        "recent": [{"page": item.page_number, "number": item.number,
                    "previous_source": item.previous_source,
                    "corrected_bbox": item.corrected_bbox, "note": item.note,
                    "created_at": item.created_at.isoformat() if item.created_at else None}
                   for item in logs[:20]],
    }


def ensure_region_for_exercise(db: Session, user_id: str, book, exercise: Exercise) -> VisionExerciseRegion | None:
    """Return the region of a saved exercise, adopting an unclaimed AI box when possible."""
    region = db.scalar(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book.id, VisionExerciseRegion.exercise_id == exercise.id))
    if region:
        return region
    candidates = list(db.scalars(select(VisionExerciseRegion).where(
        VisionExerciseRegion.book_id == book.id, VisionExerciseRegion.exercise_id.is_(None),
        VisionExerciseRegion.page_number == exercise.page_number)))
    number = (exercise.ref or "").replace("Exercise", "").strip()
    match = next((c for c in candidates if c.number and c.number == number), None)
    if match:
        match.exercise_id = exercise.id
        db.commit()
    return match
