"""Books: secure upload, listing, structure, status, file streaming, deletion, re-analysis."""
import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
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
    LearningProgress,
    Lesson,
    ProcessingJob,
    Profile,
    User,
    VocabularyWord,
)
from app.schemas import BookOut, BookStructureOut, ChapterOut, JobOut, LessonOut, OkOut, PageOut
from app.services.pdf_extractor import ocr_available, validate_and_open
from app.services.storage import get_storage
from app.services.tasks import enqueue_book_analysis

log = logging.getLogger("lingora.books")
router = APIRouter(prefix="/books", tags=["books"])


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
    try:
        get_storage().delete(book.storage_path)
    except Exception:
        log.warning("storage delete failed for %s", book.id)
    db.delete(book)  # cascades pages/structure/vocab/attempts
    db.commit()
    return OkOut(message_uz="Kitob va unga oid barcha ma'lumotlar o'chirildi.")


@router.get("/{book_id}/file")
def download_book(book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """PDF stream for the reader (pdf.js fetches this URL with the auth header). Files stay private."""
    book = owned_book(db, user, book_id)
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
    if book.status == "processing":
        raise ApiError("ALREADY_PROCESSING", "Kitob hozir tahlil qilinmoqda.", 409)
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
        has_vocab = db.query(VocabularyWord.id).filter(VocabularyWord.lesson_id == l.id).count() > 0
        locked = gating and i > 0 and not prev_passed
        gate_ok = (not has_vocab) or bool(p.vocab_gate_passed if p else False)
        out[l.id] = {
            "status": p.status if p else "not_started",
            "exercises_checked": p.exercises_checked if p else 0,
            "time_spent_seconds": p.time_spent_seconds if p else 0,
            "last_page": p.last_page if p else 0,
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
               ExerciseQuestion.answer_source.in_(["key", "ai"]))) or 0)
    ocr_pages = int(db.query(BookPage.id).filter(BookPage.book_id == book.id,
                                                 BookPage.ocr_used.is_(True)).count())
    warn_pages = int(db.query(BookPage.id).filter(BookPage.book_id == book.id,
                                                  BookPage.has_warning.is_(True)).count())
    coverage = {
        "exercises": n_ex, "questions": n_q, "questions_with_key": n_with_key,
        "vocabulary": n_vocab, "pages_ocr_used": ocr_pages, "pages_with_warnings": warn_pages,
        "ocr_available": ocr_available(),
    }
    return BookStructureOut(
        book=BookOut.model_validate(book),
        chapters=[ChapterOut.model_validate(c) for c in chapters],
        lessons=[LessonOut.model_validate(l) for l in lessons],
        lessons_progress=locks,
        coverage=coverage,
        answer_key_pages=key_pages,
    )


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
        blocks=page.blocks, images=page.images, needs_ocr=page.needs_ocr,
        ocr_used=page.ocr_used, has_warning=page.has_warning,
    )
