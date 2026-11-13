"""Opt-in page OCR is private, resumable and does not replace student work."""
from sqlalchemy import select

from app.models import Book, BookPage, Exercise, ExerciseQuestion, Lesson, StudentAnswer, VocabularyWord
from tests.conftest import auth_headers, make_user

API = '/api/v1'


def setup_scan(client, db):
    h = auth_headers(make_user(client, 'ocr@example.com')['access_token'])
    from app.models import User
    user = db.scalar(select(User).where(User.email == 'ocr@example.com'))
    book = Book(user_id=user.id, title='Scan', status='ready', page_count=2)
    db.add(book); db.flush()
    lesson = Lesson(book_id=book.id, title='Lesson', page_start=1, page_end=1, order_index=0)
    next_lesson = Lesson(book_id=book.id, title='Next', page_start=2, page_end=2, order_index=1)
    db.add_all([lesson, next_lesson]); db.flush()
    db.add_all([BookPage(book_id=book.id, page_number=i, width=600, height=800, needs_ocr=True)
                for i in (1, 2)])
    db.commit()
    return h, book.id, lesson.id, next_lesson.id


def lines(*texts):
    return {'lines': [{'text': text, 'bbox': [30, 20 + i * 20, 500, 35 + i * 20]}
                      for i, text in enumerate(texts)]}


def test_page_ingestion_is_private_idempotent_and_preserves_answers(client, db):
    h, book, lesson, next_lesson = setup_scan(client, db)
    other = auth_headers(make_user(client, 'ocr-other@example.com')['access_token'])
    url = f'{API}/books/{book}/ocr/pages/1'
    data = lines('Exercise 1. Put the verbs into the correct form.',
                 '1. She ______ to school every day. (go)', '2. They ______ football. (play)')
    assert client.get(f'{API}/books/{book}/ocr/pending', headers=other).status_code == 404
    assert client.post(url, headers=other, json=data).status_code == 404
    assert client.get(f'{API}/books/{book}/ocr/pending', headers=h).json()['pages'] == [1, 2]
    r = client.post(url, headers=h, json=data)
    assert r.status_code == 200, r.text
    assert r.json()['exercises_added'] == 1
    db.expire_all()
    ex = db.scalar(select(Exercise).where(Exercise.book_id == book))
    qs = list(db.scalars(select(ExerciseQuestion).where(ExerciseQuestion.exercise_id == ex.id)))
    assert ex.lesson_id == lesson and ex.needs_review and ex.detection == 'ocr'
    assert len(qs) == 2 and all(not q.correct_answers and q.answer_source == 'unknown' for q in qs)
    assert all(b['bbox'] is None for q in qs for b in q.blanks)
    ans = {'answers': [{'question_id': qs[0].id, 'content': {'blanks': {'b1': 'goes'}}}]}
    assert client.put(f'{API}/exercises/{ex.id}/answers', headers=h, json=ans).status_code == 200
    r = client.post(url, headers=h, json=data)
    assert r.json()['already_processed'] is True
    db.expire_all()
    assert len(list(db.scalars(select(Exercise).where(Exercise.book_id == book)))) == 1
    assert db.scalar(select(StudentAnswer).where(StudentAnswer.question_id == qs[0].id)).content['blanks']['b1'] == 'goes'
    assert client.post(f'{API}/books/{book}/reanalyze', headers=h).status_code == 409
    assert client.get(f'{API}/books/{book}/ocr/pending', headers=h).json()['pages'] == [2]


def test_empty_and_out_of_bounds_are_not_marked_processed(client, db):
    h, book, _, _ = setup_scan(client, db)
    url = f'{API}/books/{book}/ocr/pages/1'
    assert client.post(url, headers=h, json=lines('hi')).status_code == 422
    assert client.post(url, headers=h, json={'lines': [{'text': 'Words in a scanned page here', 'bbox': [0, 0, 9999, 10]}]}).status_code == 422
    assert client.get(f'{API}/books/{book}/ocr/pending', headers=h).json()['pages'] == [1, 2]


def test_untranslated_words_do_not_lock_later_lessons(client, db):
    h, book, lesson, next_lesson = setup_scan(client, db)
    db.add(VocabularyWord(book_id=book, lesson_id=lesson, term='word', needs_translation=True))
    db.commit()
    structure = client.get(f'{API}/books/{book}/structure', headers=h).json()
    assert not structure['lessons_progress'][next_lesson]['locked']
    assert client.get(f'{API}/lessons/{next_lesson}/exercises', headers=h).status_code == 200
    # An untranslated candidate must not lock the next lesson's vocabulary session.
    response = client.post(f'{API}/vocabulary/sessions?lesson_id={next_lesson}&kind=lesson_gate', headers=h)
    assert response.status_code == 404 and response.json()['error']['code'] == 'NO_VOCABULARY'


def test_ocr_questions_without_detected_underscores_still_have_input(client, db):
    h, book, lesson, _ = setup_scan(client, db)
    payload = lines('Exercise 1. Put the verbs into the correct form.',
                    '1. She to school every day. (go)')
    r = client.post(f'{API}/books/{book}/ocr/pages/1', headers=h, json=payload)
    assert r.status_code == 200 and r.json()['exercises_added'] == 1
    ex = client.get(f'{API}/lessons/{lesson}/exercises', headers=h).json()[0]
    assert ex['questions'][0]['blanks'] == [{'id': 'b1', 'bbox': None}]
    qid = ex['questions'][0]['id']
    client.put(f"{API}/exercises/{ex['id']}/answers", headers=h,
               json={'answers': [{'question_id': qid, 'content': {'blanks': {'b1': 'goes'}}}]})
    result = client.post(f"{API}/exercises/{ex['id']}/check", headers=h)
    assert result.status_code == 200, result.text
    assert result.json()['max_score'] == 0 and result.json()['verdicts'][0]['correct'] is None
