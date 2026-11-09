"""Regression tests for grading edge cases and vocabulary retry mechanisms."""
import pytest
from sqlalchemy import select

from app.models import Book, Exercise, ExerciseQuestion, Lesson, User, VocabularySession, VocabularyWord
from app.services import grading as grading_engine
from app.services import vocab_engine


def test_matching_grading_stable_indices():
    """Matching accepts pair indexes or text correctly and requires all pairs to match."""
    q = ExerciseQuestion(
        order_index=0,
        prompt="Match words",
        matching_pairs=[
            {"left": "big", "right": "katta"},
            {"left": "small", "right": "kichik"},
            {"left": "fast", "right": "tez"},
        ],
    )
    # Mock exercise relationship
    ex = Exercise(exercise_type="matching")
    q.exercise = ex

    # Partial answers -> False
    ok, rep = grading_engine.grade_question_deterministic(q, {"pairs": {"0": "katta", "1": "kichik"}})
    assert ok is False
    assert rep == "2/3"

    # All matched by text or normalized form -> True
    ok2, rep2 = grading_engine.grade_question_deterministic(q, {"pairs": {"0": "katta", "1": "kichik", "2": "tez"}})
    assert ok2 is True
    assert rep2 == "3/3"


def test_multi_blank_grading_requires_all_blanks():
    """Every blank must be filled correctly; first blank right does not mark question correct."""
    q = ExerciseQuestion(
        order_index=0,
        prompt="She _____ (go) to school and _____ (read) books.",
        blanks=[{"id": "b1"}, {"id": "b2"}],
        correct_answers=["goes", "reads"],
    )
    ex = Exercise(exercise_type="fill_blank")
    q.exercise = ex

    # Only first blank filled
    ok1, _ = grading_engine.grade_question_deterministic(q, {"blanks": {"b1": "goes", "b2": ""}})
    assert ok1 is False

    # Second blank wrong (different word)
    ok2, _ = grading_engine.grade_question_deterministic(q, {"blanks": {"b1": "goes", "b2": "sleeping"}})
    assert ok2 is False

    # Both blanks correct
    ok3, _ = grading_engine.grade_question_deterministic(q, {"blanks": {"b1": "goes", "b2": "reads"}})
    assert ok3 is True


def test_vocabulary_retry_requeues_and_scores_first_attempt(client, db):
    """Wrong vocab answers are requeued at the end of session, but score reflects first attempts strictly."""
    reg = client.post("/api/v1/auth/register", json={
        "email": "vocab_retry@lingora.uz", "password": "Password12345", "full_name": "Vocab Tester"
    }).json()
    u = db.scalar(select(User).where(User.email == "vocab_retry@lingora.uz"))

    book = Book(user_id=u.id, title="Test Book", storage_path="books/u/t.pdf")
    db.add(book)
    db.flush()

    w1 = VocabularyWord(book_id=book.id, term="brave", translation_uz="jasur")
    w2 = VocabularyWord(book_id=book.id, term="clever", translation_uz="aqlli")
    db.add_all([w1, w2])
    db.commit()

    session = vocab_engine.generate_session(
        db, user_id=u.id, book_id=book.id, lesson_id=None, kind="practice", required_score=80, limit=2
    )
    db.commit()
    assert len(session.items) == 2

    first_item = session.items[0]
    # Intentionally answer first item WRONG
    res1 = vocab_engine.answer_item(db, session, first_item, "noto'g'ri javob")
    assert res1["correct"] is False
    assert res1["requeued_item"] is not None
    assert len(session.items) == 3  # re-queued item added to queue!

    # Answer second original item CORRECTLY
    second_item = session.items[1]
    res2 = vocab_engine.answer_item(db, session, second_item, second_item["expected"])
    assert res2["correct"] is True

    # Answer requeued retry item CORRECTLY
    requeued = session.items[2]
    res3 = vocab_engine.answer_item(db, session, requeued, requeued["expected"])
    assert res3["correct"] is True

    # Complete session: score must be based on FIRST attempts: 1 correct out of 2 = 50.0%
    summary = vocab_engine.complete_session(db, session)
    assert summary["score"] == 50.0
    assert summary["passed"] is False  # required was 80
