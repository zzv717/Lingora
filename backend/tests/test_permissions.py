"""Privacy & authorization: users must never access each other's books/answers/vocabulary."""
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_sample_book

API = "/api/v1"


def _setup_two_users(client):
    ta = make_user(client, "owner@example.com")["access_token"]
    tb = make_user(client, "intruder@example.com")["access_token"]
    r = client.post(f"{API}/books/upload", headers=auth_headers(ta),
                    files={"file": ("book.pdf", make_sample_book(), "application/pdf")},
                    data={"consent": "true", "title": "Private book"})
    book_id = r.json()["id"]
    wait_for_book(client, auth_headers(ta), book_id)
    return auth_headers(ta), auth_headers(tb), book_id


def test_other_user_cannot_see_book(client):
    ha, hb, book_id = _setup_two_users(client)
    r = client.get(f"{API}/books/{book_id}", headers=hb)
    assert r.status_code == 404  # indistinguishable from nonexistent
    r = client.get(f"{API}/books", headers=hb)
    assert all(b["id"] != book_id for b in r.json())


def test_other_user_cannot_download_file(client):
    ha, hb, book_id = _setup_two_users(client)
    r = client.get(f"{API}/books/{book_id}/file", headers=hb)
    assert r.status_code == 404
    r = client.get(f"{API}/books/{book_id}/file", headers=ha)
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


def test_other_user_cannot_get_structure_or_pages(client):
    ha, hb, book_id = _setup_two_users(client)
    assert client.get(f"{API}/books/{book_id}/structure", headers=hb).status_code == 404
    assert client.get(f"{API}/books/{book_id}/pages/1", headers=hb).status_code == 404
    assert client.get(f"{API}/books/{book_id}/vocabulary", headers=hb).status_code == 404
    assert client.post(f"{API}/books/{book_id}/reanalyze", headers=hb).status_code == 404
    assert client.delete(f"{API}/books/{book_id}", headers=hb).status_code == 404
    # owner still fine
    assert client.get(f"{API}/books/{book_id}/structure", headers=ha).status_code == 200


def test_other_user_cannot_touch_exercises_or_answers(client, db):
    ha, hb, book_id = _setup_two_users(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=ha).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=ha).json()
    ex_id = exs[0]["id"]
    q_id = exs[0]["questions"][0]["id"]

    # intruder cannot read/save/check
    assert client.get(f"{API}/exercises/{ex_id}", headers=hb).status_code == 404
    assert client.put(f"{API}/exercises/{ex_id}/answers", headers=hb,
                      json={"answers": [{"question_id": q_id, "content": {"blanks": {"b1": "goes"}}}]}
                      ).status_code == 404
    assert client.post(f"{API}/exercises/{ex_id}/check", headers=hb).status_code == 404

    # owner saves + check works
    r = client.put(f"{API}/exercises/{ex_id}/answers", headers=ha,
                   json={"answers": [{"question_id": q_id, "content": {"blanks": {"b1": "goes"}}}]})
    assert r.status_code == 200
    r = client.get(f"{API}/exercises/{ex_id}/answers", headers=ha)
    assert r.status_code == 200 and len(r.json()) == 1

    # intruder cannot start vocab session for owner's lesson
    r = client.post(f"{API}/vocabulary/sessions?lesson_id={lesson_id}&kind=lesson_gate", headers=hb)
    assert r.status_code == 404


def test_answers_and_sessions_are_private(client, db):
    ha, hb, book_id = _setup_two_users(client)
    struct = client.get(f"{API}/books/{book_id}/structure", headers=ha).json()
    lesson_id = struct["lessons"][0]["id"]
    exs = client.get(f"{API}/lessons/{lesson_id}/exercises", headers=ha).json()
    ex_id = exs[0]["id"]
    answers = [{"question_id": q["id"], "content": {"blanks": {"b1": "goes"}}}
               for q in exs[0]["questions"]]
    client.put(f"{API}/exercises/{ex_id}/answers", headers=ha, json={"answers": answers})
    r = client.get(f"{API}/exercises/{ex_id}/answers", headers=hb)
    assert r.status_code == 404


def test_conversations_are_private(client):
    ta = make_user(client, "chat1@example.com")["access_token"]
    tb = make_user(client, "chat2@example.com")["access_token"]
    r = client.post(f"{API}/tutor/conversations", headers=auth_headers(ta), json={})
    conv_id = r.json()["id"]
    assert client.get(f"{API}/tutor/conversations/{conv_id}/messages", headers=auth_headers(tb)).status_code == 404
    assert client.get(f"{API}/tutor/conversations/{conv_id}/messages", headers=auth_headers(ta)).status_code == 200


def test_health_and_ai_status_public(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    r = client.get(f"{API}/ai/status")
    data = r.json()
    assert data["ai_configured"] is False
    assert data["provider"] == "none"
