"""Vision vocabulary: consent, validation, no invented translations, idempotency, limits.

The scanned word-list page these tests model is the real 4000 Essential English Words
layout: a coloured headword with its pronunciation, a part-of-speech tag, a definition
sentence, a bulleted example and a small illustration.
"""
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.models import UsageEvent, VocabularyWord
from app.services.ai.vision_vocabulary import clean_example, clean_term, normalize_word_list
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan
from tests.test_vision_map_preview import Provider, Storage

API = "/api/v1"


def word_list_output(*terms):
    words = []
    for i, term in enumerate(terms or ("afraid", "agree", "angry")):
        words.append({
            "term": f"{term} [pron-{i}] adj.",
            "part_of_speech": "adjective",
            "definition_en": f"When someone is {term}, they feel something.",
            "example_sentence": f"» The {term} woman was afraid of what she saw.",
            "bbox": [0.1, 0.1 + i * 0.08, 0.9, 0.17 + i * 0.08],
            "confidence": 0.9,
        })
    return json.dumps({"is_word_list": True, "heading": "Word List", "words": words, "warnings": []})


def setup(monkeypatch, responses):
    provider = Provider(responses)
    monkeypatch.setattr("app.services.ai.vision_vocabulary.get_provider", lambda: provider)
    monkeypatch.setattr("app.services.ai.vision_map.get_storage", lambda: Storage())
    monkeypatch.setattr(settings, "ai_vision_model", "vision-test")
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
    result = normalize_word_list({"words": [
        {"term": "afraid [uh-freyd] adj.", "definition_en": "When someone is afraid."},
        {"term": "Agree", "definition_en": "To agree is to say yes."},
        {"term": "afraid", "definition_en": "duplicate"},
        {"term": "a whole definition sentence that is too long to be a word", "definition_en": "junk"},
    ]})
    assert result.is_word_list is True
    assert [w.term for w in result.words] == ["afraid", "agree"]


def test_a_page_without_a_word_list_is_not_saved(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [json.dumps({"is_word_list": False, "words": []})])
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
    assert [w["term"] for w in r.json()["words"]] == ["afraid", "agree", "angry"]
    assert r.json()["words"][0]["bbox"] is not None
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
