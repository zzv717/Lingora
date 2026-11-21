"""Vision vocabulary: consent, validation, no invented translations, idempotency, limits.

The scanned word-list page these tests model is the real 4000 Essential English Words
layout: a coloured headword with its pronunciation, a part-of-speech tag, a definition
sentence, a bulleted example and a small illustration.
"""
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.models import Book, BookPage, UsageEvent, VocabularyWord
from app.services.ai.vision_vocabulary import clean_example, clean_term, normalize_word_list
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.test_browser_ocr import setup_scan
from tests.test_vision_map_preview import Provider, Storage

API = "/api/v1"


def word_list_output(*terms):
    words = []
    for i, term in enumerate(terms or ("afraid", "agree", "angry")):
        words.append({
            "word": f"{term} [pron-{i}] adj.",
            "part_of_speech": "adjective",
            "definition": f"When someone is {term}, they feel something.",
            "example": f"» The {term} woman was afraid of what she saw.",
            "bbox": [0.1, 0.1 + i * 0.08, 0.9, 0.17 + i * 0.08],
            "confidence": 0.9,
        })
    return json.dumps({"is_word_list": True, "unit": "Unit 1", "heading": "Word List",
                       "entries": words, "warnings": []})


def setup(monkeypatch, responses):
    provider = Provider(responses)
    monkeypatch.setattr("app.services.ai.vision_vocabulary.get_provider", lambda: provider)
    monkeypatch.setattr("app.services.ai.vision_map.get_storage", lambda: Storage())
    monkeypatch.setattr(settings, "ai_vision_model", "vision-test")
    # The test env ships AI_PROVIDER=none; the fallback decision reads this, not the mock.
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "vision_exercise_pages_per_day", 150)
    return provider


def url(book, page, suffix=""):
    return f"{API}/books/{book}/vision-vocabulary/pages/{page}{suffix}"


def test_clean_term_drops_pronunciation_and_part_of_speech():
    assert clean_term("afraid [uh-freyd] adj.") == "afraid"
    assert clean_term("bottom [bot-uhm] noun") == "bottom"
    assert clean_term("arrive [uh-rahyv] v") == "arrive"
    assert clean_term("finally") == "finally"
    assert clean_term("hide.") == "hide"
    # A definition that slipped into the term field is not a headword.
    assert clean_term("the bottom of my shoe has a hole in it") == ""
    assert clean_term("123") == ""
    assert clean_term("") == ""
    assert clean_example("» The bus always arrives at 4:00.") == "The bus always arrives at 4:00."


def test_normalisation_drops_duplicates_and_junk():
    result = normalize_word_list({"unit": "Unit 2", "entries": [
        {"word": "afraid [uh-freyd] adj.", "definition": "When someone is afraid."},
        {"word": "Agree", "definition": "To agree is to say yes."},
        {"word": "afraid", "definition": "duplicate"},
        {"word": "a whole definition sentence that is too long to be a word", "definition": "junk"},
    ]})
    assert result.is_word_list is True and result.unit == "2"
    assert [w.term for w in result.words] == ["afraid", "agree"]


def test_a_page_without_a_word_list_is_not_saved(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [json.dumps({"is_word_list": False, "entries": []})])
    r = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_A_WORD_LIST"
    db.expire_all()
    assert db.scalar(select(func.count(VocabularyWord.id)).where(VocabularyWord.book_id == book)) == 0


def test_consent_and_ownership_come_before_any_model_call(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [word_list_output()])
    other = auth_headers(make_user(client, 'vision-vocab-other@example.com')['access_token'])
    assert client.get(f"{API}/books/{book}/vision-vocabulary/pending", headers=other).status_code == 404
    assert client.post(url(book, 1), headers=other,
                       json={"consent_images_to_provider": True}).status_code == 404
    denied = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": False})
    assert denied.status_code == 422 and denied.json()["error"]["code"] == "AI_IMAGE_CONSENT_REQUIRED"
    assert provider.calls == []


def test_saved_words_are_untranslated_and_never_reset(client, db, monkeypatch):
    h, book, lesson, _ = setup_scan(client, db)
    # A word the book already knows, with a translation: it must not be touched.
    db.add(VocabularyWord(book_id=book, lesson_id=lesson, term="agree", translation_uz="rozi bo'lmoq",
                          needs_translation=False, source="book"))
    db.commit()

    setup(monkeypatch, [word_list_output("afraid", "agree")])
    r = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["words_added"] == 1 and body["words_found"] == 2

    db.expire_all()
    words = {w.term: w for w in db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book))}
    assert set(words) == {"afraid", "agree"}
    assert words["afraid"].needs_translation is True and words["afraid"].translation_uz == ""
    assert words["afraid"].source == "vision" and words["afraid"].page_number == 1
    assert words["afraid"].lesson_id == lesson and words["afraid"].definition_en
    # The existing word kept its translation and its provenance.
    assert words["agree"].translation_uz == "rozi bo'lmoq" and words["agree"].source == "book"

    # Re-reading the same page adds nothing and creates no duplicate rows.
    setup(monkeypatch, [word_list_output("afraid", "agree")])
    again = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": True})
    assert again.status_code == 200 and again.json()["words_added"] == 0
    db.expire_all()
    assert db.scalar(select(func.count(VocabularyWord.id))
                     .where(VocabularyWord.book_id == book, VocabularyWord.term == "afraid")) == 1


def test_preview_saves_nothing_and_records_usage(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [word_list_output()])
    r = client.post(url(book, 1, "/preview"), headers=h, json={"consent_images_to_provider": True})
    assert r.status_code == 200 and r.json()["saved"] is False
    assert [w["word"] for w in r.json()["entries"]] == ["afraid", "agree", "angry"]
    assert r.json()["entries"][0]["bbox"] is not None
    assert r.json()["unit"] == "1" and r.json()["page"] == 1
    db.expire_all()
    assert db.scalar(select(func.count(VocabularyWord.id)).where(VocabularyWord.book_id == book)) == 0
    assert db.scalar(select(func.count(UsageEvent.id))
                     .where(UsageEvent.feature == "vision_vocabulary")) == 1


def test_pending_lists_the_scanned_pages(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [])
    body = client.get(f"{API}/books/{book}/vision-vocabulary/pending", headers=h).json()
    assert body["pages"] == [1, 2] and body["total_pages"] == 2
    assert body["consent_required"] is True


def test_words_without_a_lesson_are_still_visible_in_the_structure(client, db, monkeypatch):
    """A scanned book has no lessons; the Lug'at screen draws one card per lesson.

    Saved words therefore used to be returned by /vocabulary and then never rendered
    because no lesson id matched. The structure has to expose a group for them.
    """
    h, book, _, _ = setup_scan(client, db)
    from app.models import Lesson, VocabularyWord

    db.query(Lesson).filter(Lesson.book_id == book).delete()
    db.add(VocabularyWord(book_id=book, term="afraid", page_number=1, source="vision",
                          needs_translation=True, definition_en="When someone is afraid."))
    db.add(VocabularyWord(book_id=book, term="agree", page_number=1, source="vision",
                          needs_translation=True, definition_en="To agree is to say yes."))
    db.commit()

    structure = client.get(f"{API}/books/{book}/structure", headers=h).json()
    ids = [lesson["id"] for lesson in structure["lessons"]]
    assert "unassigned" in ids
    group = next(lesson for lesson in structure["lessons"] if lesson["id"] == "unassigned")
    assert group["title"] == "Boshqa lug'at yozuvlari"
    # LessonOut carries the page span; the words themselves come from /vocabulary.
    assert group["page_start"] == 1 and group["page_end"] == 1

    words = client.get(f"{API}/books/{book}/vocabulary", headers=h).json()
    shown = [w for w in words if not w["lesson_id"]]
    assert {w["term"] for w in shown} == {"afraid", "agree"}
    assert words[0]["lesson_id"] is None  # nothing was invented for the DB row


def test_a_book_without_orphans_gets_no_pseudo_lesson(client, db, monkeypatch):
    h, book, lesson, _ = setup_scan(client, db)
    db.add(VocabularyWord(book_id=book, lesson_id=lesson, term="agree", page_number=1,
                          needs_translation=True))
    db.commit()
    structure = client.get(f"{API}/books/{book}/structure", headers=h).json()
    assert "unassigned" not in [l["id"] for l in structure["lessons"]]


def test_text_pages_can_be_included_when_rules_found_nothing(client, db, monkeypatch):
    """A book can have a text layer and still yield no words; re-analysis then changes nothing."""
    h, book, _, _ = setup_scan(client, db)
    from app.models import BookPage, VocabularyWord

    # Both pages carry text now: the rule detector ran and found no word list.
    for page in db.scalars(select(BookPage).where(BookPage.book_id == book)).all():
        page.needs_ocr = False
        page.text = "Word List afraid ..."
    db.add(VocabularyWord(book_id=book, term="agree", page_number=2, needs_translation=True))
    db.commit()

    setup(monkeypatch, [])
    scanned_only = client.get(f"{API}/books/{book}/vision-vocabulary/pending", headers=h).json()
    assert scanned_only["pages"] == []          # nothing scanned, so nothing is offered

    widened = client.get(f"{API}/books/{book}/vision-vocabulary/pending?include_text_pages=true",
                         headers=h).json()
    # Page 2 already has a word, so only page 1 still needs reading.
    assert widened["pages"] == [1] and widened["include_text_pages"] is True


def test_batch_reads_pages_and_reports_per_page(client, db, monkeypatch):
    """A whole-book scan is walked in bounded batches; one bad page must not lose the rest."""
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [word_list_output("afraid"), word_list_output("agree")])
    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "pages": [1, 2]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["words_added"] == 2 and body["processed"] == 2
    assert [item["status"] for item in body["results"]] == ["ok", "ok"]
    assert body["results"][0]["unit"] == "1"
    db.expire_all()
    assert {w.term for w in db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book))} \
        == {"afraid", "agree"}


def test_a_page_that_is_not_a_word_list_is_marked_scanned_and_not_offered_again(client, db, monkeypatch):
    """Re-reading a non-list page costs a paid call and cannot change the answer."""
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [json.dumps({"is_word_list": False, "entries": []})])
    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "pages": [1]})
    assert r.json()["results"][0]["status"] == "not_a_word_list"
    db.expire_all()
    page = db.scalar(select(BookPage).where(BookPage.book_id == book, BookPage.page_number == 1))
    assert page.vocab_scanned_at is not None
    remaining = client.get(f"{API}/books/{book}/vision-vocabulary/pending", headers=h).json()
    assert remaining["pages"] == [2]     # page 1 is done, page 2 still to read


def test_words_land_in_the_unit_the_model_read(client, db, monkeypatch):
    """A book whose pages carry no lesson still files words under the printed unit."""
    h, book, _, _ = setup_scan(client, db)
    from app.models import Chapter, Lesson

    db.query(Lesson).filter(Lesson.book_id == book).delete()
    chapter = Chapter(book_id=book, title="People", number="1", page_start=1, page_end=2, order_index=0)
    db.add(chapter)
    db.flush()
    db.add(Lesson(book_id=book, chapter_id=chapter.id, title="Unit 1", page_start=1, page_end=2,
                  order_index=0))
    db.commit()

    setup(monkeypatch, [word_list_output("afraid")])
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [1]})
    db.expire_all()
    word = db.scalar(select(VocabularyWord).where(VocabularyWord.book_id == book))
    assert word.chapter_id == chapter.id       # matched by the unit the banner showed
    assert word.lesson_id is not None


def test_units_view_lists_words_per_unit_and_keeps_orphans(client, db, monkeypatch):
    h, book, lesson, _ = setup_scan(client, db)
    from app.models import Lesson

    db.query(Lesson).filter(Lesson.book_id == book, Lesson.id != lesson).delete()
    db.add_all([
        VocabularyWord(book_id=book, lesson_id=lesson, term="afraid", page_number=1,
                       part_of_speech="adjective", definition_en="When someone is afraid."),
        VocabularyWord(book_id=book, term="agree", page_number=2, needs_translation=True),
    ])
    db.commit()
    body = client.get(f"{API}/books/{book}/vocabulary/units", headers=h).json()
    assert body["total"] == 2
    assert [unit["title"] for unit in body["units"]] == ["Lesson", "Boshqa lug'at yozuvlari"]
    assert [e["word"] for e in body["units"][0]["entries"]] == ["afraid"]
    assert [e["word"] for e in body["units"][1]["entries"]] == ["agree"]


# --- automatic fallback: the user must not have to notice a checkbox ------------------------

def test_the_request_carries_the_strict_json_schema(client, db, monkeypatch):
    """The model is constrained by a schema, not by a sentence in the prompt."""
    from app.services.ai.vision_vocabulary import VOCABULARY_JSON_SCHEMA

    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [word_list_output()])
    client.post(url(book, 1, "/preview"), headers=h, json={"consent_images_to_provider": True})
    schema = provider.calls[0][1].get("json_schema")
    assert schema == VOCABULARY_JSON_SCHEMA
    assert set(schema["properties"]) == {"is_word_list", "unit", "entries", "warnings"}
    entry = schema["properties"]["entries"]["items"]
    assert set(entry["properties"]) == {"word", "part_of_speech", "definition", "example", "bbox"}
    # Strict mode rejects optional properties, so every key must be required.
    assert set(entry["required"]) == set(entry["properties"])
    assert provider.calls[0][1].get("json_mode") is True


def test_a_transient_provider_error_is_retried_instead_of_losing_the_page(client, db, monkeypatch):
    """A 503 from the provider is retried; a 401 is not (it would fail on every page)."""
    from app.core.errors import ApiError

    class Flaky:
        name = "flaky"
        def __init__(self, failures):
            self.failures = failures
            self.calls = 0
        def complete(self, messages, **kwargs):
            from app.services.ai.provider import AIResponse
            self.calls += 1
            if self.calls <= self.failures:
                raise ApiError("AI_PROVIDER_BUSY", "band", 503)
            return AIResponse(content=word_list_output("afraid"), model="vision-test")

    h, book, _, _ = setup_scan(client, db)
    flaky = Flaky(1)
    monkeypatch.setattr("app.services.ai.vision_vocabulary.get_provider", lambda: flaky)
    monkeypatch.setattr("app.services.ai.vision_map.get_storage", lambda: Storage())
    monkeypatch.setattr(settings, "ai_vision_model", "vision-test")
    monkeypatch.setattr("app.services.ai.vision_vocabulary.time.sleep", lambda _s: None)
    r = client.post(url(book, 1), headers=h, json={"consent_images_to_provider": True})
    assert r.status_code == 200 and flaky.calls == 2


def test_fallback_runs_when_the_text_parser_found_nothing(client, db, monkeypatch):
    """The whole point: an unreadable text layer fills the Lug'at without a single click."""
    from tests.pdf_factory import make_sample_book

    # The sample book is grammar exercises: the text parser finds no word list at all, which
    # is the situation the user reported. The analysis itself must fall back to vision.
    monkeypatch.setattr(settings, "vocab_vision_fallback_min_entries", 50)
    monkeypatch.setattr(settings, "vocab_vision_fallback_pages", 2)
    # The renderer reads the PDF back from storage and checks its page count against the
    # Book row, so the test serves the same 2-page document that setup_scan creates.
    h, book_id, _, _ = setup_scan(client, db)
    db.get(Book, book_id).storage_path = "sciences/book.pdf"
    db.commit()
    from app.services import upload_cache
    from tests.test_vision_map_preview import pdf_bytes
    upload_cache.stash(book_id, pdf_bytes())   # what the upload endpoint leaves behind
    provider = setup(monkeypatch, [word_list_output("afraid", "agree")])
    from app.models import ProcessingJob
    from app.services.pipeline import Pipeline
    from app.services.storage import get_storage
    job = ProcessingJob(book_id=book_id, user_id=db.get(Book, book_id).user_id, status="queued",
                        job_type="reanalyze")   # setup_scan's book already has content
    db.add(job); db.commit()
    Pipeline(db, job).run()
    db.expire_all()
    book = db.get(Book, book_id)
    assert book.status == "ready"
    assert provider.calls, "the analysis must read pages with the vision model"
    vision_words = [w for w in db.scalars(select(VocabularyWord)
                                          .where(VocabularyWord.book_id == book_id))
                    if w.source == "vision"]
    assert {w.term for w in vision_words} == {"afraid", "agree"}
    assert all(w.needs_translation and w.translation_uz == "" for w in vision_words)
    assert book.vocabulary_note_uz       # the Lug'at screen can explain itself


def test_fallback_does_not_run_when_the_text_parser_succeeded(client, db, monkeypatch):
    """Vision costs money per page: a book the rules already read must not be re-read."""
    from app.models import Book

    h, book, _, _ = setup_scan(client, db)
    monkeypatch.setattr(settings, "vocab_vision_fallback_min_entries", 0)
    book_row = db.get(Book, book)
    book_row.text_vocabulary_count = 600
    db.commit()
    provider = setup(monkeypatch, [word_list_output()])
    from app.services.pipeline import Pipeline
    db.add_all([VocabularyWord(book_id=book, term=f"w{i}", page_number=1) for i in range(600)])
    db.commit()
    assert Pipeline(db, type("J", (), {"book_id": book})())._vision_vocabulary_fallback(
        db.get(Book, book), [{"page_number": 1}], 600)["words_added"] == 0
    assert provider.calls == []


def test_fallback_never_fails_the_upload_when_vision_is_unavailable(client, db, monkeypatch):
    """A missing key or a broken provider must leave a readable book readable."""
    from app.models import Book
    from tests.pdf_factory import make_sample_book

    monkeypatch.setattr(settings, "ai_provider", "none")     # no key in this deployment
    monkeypatch.setattr(settings, "vocab_vision_fallback_min_entries", 50)
    h = auth_headers(make_user(client, "fallback-off@example.com")["access_token"])
    response = client.post(f"{API}/books/upload", headers=h,
                           files={"file": ("s.pdf", make_sample_book(), "application/pdf")},
                           data={"consent": "true"})
    book_id = response.json()["id"]
    wait_for_book(client, h, book_id)
    db.expire_all()
    book = db.get(Book, book_id)
    assert book.status == "ready"        # the upload did not fail because of AI
    assert "AI (vision)" in book.vocabulary_note_uz


def test_a_batch_stops_starting_pages_when_its_time_budget_is_spent(client, db, monkeypatch):
    """A serverless kill must not swallow a batch that was already paid for."""
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [word_list_output("afraid"), word_list_output("agree")])
    # A zero budget means "do not start another page": the first one still runs, because a
    # batch that never makes progress would loop forever, and the rest wait for the next call.
    monkeypatch.setattr(settings, "vocab_vision_batch_seconds", 0.0)
    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "pages": [1, 2]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [item["status"] for item in body["results"]] == ["ok", "deferred"]
    assert body["remaining_pages"] == 1      # the deferred page is still owed
    assert body["words_added"] == 1


def test_a_dropped_database_connection_does_not_lose_the_paid_page(client, db, monkeypatch):
    """The model answer is already paid for; a dead pooled connection must not discard it."""
    from sqlalchemy.exc import OperationalError

    from app.api.v1 import books as books_api

    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [word_list_output("afraid")])
    assert books_api._is_transient_db_error(
        OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly")))
    assert not books_api._is_transient_db_error(ValueError("bad page"))

    from app.services.ai import vision_vocabulary as vv
    calls = {"n": 0}
    original_mark = vv.mark_scanned
    def flaky_mark(db_session, book_row, page_number):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("UPDATE", {}, Exception("SSL connection has been closed unexpectedly"))
        return original_mark(db_session, book_row, page_number)
    monkeypatch.setattr(vv, "mark_scanned", flaky_mark)

    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "pages": [1]})
    assert r.status_code == 200, r.text
    body = r.json()["results"][0]
    assert body["status"] == "ok" and body.get("retried") is True
    db.expire_all()
    assert db.scalar(select(func.count(VocabularyWord.id))
                     .where(VocabularyWord.book_id == book, VocabularyWord.term == "afraid")) == 1
