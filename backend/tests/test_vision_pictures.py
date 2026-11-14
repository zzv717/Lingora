import json
from sqlalchemy import func, select
from app.core.config import settings
from app.models import Exercise, StudentAnswer, UsageEvent
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan
from tests.test_vision_map_preview import Provider, Storage


def payload():
    return {'page_numbers': [2, 1], 'consent_images_to_provider': True,
            'number': '1', 'instruction': 'Look at pictures', 'questions': [
                {'number': '2', 'prompt': '...', 'evidence_pages': [2]},
                {'number': '3', 'prompt': '...', 'evidence_pages': [2]},
                {'number': '4', 'prompt': '...', 'evidence_pages': [2]}]}


def setup(monkeypatch, locations):
    provider = Provider([json.dumps({'locations': locations})])
    monkeypatch.setattr('app.services.ai.vision_pictures.get_provider', lambda: provider)
    monkeypatch.setattr('app.services.ai.vision_map.get_storage', lambda: Storage())
    monkeypatch.setattr(settings, 'ai_vision_model', 'vision-test')
    return provider


def test_localization_is_private_bounded_and_preserves_valid_items(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, 'picture-other@example.com')['access_token'])
    provider = setup(monkeypatch, [
        {'index': 0, 'picture': {'page': 2, 'bbox': [100, 100, 300, 300]}},
        {'index': 1, 'picture': {'page': 1, 'bbox': [100, 100, 300, 300]}},
        {'index': 2, 'picture': {'page': 2, 'bbox': [300, 100, 100, 300]}}])
    url = f'/api/v1/books/{book}/vision-topic/pictures'
    data = payload()
    assert client.post(url, headers=other, json=data).status_code == 404
    assert client.post(url, headers=h, json={**data, 'consent_images_to_provider': False}).status_code == 422
    for pages in ([0], [3], [1, 1], [1, 2, 3, 4, 5, 6]):
        assert client.post(url, headers=h, json={**data, 'page_numbers': pages}).status_code == 422
    assert not provider.calls
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 200, res.text
    assert res.json()['locations'] == [{'index': 0, 'picture': {'page': 2, 'bbox': [100, 100, 300, 300]}}]
    messages, args = provider.calls[0]
    assert len(messages[1].images) == 2
    sent = json.loads(messages[1].content)
    assert sent['image_order_pdf_pages'] == [1, 2]
    assert all('answer' not in item for item in sent['questions'])
    assert db.scalar(select(func.count()).select_from(Exercise)) == 0
    assert db.scalar(select(func.count()).select_from(StudentAnswer)) == 0
    assert db.scalar(select(UsageEvent)).feature == 'vision_picture_locations'


def test_invalid_indices_rejected(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [])
    url = f'/api/v1/books/{book}/vision-topic/pictures'
    for locations in ([{'index': 0, 'picture': None}, {'index': 0, 'picture': None}],
                      [{'index': 3, 'picture': None}], [{'index': '0', 'picture': None}]):
        provider.responses = [json.dumps({'locations': locations})]
        res = client.post(url, headers=h, json=payload())
        assert res.status_code == 502
