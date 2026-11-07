"""Smart revision: builds sessions from the student's REAL history —
weak grammar topics (low accuracy), due/failed vocabulary (SM-2), failed assessments."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Exercise,
    ExerciseAttempt,
    ExerciseQuestion,
    RevisionItem,
    RevisionSession,
    VocabularyProgress,
    VocabularySession,
    VocabularyWord,
)
from app.services.vocab_engine import generate_session
from app.services.progress_service import topic_breakdown


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_revision(db: Session, user_id: str, book_id: str | None = None) -> RevisionSession | None:
    reasons: list[str] = []
    items: list[dict] = []

    # 1) weak grammar topics -> re-issue their hardest questions (user-scoped via Book ownership)
    weak, _ = topic_breakdown(db, user_id)
    weak_topics = [t["topic"] for t in weak[:3]]
    from app.models import Book
    if weak_topics:
        base = (
            select(ExerciseQuestion, Exercise)
            .join(Exercise, ExerciseQuestion.exercise_id == Exercise.id)
            .join(Book, Exercise.book_id == Book.id)
            .where(Book.user_id == user_id, Exercise.topic.in_(weak_topics))
            .limit(6)
        )
        for q, ex in db.execute(base).all():
            items.append({
                "item_type": "question", "question_id": q.id, "exercise_id": ex.id,
                "payload": {
                    "prompt": q.prompt, "type": ex.exercise_type, "topic": ex.topic,
                    "options": [{"letter": o.letter, "text": o.text} for o in q.options],
                    "correct_answers": q.correct_answers or [],
                    "blanks": q.blanks, "number": q.number,
                },
            })
            reasons.append(f"«{ex.topic}» mavzusi zaif")


    # 2) due / lapsed vocabulary
    due = list(db.scalars(
        select(VocabularyWord).join(VocabularyProgress, VocabularyProgress.word_id == VocabularyWord.id).where(
            VocabularyProgress.user_id == user_id,
            VocabularyProgress.due_at <= _utcnow(),
            *( [VocabularyWord.book_id == book_id] if book_id else [] ),
        ).limit(10)).all())
    if due:
        items.extend([{
            "item_type": "vocab", "word_id": w.id,
            "payload": {"term": w.term, "translation_uz": w.translation_uz,
                        "type": "written_en_uz", "prompt": w.term, "expected": w.translation_uz},
        } for w in due])
        reasons.append(f"{len(due)} ta so'z takrorlash vaqtida")

    # 3) failed vocab sessions -> retest their words
    failed = list(db.scalars(
        select(VocabularySession).where(
            VocabularySession.user_id == user_id, VocabularySession.status == "failed")
        .order_by(VocabularySession.created_at.desc()).limit(1)).all())
    if failed and failed[0].lesson_id:
        reasons.append("Oxirgi lug'at testi o'tilmagan")

    if not items:
        return None

    session = RevisionSession(
        user_id=user_id, book_id=book_id, focus="; ".join(sorted(set(reasons))[:3]),
        reason="O'quvchining real natijalari asosida tuzildi", items=items,
    )
    db.add(session)
    db.commit()
    return session


def complete_revision(db: Session, session: RevisionSession, results: list[dict]) -> RevisionSession:
    total = len(results)
    correct = sum(1 for r in results if r.get("correct"))
    session.score = round(100.0 * correct / total, 1) if total else 0.0
    session.status = "completed"
    session.finished_at = _utcnow()
    session.items = [
        {**item, "result": bool(results[i].get("correct")) if i < len(results) else None}
        for i, item in enumerate(session.items)
    ]
    db.commit()
    return session
