"""Vision exercise scanning: consent, ownership, validation, no invented answers, idempotency, quota."""
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.models import BookPage, Exercise, ExerciseOption, ExerciseQuestion, UsageEvent
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan
from tests.test_vision_map_preview import Provider, Storage

API = "/api/v1"


def page_output(number="91"):
    return json.dumps({
        "page_kind": "exercises", "transcript": "Revision III. Look at the picture.",
        "exercises": [
            {"number": number, "instruction": "Look at the picture and write sentences as in the example:",
             "type": "write_sentences", "example": "Father is watching T.V.", "depends_on_picture": True,
             "questions": [{"number": "2", "prompt": "Mother ......"}, {"number": "3", "prompt": "The girls ......"}]},
            {"number": "92", "instruction": "Choose the correct answer:", "type": "multiple_choice",
             "questions": [{"number": "1", "prompt": "He ... home.", "options": ["A) go", "B) goes"]}]},
        ], "warnings": []})


def setup(monkeypatch, responses):
    provider = Provider(responses)
    monkeypatch.setattr("app.services.ai.vision_exercises.get_provider", lambda: provider)
    monkeypatch.setattr("app.services.ai.vision_map.get_storage", lambda: Storage())
    monkeypatch.setattr(settings, "ai_vision_model", "vision-test")
    monkeypatch.setattr(settings, "vision_exercise_pages_per_day", 150)
    return provider


def url(book, page, suffix=""):
    return f"{API}/books/{book}/vision-exercises/pages/{page}{suffix}"


def test_consent_and_ownership_before_any_model_call(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, "vx-other@example.com")["access_token"])
    provider = setup(monkeypatch, [page_output()])
    body = {"consent_images_to_provider": True}
    assert client.post(url(book, 1), headers=other, json=body).status_code == 404
    assert client.post(url(book, 1), headers=h, json={"consent_images_to_provider": False}).status_code == 422
    assert client.post(url(book, 9), headers=h, json=body).status_code == 404
    assert not provider.calls


def test_preview_saves_nothing(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_output()])
    res = client.post(url(book, 1, "/preview"), headers=h, json={"consent_images_to_provider": True})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["saved"] is False and len(body["exercises"]) == 2
    assert body["exercises"][0]["number"] == "91" and body["exercises"][0]["type"] == "sentence_construction"
    msgs, args = provider.calls[0]
    assert args["model"] == "vision-test" and args["json_mode"] and len(msgs[1].images) == 1
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Exercise)) == 0
    assert db.scalar(select(BookPage.needs_ocr).where(BookPage.book_id == book, BookPage.page_number == 1))


def test_save_creates_reviewable_exercises_without_answer_keys(client, db, monkeypatch):
    h, book, lesson, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_output()])
    res = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": True})
    assert res.status_code == 200, res.text
    assert res.json()["exercises_added"] == 2
    db.expire_all()
    exercises = list(db.scalars(select(Exercise).where(Exercise.book_id == book).order_by(Exercise.order_index)))
    assert [e.ref for e in exercises] == ["Exercise 91", "Exercise 92"]
    assert all(e.detection == "vision" and e.needs_review and e.page_number == 1 for e in exercises)
    assert exercises[0].lesson_id == lesson and "Misol" in exercises[0].instructions
    assert "rasmga" in exercises[0].instructions
    questions = list(db.scalars(select(ExerciseQuestion)))
    assert questions and all(not q.correct_answers and q.answer_source == "unknown" for q in questions)
    letters = [o.letter for o in db.scalars(select(ExerciseOption))]
    assert letters == ["A", "B"]
    page = db.scalar(select(BookPage).where(BookPage.book_id == book, BookPage.page_number == 1))
    assert not page.needs_ocr and page.ocr_used and page.has_warning and "Revision III" in page.text
    assert client.get(f"{API}/books/{book}/ocr/pending", headers=h).json()["pages"] == [2]
    assert client.get(f"{API}/books/{book}/vision-exercises/pending", headers=h).json()["pages"] == [2]
    assert len(provider.calls) == 1


def test_second_scan_is_rejected_before_paying_and_replace_works(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_output(), page_output("95")])
    ok = {"consent_images_to_provider": True}
    assert client.post(url(book, 1), headers=h, json=ok).status_code == 200
    again = client.post(url(book, 1), headers=h, json=ok)
    assert again.status_code == 409 and again.json()["error"]["code"] == "VISION_PAGE_ALREADY_DONE"
    assert len(provider.calls) == 1  # no second paid call
    replaced = client.post(url(book, 1), headers=h, json={**ok, "replace": True})
    assert replaced.status_code == 200, replaced.text
    db.expire_all()
    refs = sorted(e.ref for e in db.scalars(select(Exercise).where(Exercise.book_id == book)))
    assert refs == ["Exercise 92", "Exercise 95"]


def test_replace_refused_when_student_progress_exists(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_output(), page_output("95")])
    ok = {"consent_images_to_provider": True}
    assert client.post(url(book, 1), headers=h, json=ok).status_code == 200
    db.expire_all()
    ex = db.scalar(select(Exercise).where(Exercise.book_id == book).order_by(Exercise.order_index))
    q = db.scalar(select(ExerciseQuestion).where(ExerciseQuestion.exercise_id == ex.id))
    saved = client.put(f"{API}/exercises/{ex.id}/answers", headers=h,
                       json={"answers": [{"question_id": q.id, "content": {"text": "Mother is reading."}}]})
    assert saved.status_code == 200, saved.text
    blocked = client.post(url(book, 1), headers=h, json={**ok, "replace": True})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "VISION_PAGE_HAS_PROGRESS"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Exercise)) == 2


def test_bad_model_output_retries_once_and_saves_nothing(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, ["not json", json.dumps({"exercises": "nope"})])
    res = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": True})
    assert res.status_code == 502 and res.json()["error"]["code"] == "AI_BAD_OUTPUT"
    assert len(provider.calls) == 2
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Exercise)) == 0
    assert db.scalar(select(BookPage.needs_ocr).where(BookPage.book_id == book, BookPage.page_number == 1))


def test_page_without_exercises_is_marked_done_with_text(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [json.dumps({"page_kind": "theory", "transcript": "Plural forms: add -s.", "exercises": []})])
    res = client.post(url(book, 2), headers=h, json={"consent_images_to_provider": True})
    assert res.status_code == 200 and res.json()["exercises_added"] == 0
    db.expire_all()
    page = db.scalar(select(BookPage).where(BookPage.book_id == book, BookPage.page_number == 2))
    assert not page.needs_ocr and "Plural forms" in page.text


def test_separate_daily_quota_and_general_quota_untouched(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [page_output(), page_output("95")])
    monkeypatch.setattr(settings, "vision_exercise_pages_per_day", 1)
    ok = {"consent_images_to_provider": True}
    assert client.post(url(book, 1), headers=h, json=ok).status_code == 200
    limited = client.post(url(book, 2), headers=h, json=ok)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "AI_FEATURE_QUOTA_EXCEEDED"
    from app.services.ai import usage
    user_id = db.scalar(select(UsageEvent.user_id))
    assert usage.ai_calls_today(db, user_id) == 0  # bulk scanning does not eat the plan's general AI calls
