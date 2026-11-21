"""Dictionary-style vocabulary books: word lists, unit grouping and picture crops.

The fixture is a generated PDF, not a real textbook: it reproduces the layout that
matters (headword + definition + a round illustration in the left column, drawn into a
single background image) so the detector and the crop geometry can be checked exactly.
"""
import io

import fitz
import pytest
from PIL import Image, ImageDraw

from app.services.dictionary_pictures import attach_word_pictures, picture_box_for
from app.services.pdf_extractor import extract_document
from app.services.structure_detector import (
    _dictionary_entry,
    _key_letters,
    _match_target_word,
    _target_words,
    _unit_target_words,
    detect_structure,
)
from tests.conftest import auth_headers, make_user, wait_for_book

WORDS = [
    ("afraid", "adj", "When someone is afraid, they feel fear."),
    ("agree", "v", "To agree is to say yes or to think the same way."),
    ("angry", "adj", "When someone is angry, they may want to speak loudly."),
    ("arrive", "v", "To arrive is to get to or reach some place."),
    ("bottom", "n", "The bottom is the lowest part."),
]


def _picture_column(height: int = 700) -> Image.Image:
    """One tall strip of coloured discs — the book draws all pictures this way."""
    canvas = Image.new("RGB", (110, height), "white")
    draw = ImageDraw.Draw(canvas)
    for index in range(len(WORDS) + 3):
        top = 40 + index * 100
        draw.ellipse((10, top, 90, top + 80), fill=(60 + index * 20, 90, 160), outline=(20, 20, 20))
    return canvas


def make_dictionary_pdf() -> bytes:
    doc = fitz.open()
    column_png = io.BytesIO()
    _picture_column().save(column_png, format="PNG")
    for page_index in range(3):
        page = doc.new_page(width=508.7, height=729.8)
        # One tall picture strip in the left column, like the book's single background image.
        page.insert_image(fitz.Rect(10, 0, 120, 730), stream=column_png.getvalue())
        page.insert_text((60, 40), "UNIT", fontsize=18, fontname="hebo")
        page.insert_text((100, 60), "Word List", fontsize=18, fontname="hebo")
        y = 120.0
        for word, pos, definition in WORDS:
            page.insert_text((115, y), f"{word} [x] {pos}.", fontsize=11, fontname="helv")
            page.insert_text((115, y + 16), definition, fontsize=10, fontname="helv")
            page.insert_text((118, y + 32), "- The example sentence.", fontsize=10, fontname="helv")
            y += 100
    buffer = doc.tobytes()
    doc.close()
    return buffer


@pytest.fixture(scope="module")
def dictionary_book():
    content = make_dictionary_pdf()
    doc = fitz.open(stream=content, filetype="pdf")
    pages, _warnings = extract_document(doc)
    structure = detect_structure(pages)
    yield doc, pages, structure
    doc.close()


def _index(*words: str) -> dict[str, str]:
    return {_key_letters(word): word for word in words}


def test_spelled_out_and_noise_glued_headwords_are_repaired_with_the_book_index():
    """Real damage from the book's PDF, repaired against its own word list."""
    index = _index("afraid", "benefit", "clerk", "occur", "officer", "rich", "exercise")
    cases = {
        "r afraid [afreid] adj.": "afraid",
        "b e n e f it  [benefit] n.": "benefit",
        "p u b lis h  [pAblijl v.": None,          # not in this index: rejected, never guessed
        "C le r k  [klark] n.": "clerk",
        "r occur t e r i  v.": "occur",
        "r  officer loofisad n.": "officer",
        "r ic h  [ritj] adj.": "rich",
        "e x e r c is e  [eksarsaiz] v.": "exercise",
    }
    for text, expected in cases.items():
        entry = _dictionary_entry({"text": text, "bbox": [0, 0, 1, 1]}, index)
        assert (entry["term"] if entry else None) == expected, text


def test_common_words_that_are_not_headwords_are_never_invented():
    index = _index("seven", "autumn", "million")
    # A number table or running text on an appendix page is not a word-list entry.
    for text in ["seven", "Autumn", "one million", "The bottom is the lowest part.",
                 "To agree is to say yes or to think the same way."]:
        assert _dictionary_entry({"text": text, "bbox": [0, 0, 1, 1]}, index) is None, text


def test_target_word_index_is_read_per_unit_of_twenty():
    """The "Target Words" index page groups the words per unit; each group is a whitelist."""
    doc = fitz.open()
    rows = [", ".join(word for word, _pos, _definition in WORDS) + ","]
    layout_page = doc.new_page(width=508.7, height=729.8)
    layout_page.insert_text((60, 60), "Target Words", fontsize=16, fontname="hebo")
    y = 100.0
    for row in rows * 4:
        layout_page.insert_text((60, y), row, fontsize=10)
        y += 16
    opened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    doc.close()
    pages, _warnings = extract_document(opened)
    opened.close()
    words = _target_words(pages)
    # A row is only accepted once the page has several of them, which is the shape of a
    # real index; duplicates are collapsed and the groups are twenty words each.
    assert words[:5] == [word for word, _pos, _definition in WORDS]
    units = _unit_target_words(pages)
    assert units and all(len(unit) == 5 for unit in units)


def test_damaged_word_is_matched_to_the_single_closest_index_word():
    index = _index("burn", "seven", "competition")
    assert _match_target_word("bum", index) == "burn"
    assert _match_target_word("competitio", index) == "competition"
    # A short index word must never truncate a longer one.
    assert _match_target_word("competition", index) == "competition"


def test_headword_line_is_parsed_with_part_of_speech():
    entry = _dictionary_entry({"text": "afraid [afreid] adj.", "bbox": [1, 2, 3, 4]})
    assert entry and entry["term"] == "afraid" and entry["part_of_speech"] == "adjective"
    # A leading glyph marker is not part of the word, but articles are kept.
    assert _dictionary_entry({"text": "r agree [x] v.", "bbox": [1, 2, 3, 4]})["term"] == "agree"
    assert _dictionary_entry({"text": "a lot [x] n.", "bbox": [1, 2, 3, 4]})["term"] == "a lot"
    # Definition sentences are not headwords.
    assert _dictionary_entry({"text": "The bottom is the lowest part.", "bbox": [1, 2, 3, 4]}) is None


def test_dictionary_layout_groups_consecutive_word_list_pages_into_one_unit(dictionary_book):
    """A unit's word list can run over several pages, so consecutive lists stay together."""
    _doc, _pages, structure = dictionary_book
    assert structure.layout == "dictionary"
    assert len(structure.chapters) == 1
    chapter = structure.chapters[0]
    assert chapter["title"].startswith("Unit 1")
    assert (chapter["page_start"], chapter["page_end"]) == (1, 3)
    assert len(structure.lessons) == 1


def test_an_exercise_page_between_word_lists_starts_a_new_unit():
    doc = fitz.open()
    column = io.BytesIO()
    _picture_column().save(column, format="PNG")
    for index in range(4):
        page = doc.new_page(width=508.7, height=729.8)
        page.insert_image(fitz.Rect(10, 0, 120, 730), stream=column.getvalue())
        if index == 2:  # an exercise page ends the previous unit's list
            page.insert_text((60, 60), "Exercise 1. Choose the correct answer.", fontsize=11)
            page.insert_text((60, 80), "1. She _____ to school.", fontsize=11)
            continue
        page.insert_text((100, 60), "Word List", fontsize=18, fontname="hebo")
        y = 120.0
        for word, pos, definition in WORDS:
            page.insert_text((115, y), f"{word} [x] {pos}.", fontsize=11)
            page.insert_text((115, y + 16), definition, fontsize=10)
            y += 60
    content = doc.tobytes()
    doc.close()
    opened = fitz.open(stream=content, filetype="pdf")
    pages, _warnings = extract_document(opened)
    structure = detect_structure(pages)
    opened.close()
    assert structure.layout == "dictionary"
    assert len(structure.chapters) == 2
    assert structure.chapters[0]["page_start"] == 1
    assert structure.chapters[1]["page_start"] == 4


def test_every_headword_becomes_a_vocabulary_entry_with_its_definition(dictionary_book):
    _doc, _pages, structure = dictionary_book
    terms = [word["term"] for word in structure.vocabulary]
    assert terms[:5] == [word for word, _pos, _definition in WORDS]
    first = structure.vocabulary[0]
    assert first["definition_en"].startswith("When someone is afraid")
    assert first["part_of_speech"] == "adjective"
    assert first["needs_translation"] is True


def test_picture_is_found_beside_the_headword_and_stays_on_the_page(dictionary_book):
    doc, _pages, structure = dictionary_book
    found = attach_word_pictures(doc, structure.vocabulary)
    assert found >= len(WORDS), "every entry on the word-list pages has a picture"
    for word in structure.vocabulary:
        picture = word["picture"]
        if not picture:
            continue
        assert picture["page_number"] == word["page_number"]
        x1, y1, x2, y2 = picture["bbox"]
        assert 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1
        # The illustration lives in the left column of the page.
        assert x2 < 0.25


def test_picture_box_is_none_when_the_headword_has_no_illustration(dictionary_book):
    doc, pages, _structure = dictionary_book
    page = pages[0]
    # A line at the far right has no picture column to its left.
    assert picture_box_for(doc, page["page_number"], [480.0, 300.0, 505.0, 312.0]) is None


def test_vocabulary_picture_endpoint_crops_from_the_original_pdf(client):
    """The endpoint returns a real PNG crop of the stored PDF, owner only."""
    content = make_dictionary_pdf()
    headers = auth_headers(make_user(client, "dictionary@example.com")["access_token"])
    upload = client.post("/api/v1/books/upload", headers=headers,
                         files={"file": ("words.pdf", content, "application/pdf")},
                         data={"title": "Dictionary", "consent": "true"})
    assert upload.status_code == 201, upload.text
    book_id = upload.json()["id"]
    assert wait_for_book(client, headers, book_id)["status"] == "completed"

    words = client.get(f"/api/v1/books/{book_id}/vocabulary", headers=headers).json()
    with_picture = [word for word in words if word.get("picture_page")]
    assert with_picture, "the upload must keep the detected illustration boxes"

    word = with_picture[0]
    response = client.get(f"/api/v1/books/{book_id}/vocabulary/{word['id']}/picture",
                          headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coordinate_space"] == "normalized_0_1"
    assert body["data_url"].startswith("data:image/png;base64,")

    raw = client.get(f"/api/v1/books/{book_id}/vocabulary/{word['id']}/picture.png",
                     headers=headers)
    assert raw.status_code == 200
    image = Image.open(io.BytesIO(raw.content))
    image.load()
    # Quality, not size: the crop must be rendered at >= 180 DPI of the ORIGINAL page,
    # i.e. far sharper than a screenshot of a scaled-down page.
    x1, _y1, x2, _y2 = word["picture_bbox"]
    page_width_points = 508.7
    dpi_equivalent = image.width / max(1e-6, (x2 - x1) * page_width_points) * 72
    assert dpi_equivalent >= 180, f"crop resolution {dpi_equivalent:.0f} DPI is too low"
    assert client.get(f"/api/v1/books/{book_id}/vocabulary/{word['id']}/picture.png").status_code == 401


def test_unbalanced_pronunciation_keeps_the_part_of_speech():
    """A scan that drops a closing bracket must not cost the word its grammar.

    "angry [sengro adj." is what the real reference book's text layer contains; before this
    the entry survived with an empty part of speech, which the Lug'at screen shows as a
    blank badge. Nothing may be guessed here — the label is printed on the line.
    """
    for text, term, pos in [("r angry [sengro adj.", "angry", "adjective"),
                            ("r attack [at*io v.", "attack", "verb"),
                            ("hide [haid] y.", "hide", "verb")]:      # scanned "y" for "v"
        entry = _dictionary_entry({"text": text, "bbox": [0, 0, 1, 1]})
        assert entry and entry["term"] == term and entry["part_of_speech"] == pos, text


def test_definition_is_a_sentence_not_a_leftover_illustration_fragment():
    """A definition column polluted by an illustration must yield the sentence, or nothing."""
    from app.services.structure_detector import _looks_like_sentence

    assert _looks_like_sentence("To agree is to say yes or to think the same way.")
    assert not _looks_like_sentence("1* ^ '")
    assert not _looks_like_sentence("I iffm&")
    assert not _looks_like_sentence("r")
