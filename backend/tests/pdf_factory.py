"""Generates realistic test PDF textbooks with PyMuPDF (chapters, exercises, vocab, answer key)."""
import fitz

BODY = 11


def _page_lines(page, lines, start_y=70, leading=18, x=50):
    y = start_y
    for text, size, bold in lines:
        font = "hebo" if bold else "helv"
        page.insert_text((x, y), text, fontsize=size, fontname=font)
        y += leading + (4 if size > BODY else 0)


def make_sample_book() -> bytes:
    doc = fitz.open()

    # ---- Page 1: Unit + Lesson 1 + fill-blank exercise ----
    p = doc.new_page(width=595, height=842)
    _page_lines(p, [
        ("UNIT 1 Present Simple Tense", 20, True),
        ("Lesson 1 Present Simple", 14, True),
        ("Exercise 1. Put the verbs into the correct form.", BODY, False),
        ("1. She _____ to school every day. (go)", BODY, False),
        ("2. They _____ football on Sundays. (play)", BODY, False),
        ("3. Ann _____ her homework in the evening. (do)", BODY, False),
    ])

    # ---- Page 2: multiple choice ----
    p = doc.new_page(width=595, height=842)
    _page_lines(p, [
        ("Exercise 2. Choose the correct answer.", BODY, False),
        ("1. She _____ to school by bus.", BODY, False),
        ("A) go", BODY, False),
        ("B) goes", BODY, False),
        ("C) going", BODY, False),
        ("2. The sun _____ in the east.", BODY, False),
        ("A) rise", BODY, False),
        ("B) rises", BODY, False),
        ("C) risen", BODY, False),
    ])

    # ---- Page 3: translation ----
    p = doc.new_page(width=595, height=842)
    _page_lines(p, [
        ("Exercise 3. Translate the sentences into English.", BODY, False),
        ("1. U har kuni maktabga boradi.", BODY, False),
        ("2. Biz har yakshanba futbolda o'ynaymiz.", BODY, False),
    ])

    # ---- Page 4: vocabulary (Lesson 1) ----
    p = doc.new_page(width=595, height=842)
    _page_lines(p, [
        ("Vocabulary List", 13, True),
        ("go — borish, ketish", BODY, False),
        ("school — maktab", BODY, False),
        ("play — o'ynamoq", BODY, False),
        ("day — kun", BODY, False),
        ("work — ish qilish", BODY, False),
        ("every day — har kuni", BODY, False),
    ])

    # ---- Page 5: Lesson 2 + continuous exercise + vocab ----
    p = doc.new_page(width=595, height=842)
    _page_lines(p, [
        ("Lesson 2 Present Continuous", 14, True),
        ("Exercise 4. Put the verbs into the Present Continuous.", BODY, False),
        ("1. The teacher _____ us English now. (teach)", BODY, False),
        ("2. They _____ football at the moment. (play)", BODY, False),
        ("teach — o'qitmoq", BODY, False),
        ("moment — lahza, payt", BODY, False),
        ("now — hozir", BODY, False),
    ])

    # ---- Page 6: answer key ----
    p = doc.new_page(width=595, height=842)
    _page_lines(p, [
        ("Answer key", 14, True),
        ("Exercise 1", BODY, False),
        ("1. goes", BODY, False),
        ("2. play", BODY, False),
        ("3. does", BODY, False),
        ("Exercise 2", BODY, False),
        ("1. B", BODY, False),
        ("2. B", BODY, False),
        ("Exercise 3", BODY, False),
        ("1. He goes to school every day.", BODY, False),
        ("2. We play football every Sunday.", BODY, False),
        ("Exercise 4", BODY, False),
        ("1. is teaching", BODY, False),
        ("2. are playing", BODY, False),
    ])

    return doc.tobytes()


def make_scanned_like_book() -> bytes:
    """PDF with no extractable text (image-only page) to test the honest OCR fallback."""
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    # draw text as vector graphics? simplest: draw a filled rect so page has content but no text
    p.draw_rect(fitz.Rect(40, 40, 555, 400), color=(0, 0, 0), width=1)
    p.insert_text((50, 60), "", fontsize=BODY)
    return doc.tobytes()


def make_garbage_file() -> bytes:
    return b"this is definitely not a pdf file" * 10
