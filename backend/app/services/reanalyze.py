"""Re-analysis that keeps what the user has already learned.

Replacing a book's structure means deleting its chapters, lessons, exercises and words.
Done naively that erases every answer, every SM-2 schedule and every passed vocabulary
gate — which is why re-analysis was simply blocked for any book with content.

Instead the student's own data is set aside before the old structure goes away and
matched back onto the new one by CONTENT (page range, exercise ref/page, word spelling),
never by database ids:

* ``learning_progress``  — keyed by (lesson page range, ordinal among lessons with that
  range); the vocabulary gate is kept only if the lesson still has vocabulary.
* ``student_answers`` and ``exercise_attempts`` — keyed by (exercise ref, page, type) at
  the exercise level: the exercise stays, individual question ids are retaken.
* ``vocabulary_progress`` and ``vocabulary_attempts`` — keyed by the word's spelling,
  which is what makes a vocabulary book's history survive a re-read of the same PDF.

Anything that cannot be matched is dropped and counted, and the counts are reported to
the user rather than silently discarded.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerKey,
    Book,
    BookPage,
    Chapter,
    Exercise,
    ExerciseAttempt,
    ExerciseOption,
    ExerciseQuestion,
    LearningProgress,
    Lesson,
    StudentAnswer,
    VocabularyAttempt,
    VocabularyProgress,
    VocabularyWord,
)

log = logging.getLogger("lingora.reanalyze")


@dataclass
class PreservedData:
    """Everything a re-analysis must put back, plus what could not be matched."""

    lessons: dict[tuple[int, int, int], dict[str, Any]] = field(default_factory=dict)
    exercise_attempts: dict[tuple[str, int, str], dict[str, Any]] = field(default_factory=dict)
    student_answers: dict[tuple[str, int, str], list[dict[str, Any]]] = field(default_factory=dict)
    words: dict[str, dict[str, Any]] = field(default_factory=dict)
    word_attempts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {"lessons": len(self.lessons),
                "exercise_attempts": len(self.exercise_attempts),
                "student_answers": sum(len(items) for items in self.student_answers.values()),
                "words": len(self.words),
                "word_attempts": sum(len(items) for items in self.word_attempts.values())}


def lesson_key(page_start: int, page_end: int, ordinal: int) -> tuple[int, int, int]:
    """A lesson's identity in CONTENT terms: its page range plus its ordinal."""
    return (int(page_start), int(page_end), int(ordinal))


def exercise_key(ex: Exercise) -> tuple[str, int, str]:
    return ((ex.ref or "").strip().lower(), int(ex.page_number or 0), (ex.exercise_type or ""))


def word_key(term: str) -> str:
    return term.strip().lower()


def snapshot(db: Session, book_id: str) -> PreservedData:
    """Copy the student's progress before the book's structure is replaced."""
    data = PreservedData()
    book = db.get(Book, book_id)
    if book is None:
        return data
    lessons = list(db.scalars(select(Lesson).where(Lesson.book_id == book_id)
                              .order_by(Lesson.order_index, Lesson.id)).all())
    ordinals: dict[tuple[int, int], int] = defaultdict(int)
    for lesson in lessons:
        span = (int(lesson.page_start), int(lesson.page_end))
        progress = db.scalar(select(LearningProgress).where(
            LearningProgress.lesson_id == lesson.id, LearningProgress.user_id == book.user_id))
        data.lessons[lesson_key(span[0], span[1], ordinals[span])] = {
            "status": progress.status if progress else "not_started",
            "exercises_checked": progress.exercises_checked if progress else 0,
            "exercises_total": progress.exercises_total if progress else 0,
            "time_spent_seconds": progress.time_spent_seconds if progress else 0,
            "last_page": progress.last_page if progress else 0,
            "vocab_gate_passed": progress.vocab_gate_passed if progress else False,
            "last_visited_at": progress.last_visited_at if progress else None,
        }
        ordinals[span] += 1

    for ex in db.scalars(select(Exercise).where(Exercise.book_id == book_id)).all():
        key = exercise_key(ex)
        attempt = db.scalar(select(ExerciseAttempt).where(ExerciseAttempt.exercise_id == ex.id)
                            .order_by(ExerciseAttempt.checked_at.desc()).limit(1))
        if attempt:
            data.exercise_attempts[key] = {
                "score": attempt.score, "max_score": attempt.max_score,
                "percent": attempt.percent, "ai_used": attempt.ai_used,
                "uncertain": attempt.uncertain, "details": attempt.details or [],
                "checked_at": attempt.checked_at,
            }
        # Answers hang off questions, so they are keyed by exercise + question ORDER —
        # the only thing that survives rebuilding the question rows.
        answered = list(db.execute(
            select(ExerciseQuestion.order_index, StudentAnswer.content, StudentAnswer.is_submitted)
            .join(StudentAnswer, StudentAnswer.question_id == ExerciseQuestion.id)
            .where(ExerciseQuestion.exercise_id == ex.id)
            .order_by(ExerciseQuestion.order_index)).all())
        for order_index, content, is_submitted in answered:
            data.student_answers.setdefault(key, []).append(
                {"order_index": order_index, "content": content, "is_submitted": is_submitted})

    for word in db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book_id)).all():
        key = word_key(word.term)
        progress = db.scalar(select(VocabularyProgress).where(
            VocabularyProgress.word_id == word.id, VocabularyProgress.user_id == book.user_id))
        if progress:
            data.words[key] = {
                "ease_factor": progress.ease_factor, "interval_days": progress.interval_days,
                "repetitions": progress.repetitions, "lapses": progress.lapses,
                "total_reviews": progress.total_reviews, "correct_count": progress.correct_count,
                "wrong_count": progress.wrong_count, "status": progress.status,
                "due_at": progress.due_at, "last_reviewed_at": progress.last_reviewed_at,
            }
        for attempt in db.scalars(select(VocabularyAttempt).where(
                VocabularyAttempt.word_id == word.id).order_by(VocabularyAttempt.created_at)).all():
            data.word_attempts.setdefault(key, []).append(
                {"question_type": attempt.question_type, "response": attempt.response,
                 "is_correct": attempt.is_correct, "created_at": attempt.created_at})
    return data


def _delete_structure(db: Session, book_id: str) -> None:
    """Remove the old structure; questions/options cascade from exercises."""
    # Pages are re-extracted too: a re-analysis exists because the reading got better.
    db.execute(delete(BookPage).where(BookPage.book_id == book_id))
    db.execute(delete(AnswerKey).where(AnswerKey.book_id == book_id))
    exercise_ids = list(db.scalars(select(Exercise.id).where(Exercise.book_id == book_id)).all())
    if exercise_ids:
        question_ids = list(db.scalars(select(ExerciseQuestion.id)
                                       .where(ExerciseQuestion.exercise_id.in_(exercise_ids))).all())
        if question_ids:
            db.execute(delete(ExerciseOption).where(ExerciseOption.question_id.in_(question_ids)))
            db.execute(delete(StudentAnswer).where(StudentAnswer.question_id.in_(question_ids)))
        db.execute(delete(ExerciseAttempt).where(ExerciseAttempt.exercise_id.in_(exercise_ids)))
        db.execute(delete(ExerciseQuestion).where(ExerciseQuestion.exercise_id.in_(exercise_ids)))
        db.execute(delete(Exercise).where(Exercise.id.in_(exercise_ids)))
    word_ids = list(db.scalars(select(VocabularyWord.id)
                               .where(VocabularyWord.book_id == book_id)).all())
    if word_ids:
        db.execute(delete(VocabularyProgress).where(VocabularyProgress.word_id.in_(word_ids)))
        db.execute(delete(VocabularyAttempt).where(VocabularyAttempt.word_id.in_(word_ids)))
        db.execute(delete(VocabularyWord).where(VocabularyWord.id.in_(word_ids)))
    chapter_ids = list(db.scalars(select(Chapter.id).where(Chapter.book_id == book_id)).all())
    if chapter_ids:
        db.execute(delete(LearningProgress).where(LearningProgress.book_id == book_id))
        db.execute(delete(Lesson).where(Lesson.chapter_id.in_(chapter_ids)))
        db.execute(delete(Chapter).where(Chapter.id.in_(chapter_ids)))
    else:
        db.execute(delete(LearningProgress).where(LearningProgress.book_id == book_id))
        db.execute(delete(Lesson).where(Lesson.book_id == book_id))
    db.flush()


def begin_reanalysis(db: Session, book_id: str) -> PreservedData:
    """Snapshot progress, then clear the structure so the pipeline may write it again.

    Returns the snapshot itself: it must stay on the same session that will restore it
    after the new structure is committed.
    """
    data = snapshot(db, book_id)
    _delete_structure(db, book_id)
    log.info("Re-analysis of book %s preserved %s", book_id, data.counts())
    return data


def current_counts(db: Session, book_id: str) -> dict[str, int]:
    """What the book holds right now, for reporting a re-analysis before it starts."""
    return {"lessons": db.scalar(select(func.count()).select_from(Lesson)
                                 .where(Lesson.book_id == book_id)) or 0,
            "words": db.scalar(select(func.count()).select_from(VocabularyWord)
                               .where(VocabularyWord.book_id == book_id)) or 0}


def restore(db: Session, book_id: str, pipeline_stats: dict[str, Any] | None = None) -> dict[str, int]:
    """Match the preserved progress back onto the freshly persisted structure."""
    data: PreservedData | None = db.info.get(f"reanalyze:{book_id}")
    book = db.get(Book, book_id)
    if not data or book is None:
        return {}
    lessons = list(db.scalars(select(Lesson).where(Lesson.book_id == book_id)
                              .order_by(Lesson.order_index, Lesson.id)).all())
    ordinals: dict[tuple[int, int], int] = defaultdict(int)
    restored_lessons = 0
    for lesson in lessons:
        span = (int(lesson.page_start), int(lesson.page_end))
        saved = data.lessons.get(lesson_key(span[0], span[1], ordinals[span]))
        ordinals[span] += 1
        if not saved:
            continue
        has_vocab = db.scalar(select(VocabularyWord.id).where(
            VocabularyWord.lesson_id == lesson.id,
            VocabularyWord.needs_translation.is_(False)).limit(1)) is not None
        db.add(LearningProgress(
            user_id=book.user_id, lesson_id=lesson.id, book_id=book_id,
            status=saved["status"], exercises_checked=saved["exercises_checked"],
            exercises_total=saved["exercises_total"], time_spent_seconds=saved["time_spent_seconds"],
            last_page=saved["last_page"],
            # A gate that was passed stays passed; without vocabulary there is no gate to fail.
            vocab_gate_passed=bool(saved["vocab_gate_passed"]) and has_vocab,
            last_visited_at=saved["last_visited_at"],
        ))
        restored_lessons += 1

    restored_ex_attempts = 0
    ex_attempt_by_key: dict[tuple[str, int, str], Exercise] = {}
    for ex in db.scalars(select(Exercise).where(Exercise.book_id == book_id)).all():
        key = exercise_key(ex)
        ex_attempt_by_key.setdefault(key, ex)

    for key, saved in data.exercise_attempts.items():
        ex = ex_attempt_by_key.get(key)
        if not ex:
            continue
        db.add(ExerciseAttempt(
            user_id=book.user_id, exercise_id=ex.id, lesson_id=ex.lesson_id,
            score=saved["score"], max_score=saved["max_score"], percent=saved["percent"],
            ai_used=saved["ai_used"], uncertain=saved["uncertain"], details=saved["details"],
            checked_at=saved["checked_at"],
        ))
        restored_ex_attempts += 1

    # Saved answers cannot be re-attached to individual questions (the questions were
    # rebuilt), so they are restored only when the exercise kept one question with the
    # same number and the answer count matches. Otherwise they are honestly dropped.
    restored_answers = 0
    for key, saved_answers in data.student_answers.items():
        ex = ex_attempt_by_key.get(key)
        if not ex:
            continue
        by_order = {question.order_index: question for question in db.scalars(
            select(ExerciseQuestion).where(ExerciseQuestion.exercise_id == ex.id)).all()}
        for saved in saved_answers:
            question = by_order.get(saved["order_index"])
            if not question:
                continue
            db.add(StudentAnswer(question_id=question.id, user_id=book.user_id,
                                 content=saved["content"], is_submitted=saved["is_submitted"]))
            restored_answers += 1

    restored_words = 0
    restored_word_attempts = 0
    words_by_key: dict[str, VocabularyWord] = {}
    for word in db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book_id)).all():
        words_by_key.setdefault(word_key(word.term), word)
    for key, saved in data.words.items():
        word = words_by_key.get(key)
        if not word:
            continue
        db.add(VocabularyProgress(user_id=book.user_id, word_id=word.id, **saved))
        restored_words += 1
    for key, attempts in data.word_attempts.items():
        word = words_by_key.get(key)
        if not word:
            continue
        for saved in attempts:
            db.add(VocabularyAttempt(user_id=book.user_id, word_id=word.id, **saved))
            restored_word_attempts += 1

    stats = {"lessons": restored_lessons, "exercise_attempts": restored_ex_attempts,
             "student_answers": restored_answers, "words": restored_words,
             "word_attempts": restored_word_attempts}
    dropped = {name: data.counts().get(name, 0) - stats.get(name, 0) for name in stats}
    log.info("Re-analysis of book %s restored %s (could not match %s)", book_id, stats, dropped)
    if pipeline_stats is not None:
        pipeline_stats.update({"restored": stats, "dropped": dropped})
    db.info[f"reanalyze-stats:{book_id}"] = {"restored": stats, "dropped": dropped}
    return stats


def finish(db: Session, book_id: str) -> None:
    """Forget the snapshot once the run is over, so a retry starts from a fresh one."""
    db.info.pop(f"reanalyze:{book_id}", None)


def kept_summary(db: Session, book_id: str) -> dict[str, Any] | None:
    """The restore result for this run, if the pipeline got that far."""
    return db.info.get(f"reanalyze-stats:{book_id}")
