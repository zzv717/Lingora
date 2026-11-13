"""Progress analytics, exercise checking (deterministic path), and honest AI-unconfigured behavior."""
from app.core.config import settings
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_sample_book

API = "/api/v1"


def _setup(client, email="prog@example.com"):
    tokens = make_user(client, email)["access_token"]
    h = auth_headers(tokens)
    r = client.post(f"{API}/books/upload", headers=h,
                    files={"file": ("book.pdf", make_sample_book(), "application/pdf")},
                    data={"consent": "true"})
    book_id = r.json()["id"]
    wait_for_book(client, h, book_id)
    return h, book_id


def _answer_all(client, h, ex):
    answers = []
    for q in ex["questions"]:
        if ex["exercise_type"] == "multiple_choice":
            answers.append({"question_id": q["id"], "content": {"selection": "B"}})
        elif ex["exercise_type"] == "fill_blank":
            blank_answer = "goes" if "She" in q["prompt"] else (
                "play" if "They" in q["prompt"] else (
                "does" if "Ann" in q["prompt"] else (
                "is teaching" if "teacher" in q["prompt"] else "are playing")))
            answers.append({"question_id": q["id"], "content": {"blanks": {"b1": blank_answer}}})
        else:
            answers.append({"question_id": q["id"], "content": {"text": "He goes to school every day."}})
    return answers


def test_check_fill_blank_with_key(client):
    h, book_id = _setup(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=h).json()
    fill = next(e for e in exs if e["exercise_type"] == "fill_blank")

    r = client.put(f"{API}/exercises/{fill['id']}/answers", headers=h,
                   json={"answers": _answer_all(client, h, fill)})
    assert r.status_code == 200
    r = client.post(f"{API}/exercises/{fill['id']}/check", headers=h)
    data = r.json()
    assert r.status_code == 200
    assert data["percent"] == 100.0
    assert all(v["correct"] is True for v in data["verdicts"])
    # graded from the verified book key, not AI
    assert all(v["source"] == "key" for v in data["verdicts"])
    assert data["verdicts"][0]["expected"] == "goes"

    # attempt recorded + shown in history
    hist = client.get(f"{API}/exercises/{fill['id']}/attempts", headers=h).json()
    assert len(hist) == 1 and hist[0]["percent"] == 100.0


def test_check_mc_wrong_answer(client):
    h, book_id = _setup(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=h).json()
    mc = next(e for e in exs if e["exercise_type"] == "multiple_choice")
    answers = [{"question_id": q["id"], "content": {"selection": "A"}} for q in mc["questions"]]
    client.put(f"{API}/exercises/{mc['id']}/answers", headers=h, json={"answers": answers})
    data = client.post(f"{API}/exercises/{mc['id']}/check", headers=h).json()
    assert data["percent"] == 0.0
    assert all(v["correct"] is False for v in data["verdicts"])
    # explanation in Uzbek is always provided
    assert all(v["explanation_uz"] for v in data["verdicts"])


def test_translation_unverable_without_ai_is_honest(client):
    h, book_id = _setup(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=h).json()
    tr = next(e for e in exs if e["exercise_type"] == "translation")
    answers = [{"question_id": q["id"], "content": {"text": "He goes to school every day."}}
               for q in tr["questions"]]
    client.put(f"{API}/exercises/{tr['id']}/answers", headers=h, json={"answers": answers})
    data = client.post(f"{API}/exercises/{tr['id']}/check", headers=h).json()
    # AI not configured -> verdicts are honestly unverified, NOT faked correct/incorrect
    assert data["ai_used"] is False
    assert data["uncertain"] is True
    assert all(v["correct"] is None and v["source"] == "unverified" for v in data["verdicts"])
    assert "AI" in data["overall_feedback_uz"]


def test_answer_persistence_after_refetch(client):
    """Simulates app restart: answers must persist (autosave & resume)."""
    h, book_id = _setup(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=h).json()
    ex = exs[0]
    client.put(f"{API}/exercises/{ex['id']}/answers", headers=h,
               json={"answers": _answer_all(client, h, ex)})
    # "refresh" -> fetch again
    r = client.get(f"{API}/exercises/{ex['id']}/answers", headers=h)
    saved = {a["question_id"]: a["content"] for a in r.json()}
    assert len(saved) == len(ex["questions"])
    first = ex["questions"][0]["id"]
    assert saved[first]["blanks"]["b1"] == "goes"


def test_dashboard_stats(client):
    h, book_id = _setup(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=h).json()
    fill = next(e for e in exs if e["exercise_type"] == "fill_blank")
    client.put(f"{API}/exercises/{fill['id']}/answers", headers=h,
               json={"answers": _answer_all(client, h, fill)})
    client.post(f"{API}/exercises/{fill['id']}/check", headers=h)

    r = client.get(f"{API}/progress/dashboard", headers=h)
    d = r.json()
    assert r.status_code == 200
    assert d["books_total"] == 1 and d["books_ready"] == 1
    assert d["exercises_checked"] >= 1
    assert d["avg_accuracy"] == 100.0
    assert len(d["activity_last_14d"]) == 14
    assert "weak_topics" in d and "strong_topics" in d

    # heartbeat -> study time
    r = client.post(f"{API}/progress/heartbeat", headers=h,
                    json={"seconds": 60, "lesson_id": lesson_id, "page": 2})
    assert r.status_code == 200
    d = client.get(f"{API}/progress/dashboard", headers=h).json()
    assert d["today_minutes"] >= 1.0


def test_ai_endpoints_report_not_configured(client):
    assert settings.ai_provider == "none"
    h, book_id = _setup(client, "aifix@example.com")
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]

    r = client.post(f"{API}/tutor/conversations", headers=h,
                    json={"book_id": book_id, "lesson_id": lesson_id})
    assert r.status_code == 201
    conv = r.json()["id"]
    r = client.post(f"{API}/tutor/conversations/{conv}/messages", headers=h,
                    json={"content": "Present Simple qoidasini tushuntir"})
    assert r.status_code == 503
    body = r.json()["error"]
    assert body["code"] == "AI_NOT_CONFIGURED"
    assert "AI_PROVIDER" in body["message_uz"]

    r = client.post(f"{API}/tutor/lessons/{lesson_id}/extra-exercises", headers=h)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "AI_NOT_CONFIGURED"


def test_plan_limits_visible(client):
    h, _ = _setup(client, "plan@example.com")
    r = client.get(f"{API}/me/plan", headers=h)
    data = r.json()
    assert data["plan"] == "free"
    assert data["max_books"] == 10  # set in test env
    assert data["ai_configured"] is False


def test_reader_position_is_saved_and_returned_without_adding_study_time(client):
    h, book_id = _setup(client, "resume@example.com")
    struct = client.get(f"{API}/books/{book_id}/structure", headers=h).json()
    lesson_id = struct["lessons"][0]["id"]
    assert struct["lessons_progress"][lesson_id]["last_visited_at"] is None
    assert client.post(f"{API}/progress/heartbeat", headers=h,
                       json={"seconds": 0, "lesson_id": lesson_id, "page": 2}).status_code == 200
    updated = client.get(f"{API}/books/{book_id}/structure", headers=h).json()["lessons_progress"][lesson_id]
    assert updated["last_page"] == 2
    assert updated["last_visited_at"]
    assert updated["time_spent_seconds"] == 0
    # Time heartbeats must not erase the saved location.
    client.post(f"{API}/progress/heartbeat", headers=h, json={"seconds": 60, "lesson_id": lesson_id})
    assert client.get(f"{API}/books/{book_id}/structure", headers=h).json()["lessons_progress"][lesson_id]["last_page"] == 2
