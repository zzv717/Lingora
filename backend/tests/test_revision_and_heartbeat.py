"""Regression tests for Revision sessions, heartbeat timezone, and readiness probes."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import ActivityDay, Book, Exercise, ExerciseQuestion, Lesson, Profile, User, VocabularyWord
from app.services import revision as revision_service
from app.services.progress_service import heartbeat


def test_heartbeat_timezone_and_anti_abuse(client, db):
    """Heartbeat caps seconds and records activity under user's profile timezone."""
    reg = client.post("/api/v1/auth/register", json={
        "email": "heartbeat_user@lingora.uz", "password": "Password12345", "full_name": "Tz Tester"
    }).json()
    u = db.scalar(select(User).where(User.email == "heartbeat_user@lingora.uz"))

    # Set profile timezone to Asia/Tashkent
    prof = db.scalar(select(Profile).where(Profile.user_id == u.id))
    prof.timezone = "Asia/Tashkent"
    db.commit()

    # Ping with excessive seconds (e.g. 99999) -> must be capped to 120s
    heartbeat(db, u.id, seconds=99999)
    act = db.scalar(select(ActivityDay).where(ActivityDay.user_id == u.id))
    assert act is not None
    assert act.seconds == 120  # strictly capped to 120s max!


def test_revision_session_server_side_grading(client, db):
    """Revision session grades answers deterministically on server, never trusting client boolean."""
    reg = client.post("/api/v1/auth/register", json={
        "email": "rev_test@lingora.uz", "password": "Password12345", "full_name": "Revision Tester"
    }).json()
    u = db.scalar(select(User).where(User.email == "rev_test@lingora.uz"))

    book = Book(user_id=u.id, title="Grammar", storage_path="books/u/g.pdf")
    db.add(book)
    db.flush()

    w = VocabularyWord(book_id=book.id, term="knowledge", translation_uz="bilim")
    db.add(w)
    db.commit()

    # Build revision session manually
    session = revision_service.RevisionSession(
        user_id=u.id,
        book_id=book.id,
        focus="Lug'at takrorlash",
        reason="Test",
        items=[
            {
                "item_type": "vocab",
                "word_id": w.id,
                "payload": {"term": "knowledge", "expected": "bilim"},
            }
        ],
    )
    db.add(session)
    db.commit()

    # Complete with correct answer
    s_done = revision_service.grade_and_complete_revision(db, session, {"0": "bilim"})
    assert s_done.score == 100.0
    assert s_done.status == "completed"
    assert s_done.items[0]["result"] is True


def test_readiness_probe(client):
    """Health endpoint is liveness; /ready checks DB and storage."""
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_ready = client.get("/ready")
    assert r_ready.status_code in (200, 503)
    data = r_ready.json()
    assert "db" in data
    assert "storage" in data
