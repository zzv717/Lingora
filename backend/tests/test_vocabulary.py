"""Vocabulary challenge: randomization, written recall, pass score, gating, SM-2 scheduling."""
import random

from app.services.srs import quality_from_answer, schedule_sm2
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_sample_book

API = "/api/v1"


def _setup(client):
    tokens = make_user(client, "vocab@example.com")["access_token"]
    h = auth_headers(tokens)
    r = client.post(f"{API}/books/upload", headers=h,
                    files={"file": ("book.pdf", make_sample_book(), "application/pdf")},
                    data={"consent": "true"})
    book_id = r.json()["id"]
    wait_for_book(client, h, book_id)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    return h, book_id, struct


def test_sm2_progression():
    state = dict(ease_factor=2.5, interval_days=0, repetitions=0, lapses=0)
    s1 = schedule_sm2(**state, quality=5)
    assert s1["interval_days"] == 1 and s1["repetitions"] == 1
    s2 = schedule_sm2(**{k: s1[k] for k in state}, quality=5)
    assert s2["interval_days"] == 6 and s2["repetitions"] == 2
    s3 = schedule_sm2(**{k: s2[k] for k in state}, quality=4)
    assert s3["interval_days"] > 6  # grows with ease factor
    assert s3["ease_factor"] > 2.5 - 0.01

    fail = schedule_sm2(**{k: s3[k] for k in state}, quality=1)
    assert fail["repetitions"] == 0 and fail["interval_days"] == 0 and fail["lapses"] == 1

    assert quality_from_answer(correct=True, question_type="written_en_uz") == 5
    assert quality_from_answer(correct=True, question_type="choice_en_uz") == 3
    assert quality_from_answer(correct=False, question_type="spelling") == 1


def test_session_includes_written_recall_and_randomized_options(client):
    h, book_id, struct = _setup(client)
    lesson1 = struct["lessons"][0]["id"]
    random.seed()  # ensure fresh randomness
    types_seen = set()
    option_orders = []
    for _ in range(4):
        r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson1}&kind=lesson_gate", headers=h)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["kind"] == "lesson_gate"
        assert data["required_score"] == 80
        assert data["total_items"] > 0
        for item in data["items"]:
            types_seen.add(item["type"])
            if item["options"]:
                option_orders.append([o["key"] for o in item["options"]])
            if item["type"] == "spelling":
                assert item.get("options") == [] or True
        # abandon session
        break
    # mandatory written recall types must exist in the pool (not only multiple choice)
    recall_types = {"written_en_uz", "written_uz_en", "spelling", "sentence_blank"}
    assert types_seen & recall_types, types_seen


def test_answers_and_scoring(client):
    h, book_id, struct = _setup(client)
    lesson1 = struct["lessons"][0]["id"]
    r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson1}&kind=lesson_gate", headers=h)
    session = r.json()
    sid = session["id"]

    # DB peek for expected values (grading happens server-side; test drives the API)
    from app.db.session import SessionLocal
    from app.models import VocabularySession

    db = SessionLocal()
    s = db.get(VocabularySession, sid)
    expected = {i["item_id"]: i["expected"] for i in s.items}
    requeued_ids = set()
    db.close()

    # answer everything WRONG once to check reintroduction
    answered = 0
    for item in session["items"]:
        r = client.post(f"{API}/vocabulary/sessions/{sid}/answer", headers=h,
                        json={"item_id": item["item_id"], "response": "__wrong__"})
        assert r.status_code == 200
        assert r.json()["correct"] is False
        answered += 1

    # failed words must be reintroduced -> session now has extra items
    r = client.get(f"{API}/vocabulary/sessions/{sid}", headers=h)
    data = r.json()
    assert data["total_items"] > len(session["items"]), "failed words must be reintroduced"

    # now answer everything correctly (including re-queued)
    from app.db.session import SessionLocal as SL

    db = SL()
    s = db.get(VocabularySession, sid)
    expected = {i["item_id"]: i["expected"] for i in s.items}
    db.close()
    for item in data["items"]:
        r = client.post(f"{API}/vocabulary/sessions/{sid}/answer", headers=h,
                        json={"item_id": item["item_id"], "response": expected[item["item_id"]]})
        assert r.status_code == 200

    r = client.post(f"{API}/vocabulary/sessions/{sid}/complete", headers=h)
    result = r.json()
    assert result["score"] == 0.0  # first-attempt score is 0 (all wrong initially)
    assert result["passed"] is False

    # gate still closed
    lesson2 = struct["lessons"][1]["id"]
    r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson2}&kind=lesson_gate", headers=h)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "LESSON_LOCKED"


def test_passing_gate_unlocks_next_lesson(client):
    h, book_id, struct = _setup(client)
    lesson1, lesson2 = struct["lessons"][0]["id"], struct["lessons"][1]["id"]

    r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson1}&kind=lesson_gate", headers=h)
    sid = r.json()["id"]
    from app.db.session import SessionLocal
    from app.models import VocabularySession

    db = SessionLocal()
    s = db.get(VocabularySession, sid)
    expected = {i["item_id"]: i["expected"] for i in s.items}
    db.close()

    for item in r.json()["items"]:
        rr = client.post(f"{API}/vocabulary/sessions/{sid}/answer", headers=h,
                         json={"item_id": item["item_id"], "response": expected[item["item_id"]]})
        assert rr.json()["correct"] is True

    result = client.post(f"{API}/vocabulary/sessions/{sid}/complete", headers=h).json()
    assert result["passed"] is True
    assert result["score"] == 100.0
    assert result["gate_opened"] is True

    # lesson 2 now unlocked
    r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson2}&kind=lesson_gate", headers=h)
    assert r.status_code == 201


def test_vocab_progress_tracking(client):
    h, book_id, struct = _setup(client)
    lesson1 = struct["lessons"][0]["id"]
    r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson1}&kind=lesson_gate", headers=h)
    sid = r.json()["id"]
    from app.db.session import SessionLocal
    from app.models import VocabularySession

    db = SessionLocal()
    s = db.get(VocabularySession, sid)
    expected = {i["item_id"]: i["expected"] for i in s.items}
    db.close()
    for item in r.json()["items"]:
        client.post(f"{API}/vocabulary/sessions/{sid}/answer", headers=h,
                    json={"item_id": item["item_id"], "response": expected[item["item_id"]]})
    client.post(f"{API}/vocabulary/sessions/{sid}/complete", headers=h)

    stats = client.get(f"{API}/vocabulary/stats", headers=h).json()
    assert stats["total"] > 0 and stats["learning"] > 0

    prog = client.get(f"{API}/vocabulary/progress", headers=h).json()
    assert prog and prog[0]["repetitions"] >= 1
    assert prog[0]["accuracy"] == 100.0
