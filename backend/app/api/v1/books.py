"""Books: secure upload, listing, structure, status, file streaming, deletion, re-analysis."""
import io
import logging
import math
import uuid
from datetime import timedelta
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_user_plan, owned_book
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limit
from app.db.session import get_db
from app.models import (
    AnswerKey,
    Book,
    BookPage,
    Chapter,
    Exercise,
    ExerciseQuestion,
    ExerciseOption,
    LearningProgress,
    Lesson,
    ProcessingJob,
    Profile,
    User,
    VocabularyWord,
)
from app.schemas import DirectUploadIn, BookOut, BookStructureOut, ChapterOut, JobOut, LessonOut, OkOut, PageOut, OCRPageIn
from app.services.pdf_extractor import ocr_available, validate_and_open
from app.services.storage import get_storage, SupabaseStorage, DIRECT_UPLOAD_FILENAME, direct_upload_token_active
from app.services.tasks import enqueue_book_analysis
from app.services.content_integrity import has_book_content

log = logging.getLogger("lingora.books")
router = APIRouter(prefix="/books", tags=["books"])


def _check_book_quota(db: Session, user: User) -> None:
    # Serialize direct-upload reservations per user on PostgreSQL.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    plan = settings.plan_limits(get_user_plan(db, user.id))
    n_books = int(db.scalar(select(func.count(Book.id)).where(Book.user_id == user.id)) or 0)
    if n_books >= plan["max_books"]:
        raise ApiError("PLAN_LIMIT", f"Rejangiz bo'yicha ko'pi bilan {plan['max_books']} ta kitob yuklash mumkin.", 403)


@router.post("/upload/prepare")
def prepare_upload(data: DirectUploadIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Reserve a private object and return a path-scoped TUS token, never a service key."""
    limit(request, "upload", 10, 3600, user.id)
    if settings.storage_backend != "supabase" or not settings.supabase_direct_upload_enabled:
        return {"direct": False}
    import jwt
    public_key = settings.supabase_publishable_key
    try:
        is_public = public_key.startswith("sb_publishable_") or (
            jwt.decode(public_key, options={"verify_signature": False}).get("role") == "anon"
        )
    except Exception:
        is_public = False
    if not is_public or public_key == settings.supabase_service_key:
        raise ApiError("STORAGE_MISCONFIGURED", "Storage uchun public kalit sozlanmagan.", 503)
    if not data.consent:
        raise ApiError("CONSENT_REQUIRED", "Kitobni qayta ishlash huquqingizni tasdiqlang.", 400)
    if not data.filename.lower().endswith(".pdf"):
        raise ApiError("INVALID_FILE", "Faqat PDF fayl qabul qilinadi.", 415)
    if data.size_bytes > settings.upload_max_mb * 1024 * 1024:
        raise ApiError("FILE_TOO_LARGE", f"Fayl {settings.upload_max_mb} MB dan katta.", 413)
    # Hold the user row while reserving slots and cleaning old reservations.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    # Expired unfinished reservations can no longer be uploaded to; reclaim them
    # when this user starts another upload. Keep records if deletion fails.
    stale = db.scalars(select(Book).where(Book.user_id == user.id, Book.status == "uploading",
                       Book.created_at < datetime.now(timezone.utc) - timedelta(hours=2, minutes=1))).all()
    storage = get_storage()
    for old in stale:
        storage.delete(old.storage_path)
        db.delete(old)
    db.flush()
    _check_book_quota(db, user)
    book_id = str(uuid.uuid4())
    path = f"books/{user.id}/{book_id}/{DIRECT_UPLOAD_FILENAME}"
    storage = get_storage()
    assert isinstance(storage, SupabaseStorage)
    storage.require_private_upload_limit()
    token = storage.create_signed_upload(path)
    book = Book(id=book_id, user_id=user.id, title=(data.title.strip() or data.filename.rsplit(".", 1)[0])[:500],
                original_filename=data.filename, file_size_bytes=data.size_bytes, storage_path=path,
                status="uploading", consent_confirmed_at=datetime.now(timezone.utc))
    db.add(book)
    db.commit()
    return {"direct": True, "book_id": book_id, "endpoint": f"{settings.supabase_url.rstrip('/')}/storage/v1/upload/resumable/sign",
            "bucket": settings.supabase_storage_bucket, "path": path, "token": token, "public_key": public_key}


@router.post("/upload/{book_id}/complete", response_model=BookOut)
def complete_upload(book_id: str, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Only the owner can finalize; verify actual bytes before creating a processing job."""
    limit(request, "upload_complete", 30, 3600, user.id)
    book = owned_book(db, user, book_id)
    if book.status != "uploading":
        # Retrying a lost response must not enqueue a second job.
        if book.storage_path.endswith("/" + DIRECT_UPLOAD_FILENAME):
            return book
        raise ApiError("UPLOAD_ALREADY_COMPLETED", "Yuklash allaqachon yakunlangan.", 409)
    if not direct_upload_token_active(book):
        raise ApiError("UPLOAD_EXPIRED", "Yuklash muddati tugadi. Qayta yuklang.", 409)
    storage = get_storage()
    if not isinstance(storage, SupabaseStorage):
        raise ApiError("STORAGE_MISCONFIGURED", "Storage sozlanmagan.", 503)
    content = storage.read_limited(book.storage_path, settings.upload_max_mb * 1024 * 1024)
    if len(content) != book.file_size_bytes:
        raise ApiError("UPLOAD_SIZE_MISMATCH", "Yuklangan fayl hajmi mos kelmadi.", 400)
    doc = validate_and_open(content)
    pages = doc.page_count
    doc.close()
    del content  # release large file before the analysis downloads it again
    # Compare-and-swap so concurrent finalize calls cannot create duplicate jobs.
    claimed = db.execute(update(Book).where(Book.id == book.id, Book.user_id == user.id,
                                            Book.status == "uploading").values(status="processing", page_count=pages))
    if claimed.rowcount != 1:
        db.rollback()
        raise ApiError("UPLOAD_ALREADY_COMPLETED", "Yuklash allaqachon yakunlangan.", 409)
    db.add(ProcessingJob(book_id=book.id, user_id=user.id, status="queued", stage_label_uz="Navbatda..."))
    db.commit()
    db.refresh(book)
    enqueue_book_analysis(book.id, user.id)
    return book


@router.post("/upload", response_model=BookOut, status_code=201)
async def upload_book(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    consent: bool = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit(request, "upload", 10, 3600, user.id)
    if not consent:
        raise ApiError(
            "CONSENT_REQUIRED",
            "Kitobni yuklash uchun uni qayta ishlash huquqingiz borligini tasdiqlashingiz kerak.",
            400,
        )
    content = await file.read()
    doc = validate_and_open(content)  # magic bytes, size, page count
    page_count = doc.page_count
    doc.close()

    plan = settings.plan_limits(get_user_plan(db, user.id))
    n_books = int(db.scalar(select(func.count(Book.id)).where(Book.user_id == user.id)) or 0)
    if n_books >= plan["max_books"]:
        raise ApiError(
            "PLAN_LIMIT",
            f"Rejangiz bo'yicha ko'pi bilan {plan['max_books']} ta kitob yuklash mumkin. "
            "Eski kitobni o'chirib bo'sh joy ochingiz.",
            403,
        )

    book = Book(
        user_id=user.id,
        title=(title.strip() or (file.filename or "Kitob").rsplit(".", 1)[0])[:500],
        original_filename=(file.filename or "book.pdf")[:500],
        file_size_bytes=len(content),
        status="uploaded",
        consent_confirmed_at=datetime.now(timezone.utc),
    )
    db.add(book)
    db.flush()
    book.storage_path = get_storage().save(user.id, book.id, file.filename or "book.pdf", content)
    db.add(ProcessingJob(book_id=book.id, user_id=user.id, status="queued",
                         stage_label_uz="Navbatda..."))
    book.status = "processing"
    db.commit()
    enqueue_book_analysis(book.id, user.id)
    return book


@router.get("", response_model=list[BookOut])
def list_books(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(db.scalars(select(Book).where(Book.user_id == user.id)
                           .order_by(Book.updated_at.desc())).all())


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return owned_book(db, user, book_id)


@router.delete("/{book_id}", response_model=OkOut)
def delete_book(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = owned_book(db, user, book_id)
    # The signed upload URL cannot be revoked; wait until it expires before deleting
    # a reservation, otherwise it could recreate an untracked object.
    if direct_upload_token_active(book):
        raise ApiError("UPLOAD_ACTIVE", "Xavfsizlik uchun yuklangandan keyin 2 soat o'tgach o'chiring.", 409)
    get_storage().delete(book.storage_path)
    db.delete(book)  # cascades pages/structure/vocab/attempts
    db.commit()
    return OkOut(message_uz="Kitob va unga oid barcha ma'lumotlar o'chirildi.")


@router.get("/{book_id}/file")
def download_book(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """PDF stream for the reader (pdf.js fetches this URL with the auth header). Files stay private."""
    book = owned_book(db, user, book_id)
    if book.status == "uploading":
        raise ApiError("UPLOAD_INCOMPLETE", "Fayl hali tekshirilmagan.", 409)
    content = get_storage().read(book.storage_path)
    return StreamingResponse(io.BytesIO(content), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="book-{book.id}.pdf"'})


@router.get("/{book_id}/status", response_model=Optional[JobOut])
def book_status(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_book(db, user, book_id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.book_id == book_id)
                    .order_by(ProcessingJob.created_at.desc()).limit(1))
    return job


@router.post("/{book_id}/reanalyze", response_model=JobOut)
def reanalyze(book_id: str, request: Request, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    limit(request, "reanalyze", 10, 3600, user.id)
    book = owned_book(db, user, book_id)
    db.scalar(select(Book).where(Book.id == book.id).with_for_update())
    if book.status == "uploading":
        raise ApiError("UPLOAD_INCOMPLETE", "Fayl hali tekshirilmagan.", 409)
    if book.status == "processing":
        raise ApiError("ALREADY_PROCESSING", "Kitob hozir tahlil qilinmoqda.", 409)
    if has_book_content(db, book.id):
        raise ApiError("REANALYZE_UNSAFE", "Qayta tahlil mavjud javoblar va progressni o'chirishi mumkin; xavfsiz qayta tahlil hali mavjud emas.", 409)
    job = ProcessingJob(book_id=book.id, user_id=user.id, status="queued",
                        stage_label_uz="Navbatda...")
    db.add(job)
    book.status = "processing"
    db.commit()
    enqueue_book_analysis(book.id, user.id)
    return job


def _lesson_locks(db: Session, book: Book, profile: Profile | None) -> tuple[dict[str, dict], list[int]]:
    """Vocabulary gating: next lesson unlocks after the previous lesson's vocab test is passed."""
    lessons = list(db.scalars(select(Lesson).where(Lesson.book_id == book.id)
                              .order_by(Lesson.order_index)).all())
    lesson_ids = [l.id for l in lessons] or [""]
    progresses = {p.lesson_id: p for p in db.scalars(select(LearningProgress).where(
        LearningProgress.user_id == book.user_id,
        LearningProgress.lesson_id.in_(lesson_ids))).all()}
    gating = profile.vocabulary_gating if profile else True

    out: dict[str, dict] = {}
    prev_passed = True
    for i, l in enumerate(lessons):
        p = progresses.get(l.id)
        has_vocab = db.query(VocabularyWord.id).filter(VocabularyWord.lesson_id == l.id, VocabularyWord.needs_translation.is_(False)).count() > 0
        locked = gating and i > 0 and not prev_passed
        gate_ok = (not has_vocab) or bool(p.vocab_gate_passed if p else False)
        out[l.id] = {
            "status": p.status if p else "not_started",
            "exercises_checked": p.exercises_checked if p else 0,
            "time_spent_seconds": p.time_spent_seconds if p else 0,
            "last_page": p.last_page if p else 0,
            "last_visited_at": p.last_visited_at.isoformat() if p and p.last_visited_at else None,
            "vocab_gate_passed": gate_ok,
            "has_vocabulary": has_vocab,
            "locked": locked,
        }
        prev_passed = gate_ok
    return out


@router.get("/{book_id}/structure", response_model=BookStructureOut)
def book_structure(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book = owned_book(db, user, book_id)
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id)
                               .order_by(Chapter.order_index)).all())
    lessons = list(db.scalars(select(Lesson).where(Lesson.book_id == book.id)
                              .order_by(Lesson.order_index)).all())
    locks = _lesson_locks(db, book, profile)
    key_pages = [row for row in db.scalars(select(AnswerKey.page_number)
                                           .where(AnswerKey.book_id == book.id)).all()]
    n_ex = int(db.scalar(select(func.count(Exercise.id)).where(Exercise.book_id == book.id)) or 0)
    n_vocab = int(db.scalar(select(func.count(VocabularyWord.id)).where(VocabularyWord.book_id == book.id)) or 0)
    n_q = int(db.scalar(
        select(func.count(ExerciseQuestion.id))
        .join(Exercise, Exercise.id == ExerciseQuestion.exercise_id)
        .where(Exercise.book_id == book.id)) or 0)
    n_with_key = int(db.scalar(
        select(func.count(ExerciseQuestion.id))
        .join(Exercise, Exercise.id == ExerciseQuestion.exercise_id)
        .where(Exercise.book_id == book.id,
               ExerciseQuestion.answer_source == "key")) or 0)
    ocr_pages = int(db.query(BookPage.id).filter(BookPage.book_id == book.id,
                                                 BookPage.ocr_used.is_(True)).count())
    warn_pages = int(db.query(BookPage.id).filter(BookPage.book_id == book.id,
                                                  BookPage.has_warning.is_(True)).count())
    coverage = {
        "exercises": n_ex, "questions": n_q, "questions_with_key": n_with_key,
        "vocabulary": n_vocab, "pages_ocr_used": ocr_pages, "pages_with_warnings": warn_pages,
        "ocr_available": ocr_available(),
        "pages_needing_ocr": int(db.query(BookPage.id).filter(BookPage.book_id == book.id,
                                               BookPage.needs_ocr.is_(True)).count()),
    }
    return BookStructureOut(
        book=BookOut.model_validate(book),
        chapters=[ChapterOut.model_validate(c) for c in chapters],
        lessons=[LessonOut.model_validate(l) for l in lessons],
        lessons_progress=locks,
        coverage=coverage,
        answer_key_pages=key_pages,
    )


def _inferred_page_type(page: BookPage) -> str:
    # Once OCR has been stored, original native text cannot be distinguished
    # from OCR text on legacy rows. Never claim a definitive original type.
    if page.ocr_used:
        return "unknown"
    has_text = bool(page.text.strip())
    has_images = bool(page.images)
    return "mixed" if has_text and has_images else "text" if has_text else "scanned" if has_images else "unknown"


@router.get("/{book_id}/pages/{page_number}", response_model=PageOut)
def get_page(book_id: str, page_number: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    owned_book(db, user, book_id)
    page = db.query(BookPage).filter(BookPage.book_id == book_id,
                                     BookPage.page_number == page_number).first()
    if not page:
        raise ApiError("PAGE_NOT_FOUND", "Sahifa topilmadi.", 404)
    return PageOut(
        page_number=page.page_number, width=page.width, height=page.height, text=page.text,
        blocks=page.blocks, images=page.images, page_type=_inferred_page_type(page), needs_ocr=page.needs_ocr,
        ocr_used=page.ocr_used, has_warning=page.has_warning,
    )


@router.get("/{book_id}/ocr/pending")
def ocr_pending(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return page numbers only; OCR itself runs in the user's browser."""
    book = owned_book(db, user, book_id)
    if book.status != "ready":
        raise ApiError("BOOK_NOT_READY", "Kitob tahlili hali yakunlanmagan.", 409)
    return {"pages": list(db.scalars(select(BookPage.page_number).where(
        BookPage.book_id == book.id, BookPage.needs_ocr.is_(True)).order_by(BookPage.page_number)).all())}


def _valid_ocr_box(page: BookPage, box: list[float]) -> bool:
    x0, y0, x1, y1 = box
    return (page.width > 0 and page.height > 0 and all(math.isfinite(v) for v in box)
            and 0 <= x0 < x1 <= page.width and 0 <= y0 < y1 <= page.height)


def _prepare_ocr(page: BookPage, data: OCRPageIn):
    from app.services.ocr_layout import order_ocr_lines
    from app.services.structure_detector import detect_structure

    lines = []
    for item in data.lines:
        if not _valid_ocr_box(page, item.bbox) or any(not _valid_ocr_box(page, word.bbox) for word in item.words):
            raise ApiError("INVALID_OCR", "Sahifa koordinatalari noto'g'ri.", 422)
        lines.append({"text": item.text.strip(), "bbox": item.bbox, "confidence": item.confidence,
                      "words": [word.model_dump() for word in item.words],
                      "size": 10, "bold": False, "x0": item.bbox[0]})
    lines, layout = order_ocr_lines(lines, page.width)
    text = "\n".join(line["text"] for line in lines)
    if len(text.strip()) < 24:
        raise ApiError("OCR_TOO_LITTLE_TEXT", "Sahifadan yetarli matn ajratilmadi; keyin qayta urinib ko'ring.", 422)
    # No silent truncation of the persisted text column.
    if len(text) > 60000:
        raise ApiError("OCR_TOO_MUCH_TEXT", "Sahifa matni saqlash chegarasidan oshdi; ko'rib chiqish kerak.", 422)
    structure = detect_structure([{"page_number": page.page_number, "width": page.width,
                                  "height": page.height, "text": text, "lines": lines, "ocr_used": True}])
    if layout != "original":
        structure.warnings.append({"page": page.page_number, "code": "OCR_LAYOUT_REVIEW",
            "message_uz": ("Ikki ustun taxmin qilindi; o'qish tartibini tekshiring." if layout == "two_columns"
                            else "Sahifa ustun yoki jadval bo'lishi mumkin; o'qish tartibini tekshiring.")})
    return lines, text, structure


def _ocr_geometry(page: BookPage, bbox, lines):
    if not bbox or not _valid_ocr_box(page, bbox):
        return None
    x0, y0, x1, y1 = bbox
    confidences = [line["confidence"] for line in lines
                   if line["confidence"] is not None
                   and line["bbox"][0] < x1 and line["bbox"][2] > x0
                   and line["bbox"][1] < y1 and line["bbox"][3] > y0]
    return {"bbox": bbox, "normalized_bbox": [x0 / page.width, y0 / page.height,
            x1 / page.width, y1 / page.height], "page_index": page.page_number - 1,
            "ocr_confidence": sum(confidences) / len(confidences) if confidences else None,
            "coordinate_space": "unrotated_crop_points"}


@router.post("/{book_id}/ocr/pages/{page_number}/preview")
def preview_browser_ocr(book_id: str, page_number: int, data: OCRPageIn, request: Request,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Inspect a page without changing existing OCR, exercises, answers or progress."""
    limit(request, "browser_ocr", 600, 3600, user.id)
    book = owned_book(db, user, book_id)
    if book.status != "ready":
        raise ApiError("BOOK_NOT_READY", "Kitob tahlili hali yakunlanmagan.", 409)
    page = db.scalar(select(BookPage).where(BookPage.book_id == book.id, BookPage.page_number == page_number))
    if not page:
        raise ApiError("PAGE_NOT_FOUND", "Sahifa topilmadi.", 404)
    lines, text, structure = _prepare_ocr(page, data)
    lesson = db.scalar(select(Lesson).where(Lesson.book_id == book.id,
                      Lesson.page_start <= page_number, Lesson.page_end >= page_number)
                      .order_by(Lesson.order_index).limit(1))
    return {"page_number": page_number, "already_processed": not page.needs_ocr,
            "text": text, "lines": lines, "lesson": {"id": lesson.id, "title": lesson.title} if lesson else None,
            "exercises": [{"title": ex.title, "instructions": ex.instructions, "type": ex.exercise_type,
                "geometry": _ocr_geometry(page, ex.bbox, lines), "needs_review": True,
                "questions": [{"number": q.number, "prompt": q.prompt} for q in ex.questions]}
                for ex in structure.exercises], "warnings": structure.warnings}


@router.post("/{book_id}/ocr/pages/{page_number}")
def save_browser_ocr(book_id: str, page_number: int, data: OCRPageIn, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Store one locally recognized page and append reviewable exercises; never replace existing work."""
    limit(request, "browser_ocr", 600, 3600, user.id)
    book = owned_book(db, user, book_id)
    # Serialize with other imports for the same book on PostgreSQL.
    db.scalar(select(Book).where(Book.id == book.id).with_for_update())
    if book.status != "ready":
        raise ApiError("BOOK_NOT_READY", "Kitob tahlili hali yakunlanmagan.", 409)
    page = db.scalar(select(BookPage).where(BookPage.book_id == book.id,
                                            BookPage.page_number == page_number).with_for_update())
    if not page:
        raise ApiError("PAGE_NOT_FOUND", "Sahifa topilmadi.", 404)
    if not page.needs_ocr:
        return {"already_processed": True, "exercises_added": 0, "words_added": 0}
    if page.text.strip():
        raise ApiError("MIXED_PAGE_REVIEW_REQUIRED", "Sahifada avvalgi matn mavjud; uni almashtirmaslik uchun faqat OCR sinovidan foydalaning.", 409)
    lines, text, structure = _prepare_ocr(page, data)
    lesson = db.scalar(select(Lesson).where(Lesson.book_id == book.id,
                     Lesson.page_start <= page_number, Lesson.page_end >= page_number)
                     .order_by(Lesson.order_index).limit(1))
    count = 0
    for ex in structure.exercises:
        if not ex.questions:
            continue
        geometry = _ocr_geometry(page, ex.bbox, lines)
        row = Exercise(book_id=book.id, lesson_id=lesson.id if lesson else None,
                       chapter_id=lesson.chapter_id if lesson else None,
                       exercise_type=ex.exercise_type, title=ex.title, instructions=ex.instructions,
                       ref=ex.ref, page_number=page_number, source="book", topic=ex.topic, bbox=geometry,
                       order_index=page_number * 100 + count, detection="ocr", needs_review=True)
        db.add(row)
        db.flush()
        for qi, q in enumerate(ex.questions):
            # OCR coordinates/answers can be unreliable: show editable cards, not PDF overlays or invented keys.
            blanks = [{**b, "bbox": None} for b in q.blanks]
            if ex.exercise_type == "fill_blank" and not blanks:
                blanks = [{"id": "b1", "bbox": None}]
            question = ExerciseQuestion(exercise_id=row.id, order_index=qi, number=q.number,
                     prompt=q.prompt, blanks=blanks, matching_pairs=q.matching_pairs,
                     correct_answers=[], answer_source="unknown", needs_review=True)
            db.add(question)
            db.flush()
            for option in q.options:
                db.add(ExerciseOption(question_id=question.id, letter=option["letter"], text=option["text"]))
        count += 1
    existing = {w.lower() for w in db.scalars(select(VocabularyWord.term).where(VocabularyWord.book_id == book.id)).all()}
    words_added = 0
    for v in structure.vocabulary:
        term = v["term"].strip()[:255]
        if not term or term.lower() in existing:
            continue
        # A dash in an English book may be a definition rather than an Uzbek translation.
        db.add(VocabularyWord(book_id=book.id, lesson_id=lesson.id if lesson else None,
               chapter_id=lesson.chapter_id if lesson else None, term=term,
               translation_uz="", definition_en=v.get("translation_uz", "")[:2000],
               page_number=page_number, source="book", needs_translation=True))
        existing.add(term.lower())
        words_added += 1
    page.text = text
    page.blocks = lines
    page.needs_ocr = False
    page.ocr_used = True
    page.has_warning = True  # OCR output always requires review.
    db.commit()
    return {"already_processed": False, "exercises_added": count, "words_added": words_added}
