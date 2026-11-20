"""Vocabulary: word lists, word illustrations, challenge sessions, SM-2 review flow."""
import base64
import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_profile, get_current_user, owned_book
from app.core.errors import ApiError
from app.core.rate_limit import limit
from app.db.session import get_db
from app.models import (
    Book,
    LearningProgress,
    Lesson,
    Profile,
    User,
    VocabularyProgress,
    VocabularySession,
    VocabularyWord,
)
from app.schemas import (
    OkOut,
    VocabAnswerIn,
    VocabAnswerOut,
    VocabSessionCompleteOut,
    VocabSessionItemOut,
    VocabSessionOut,
    VocabWordOut,
)
from app.services import vocab_engine

log = logging.getLogger("lingora.vocab")
router = APIRouter(tags=["vocabulary"])


@router.get("/books/{book_id}/vocabulary", response_model=list[VocabWordOut])
def book_vocabulary(book_id: str, lesson_id: str = "", limit_words: int = Query(default=2000, ge=1, le=5000),
                    offset: int = Query(default=0, ge=0),
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Every word of the book, in page order.

    A dictionary book has hundreds of words (4000 Essential English Words 1 has 600), so
    the old fixed limit of 500 silently hid the rest; paging is explicit instead.
    """
    owned_book(db, user, book_id)
    q = select(VocabularyWord).where(VocabularyWord.book_id == book_id)
    if lesson_id:
        q = q.where(VocabularyWord.lesson_id == lesson_id)
    words = db.scalars(q.order_by(VocabularyWord.page_number, VocabularyWord.term)
                       .offset(offset).limit(limit_words)).all()
    return words


@router.get("/books/{book_id}/vocabulary/{word_id}/picture")
@router.get("/books/{book_id}/vocabulary/{word_id}/picture.png")
def word_picture(book_id: str, word_id: str, request: Request, as_json: bool | None = Query(default=None),
                 max_edge: int = Query(default=1000, ge=200, le=2400),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Illustration of one word, cropped from the ORIGINAL PDF page.

    The stored box is normalized, so the crop is rendered at a real, high resolution
    (>= 200 DPI) instead of a downscaled screenshot: pictures stay sharp on retina
    screens and in full-screen view. Only the authenticated owner can read it.
    """
    book = owned_book(db, user, book_id)
    word = db.get(VocabularyWord, word_id)
    if not word or word.book_id != book.id:
        raise ApiError("WORD_NOT_FOUND", "So'z topilmadi.", 404)
    if not word.picture_page or not word.picture_bbox:
        raise ApiError("PICTURE_NOT_FOUND", "Bu so'z uchun rasm aniqlanmagan.", 404)
    from app.services.ai import vision_regions
    png = vision_regions.crop_png(book, word.picture_page, list(word.picture_bbox),
                                  pad_ratio=0.01, dpi=220, max_edge=max_edge)
    # "/picture.png" is the raw image; "/picture" is JSON unless ?as_json=false is passed.
    raw = request.url.path.endswith(".png") if as_json is None else not as_json
    if raw:
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})
    return {"word_id": word.id, "page": word.picture_page, "bbox": list(word.picture_bbox),
            "coordinate_space": "normalized_0_1",
            "data_url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}


@router.get("/vocabulary/due")
def due_words(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(
        select(VocabularyWord, VocabularyProgress)
        .join(VocabularyProgress, VocabularyProgress.word_id == VocabularyWord.id)
        .where(VocabularyProgress.user_id == user.id,
               VocabularyProgress.due_at <= func.now())
        .limit(50)
    ).all()
    return [{"word": VocabWordOut.model_validate(w).model_dump(),
             "due_at": p.due_at, "status": p.status, "interval_days": p.interval_days}
            for w, p in rows]


@router.get("/vocabulary/stats")
def vocab_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    book_vocab_count = int(db.scalar(
        select(func.count(VocabularyWord.id)).join(Book, VocabularyWord.book_id == Book.id).where(Book.user_id == user.id)
    ) or 0)
    prog_total = int(db.scalar(select(func.count(VocabularyProgress.id)).where(
        VocabularyProgress.user_id == user.id)) or 0)
    total = max(book_vocab_count, prog_total)
    mastered = int(db.scalar(select(func.count(VocabularyProgress.id)).where(
        VocabularyProgress.user_id == user.id, VocabularyProgress.status == "mastered")) or 0)
    due = int(db.scalar(select(func.count(VocabularyProgress.id)).where(
        VocabularyProgress.user_id == user.id,
        VocabularyProgress.due_at <= func.now())) or 0)
    return {"learning": max(0, total - mastered), "mastered": mastered, "due": due, "total": total}


@router.post("/vocabulary/sessions", response_model=VocabSessionOut, status_code=201)
def create_session(request: Request, book_id: str = "", lesson_id: str = "",
                   kind: str = "practice", db: Session = Depends(get_db),
                   user: User = Depends(get_current_user),
                   profile: Profile = Depends(get_current_profile)):
    limit(request, "vocab_session", 30, 3600, user.id)
    if kind not in ("practice", "lesson_gate", "review", "custom"):
        kind = "practice"
    if lesson_id:
        lesson = db.get(Lesson, lesson_id)
        if not lesson:
            raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
        book = db.get(Book, lesson.book_id)
        if not book or book.user_id != user.id:
            raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
        book_id = book.id
        if kind == "practice":
            kind = "lesson_gate"
        if kind == "lesson_gate":
            prev = db.scalar(select(Lesson).where(
                Lesson.book_id == book.id, Lesson.order_index < lesson.order_index)
                .order_by(Lesson.order_index.desc()).limit(1))
            if prev and profile.vocabulary_gating:
                prev_vocab = db.query(VocabularyWord.id).filter(
                    VocabularyWord.lesson_id == prev.id, VocabularyWord.needs_translation.is_(False)).count() > 0
                lp = db.scalar(select(LearningProgress).where(
                    LearningProgress.user_id == user.id, LearningProgress.lesson_id == prev.id))
                if prev_vocab and not (lp and lp.vocab_gate_passed):
                    raise ApiError(
                        "LESSON_LOCKED",
                        "Avval oldingi darsning lug'at testini o'tishingiz kerak. "
                        "Bu — o'quv tartibi talabi.",
                        403,
                    )
    elif book_id:
        owned_book(db, user, book_id)

    session = vocab_engine.generate_session(
        db, user_id=user.id, book_id=book_id or None, lesson_id=lesson_id or None,
        kind=kind, required_score=profile.vocab_pass_score,
    )
    db.commit()
    if not session.items:
        raise ApiError(
            "NO_VOCABULARY",
            "Bu dars/kitobda hali lug'at so'zlari topilmadi yoki takrorlash uchun so'zlar yo'q.",
            404,
        )
    return _session_out(session)


def _session_out(s: VocabularySession) -> VocabSessionOut:
    return VocabSessionOut(
        id=s.id, kind=s.kind, status=s.status, required_score=s.required_score, score=s.score,
        total_items=len(s.items),
        answered_items=sum(1 for i in s.items if i.get("first_correct") is not None and not i.get("requeued")),
        items=[VocabSessionItemOut(
            item_id=i["item_id"], word_id=i["word_id"], type=i["type"], prompt=i["prompt"],
            options=i.get("options", []), audio_text=i.get("audio_text", ""),
            sentence=i.get("sentence", ""), hint=i.get("hint", ""),
        ) for i in s.items],
    )


@router.get("/vocabulary/sessions/{session_id}", response_model=VocabSessionOut)
def get_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _owned_session(db, user, session_id)
    return _session_out(s)


@router.post("/vocabulary/sessions/{session_id}/answer", response_model=VocabAnswerOut)
def answer(session_id: str, data: VocabAnswerIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    s = _owned_session(db, user, session_id)
    if s.status != "active":
        raise ApiError("SESSION_CLOSED", "Bu test allaqachon yakunlangan.", 409)
    item = next((i for i in s.items if i["item_id"] == data.item_id), None)
    if not item:
        raise ApiError("ITEM_NOT_FOUND", "Savol topilmadi.", 404)
    result = vocab_engine.answer_item(db, s, item, data.response)
    return VocabAnswerOut(
        item_id=data.item_id,
        correct=result["correct"],
        expected=result["expected"],
        response=data.response,
        word_id=result["word_id"],
        term=result["term"],
        translation_uz=result["translation_uz"],
        requeued_item=VocabSessionItemOut(
            item_id=result["requeued_item"]["item_id"],
            word_id=result["requeued_item"]["word_id"],
            type=result["requeued_item"]["type"],
            prompt=result["requeued_item"]["prompt"],
            options=result["requeued_item"].get("options", []),
            audio_text=result["requeued_item"].get("audio_text", ""),
            sentence=result["requeued_item"].get("sentence", ""),
            hint=result["requeued_item"].get("hint", ""),
        ) if result.get("requeued_item") else None,
    )


@router.post("/vocabulary/sessions/{session_id}/complete", response_model=VocabSessionCompleteOut)
def complete(session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _owned_session(db, user, session_id)
    if s.status != "active":
        return VocabSessionCompleteOut(
            status=s.status, score=s.score, required_score=s.required_score,
            passed=(s.status == "passed"), gate_opened=False,
            message_uz="Bu test yakunlangan.")
    result = vocab_engine.complete_session(db, s)
    return VocabSessionCompleteOut(**result)


@router.get("/vocabulary/progress")
def vocab_progress_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(
        select(VocabularyWord, VocabularyProgress)
        .join(VocabularyProgress, VocabularyProgress.word_id == VocabularyWord.id)
        .where(VocabularyProgress.user_id == user.id)
        .order_by(VocabularyProgress.due_at)
        .limit(200)
    ).all()
    return [{
        "term": w.term, "translation_uz": w.translation_uz, "status": p.status,
        "due_at": p.due_at, "interval_days": p.interval_days, "repetitions": p.repetitions,
        "lapses": p.lapses, "accuracy": round(100.0 * p.correct_count / max(p.total_reviews, 1), 1),
        "last_reviewed_at": p.last_reviewed_at,
    } for w, p in rows]


def _owned_session(db: Session, user: User, session_id: str) -> VocabularySession:
    s = db.get(VocabularySession, session_id)
    if not s or s.user_id != user.id:
        raise ApiError("SESSION_NOT_FOUND", "Test topilmadi.", 404)
    return s
