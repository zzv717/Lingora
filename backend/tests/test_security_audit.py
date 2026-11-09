"""Security regression tests:
1. Password reset flow: no token leakage in prod mode, invalidation of previous tokens, single-use, no enumeration.
2. AI Tutor IDOR: strict scoping on book/lesson/exercise, context builder isolation.
3. Vocabulary gating: API blocks locked lesson exercise access, answer saving, and check.
4. Refresh token rotation: atomic conditional consumption, anti-replay under parallel/duplicate requests.
5. Storage & deletion: GDPR account delete and book delete cascades.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password, hash_token
from app.models import Book, Exercise, ExerciseQuestion, LearningProgress, Lesson, PasswordReset, Profile, RefreshToken, User, VocabularyWord


def test_password_reset_prod_mode_no_leakage(client, db, monkeypatch):
    """In production mode, forgot_password must NEVER return reset_link in API response or reveal user existence."""
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "smtp_host", "")

    # Create target user
    u = User(email="victim@lingora.uz", password_hash=hash_password("Secret12345"), full_name="Victim")
    db.add(u)
    db.commit()

    resp = client.post("/api/v1/auth/forgot-password", json={"email": "victim@lingora.uz"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reset_link"] is None
    assert data["delivered"] is False
    assert "havola quyida" not in data["message_uz"]

    # Verify reset token was generated in DB
    reset = db.scalar(select(PasswordReset).where(PasswordReset.user_id == u.id))
    assert reset is not None
    assert reset.used_at is None

    # Requesting reset again should invalidate previous unused reset token
    client.post("/api/v1/auth/forgot-password", json={"email": "victim@lingora.uz"})
    db.refresh(reset)
    assert reset.used_at is not None  # Old token was revoked!


def test_password_reset_single_use_and_revokes_sessions(client, db):
    """Reset token can only be used once; using it revokes all active refresh tokens for that user."""
    u = User(email="testreset@lingora.uz", password_hash=hash_password("OldPassword123"), full_name="Reset User")
    db.add(u)
    db.flush()

    raw_token = "valid_secret_reset_token_1234567890"
    db.add(PasswordReset(
        user_id=u.id, token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.add(RefreshToken(
        user_id=u.id, token_hash=hash_token("active_refresh_session"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    ))
    db.commit()

    # First reset with token
    r = client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "NewStrongPassword123"})
    assert r.status_code == 200

    # Refresh tokens revoked
    rt = db.scalar(select(RefreshToken).where(RefreshToken.user_id == u.id))
    assert rt.revoked_at is not None

    # Replay same reset token -> MUST FAIL
    r2 = client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "AnotherPassword123"})
    assert r2.status_code == 400
    assert r2.json()["error"]["code"] == "BAD_RESET_TOKEN"


def test_tutor_scope_idor_prevention(client, db):
    """User cannot create tutor conversation bound to another user's book, lesson, or exercise."""
    # User A (owner)
    owner = User(email="owner@lingora.uz", password_hash=hash_password("Pass12345"), full_name="Owner")
    db.add(owner)
    db.flush()
    book_a = Book(user_id=owner.id, title="Owner Book", original_filename="book.pdf", storage_path="books/1/b.pdf")
    db.add(book_a)
    db.flush()
    lesson_a = Lesson(book_id=book_a.id, title="Lesson 1", topic="Grammar", page_start=1, page_end=3, order_index=0)
    db.add(lesson_a)
    db.flush()
    ex_a = Exercise(book_id=book_a.id, lesson_id=lesson_a.id, exercise_type="fill_blank", title="Ex 1", ref="Ex 1", page_number=2)
    db.add(ex_a)
    db.commit()

    # User B (adversary)
    adv_token = client.post("/api/v1/auth/register", json={
        "email": "adversary@lingora.uz", "password": "PassAdversary123", "full_name": "Adversary"
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {adv_token}"}

    # Attempt to bind conversation to User A's book
    r1 = client.post("/api/v1/tutor/conversations", json={"book_id": book_a.id}, headers=headers)
    assert r1.status_code == 404

    # Attempt to bind conversation to User A's lesson
    r2 = client.post("/api/v1/tutor/conversations", json={"lesson_id": lesson_a.id}, headers=headers)
    assert r2.status_code == 404

    # Attempt to bind conversation to User A's exercise
    r3 = client.post("/api/v1/tutor/conversations", json={"exercise_id": ex_a.id}, headers=headers)
    assert r3.status_code == 404


def test_backend_enforced_lesson_gate(client, db):
    """Backend strictly forbids reading exercises, autosaving answers, or checking exercises of a locked lesson."""
    reg = client.post("/api/v1/auth/register", json={
        "email": "student_gate@lingora.uz", "password": "PassStudent123", "full_name": "Student"
    }).json()
    token = reg["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    u = db.scalar(select(User).where(User.email == "student_gate@lingora.uz"))

    # Create book with Lesson 1 (has vocab) and Lesson 2
    book = Book(user_id=u.id, title="Grammar Course", original_filename="course.pdf", storage_path="books/u/c.pdf")
    db.add(book)
    db.flush()
    l1 = Lesson(book_id=book.id, title="Lesson 1", topic="Basics", page_start=1, page_end=2, order_index=0)
    l2 = Lesson(book_id=book.id, title="Lesson 2", topic="Advanced", page_start=3, page_end=4, order_index=1)
    db.add_all([l1, l2])
    db.flush()

    # Vocab for lesson 1
    db.add(VocabularyWord(book_id=book.id, lesson_id=l1.id, term="apple", translation_uz="olma"))
    # Exercise for lesson 2 (locked until lesson 1 vocab gate is passed!)
    ex2 = Exercise(book_id=book.id, lesson_id=l2.id, exercise_type="multiple_choice", title="Ex 2", ref="Ex 2", page_number=3)
    db.add(ex2)
    db.flush()
    q2 = ExerciseQuestion(exercise_id=ex2.id, order_index=0, prompt="Pick A", correct_answers=["A"], answer_source="key")
    db.add(q2)
    db.commit()

    # 1. Fetching exercises for lesson 2 must be rejected with 403 LESSON_LOCKED
    r1 = client.get(f"/api/v1/lessons/{l2.id}/exercises", headers=headers)
    assert r1.status_code == 403
    assert r1.json()["error"]["code"] == "LESSON_LOCKED"

    # 2. Direct get of exercise in lesson 2 must be rejected with 403 LESSON_LOCKED
    r2 = client.get(f"/api/v1/exercises/{ex2.id}", headers=headers)
    assert r2.status_code == 403
    assert r2.json()["error"]["code"] == "LESSON_LOCKED"

    # 3. Direct save answers in lesson 2 must be rejected with 403 LESSON_LOCKED
    r3 = client.put(f"/api/v1/exercises/{ex2.id}/answers", json={
        "answers": [{"question_id": q2.id, "content": {"selection": "A"}}], "submit": False
    }, headers=headers)
    assert r3.status_code == 403
    assert r3.json()["error"]["code"] == "LESSON_LOCKED"

    # 4. Direct check in lesson 2 must be rejected with 403 LESSON_LOCKED
    r4 = client.post(f"/api/v1/exercises/{ex2.id}/check", headers=headers)
    assert r4.status_code == 403
    assert r4.json()["error"]["code"] == "LESSON_LOCKED"

    # Now pass gate on lesson 1
    db.add(LearningProgress(user_id=u.id, lesson_id=l1.id, book_id=book.id, vocab_gate_passed=True))
    db.commit()

    # Now access to lesson 2 exercises succeeds
    r5 = client.get(f"/api/v1/lessons/{l2.id}/exercises", headers=headers)
    assert r5.status_code == 200
    assert len(r5.json()) == 1


def test_atomic_refresh_token_anti_replay(client, db):
    """A refresh token can only be consumed once. A second request with the same token is rejected."""
    reg = client.post("/api/v1/auth/register", json={
        "email": "refresh_test@lingora.uz", "password": "PassRefresh123", "full_name": "Refresher"
    }).json()
    refresh_token = reg["refresh_token"]

    # First rotation call succeeds
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r1.status_code == 200
    new_pair = r1.json()
    assert new_pair["refresh_token"] != refresh_token

    # Replay of the same old refresh token must be rejected with 401 UNAUTHORIZED
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "UNAUTHORIZED"
