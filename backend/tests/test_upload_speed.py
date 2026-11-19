"""Fast paths introduced for large vocabulary books and direct upload finalization."""
import json
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.core.config import settings
from app.core.errors import ApiError
from app.models import Book, ProcessingJob, User, VocabularyWord
from app.services.ai.provider import AIResponse
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_sample_book


def _configure_ai(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "ai_api_key", "fake-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_enrich_workers", 4)
    monkeypatch.setattr(settings, "ai_daily_request_limits_enabled", False)
    monkeypatch.setattr(settings, "ai_daily_token_limit", 0)


def test_vocabulary_enrichment_parallelizes_provider_calls(client, db, monkeypatch):
    from app.services.ai import enrich

    _configure_ai(monkeypatch)
    monkeypatch.setattr(enrich, "get_provider", lambda: SimpleNamespace(name="fake"))
    user = make_user(client, "fast-vocab@example.com")
    user_id = db.scalar(select(User.id).where(User.email == "fast-vocab@example.com"))
    book = Book(id="fast-vocab-book", user_id=user_id, title="Dictionary",
                original_filename="dictionary.pdf", storage_path="unused",
                status="processing", consent_confirmed_at=datetime.now(timezone.utc))
    db.add(book)
    db.flush()
    words = [VocabularyWord(book_id=book.id, term=f"word{i}", needs_translation=True)
             for i in range(320)]  # 8 batches of 40
    db.add_all(words)
    db.commit()

    lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def fake_structured(schema, messages, **kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.05)
        terms = [w["term"] for w in json.loads(messages[-1].content)]
        with lock:
            state["active"] -= 1
        output = {"translations": [{"term": term, "translation_uz": "tarjima"}
                                   for term in terms]}
        return schema.model_validate(output), AIResponse(content="{}", model="test-model")

    monkeypatch.setattr(enrich, "structured", fake_structured)
    progress = []
    done = enrich.enrich_vocabulary_translations(db, user_id, words, progress.append)

    assert done == 320
    assert state["max_active"] >= 2, "translation batches should not run strictly one-by-one"
    assert progress[-1] == 1.0
    assert all(w.needs_translation is False and w.translation_uz == "tarjima" for w in words)


def test_enrich_book_reports_progress_without_lessons(client, db, monkeypatch):
    from app.services.ai import enrich

    _configure_ai(monkeypatch)
    monkeypatch.setattr(enrich, "get_provider", lambda: SimpleNamespace(name="fake"))
    user = make_user(client, "fast-progress@example.com")
    user_id = db.scalar(select(User.id).where(User.email == "fast-progress@example.com"))
    book = Book(id="fast-progress-book", user_id=user_id, title="Dictionary",
                original_filename="dictionary.pdf", storage_path="unused", status="processing")
    db.add(book)
    db.flush()
    db.add_all([VocabularyWord(book_id=book.id, term=f"term{i}", needs_translation=True)
                for i in range(80)])
    db.commit()

    def fake_structured(schema, messages, **kwargs):
        terms = [w["term"] for w in json.loads(messages[-1].content)]
        return schema.model_validate({"translations": [
            {"term": term, "translation_uz": "tarjima"} for term in terms]}), AIResponse(
                content="{}", model="test-model")

    monkeypatch.setattr(enrich, "structured", fake_structured)
    progress = []
    assert enrich.enrich_book(db, book.id, progress.append) == []
    assert progress and progress[-1] == 1.0
