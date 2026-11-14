"""AI personal tutor: context-aware conversations + extra exercise generation."""
import json
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import limit
from app.db.session import get_db
from app.models import AIConversation, AIMessage, Book, Exercise, Lesson, User
from app.schemas import (
    ConversationCreateIn,
    ConversationOut,
    ExtraExerciseOut,
    MessageOut,
    MessageSendIn,
    TutorMessageOut,
)
from app.services.ai import usage as usage_service
from app.services.ai.provider import AINotConfigured, get_provider
from app.services.tutor_service import generate_extra_exercises, tutor_reply

log = logging.getLogger("lingora.tutor")
router = APIRouter(prefix="/tutor", tags=["tutor"])


from app.services.ai.translator import TranslationIn


@router.post("/translate")
def translate_text(data: TranslationIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Translate explicitly provided text only, with per-user rate and AI quotas."""
    limit(request, "translator", 60, 3600, user.id)
    if not data.consent_text_to_provider:
        raise ApiError("AI_TEXT_CONSENT_REQUIRED", "Matnni AI xizmatiga yuborishga rozilik kerak.", 422)
    if not data.text.strip():
        raise ApiError("EMPTY_TEXT", "Tarjima uchun matn kiriting.", 422)
    from app.services.ai.translator import translate
    return translate(db, user.id, data)


@router.get("/status")
def tutor_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.core.config import settings as cfg

    return {
        "available": cfg.ai_configured,
        "ai_configured": cfg.ai_configured,
        "configured": cfg.ai_configured,  # for frontend compatibility
        "provider": cfg.ai_provider if cfg.ai_configured else "none",
        "model": cfg.ai_model if cfg.ai_configured else "none",
        "calls_today": usage_service.ai_calls_today(db, user.id),
    }


def _verify_tutor_scope(db: Session, user: User, book_id: str | None, lesson_id: str | None, exercise_id: str | None) -> tuple[str | None, str | None, str | None]:
    """Strict ownership & hierarchy check:
    - If book_id: book must belong to user.
    - If lesson_id: lesson must exist, its book must belong to user, and if book_id was passed it must match.
    - If exercise_id: exercise must exist, its book must belong to user, and must match lesson/book.
    """
    resolved_book_id = book_id
    resolved_lesson_id = lesson_id
    resolved_exercise_id = exercise_id

    if resolved_book_id:
        book = db.get(Book, resolved_book_id)
        if not book or book.user_id != user.id:
            raise ApiError("BOOK_NOT_FOUND", "Kitob topilmadi.", 404)

    if resolved_lesson_id:
        lesson = db.get(Lesson, resolved_lesson_id)
        if not lesson:
            raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
        lesson_book = db.get(Book, lesson.book_id)
        if not lesson_book or lesson_book.user_id != user.id:
            raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
        if resolved_book_id and lesson.book_id != resolved_book_id:
            raise ApiError("INVALID_SCOPE", "Ko'rsatilgan dars berilgan kitobga tegishli emas.", 400)
        resolved_book_id = lesson.book_id

    if resolved_exercise_id:
        ex = db.get(Exercise, resolved_exercise_id)
        if not ex:
            raise ApiError("EXERCISE_NOT_FOUND", "Mashq topilmadi.", 404)
        ex_book = db.get(Book, ex.book_id)
        if not ex_book or ex_book.user_id != user.id:
            raise ApiError("EXERCISE_NOT_FOUND", "Mashq topilmadi.", 404)
        if resolved_book_id and ex.book_id != resolved_book_id:
            raise ApiError("INVALID_SCOPE", "Ko'rsatilgan mashq berilgan kitobga tegishli emas.", 400)
        if resolved_lesson_id and ex.lesson_id and ex.lesson_id != resolved_lesson_id:
            raise ApiError("INVALID_SCOPE", "Ko'rsatilgan mashq berilgan darsga tegishli emas.", 400)
        resolved_book_id = ex.book_id
        if ex.lesson_id and not resolved_lesson_id:
            resolved_lesson_id = ex.lesson_id

    return resolved_book_id, resolved_lesson_id, resolved_exercise_id


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(data: ConversationCreateIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    b_id, l_id, e_id = _verify_tutor_scope(db, user, data.book_id, data.lesson_id, data.exercise_id)
    conv = AIConversation(user_id=user.id, book_id=b_id, lesson_id=l_id,
                          exercise_id=e_id, title=data.title[:255])
    db.add(conv)
    db.commit()
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(db.scalars(select(AIConversation).where(AIConversation.user_id == user.id)
                           .order_by(AIConversation.updated_at.desc()).limit(50)).all())


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _owned_conversation(db, user, conversation_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = _owned_conversation(db, user, conversation_id)
    return list(db.scalars(select(AIMessage).where(AIMessage.conversation_id == conv.id)
                           .order_by(AIMessage.created_at)).all())


@router.post("/conversations/{conversation_id}/messages", response_model=TutorMessageOut)
def send_message(conversation_id: str, data: MessageSendIn, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    limit(request, "tutor", 40, 3600, user.id)
    conv = _owned_conversation(db, user, conversation_id)
    db.add(AIMessage(conversation_id=conv.id, role="user", content=data.content))
    db.commit()
    try:
        msg, _resp = tutor_reply(db, user.id, conv, data.content)
    except AINotConfigured:
        raise
    except Exception as e:
        log.exception("tutor failed")
        raise ApiError("AI_PROVIDER_ERROR", getattr(e, "message_uz", None) or
                       "AI murabbiy javob bermadi. Keyinroq qayta urinib ko'ring.", 502)
    # detect requested extra exercises marker
    extras: list[ExtraExerciseOut] = []
    if "mashq tuz" in data.content.lower() or "qo'shimcha mashq" in data.content.lower():
        if conv.lesson_id:
            lesson = db.get(Lesson, conv.lesson_id)
            if lesson:
                try:
                    extras = generate_extra_exercises(db, user.id, lesson)
                except Exception as e:
                    log.warning("extra exercises failed: %s", e)
    return TutorMessageOut(message=MessageOut.model_validate(msg), extra_exercises=extras)


@router.post("/lessons/{lesson_id}/extra-exercises", response_model=list[ExtraExerciseOut])
def extra_exercises(lesson_id: str, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    limit(request, "extra_exercises", 10, 3600, user.id)
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
    book = db.get(Book, lesson.book_id)
    if not book or book.user_id != user.id:
        raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
    return generate_extra_exercises(db, user.id, lesson)


@router.delete("/conversations/{conversation_id}", response_model=dict)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    conv = _owned_conversation(db, user, conversation_id)
    db.delete(conv)
    db.commit()
    return {"ok": True}


def _owned_conversation(db: Session, user: User, conversation_id: str) -> AIConversation:
    conv = db.get(AIConversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise ApiError("CONVERSATION_NOT_FOUND", "Suhbat topilmadi.", 404)
    return conv
