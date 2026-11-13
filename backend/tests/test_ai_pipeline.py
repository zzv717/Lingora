"""Exercise the configured-AI pipeline with a stub provider; no real API key is required."""
from types import SimpleNamespace
import pytest
import httpx
from app.core.config import settings
from app.core.errors import ApiError
from app.services.ai.provider import AIResponse, ChatMessage, GeminiProvider
from tests.conftest import make_user, auth_headers, wait_for_book
from tests.pdf_factory import make_sample_book


def test_gemini_key_is_header_and_not_logged_on_error(monkeypatch, caplog):
    secret = "test-secret-do-not-log"
    monkeypatch.setattr(settings, "ai_api_key", secret)
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_max_retries", 0)
    requests = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, headers):
            requests.append((url, headers))
            return httpx.Response(401, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(ApiError) as err:
        GeminiProvider().complete([ChatMessage(role="user", content="hello")])
    assert secret not in requests[0][0]
    assert requests[0][1]["x-goog-api-key"] == secret
    assert secret not in str(err.value) and secret not in caplog.text


def test_pipeline_calls_configured_ai_and_saves_explanations(client, monkeypatch):
    import json
    from app.services.ai import enrich
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_api_key", "fake-key")
    calls = []
    def fake_structured(schema, messages, **kwargs):
        calls.append(schema.__name__)
        if schema is enrich.GrammarExplanationsOut:
            lessons = json.loads(messages[-1].content.split("\n", 1)[1])
            output = {"explanations": [{"lesson_title": item["lesson_title"],
                    "explanation_uz": "Test grammatik tushuntirish", "summary_uz": "Test"} for item in lessons]}
        else:
            output = {"translations": []}
        return schema.model_validate(output), AIResponse(content="{}", model="test-model", tokens_in=10, tokens_out=5)
    monkeypatch.setattr(enrich, "structured", fake_structured)
    monkeypatch.setattr(enrich, "get_provider", lambda: SimpleNamespace(name="fake"))
    user = make_user(client, "aipipeline@example.com")
    h = auth_headers(user["access_token"])
    r = client.post("/api/v1/books/upload", headers=h, files={"file": ("book.pdf", make_sample_book(), "application/pdf")}, data={"consent": "true"})
    assert r.status_code == 201, r.text
    book_id = r.json()["id"]
    job = wait_for_book(client, h, book_id)
    assert job["status"] == "completed", job
    assert "GrammarExplanationsOut" in calls
    structure = client.get(f"/api/v1/books/{book_id}/structure", headers=h).json()
    assert any(l["grammar_explanation_uz"] == "Test grammatik tushuntirish" for l in structure["lessons"])
    assert not any(w["code"] == "AI_ENRICHMENT_FAILED" for w in job["warnings"])


def test_pipeline_reports_failed_ai_but_keeps_basic_analysis(client, monkeypatch):
    from app.services.ai import enrich
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_api_key", "fake-key")
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(enrich, "structured", fail)
    user = make_user(client, "aifailure@example.com")
    h = auth_headers(user["access_token"])
    r = client.post("/api/v1/books/upload", headers=h, files={"file": ("book.pdf", make_sample_book(), "application/pdf")}, data={"consent": "true"})
    assert r.status_code == 201, r.text
    job = wait_for_book(client, h, r.json()["id"])
    assert job["status"] == "completed", job
    assert any(w["code"] == "AI_ENRICHMENT_FAILED" for w in job["warnings"])
