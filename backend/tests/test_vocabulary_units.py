"""Vocabulary units, cleaning, dedupe, Uzbek translation and the grouped Lug'at view.

The behaviour these tests lock in is what the user actually saw on the reference book:

* units came out as single pages ("9–9") and with a title that was a stray glyph;
* German-numbered duplicates and entries with no definition were stored;
* every word arrived without an Uzbek translation and was therefore excluded from tests.

The fixtures below therefore look like that book — a banner page, a continuation page, a
page that is not a word list at all — rather than like an ideal one.
"""
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.models import VocabularyUnit, VocabularyWord
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan
from tests.test_vision_vocabulary import API, setup

BOOK_PAGES = 6


class Storage:
    """A PDF with exactly as many pages as the book claims.

    The renderer checks the page count against the ``Book`` row (a stale PDF must not be
    rendered), so a fixture book cannot borrow another test's document.
    """

    def __init__(self, pages: int = BOOK_PAGES):
        self.pages = pages

    def read(self, path):
        import fitz

        doc = fitz.open()
        for _ in range(self.pages):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50), "Word List")
        result = doc.tobytes()
        doc.close()
        return result


def _setup_book(client, db, pages=BOOK_PAGES):
    """A ready book with ``pages`` scanned pages and no lesson, like a real word-list book."""
    h, book, _lesson, _next = setup_scan(client, db)
    from app.models import Book, BookPage, Lesson
    from sqlalchemy import delete

    db.execute(delete(Lesson).where(Lesson.book_id == book))
    db.execute(delete(BookPage).where(BookPage.book_id == book))
    db.add_all([BookPage(book_id=book, page_number=i, width=600, height=800, needs_ocr=True)
                for i in range(1, pages + 1)])
    db.get(Book, book).page_count = pages
    db.commit()
    _PAGES[0] = pages          # the fixture PDF must match the page count the row claims
    return h, book


def headings(*rows):
    """Pass-1 answer: (page, unit_number, title, confidence)."""
    return json.dumps({"warnings": [], "pages": [
        {"page": page, "unit_number": number, "unit_title": title,
         "has_banner": bool(title), "confidence": confidence}
        for page, number, title, confidence in rows]})


def words(*entries, unit="1", title=""):
    payload = []
    for index, (word, pos, definition) in enumerate(entries, start=1):
        payload.append({"word": word, "part_of_speech": pos, "definition": definition,
                        "example": f"The word {word} is used here.", "order_in_page": index,
                        "bbox": [0.05, 0.1 + index * 0.05, 0.5, 0.14 + index * 0.05]})
    return json.dumps({"is_word_list": True, "unit": unit, "unit_title": title,
                       "entries": payload, "warnings": []})


def not_a_word_list():
    return json.dumps({"is_word_list": False, "unit": "", "unit_title": "",
                       "entries": [], "warnings": []})


def translations(*pairs):
    return json.dumps({"translations": [
        {"id": word_id, "translation_uz": translation, "alt_translations": []}
        for word_id, translation in pairs]})


_PAGES = [BOOK_PAGES]


class ScriptedProvider:
    """A provider that answers by schema, not by call order.

    One extraction makes three different calls (headings, page words, translations) and the
    order of the last two depends on the batch; keying the answers by the requested schema is
    what keeps these tests about behaviour instead of about call sequencing.
    """

    name = "mock"

    def __init__(self, heading_rows, page_words=None, translate=None):
        self.heading_rows = heading_rows
        # Keyed by page number: a batch may read its pages in any order, and a fixture that
        # relies on call order would be testing the order, not the behaviour.
        self.page_words = dict(page_words or {})
        self.translate = translate          # optional callable(ids) -> dict
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        schema = (kwargs.get("json_schema") or {}).get("title", "")
        if schema == "page_unit_map":
            content = headings(*self.heading_rows)
        elif schema == "vocabulary_page":
            page = json.loads(messages[-1].content).get("pdf_page")
            content = self.page_words.pop(page, not_a_word_list())
        elif schema == "vocabulary_translations":
            payload = json.loads(messages[-1].content)
            ids = [item["id"] for item in payload]
            if self.translate:
                content = json.dumps({"translations": self.translate(ids)})
            else:
                content = json.dumps({"translations": [
                    {"id": word_id, "translation_uz": f"tarjima-{index}",
                     "alt_translations": []} for index, word_id in enumerate(ids, start=1)]})
        else:
            raise AssertionError(f"unexpected schema {schema!r}")
        from app.services.ai.provider import AIResponse

        return AIResponse(content=content, model="vision-test", tokens_in=100, tokens_out=20)


def _setup_ai(monkeypatch, responses=None, *, heading_rows=None, page_words=None, translate=None):
    if isinstance(responses, ScriptedProvider):
        provider = responses
    else:
        provider = ScriptedProvider(heading_rows or [], page_words or [])
    for module in ("vision_vocabulary", "vocabulary_units", "vocab_translate"):
        monkeypatch.setattr(f"app.services.ai.{module}.get_provider", lambda p=provider: p)
    monkeypatch.setattr("app.services.ai.vision_map.get_storage", lambda: Storage(_PAGES[0]))
    monkeypatch.setattr(settings, "ai_vision_model", "vision-test")
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "chat-test")
    monkeypatch.setattr(settings, "vision_exercise_pages_per_day", 500)
    return provider


# --- Pass 1: unit numbers, titles, ranges -----------------------------------------------------

def test_units_come_from_the_heading_pass_with_ranges_until_the_next_unit(client, db, monkeypatch):
    """The reported defect: unit 1 was "page 9-9" and its title was a stray glyph."""
    h, book = _setup_book(client, db)
    _setup_ai(monkeypatch, heading_rows=[
        (1, 1, "People", 0.9), (2, 1, "", 0.8), (3, 2, "The Family", 0.9),
        (4, 2, "", 0.7), (5, 0, "", 0.3), (6, 3, "School", 0.85)])
    r = client.post(f"{API}/books/{book}/vocabulary/units/detect", headers=h,
                    json={"consent_images_to_provider": True})
    assert r.status_code == 200, r.text
    units = r.json()["units"]
    assert [(u["number"], u["title"]) for u in units] == [(1, "People"), (2, "The Family"),
                                                         (3, "School")]
    # A unit runs from its own banner page to the page before the next banner: page 3 is the
    # last page of unit 1, not "9-9", and a page with no banner (5) stays in unit 2.
    assert [(u["page_start"], u["page_end"]) for u in units] == [(1, 2), (3, 5), (6, 6)]
    db.expire_all()
    stored = db.scalars(select(VocabularyUnit).where(VocabularyUnit.book_id == book)
                        .order_by(VocabularyUnit.number)).all()
    assert [u.title for u in stored] == ["People", "The Family", "School"]


def test_a_title_that_is_one_glyph_becomes_unit_n_and_never_a_letter(client, db, monkeypatch):
    """The banner is not in the text layer, so the model once answered "r" as the title."""
    h, book = _setup_book(client, db)
    _setup_ai(monkeypatch, heading_rows=[(1, 6, "r", 0.4), (2, 6, "6-unit · r", 0.3)])
    r = client.post(f"{API}/books/{book}/vocabulary/units/detect", headers=h,
                    json={"consent_images_to_provider": True})
    assert r.status_code == 200, r.text
    unit = r.json()["units"][0]
    assert unit["title"] == "Unit 6"
    assert len(unit["title"]) >= 3


def test_a_low_confidence_unit_number_still_produces_a_sequential_unit(client, db, monkeypatch):
    h, book = _setup_book(client, db)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.2), (2, 0, "", 0.1),
                                         (3, 2, "School", 0.2)])
    client.post(f"{API}/books/{book}/vocabulary/units/detect", headers=h,
                json={"consent_images_to_provider": True})
    db.expire_all()
    numbers = [u.number for u in db.scalars(select(VocabularyUnit)
                                            .where(VocabularyUnit.book_id == book)).all()]
    assert numbers == [1, 2]


# --- Pass 2: cleaning, dedupe, rejection ------------------------------------------------------

def test_words_are_cleaned_deduped_and_entries_without_a_definition_are_rejected(client, db, monkeypatch):
    h, book = _setup_book(client, db, pages=2)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("1. afraid [uh-freyd] adj.", "adjective", "When someone is afraid."),
                                   ("afraid", "adjective", "duplicate of the same entry"),
                                   ("agree", "verb", ""),       # no definition -> rejected
                                   ("angry", "adjective", "When someone is angry."),
                                   ("a whole sentence that is not a headword at all", "noun", "junk"))})
    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "pages": [1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rejected"] >= 2          # no definition, and a sentence in the word field
    db.expire_all()
    words_in_db = {w.term for w in db.scalars(
        select(VocabularyWord).where(VocabularyWord.book_id == book)).all()}
    assert words_in_db == {"afraid", "angry"}
    unit = db.scalar(select(VocabularyUnit).where(VocabularyUnit.book_id == book))
    assert unit is not None and unit.title == "People"
    word = db.scalar(select(VocabularyWord).where(VocabularyWord.term == "afraid"))
    # Reading order is stored, so the Lug'at can list the page exactly as the book does.
    assert word.position >= 1 and word.unit_id == unit.id


def test_positions_count_within_the_unit_not_within_the_page(client, db, monkeypatch):
    """A unit's words are one list: page 2 must continue page 1's numbering, not restart."""
    h, book = _setup_book(client, db, pages=2)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "d1"), ("agree", "verb", "d2")),
                          2: words(("angry", "adjective", "d3"))})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [1, 2]})
    body = client.get(f"{API}/books/{book}/vocabulary/units", headers=h).json()
    entries = body["units"][0]["entries"]
    assert [e["word"] for e in entries] == ["afraid", "agree", "angry"]
    assert [e["position"] for e in entries] == [1, 2, 3]


def test_two_columns_keep_reading_order(client, db, monkeypatch):
    """A two-column page must be read left column first, as the order the book teaches."""
    h, book = _setup_book(client, db, pages=2)
    two_columns = json.dumps({"is_word_list": True, "unit": "1", "unit_title": "People",
                              "warnings": [], "entries": [
        {"word": "afraid", "part_of_speech": "adjective", "definition": "d1",
         "example": "e1", "order_in_page": 1, "bbox": []},
        {"word": "bottom", "part_of_speech": "noun", "definition": "d2",
         "example": "e2", "order_in_page": 2, "bbox": []},
    ]})
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: two_columns})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [1]})
    body = client.get(f"{API}/books/{book}/vocabulary/units", headers=h).json()
    assert [e["word"] for e in body["units"][0]["entries"]] == ["afraid", "bottom"]


def test_re_extraction_replaces_the_previous_machine_rows(client, db, monkeypatch):
    """Re-reading a book must not double it, and must replace the broken first extraction."""
    h, book = _setup_book(client, db, pages=2)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "old extraction")),
                          2: words(("agree", "verb", "a better extraction finds agree"))})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [1]})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [2]})
    db.expire_all()
    assert db.scalar(select(func.count(VocabularyWord.id))
                     .where(VocabularyWord.book_id == book)) == 2

    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "new extraction"))})
    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "replace_existing": True})
    assert r.status_code == 200, r.text
    assert r.json()["cleared"]["words_removed"] == 2
    db.expire_all()
    rows = list(db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book)).all())
    assert len(rows) == 1 and rows[0].definition_en == "new extraction"


def test_a_human_edited_word_survives_a_re_extraction(client, db, monkeypatch):
    h, book = _setup_book(client, db, pages=2)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "definition"))})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [1]})
    db.expire_all()
    word = db.scalar(select(VocabularyWord).where(VocabularyWord.book_id == book))
    edited = client.patch(f"{API}/books/{book}/vocabulary/{word.id}", headers=h,
                          json={"translation_uz": "qo'rqmoq"}).json()
    assert edited["translation_status"] == "edited"

    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "definition"))})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "replace_existing": True})
    db.expire_all()
    assert db.scalar(select(VocabularyWord.translation_uz)
                     .where(VocabularyWord.book_id == book, VocabularyWord.term == "afraid")) \
        == "qo'rqmoq"


# --- Pass 3: Uzbek translations ---------------------------------------------------------------

def test_extraction_translates_words_and_auto_translations_are_usable_in_tests(client, db, monkeypatch):
    """The reported defect: every word said "tarjima tekshirilmagan" and was not testable."""
    h, book = _setup_book(client, db, pages=2)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "When someone is afraid."),
                                   ("agree", "verb", "To agree is to say yes."))})
    r = client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                    json={"consent_images_to_provider": True, "pages": [1]})
    assert r.status_code == 200, r.text
    db.expire_all()
    rows = list(db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book)).all())
    assert len(rows) == 2
    # Extraction translated the words it just stored: the Lug'at is usable without a second
    # manual step, and "auto" means machine translated, not unusable.
    assert all(row.translation_uz for row in rows)
    assert all(row.translation_status == "auto" for row in rows)
    assert all(row.needs_translation is False for row in rows)
    assert r.json()["translated"] == 2


def test_translation_skips_words_that_already_have_one_and_never_overwrites_a_human(client, db, monkeypatch):
    h, book = _setup_book(client, db, pages=2)
    db.add_all([
        VocabularyWord(book_id=book, term="afraid", translation_uz="qo'rqmoq",
                       translation_status="verified", needs_translation=False, source="vision"),
        VocabularyWord(book_id=book, term="agree", translation_uz="", translation_status="",
                       needs_translation=True, source="vision"),
    ])
    db.commit()
    provider = _setup_ai(monkeypatch, ScriptedProvider([], translate=lambda ids: [
        {"id": word_id, "translation_uz": "rozi bo'lmoq", "alt_translations": ["kelishmoq"]}
        for word_id in ids]))
    r = client.post(f"{API}/books/{book}/vocabulary/translate-missing", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["requested"] == 1
    assert provider.calls, "one batch call is expected"
    db.expire_all()
    afraid = db.scalar(select(VocabularyWord).where(VocabularyWord.term == "afraid"))
    agree = db.scalar(select(VocabularyWord).where(VocabularyWord.term == "agree"))
    assert afraid.translation_uz == "qo'rqmoq" and afraid.translation_status == "verified"
    assert agree.translation_uz == "rozi bo'lmoq" and agree.translation_status == "auto"
    assert agree.alt_translations == ["kelishmoq"]


def test_a_translation_batch_failure_keeps_the_words_and_is_retryable(client, db, monkeypatch):
    from app.core.errors import ApiError
    from app.models import Book
    from app.services.ai import vocab_translate

    h, book = _setup_book(client, db, pages=2)
    db.add_all([VocabularyWord(book_id=book, term="afraid", source="vision", needs_translation=True),
                VocabularyWord(book_id=book, term="agree", source="vision", needs_translation=True)])
    db.commit()

    class Broken:
        name = "broken"
        calls = 0

        def complete(self, *args, **kwargs):
            Broken.calls += 1
            raise ApiError("AI_QUOTA_EXCEEDED", "kvota tugadi", 429)

    _setup_ai(monkeypatch, ScriptedProvider([]))
    monkeypatch.setattr("app.services.ai.vocab_translate.get_provider", lambda: Broken())
    stats = vocab_translate.translate_words(
        db, db.get(Book, book).user_id, vocab_translate.missing_translations(db, book))
    assert stats["translated"] == 0 and stats["failed_batches"] == 1
    assert Broken.calls == 1          # an account-level failure is not retried per batch
    db.expire_all()
    # The words are still there, still missing a translation, and the ids still match: a
    # later call simply picks them up again.
    assert db.scalar(select(func.count(VocabularyWord.id))
                     .where(VocabularyWord.book_id == book)) == 2
    assert len(vocab_translate.missing_translations(db, book)) == 2


def test_the_translation_prompt_is_short_and_asks_for_a_single_uzbek_word():
    from app.services.ai import vocab_translate

    prompt = vocab_translate.PROMPT
    assert "o'zbek" in prompt
    assert "alt_translations" in prompt
    assert vocab_translate.BATCH_SIZE >= 20 and vocab_translate.BATCH_SIZE <= 30


def test_translation_cleanup_drops_explanations_and_part_of_speech_tags():
    from app.services.ai.vocab_translate import clean_translation

    assert clean_translation("jasur — brave, botir") == "jasur"
    assert clean_translation("(ot) kitob") == "kitob"
    assert clean_translation("  Kitob.  ") == "Kitob"
    assert clean_translation("") == ""
    assert clean_translation("juda uzoq va tushunarsiz izoh bilan yozilgan ibora") == ""


# --- The grouped Lug'at view ------------------------------------------------------------------

def test_the_units_view_orders_by_unit_and_page_and_reports_counts(client, db, monkeypatch):
    h, book = _setup_book(client, db, pages=4)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 1, "", 0.9),
                                        (3, 2, "The Family", 0.9), (4, 2, "", 0.9)],
              page_words={1: words(("afraid", "adjective", "d1")),
                          3: words(("family", "noun", "d3"))})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [3, 1]})
    body = client.get(f"{API}/books/{book}/vocabulary/units", headers=h).json()
    assert [u["number"] for u in body["units"]] == [1, 2]
    assert [u["title"] for u in body["units"]] == ["People", "The Family"]
    assert [u["count"] for u in body["units"]] == [1, 1]
    assert body["units"][0]["page_start"] == 1 and body["units"][1]["page_start"] == 3
    assert [e["word"] for e in body["units"][0]["entries"]] == ["afraid"]
    assert [e["word"] for e in body["units"][1]["entries"]] == ["family"]
    assert body["total"] == 2 and body["translated"] == 2


def test_a_word_can_be_edited_verified_moved_and_deleted(client, db, monkeypatch):
    h, book = _setup_book(client, db, pages=2)
    _setup_ai(monkeypatch, heading_rows=[(1, 1, "People", 0.9), (2, 2, "Family", 0.9)],
              page_words={1: words(("afraid", "adjective", "d1")),
                          2: words(("family", "noun", "d2"))})
    client.post(f"{API}/books/{book}/vision-vocabulary/batch", headers=h,
                json={"consent_images_to_provider": True, "pages": [1, 2]})
    db.expire_all()
    units = db.scalars(select(VocabularyUnit).where(VocabularyUnit.book_id == book)
                       .order_by(VocabularyUnit.number)).all()
    word_id = db.scalar(select(VocabularyWord.id)
                        .where(VocabularyWord.term == "afraid"))

    moved = client.patch(f"{API}/books/{book}/vocabulary/{word_id}", headers=h,
                         json={"unit_id": units[1].id}).json()
    assert moved["unit_id"] == units[1].id
    assert moved["position"] >= 1

    edited = client.patch(f"{API}/books/{book}/vocabulary/{word_id}", headers=h,
                          json={"translation_uz": "qo'rqmoq", "word": "Afraid"}).json()
    assert edited["translation_uz"] == "qo'rqmoq" and edited["word"] == "Afraid"
    verified = client.post(f"{API}/books/{book}/vocabulary/{word_id}/verify", headers=h).json()
    assert verified["translation_status"] == "verified"

    assert client.delete(f"{API}/books/{book}/vocabulary/{word_id}", headers=h).status_code == 200
    db.expire_all()
    assert db.scalar(select(VocabularyWord.id).where(VocabularyWord.id == word_id)) is None


def test_the_word_update_refuses_a_definition_sized_headword(client, db):
    h, book = _setup_book(client, db, pages=1)
    db.add(VocabularyWord(book_id=book, term="afraid", source="vision"))
    db.commit()
    word_id = db.scalar(select(VocabularyWord.id).where(VocabularyWord.book_id == book))
    r = client.patch(f"{API}/books/{book}/vocabulary/{word_id}", headers=h,
                     json={"word": "a full sentence pretending to be a headword"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "WORD_TOO_LONG"


def test_the_units_view_is_private(client, db):
    h, book = _setup_book(client, db, pages=1)
    other = auth_headers(make_user(client, "vocab-units-other@example.com")["access_token"])
    assert client.get(f"{API}/books/{book}/vocabulary/units", headers=other).status_code == 404
    assert client.post(f"{API}/books/{book}/vocabulary/units/detect", headers=other,
                       json={"consent_images_to_provider": True}).status_code == 404
