"""Lesson-start options are owner-scoped, read-only counts of existing data."""
from sqlalchemy import func, select

from app.models import Book, BookPage, Exercise, Lesson, LearningProgress, Profile, StudentAnswer, User, VocabularyWord
from tests.conftest import auth_headers, make_user


def test_lesson_options_counts_progress_locks_and_privacy(client, db):
    owner = auth_headers(make_user(client, 'lesson-plan@example.com')['access_token'])
    other = auth_headers(make_user(client, 'lesson-plan-other@example.com')['access_token'])
    user = db.scalar(select(User).where(User.email == 'lesson-plan@example.com'))
    book = Book(user_id=user.id, title='Scanned', status='ready', page_count=3)
    db.add(book); db.flush()
    first = Lesson(book_id=book.id, title='First', page_start=1, page_end=2, order_index=0, grammar_explanation_uz='Qoidalar')
    second = Lesson(book_id=book.id, title='Second', page_start=2, page_end=3, order_index=1)
    db.add_all([first, second]); db.flush()
    db.add_all([BookPage(book_id=book.id, page_number=n, needs_ocr=(n == 2)) for n in (1, 2, 3)])
    db.add_all([Exercise(book_id=book.id, lesson_id=first.id, exercise_type='fill_blank'),
                Exercise(book_id=book.id, lesson_id=first.id, exercise_type='writing'),
                VocabularyWord(book_id=book.id, lesson_id=first.id, term='hello', translation_uz='salom'),
                LearningProgress(user_id=user.id, book_id=book.id, lesson_id=first.id, status='in_progress')])
    db.commit()
    url = f'/api/v1/books/{book.id}/lesson-options'
    assert client.get(url).status_code == 401
    assert client.get(url, headers=other).status_code == 404
    response = client.get(url, headers=owner)
    assert response.status_code == 200, response.text
    data = response.json()['lessons']
    assert [x['id'] for x in data] == [first.id, second.id]
    assert data[0]['exercise_count'] == 2 and data[0]['vocabulary_count'] == 1
    assert data[0]['has_explanation'] and data[0]['pending_ocr_pages'] == 1
    assert data[1]['pending_ocr_pages'] == 1 and data[1]['page_inventory_complete']
    assert data[0]['progress']['status'] == 'in_progress' and data[1]['progress']['locked']
    # Read-only: don't mark pages processed or create answers/progress records.
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(LearningProgress)) == 1
    assert db.scalar(select(func.count()).select_from(StudentAnswer)) == 0
    assert db.scalar(select(BookPage.needs_ocr).where(BookPage.book_id == book.id, BookPage.page_number == 2))
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    profile.vocabulary_gating = False
    db.delete(db.scalar(select(BookPage).where(BookPage.book_id == book.id, BookPage.page_number == 3)))
    db.commit()
    result = client.get(url, headers=owner).json()['lessons']
    assert not result[1]['progress']['locked'] and not result[1]['page_inventory_complete']


def test_options_reject_unready_book(client, db):
    owner = auth_headers(make_user(client, 'lesson-unready@example.com')['access_token'])
    user = db.scalar(select(User).where(User.email == 'lesson-unready@example.com'))
    book = Book(user_id=user.id, title='Pending', status='processing')
    db.add(book); db.commit()
    response = client.get(f'/api/v1/books/{book.id}/lesson-options', headers=owner)
    assert response.status_code == 409 and response.json()['error']['code'] == 'BOOK_NOT_READY'


def test_uploaded_textbook_options_link_to_existing_exercises_and_saved_answers(client, db):
    from tests.conftest import wait_for_book
    from tests.pdf_factory import make_sample_book
    h = auth_headers(make_user(client, 'plan-flow@example.com')['access_token'])
    upload = client.post('/api/v1/books/upload', headers=h,
                         files={'file': ('sample.pdf', make_sample_book(), 'application/pdf')},
                         data={'consent': 'true'})
    assert upload.status_code == 201, upload.text
    book = upload.json()['id']
    assert wait_for_book(client, h, book)['status'] == 'completed'
    options = client.get(f'/api/v1/books/{book}/lesson-options', headers=h).json()['lessons']
    assert options and options[0]['exercise_count'] > 0
    first = options[0]
    response = client.get(f"/api/v1/lessons/{first['id']}/exercises", headers=h)
    assert response.status_code == 200 and len(response.json()) == first['exercise_count']
    ex = next(e for e in response.json() if e['questions'])
    qid = ex['questions'][0]['id']
    saved = client.put(f"/api/v1/exercises/{ex['id']}/answers", headers=h,
                       json={'answers': [{'question_id': qid, 'content': {'text': 'my saved response'}}]})
    assert saved.status_code == 200
    assert client.post('/api/v1/progress/heartbeat', headers=h,
                       json={'seconds': 0, 'lesson_id': first['id'], 'page': first['page_start']}).status_code == 200
    after = client.get(f"/api/v1/exercises/{ex['id']}/answers", headers=h).json()
    assert next(a for a in after if a['question_id'] == qid)['content']['text'] == 'my saved response'
    refreshed = client.get(f'/api/v1/books/{book}/lesson-options', headers=h).json()['lessons']
    assert refreshed[0]['progress']['last_page'] == first['page_start']
