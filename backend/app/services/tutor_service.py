"""Context-aware AI personal tutor.

The tutor always receives REAL context from the database: which book/lesson/exercise is
open, the lesson's grammar explanation, relevant vocabulary and the student's recent
mistakes. It responds in Uzbek with English examples and is instructed never to invent
book content. Requires a configured AI provider — otherwise 503 AI_NOT_CONFIGURED.
"""
import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AIConversation,
    AIMessage,
    Exercise,
    ExerciseAttempt,
    Lesson,
    VocabularyWord,
)
from app.services.ai import usage as usage_service
from app.services.ai.provider import AIResponse, ChatMessage, get_provider
from app.schemas import ExtraExerciseOut

log = logging.getLogger("lingora.tutor")

MAX_HISTORY = 12

SYSTEM_BASE = (
    "Siz Lingora platformasining shaxsiy ingliz tili murabbiyisiz. O'quvchi o'zbek tilida so'raydi, "
    "siz o'zbek tilida tushuntirasiz; misollar va terminlar inglizcha bo'ladi.\n"
    "Qoidalar:\n"
    "1. Kontekstga tayan — o'quvchining kitobi, darsi va oldingi xatolari quyida keltirilgan.\n"
    "2. Kitobda yo'q bo'lgan kontentni (sahifa, mashq raqami, qoida) O'YLAB TOPMANG. Kitob kontekstidan "
    "tashqari umumiy grammatika tushuntirishlariga ruxsat beriladi.\n"
    "3. Javoblar aniq, sodda, tartiblangan bo'lsin (qisqa paragraflar, zarur bo'lsa ro'yxat va misollar).\n"
    "4. O'quvchi xatosini tushuntirsangiz, avval nima uchun xato ekanini, keyin to'g'ri qoidani, "
    "oxirida 1-2 mashq misolini bering.\n"
    "5. O'zbek tili tabiiy va soddа bo'lsin (lotin yozuvi)."
)

EXTRA_EXERCISE_SYSTEM = (
    "Siz ingliz tili mashq generatorysisz. Berilgan mavzu va dars kontekstiga qarab mashqlar tuzasiz. "
    "FAQAT JSON qaytaring: {\"exercises\":[{\"exercise_type\":\"fill_blank|multiple_choice|translation|"
    "true_false\",\"instructions\":\"...(uz)\",\"topic\":\"...\",\"questions\":[{\"number\":\"1\","
    "\"prompt\":\"She _____ to school.\",\"options\":[{\"letter\":\"A\",\"text\":\"...\"}],"
    "\"correct_answers\":[\"goes\"]}]}]}. Kamida 3 ta savol, daraja o'quvchiga mos bo'lsin."
)


def build_context(db: Session, user_id: str, conv: AIConversation) -> str:
    parts: list[str] = ["=== KONTEKST ==="]
    lesson: Lesson | None = db.get(Lesson, conv.lesson_id) if conv.lesson_id else None
    book_title = ""
    if conv.book_id:
        from app.models import Book

        book = db.get(Book, conv.book_id)
        book_title = book.title if book else ""
    if book_title:
        parts.append(f"O'quvchining kitobi: «{book_title}»")
    if lesson:
        parts.append(f"Ochilgan dars: «{lesson.title}» (sahifalar {lesson.page_start}-{lesson.page_end})")
        if lesson.topic:
            parts.append(f"Dars mavzusi: {lesson.topic}")
        if lesson.grammar_explanation_uz:
            parts.append(f"Dars tushuntirishi (uz): {lesson.grammar_explanation_uz[:1500]}")
        words = list(db.scalars(select(VocabularyWord).where(
            VocabularyWord.lesson_id == lesson.id).limit(15)).all())
        if words:
            parts.append("Dars lug'ati: " + "; ".join(f"{w.term} — {w.translation_uz}" for w in words))
    if conv.exercise_id:
        ex = db.get(Exercise, conv.exercise_id)
        if ex:
            parts.append(f"Muhokama qilinayotgan mashq: {ex.ref} (sahifa {ex.page_number}, {ex.exercise_type})")
            parts.append(f"Mashq ko'rsatmasi: {ex.instructions[:300]}")
            for q in ex.questions[:6]:
                parts.append(f"  - Savol {q.number or q.order_index + 1}: {q.prompt[:200]}")
    # recent mistakes (last 10 wrong answers in this book)
    wrong = list(db.scalars(
        select(ExerciseAttempt).where(
            ExerciseAttempt.user_id == user_id,
            ExerciseAttempt.book_id == conv.book_id if conv.book_id else ExerciseAttempt.user_id == user_id,
        ).order_by(ExerciseAttempt.created_at.desc()).limit(5)).all())
    mistake_lines = []
    for att in wrong:
        for d in att.details:
            if d.get("correct") is False:
                mistake_lines.append(f"{d.get('number','?')}: yozdi «{d.get('given','')}», to'g'risi «{d.get('expected','')}»")
    if mistake_lines:
        parts.append("O'quvchining so'nggi xatolari: " + "; ".join(mistake_lines[:8]))
    return "\n".join(parts)


def tutor_reply(db: Session, user_id: str, conv: AIConversation, user_message: str) -> tuple[AIMessage, AIResponse]:
    usage_service.enforce_ai_quota(db, user_id, "tutor")
    provider = get_provider()
    history = list(db.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conv.id)
        .order_by(AIMessage.created_at.desc()).limit(MAX_HISTORY)).all())
    history.reverse()

    messages = [ChatMessage(role="system", content=SYSTEM_BASE + "\n\n" + build_context(db, user_id, conv))]
    for m in history:
        if m.role in ("user", "assistant") and m.content:
            messages.append(ChatMessage(role=m.role, content=m.content[:4000]))
    messages.append(ChatMessage(role="user", content=user_message))

    resp = provider.complete(messages, max_tokens=1500, temperature=0.4)
    usage_service.record_usage(db, user_id, "tutor", provider.name, resp.model,
                               resp.tokens_in, resp.tokens_out)
    msg = AIMessage(conversation_id=conv.id, role="assistant", content=resp.content,
                    model=resp.model, tokens_in=resp.tokens_in, tokens_out=resp.tokens_out)
    db.add(msg)
    if conv.title == "Yangi suhbat":
        conv.title = user_message[:60]
    db.commit()
    return msg, resp


def generate_extra_exercises(db: Session, user_id: str, lesson: Lesson,
                             count: int = 3) -> list[ExtraExerciseOut]:
    """Generate additional practice exercises for a lesson (returned to client, stored as message meta)."""
    from pydantic import BaseModel, Field

    class _Q(BaseModel):
        number: str = "1"
        prompt: str
        options: list[dict] = []
        correct_answers: list[str] = []

    class _Ex(BaseModel):
        exercise_type: str
        instructions: str = ""
        topic: str = ""
        questions: list[_Q]

    class _Out(BaseModel):
        exercises: list[_Ex]

    usage_service.enforce_ai_quota(db, user_id, "extra_exercises")
    words = list(db.scalars(select(VocabularyWord).where(
        VocabularyWord.lesson_id == lesson.id).limit(10)).all())
    context = {
        "lesson_title": lesson.title, "topic": lesson.topic,
        "grammar_uz": (lesson.grammar_explanation_uz or "")[:800],
        "vocabulary": [f"{w.term} — {w.translation_uz}" for w in words],
        "page_excerpt": (lesson.summary or "")[:600],
    }
    provider = get_provider()
    schema, resp = structured(
        _Out,
        [ChatMessage(role="system", content=EXTRA_EXERCISE_SYSTEM),
         ChatMessage(role="user", content=json.dumps(context, ensure_ascii=False))],
        max_tokens=2500,
    )
    usage_service.record_usage(db, user_id, "extra_exercises", provider.name, resp.model,
                               resp.tokens_in, resp.tokens_out)
    out: list[ExtraExerciseOut] = []
    for ex in schema.exercises[:count]:
        qs = []
        for q in ex.questions:
            qs.append({
                "number": q.number, "prompt": q.prompt,
                "options": [o for o in q.options if o.get("text")],
                "correct_answers": q.correct_answers,
            })
        out.append(ExtraExerciseOut(
            exercise_type=ex.exercise_type, instructions=ex.instructions,
            topic=ex.topic or lesson.topic, questions=qs))
    return out
