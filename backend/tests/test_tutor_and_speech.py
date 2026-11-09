"""Tests for AI Tutor scope, status, conversation management, and speech endpoints."""
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_sample_book

API = "/api/v1"


def test_tutor_status_endpoint(client):
    u = make_user(client, "tutor_status@example.com")
    h = auth_headers(u["access_token"])
    res = client.get(f"{API}/tutor/status", headers=h)
    assert res.status_code == 200
    data = res.json()
    assert "available" in data
    assert "provider" in data
    assert "model" in data


def test_tutor_conversation_delete(client):
    u = make_user(client, "tutor_conv@example.com")
    h = auth_headers(u["access_token"])

    # Upload a book to scope the conversation
    r = client.post(
        f"{API}/books/upload",
        headers=h,
        files={"file": ("book.pdf", make_sample_book(), "application/pdf")},
        data={"consent": "true", "title": "Conv Book"},
    )
    book_id = r.json()["id"]
    wait_for_book(client, h, book_id)

    # Create conversation
    res = client.post(f"{API}/tutor/conversations", json={"book_id": book_id}, headers=h)
    assert res.status_code == 201
    cid = res.json()["id"]

    # Delete conversation
    del_res = client.delete(f"{API}/tutor/conversations/{cid}", headers=h)
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True

    # Check conversation is gone
    get_res = client.get(f"{API}/tutor/conversations/{cid}", headers=h)
    assert get_res.status_code == 404
