"""Safety, coordinate and answer-key regression coverage with generated PDFs."""
import fitz
import pytest
from sqlalchemy import select

from app.models import Book, BookPage, Exercise, ExerciseQuestion, LearningProgress, StudentAnswer
from app.services.grading import grade_question_deterministic
from app.services.pdf_extractor import extract_document
from app.services.structure_detector import detect_structure
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_sample_book
from tests.test_pipeline import upload


def test_native_character_boxes_are_actual_glyph_bounds():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((40, 70), 'Exercise 1. Complete the sentence.', fontsize=12)
    page.insert_text((40, 100), '1. Wide WWWW _____ next iii _____ end', fontsize=12)
    pages, _ = extract_document(doc)
    structure = detect_structure(pages)
    q = structure.exercises[0].questions[0]
    line = pages[0]['lines'][1]
    positions = [i for i, ch in enumerate(line['text']) if ch == '_']
    expected = [[min(line['chars'][i][0] for i in positions[j:j+5]),
                 min(line['chars'][i][1] for i in positions[j:j+5]),
                 max(line['chars'][i][2] for i in positions[j:j+5]),
                 max(line['chars'][i][3] for i in positions[j:j+5])] for j in (0, 5)]
    assert len(q.blanks) == 2
    for blank, box in zip(q.blanks, expected):
        assert blank['geometry'] == 'native_chars'
        assert blank['bbox'] == pytest.approx(box, abs=0.02)
    doc.close()


def test_missing_glyph_geometry_never_generates_guessed_boxes():
    line = lambda text, y: {'text': text, 'bbox': [10, y, 400, y+10], 'size': 10, 'bold': False, 'x0': 10}
    page = {'page_number': 1, 'width': 600, 'height': 800,
            'lines': [line('Exercise 1. Complete the sentence.', 10), line('1. She _____ here.', 30)]}
    result = detect_structure([page])
    assert result.exercises[0].questions[0].blanks[0]['bbox'] is None
    assert result.exercises[0].needs_review
    assert any(w['code'] == 'BLANK_LOCATION_UNKNOWN' for w in result.warnings)


def test_instruction_without_exercise_heading():
    doc = fitz.open(); page = doc.new_page()
    for y, text in [(60, 'Complete the sentences.'), (90, '1. She _____ home.'), (110, '2. We _____ here.')]:
        page.insert_text((50, y), text)
    pages, _ = extract_document(doc)
    result = detect_structure(pages)
    assert len(result.exercises) == 1 and len(result.exercises[0].questions) == 2
    assert result.exercises[0].instructions == 'Complete the sentences.'
    assert result.exercises[0].needs_review
    doc.close()


def test_reanalysis_guard_preserves_answer_and_progress(client, db):
    headers = auth_headers(make_user(client, 'integrity@example.com')['access_token'])
    book = upload(client, headers, make_sample_book()).json()['id']
    assert wait_for_book(client, headers, book)['status'] == 'completed'
    structure = client.get(f'/api/v1/books/{book}/structure', headers=headers).json()
    lesson = structure['lessons'][0]['id']
    exercise = client.get(f'/api/v1/lessons/{lesson}/exercises', headers=headers).json()[0]
    qid = exercise['questions'][0]['id']
    assert client.put(f"/api/v1/exercises/{exercise['id']}/answers", headers=headers,
                      json={'answers': [{'question_id': qid, 'content': {'blanks': {'b1': 'goes'}}}]}).status_code == 200
    assert client.post('/api/v1/progress/heartbeat', headers=headers,
                       json={'seconds': 0, 'lesson_id': lesson, 'page': 2}).status_code == 200
    assert client.post(f'/api/v1/books/{book}/reanalyze', headers=headers).status_code == 409
    db.expire_all()
    assert db.get(ExerciseQuestion, qid) is not None
    assert db.scalar(select(StudentAnswer).where(StudentAnswer.question_id == qid)).content['blanks']['b1'] == 'goes'
    assert db.scalar(select(LearningProgress).where(LearningProgress.lesson_id == lesson)).last_page == 2
    assert db.get(Book, book).status == 'ready'


def test_pipeline_write_failure_rolls_back_partial_content(client, db, monkeypatch):
    from app.core.config import settings
    from app.services.pipeline import Pipeline
    original = Pipeline.progress
    def fail_during_write(self, value, stage, **kwargs):
        if stage == 'vocabulary':
            raise RuntimeError('simulated database/write interruption')
        return original(self, value, stage, **kwargs)
    monkeypatch.setattr(settings, 'task_backend', 'sync')
    monkeypatch.setattr(Pipeline, 'progress', fail_during_write)
    headers = auth_headers(make_user(client, 'rollback@example.com')['access_token'])
    response = upload(client, headers, make_sample_book())
    book = response.json()['id']
    assert client.get(f'/api/v1/books/{book}/status', headers=headers).json()['status'] == 'failed'
    db.expire_all()
    assert not db.scalar(select(BookPage.id).where(BookPage.book_id == book))
    assert not db.scalar(select(Exercise.id).where(Exercise.book_id == book))


def test_matching_guesses_are_unverified_and_incomplete_blank_is_wrong():
    ex = Exercise(book_id='b', exercise_type='matching', detection='rule')
    q = ExerciseQuestion(exercise_id='x', matching_pairs=[{'left': 'a', 'right': 'b'}], answer_source='unknown')
    q.exercise = ex
    assert grade_question_deterministic(q, {'pairs': {'0': 'b'}})[0] is None
    ex2 = Exercise(book_id='b', exercise_type='fill_blank')
    q2 = ExerciseQuestion(exercise_id='x', blanks=[{'id': 'b1'}, {'id': 'b2'}], correct_answers=['is going'])
    q2.exercise = ex2
    assert grade_question_deterministic(q2, {'blanks': {'b1': 'is'}})[0] is False


def test_answer_key_with_repeated_numbers_requires_unique_exercise_reference():
    doc = fitz.open()
    page = doc.new_page()
    for y, text in [(50, 'Exercise 1. Complete the sentence.'), (70, '1. She _____ home.'),
                    (100, 'Exercise 2. Complete the sentence.'), (120, '1. We _____ home.')]:
        page.insert_text((50, y), text)
    key = doc.new_page()
    for y, text in [(50, 'Answer key'), (70, 'Exercise 1'), (90, '1. goes'),
                    (110, 'Exercise 2'), (130, '1. go')]:
        key.insert_text((50, y), text)
    pages, _ = extract_document(doc)
    result = detect_structure(pages)
    assert len(result.exercises) == 2
    assert result.exercises[0].questions[0].correct_answers == ['goes']
    assert result.exercises[1].questions[0].correct_answers == ['go']
    # An unlabelled single 1 cannot be assigned to either of two questions.
    doc.delete_page(1)
    key = doc.new_page()
    key.insert_text((50, 50), 'Answer key'); key.insert_text((50, 70), '1. goes')
    pages, _ = extract_document(doc)
    result = detect_structure(pages)
    assert all(not getattr(ex.questions[0], 'correct_answers', []) for ex in result.exercises)
    assert any(w['code'] == 'KEY_AMBIGUOUS' for w in result.warnings)
    doc.close()


def test_local_ocr_words_are_retained_but_not_guessed_as_blank_locations(monkeypatch):
    import app.services.pdf_extractor as extractor
    doc = fitz.open(); page = doc.new_page(width=600, height=800)
    words = [{'text': 'Exercise', 'bbox': [10, 20, 70, 30], 'confidence': 91.0}]
    monkeypatch.setattr(extractor, 'ocr_page_lines', lambda p: [
        {'text': 'Exercise 1. Complete the sentence.', 'bbox': [10, 20, 300, 35],
         'words': words, 'confidence': 91.0, 'size': 10.0, 'bold': False, 'x0': 10},
        {'text': '1. She _____ goes to school.', 'bbox': [10, 50, 300, 65],
         'words': words, 'confidence': 80.0, 'size': 10.0, 'bold': False, 'x0': 10},
    ])
    pages, warnings = extract_document(doc)
    assert pages[0]['ocr_used'] and pages[0]['lines'][0]['words'] == words
    assert any(w['code'] == 'OCR_REVIEW_REQUIRED' for w in warnings)
    assert detect_structure(pages).exercises[0].questions[0].blanks[0]['bbox'] is None
    monkeypatch.setattr(extractor, 'ocr_available', lambda: True)
    monkeypatch.setattr(extractor, 'ocr_page_lines', lambda p: [{'text': 'abc'}])
    pages, _ = extract_document(doc)
    assert pages[0]['needs_ocr'] and not pages[0]['ocr_used']
    doc.close()


def test_native_boxes_unrotated_with_cropped_rotated_page():
    doc = fitz.open(); page = doc.new_page(width=700, height=900)
    page.set_cropbox(fitz.Rect(50, 50, 650, 850))
    page.insert_text((30, 40), 'Exercise 1. Complete the sentence.')
    page.insert_text((30, 70), '1. She _____ home.')
    page.set_rotation(90)
    pages, _ = extract_document(doc)
    assert (pages[0]['width'], pages[0]['height']) == (600, 800)
    box = detect_structure(pages).exercises[0].questions[0].blanks[0]['bbox']
    assert 0 < box[0] < box[2] < 600 and 0 < box[1] < box[3] < 800
    doc.close()


def test_mixed_native_and_unrecognized_page_remains_pending(monkeypatch):
    import app.services.pdf_extractor as extractor
    doc = fitz.open()
    page = doc.new_page(); page.insert_text((40, 60), 'This page has enough native text to avoid OCR.')
    doc.new_page()
    monkeypatch.setattr(extractor, 'ocr_available', lambda: True)
    monkeypatch.setattr(extractor, 'ocr_page_lines', lambda p: [
        {'text': 'An uncertain recognition that should remain pending', 'confidence': 12,
         'bbox': [0, 0, 40, 20], 'size': 10, 'bold': False, 'x0': 0}])
    pages, warnings = extract_document(doc)
    assert len(pages) == 2 and not pages[0]['needs_ocr']
    assert pages[1]['needs_ocr'] and not pages[1]['ocr_used']
    assert any(w['page'] == 2 and w['code'] == 'OCR_FAILED' for w in warnings)
    doc.close()


def test_direct_pipeline_call_cannot_replace_existing_content(client, db):
    from app.models import ProcessingJob, User
    from app.services.pipeline import Pipeline
    from app.services.storage import get_storage
    headers = auth_headers(make_user(client, 'pipeline-guard@example.com')['access_token'])
    book_id = upload(client, headers, make_sample_book()).json()['id']
    assert wait_for_book(client, headers, book_id)['status'] == 'completed'
    db.expire_all()
    old_ids = list(db.scalars(select(ExerciseQuestion.id).join(Exercise).where(Exercise.book_id == book_id)))
    book = db.get(Book, book_id)
    job = ProcessingJob(book_id=book_id, user_id=book.user_id, status='queued')
    db.add(job); db.commit()
    Pipeline(db, job).run()
    assert job.status == 'failed' and job.error_code == 'REANALYZE_UNSAFE'
    assert book.status == 'ready'
    assert list(db.scalars(select(ExerciseQuestion.id).join(Exercise).where(Exercise.book_id == book_id))) == old_ids
