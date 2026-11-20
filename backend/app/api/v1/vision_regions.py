"""Exercise crop regions: detect, review, correct, crop and debug.

These endpoints are the API behind "Tuzatish" in the reader. Every route checks
ownership, consent for image uploads and a rate limit; nothing here invents text,
answers or grades.

Detection is cached per page image hash (``vision_page_region_cache``) and stored
in normalized coordinates (``vision_exercise_regions``).
"""
from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, owned_book
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limit
from app.db.session import get_db
from app.models import Exercise, User
from app.services.ai import vision_region_store as store
from app.services.ai import vision_regions
from app.services.ai.vision_regions import FEATURE, detect_book, detect_page

router = APIRouter(prefix="/books", tags=["vision-regions"])


class RegionDetectIn(BaseModel):
    page_numbers: list[int] = Field(min_length=1, max_length=40)
    consent_images_to_provider: bool
    force: bool = False


class RegionCorrectIn(BaseModel):
    bbox: list[float] = Field(min_length=4, max_length=4)
    note: str = Field(default="", max_length=300)


class RegionAddIn(BaseModel):
    page_number: int = Field(ge=1)
    number: str = Field(default="", max_length=16)
    bbox: list[float] = Field(min_length=4, max_length=4)
    note: str = Field(default="", max_length=300)


class RegionStatusIn(BaseModel):
    """Reviewer decision for one box: accepted, or still needs correction."""

    needs_review: bool = False
    note: str = Field(default="", max_length=300)


def _require_consent(consent: bool) -> None:
    if not consent:
        raise ApiError("AI_IMAGE_CONSENT_REQUIRED",
                       "Sahifa rasmlarini AI xizmatiga yuborish uchun rozilik kerak.", 422)


def _book_ready(book) -> None:
    if book.status != "ready":
        raise ApiError("BOOK_NOT_READY", "Kitob tayyor emas.", 409)


def _check_pages(book, pages: list[int]) -> None:
    if len(set(pages)) != len(pages) or any(n < 1 or n > book.page_count for n in pages):
        raise ApiError("INVALID_PAGE_SELECTION",
                       "Takrorlanmagan va kitob oralig'idagi PDF sahifa raqamlarini tanlang.", 422)


def _bypass_cache():
    """Context manager that disables the page cache for one detection run."""
    import contextlib

    @contextlib.contextmanager
    def _inner():
        original = settings.vision_region_cache_enabled
        settings.vision_region_cache_enabled = False
        try:
            yield
        finally:
            settings.vision_region_cache_enabled = original

    return _inner()


@router.get("/{book_id}/exercise-regions")
def list_regions(book_id: str, page: int | None = Query(default=None, ge=1),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Stored normalized boxes of a book (optionally one page), with correction stats."""
    book = owned_book(db, user, book_id)
    regions = (store.page_regions(db, book.id, page) if page
               else store.all_regions(db, book.id))
    return {
        "book_id": book.id,
        "page_count": book.page_count,
        "dpi": settings.vision_region_dpi,
        "coordinate_space": "normalized_0_1",
        "regions": regions,
        "warnings": store.library_warnings(db, book.id),
        "stats": store.correction_stats(db, book.id),
    }


@router.post("/{book_id}/exercise-regions/detect")
def detect_regions(book_id: str, data: RegionDetectIn, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Detect and store exercise boxes for up to 40 pages; cached pages are free."""
    limit(request, "vision_region_detect", 60, 3600, user.id)
    book = owned_book(db, user, book_id)
    _book_ready(book)
    _require_consent(data.consent_images_to_provider)
    pages = sorted(set(data.page_numbers))
    _check_pages(book, pages)
    if data.force:
        # "Qayta aniqlash" must re-ask the model instead of serving the cached answer.
        monkey = _bypass_cache()
        with monkey:
            outcomes = detect_book(db, user.id, book, pages)
    else:
        outcomes = detect_book(db, user.id, book, pages)
    results = []
    for outcome in outcomes:
        if outcome.error:
            results.append({"page": outcome.page, "error": outcome.error,
                            "error_code": outcome.error_code, "regions": [], "cached": False})
            continue
        saved = store.save_page_regions(db, book, outcome.page, outcome.exercises,
                                        model=settings.ai_vision_model or settings.ai_model)
        results.append({"page": outcome.page, "cached": outcome.cached, "dpi": outcome.dpi,
                        "warnings": outcome.warnings, "regions": saved})
    failed = [r for r in results if r.get("error")]
    return {
        "book_id": book.id,
        "pages": results,
        "coordinate_space": "normalized_0_1",
        "detected": sum(len(r["regions"]) for r in results),
        "failed_pages": failed,
        "message_uz": (f"{len(results) - len(failed)} sahifa tahlil qilindi, "
                       f"{sum(len(r['regions']) for r in results)} mashq topildi."
                       if not failed else
                       "Ba'zi sahifalar tahlil qilinmadi. Xato sabablari ro'yxatda."),
    }


@router.get("/{book_id}/exercise-regions/cache/stats")
def cache_stats(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Cache hit/miss visibility for cost checks."""
    from app.models import VisionPageRegionCache

    book = owned_book(db, user, book_id)
    rows = list(db.scalars(select(VisionPageRegionCache).where(VisionPageRegionCache.book_id == book.id)))
    return {"entries": len(rows), "hits": sum(row.hits for row in rows),
            "ttl_days": settings.vision_region_cache_ttl_days,
            "enabled": settings.vision_region_cache_enabled}


@router.post("/{book_id}/exercise-regions/cache/prune")
def prune_cache(book_id: str, request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    limit(request, "vision_region_correct", 30, 3600, user.id)
    owned_book(db, user, book_id)
    removed = vision_regions.prune_cache(db)
    return {"removed": removed, "message_uz": f"{removed} ta eskirgan kesh yozuvi o'chirildi."}


@router.post("/{book_id}/exercise-regions/attach")
def attach_regions(book_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Link saved vision exercises to their boxes (used after a page scan)."""
    book = owned_book(db, user, book_id)
    _book_ready(book)
    exercises = list(db.scalars(select(Exercise).where(
        Exercise.book_id == book.id, Exercise.detection == "vision")))
    attached = 0
    for exercise in exercises:
        if store.ensure_region_for_exercise(db, user.id, book, exercise):
            attached += 1
    db.commit()
    return {"exercises": len(exercises), "attached": attached,
            "message_uz": f"{attached} ta mashq qirqimga bog'landi."}


__all__ = ["router", "FEATURE"]
@router.post("/{book_id}/exercise-regions/debug")
def save_debug(book_id: str, data: RegionDetectIn, request: Request,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Write debug PNGs (boxes drawn) to VISION_REGION_DEBUG_DIR and return their paths."""
    limit(request, "vision_region_debug", 30, 3600, user.id)
    book = owned_book(db, user, book_id)
    _check_pages(book, sorted(set(data.page_numbers)))
    if not settings.vision_region_debug:
        raise ApiError("DEBUG_DISABLED", "Debug rejimi o'chirilgan (VISION_REGION_DEBUG=true qiling).", 409)
    saved = []
    for page in sorted(set(data.page_numbers)):
        regions = store.page_regions(db, book.id, page)
        corrections = [r for r in regions if r["source"] == "manual"]
        path = vision_regions.save_debug_image(book, page, regions, corrections)
        if path:
            saved.append({"page": page, "path": path, "regions": len(regions)})
    return {"files": saved, "message_uz": f"{len(saved)} ta debug rasm saqlandi."}


@router.patch("/{book_id}/exercise-regions/{region_id}")
def correct_region(book_id: str, region_id: str, data: RegionCorrectIn, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Save a manually drawn box — it takes priority over the AI box for that exercise."""
    limit(request, "vision_region_correct", 300, 3600, user.id)
    book = owned_book(db, user, book_id)
    region = store.region_for_user(db, user.id, region_id)
    if region.book_id != book.id:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    saved = store.apply_correction(db, user.id, region_id, data.bbox, data.note)
    crop = vision_regions.crop_data_url(book, saved["page"], saved["bbox"])
    return {"region": saved, "crop_data_url": crop,
            "message_uz": "Qirqim chegarasi saqlandi. Endi bu chegara AI natijasidan ustun."}


@router.post("/{book_id}/exercise-regions")
def add_region(book_id: str, data: RegionAddIn, request: Request,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Add a box the model missed (drawn by the reviewer)."""
    limit(request, "vision_region_correct", 300, 3600, user.id)
    book = owned_book(db, user, book_id)
    saved = store.create_manual_region(db, user.id, book, data.page_number, data.number,
                                       data.bbox, data.note)
    return {"region": saved, "crop_data_url": vision_regions.crop_data_url(book, saved["page"], saved["bbox"]),
            "message_uz": "Yangi chegara qo'shildi."}


@router.delete("/{book_id}/exercise-regions/{region_id}")
def remove_region(book_id: str, region_id: str, request: Request,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    limit(request, "vision_region_correct", 300, 3600, user.id)
    book = owned_book(db, user, book_id)
    region = store.region_for_user(db, user.id, region_id)
    if region.book_id != book.id:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    return store.delete_region(db, user.id, region_id)


@router.patch("/{book_id}/exercise-regions/{region_id}/review")
def review_region(book_id: str, region_id: str, data: RegionStatusIn, request: Request,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Mark a box as reviewed (no geometry change) or send it back for correction."""
    limit(request, "vision_region_correct", 300, 3600, user.id)
    book = owned_book(db, user, book_id)
    region = store.region_for_user(db, user.id, region_id)
    if region.book_id != book.id:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    region.needs_review = data.needs_review
    if not data.needs_review:
        region.flags = sorted(set(list(region.flags or []) + ["reviewed_by_user"]))
    db.commit()
    return {"region": store._payload(region),
            "message_uz": "Tasdiqlandi." if not data.needs_review else "Qayta tekshirish uchun belgilandi."}


@router.get("/{book_id}/exercise-regions/{region_id}/crop")
def region_crop(book_id: str, region_id: str, page: int | None = Query(default=None, ge=1),
                as_json: bool = True, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Crop the ORIGINAL PDF page at >=150 DPI using the stored normalized box."""
    book = owned_book(db, user, book_id)
    region = store.region_for_user(db, user.id, region_id)
    if region.book_id != book.id:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    png = vision_regions.crop_png(book, region.page_number, list(region.bbox))
    if not as_json:
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    return {"page": region.page_number, "bbox": list(region.bbox),
            "coordinate_space": "normalized_0_1",
            "data_url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}


@router.get("/{book_id}/exercise-regions/{region_id}/debug.png")
def region_debug(book_id: str, region_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Page render with the AI box and its manual correction drawn on it."""
    book = owned_book(db, user, book_id)
    region = store.region_for_user(db, user.id, region_id)
    if region.book_id != book.id:
        raise ApiError("REGION_NOT_FOUND", "Mashq qirqimi topilmadi.", 404)
    siblings = store.page_regions(db, book.id, region.page_number)
    corrections = [r for r in siblings if r["source"] == "manual"]
    png = vision_regions.debug_image(book, region.page_number, siblings, corrections)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


