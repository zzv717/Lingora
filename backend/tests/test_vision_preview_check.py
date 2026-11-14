"""The preview check must be consented, bounded, image-grounded, and non-persistent."""
import json
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Exercise, StudentAnswer, UsageEvent
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan
from tests.test_vision_map_preview import Provider, Storage


def payload():
    return {'page_numbers': [2, 1], 'consent_to_provider': True, 'number': '1',
            'instruction': 'Look at the pictures', 'context': '', 'questions': [
                {'number': '1', 'prompt': '...', 'options': [], 'answer': 'an apple'},
                {'number': '2', 'prompt': '...', 'options': [], 'answer': ''},
                {'number': '3', 'prompt': '...', 'options': [], 'answer': 'a cat'},
                {'number': '4', 'prompt': '...', 'options': [], 'answer': 'a dog'}]}


def mock_provider(monkeypatch, verdicts):
    provider = Provider([json.dumps({'verdicts': verdicts})])
    monkeypatch.setattr('app.services.ai.vision_preview_check.get_provider', lambda: provider)
    monkeypatch.setattr('app.services.ai.vision_map.get_storage', lambda: Storage())
    monkeypatch.setattr(settings, 'ai_vision_model', 'vision-test')
    return provider


def verdict(index, correct=True, confidence=.95):
    return {'index': index, 'correct': correct, 'confidence': confidence, 'explanation_uz': 'Izoh'}


def test_permission_bounds_and_image_feedback(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, 'check-other@example.com')['access_token'])
    provider = mock_provider(monkeypatch, [verdict(0), verdict(1), verdict(2, False, .4)])
    url = f'/api/v1/books/{book}/vision-topic/check'
    data = payload()
    assert client.post(url, headers=other, json=data).status_code == 404
    assert client.post(url, headers=h, json={**data, 'consent_to_provider': False}).status_code == 422
    for pages in ([0], [3], [1, 1], [1, 2, 3, 4, 5, 6]):
        assert client.post(url, headers=h, json={**data, 'page_numbers': pages}).status_code == 422
    assert client.post(url, headers=h, json={**data, 'questions': [dict(data['questions'][0], answer=' ')]}).status_code == 422
    assert not provider.calls
    r = client.post(url, headers=h, json=data)
    assert r.status_code == 200, r.text
    assert [x['correct'] for x in r.json()['verdicts']] == [True, None, None, None]
    msgs, args = provider.calls[0]
    assert len(msgs[1].images) == 2 and args['model'] == 'vision-test' and args['json_mode']
    assert json.loads(msgs[1].content)['image_order_pdf_pages'] == [1, 2]
    assert db.scalar(select(func.count()).select_from(Exercise)) == 0
    assert db.scalar(select(func.count()).select_from(StudentAnswer)) == 0
    assert db.scalar(select(UsageEvent)).feature == 'vision_preview_check'


def test_malformed_or_duplicate_feedback_fails_closed(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = mock_provider(monkeypatch, [verdict(0), verdict(0)])
    url = f'/api/v1/books/{book}/vision-topic/check'
    for content in [provider.responses[0], '{', json.dumps({'verdicts': [verdict(5)]}),
                    json.dumps({'verdicts': [verdict(0, 'true')]})]:
        provider.responses = [content]
        r = client.post(url, headers=h, json=payload())
        assert r.status_code == 502 and r.json()['error']['code'] == 'AI_BAD_OUTPUT'
