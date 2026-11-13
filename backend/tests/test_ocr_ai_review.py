"""OCR text-only AI review is explicit, grounded and never changes book content."""
import json
from sqlalchemy import select, func
from app.core.config import settings
from app.models import BookPage, Exercise, ExerciseQuestion, StudentAnswer, UsageEvent
from app.services.ai.provider import AIResponse
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan, lines


class Provider:
    name = 'mock'
    def __init__(self, output):
        self.output = output
        self.messages = []
    def complete(self, messages, **kwargs):
        self.messages.append(messages)
        return AIResponse(content=self.output, model='mock-model', tokens_in=20, tokens_out=40)


def output(source=2):
    return json.dumps({'exercises': [{'number': '9', 'instruction': 'Complete the passage.',
        'exercise_type': 'cloze', 'context': 'A single passage.', 'source_line_ids': [1, 2],
        'questions': [{'number': str(n), 'prompt': f'Blank {n}', 'source_line_ids': [source]}
                      for n in range(1, 11)], 'uncertainty': 'OCR may be incomplete.'}], 'warnings': []})


def test_review_is_opt_in_private_text_only_and_preserves_work(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, 'other-ai-review@example.com')['access_token'])
    url = f'/api/v1/books/{book}/ocr/pages/1/ai-review'
    payload = {**lines('Complete the passage.', '1) ... 2) ... 3) ... 4) ... 5) ... 6) ... 7) ... 8) ... 9) ... 10) ...'),
               'consent_text_to_provider': True}
    provider = Provider(output())
    monkeypatch.setattr('app.services.ai.ocr_review.get_provider', lambda: provider)
    assert client.post(url, headers=other, json=payload).status_code == 404
    assert client.post(url, headers=h, json={**payload, 'consent_text_to_provider': False}).status_code == 422
    assert not provider.messages
    res = client.post(url, headers=h, json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['needs_review'] and len(body['exercises']) == 1
    assert len(body['exercises'][0]['questions']) == 10
    assert body['source_lines'][1]['text'].startswith('1)')
    assert len(provider.messages) == 1 and all(not m.images for m in provider.messages[0])
    sent = json.loads(provider.messages[0][1].content)
    assert set(sent) == {'page_number', 'width', 'height', 'lines'}
    assert set(sent['lines'][0]) == {'id', 'text', 'bbox', 'confidence'}
    db.expire_all()
    page = db.scalar(select(BookPage).where(BookPage.book_id == book, BookPage.page_number == 1))
    assert page.needs_ocr and not page.text
    for table in (Exercise, ExerciseQuestion, StudentAnswer):
        assert db.scalar(select(func.count()).select_from(table)) == 0
    event = db.scalar(select(UsageEvent))
    assert event.feature == 'ocr_review' and event.tokens_in == 20


def test_invalid_output_rejected_and_call_accounted(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    url = f'/api/v1/books/{book}/ocr/pages/1/ai-review'
    provider = Provider(output(999))
    monkeypatch.setattr('app.services.ai.ocr_review.get_provider', lambda: provider)
    data = {**lines('Complete the passage.', '1) ... 2) ... long enough for test.'), 'consent_text_to_provider': True}
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 502 and res.json()['error']['code'] == 'AI_BAD_OUTPUT'
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 1
    db.expire_all()
    assert db.scalar(select(BookPage.needs_ocr).where(BookPage.book_id == book, BookPage.page_number == 1))
    provider.output = 'not JSON'
    assert client.post(url, headers=h, json=data).status_code == 502
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 2


def test_ai_unconfigured_and_oversize_do_not_send(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    url = f'/api/v1/books/{book}/ocr/pages/1/ai-review'
    payload = {**lines('Complete the passage.', '1) This is a long enough line.'), 'consent_text_to_provider': True}
    monkeypatch.setattr(settings, 'ai_provider', 'none')
    res = client.post(url, headers=h, json=payload)
    assert res.status_code == 503 and res.json()['error']['code'] == 'AI_NOT_CONFIGURED'
    provider = Provider(output())
    monkeypatch.setattr('app.services.ai.ocr_review.get_provider', lambda: provider)
    payload['lines'] = [{'text': 'a' * 999, 'bbox': [30, 20, 500, 35]} for _ in range(22)]
    res = client.post(url, headers=h, json=payload)
    assert res.status_code == 422 and res.json()['error']['code'] == 'AI_OCR_PAGE_TOO_LARGE'
    assert not provider.messages


def test_daily_quota_prevents_provider_call(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    from app.core.errors import ApiError
    provider = Provider(output())
    monkeypatch.setattr('app.services.ai.ocr_review.get_provider', lambda: provider)
    def deny(*args):
        raise ApiError('AI_QUOTA_EXCEEDED', 'Quota exceeded', 429)
    monkeypatch.setattr('app.services.ai.ocr_review.usage.enforce_ai_quota', deny)
    res = client.post(f'/api/v1/books/{book}/ocr/pages/1/ai-review', headers=h,
                      json={**lines('Complete the passage.', '1) This is a long enough line.'), 'consent_text_to_provider': True})
    assert res.status_code == 429 and not provider.messages
