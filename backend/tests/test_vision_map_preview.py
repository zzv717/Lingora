"""Vision preview only sends consented pages, validates output and preserves book data."""
import base64
import json
import fitz
from sqlalchemy import select, func

from app.core.config import settings
from app.models import BookPage, Exercise, StudentAnswer, UsageEvent
from app.services.ai.provider import AIResponse
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan


def pdf_bytes():
    doc = fitz.open()
    for text in ('Cover', 'Contents'):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), text)
    result = doc.tobytes()
    doc.close()
    return result


def model_output(evidence=2, page_start=1, page_end=2):
    return json.dumps({'title': 'Example', 'author': '', 'topics': [
        {'title': 'Present tenses', 'page_start': page_start, 'page_end': page_end,
         'evidence_pages': [evidence], 'content_types': ['theory', 'exercise'], 'uncertainty': 'Partial sample.'}],
         'warnings': ['Not a complete map.']})


class Storage:
    def read(self, path):
        return pdf_bytes()


class Provider:
    name = 'mock'
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return AIResponse(content=self.responses[min(len(self.calls)-1, len(self.responses)-1)],
                          model='vision-test', tokens_in=100, tokens_out=20)


def setup(monkeypatch, responses):
    provider = Provider(responses)
    monkeypatch.setattr('app.services.ai.vision_map.get_provider', lambda: provider)
    monkeypatch.setattr('app.services.ai.vision_map.get_storage', lambda: Storage())
    monkeypatch.setattr(settings, 'ai_vision_model', 'vision-test')
    return provider


def test_page_consent_ownership_and_read_only(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, 'vision-other@example.com')['access_token'])
    provider = setup(monkeypatch, [model_output()])
    url = f'/api/v1/books/{book}/vision-map/preview'
    data = {'page_numbers': [2], 'consent_images_to_provider': True}
    assert client.post(url, headers=other, json=data).status_code == 404
    assert client.post(url, headers=h, json={**data, 'consent_images_to_provider': False}).status_code == 422
    for pages in ([0], [3], [1, 1], [1, 2, 3, 4, 5, 6]):
        assert client.post(url, headers=h, json={**data, 'page_numbers': pages}).status_code == 422
    assert not provider.calls
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['partial'] and body['sampled_pages'] == [2] and body['topics'][0]['evidence_pages'] == [2]
    msgs, args = provider.calls[0]
    assert args['model'] == 'vision-test' and args['json_mode']
    assert json.loads(msgs[1].content)['image_order_pdf_pages'] == [2]
    assert len(msgs[1].images) == 1 and msgs[1].images[0]['mime_type'] == 'image/png'
    pix = fitz.Pixmap(base64.b64decode(msgs[1].images[0]['data_base64']))
    assert max(pix.width, pix.height) <= 1800
    db.expire_all()
    assert db.scalar(select(BookPage.needs_ocr).where(BookPage.book_id == book, BookPage.page_number == 1))
    assert db.scalar(select(func.count()).select_from(Exercise)) == 0
    assert db.scalar(select(func.count()).select_from(StudentAnswer)) == 0
    assert db.scalar(select(UsageEvent)).feature == 'vision_map'


def test_invalid_model_output_retries_and_never_claims_success(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    url = f'/api/v1/books/{book}/vision-map/preview'
    data = {'page_numbers': [2], 'consent_images_to_provider': True}
    provider = setup(monkeypatch, ['bad json', model_output(evidence=1)])
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 502 and res.json()['error']['code'] == 'AI_BAD_OUTPUT'
    assert len(provider.calls) == 2
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 2
    provider.responses = ['bad json', model_output()]; provider.calls = []
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 200 and len(provider.calls) == 2


def test_no_provider_or_vision_model_never_sends_image(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    url = f'/api/v1/books/{book}/vision-map/preview'
    data = {'page_numbers': [1], 'consent_images_to_provider': True}
    monkeypatch.setattr(settings, 'ai_provider', 'none')
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 503 and res.json()['error']['code'] == 'AI_NOT_CONFIGURED'
    provider = setup(monkeypatch, [model_output()])
    monkeypatch.setattr(settings, 'ai_vision_model', '')
    res = client.post(url, headers=h, json=data)
    assert res.status_code == 503 and res.json()['error']['code'] == 'AI_VISION_NOT_CONFIGURED'
    assert not provider.calls


def topic_output(evidence=2):
    return json.dumps({'topic': 'Present Forms', 'theory': [{'text': 'Theory text', 'evidence_pages': [1]}],
        'exercises': [{'number': '9', 'instruction': 'Complete the passage.', 'exercise_type': 'cloze',
        'context': 'Shared passage', 'evidence_pages': [2], 'uncertainty': 'Review the scan.',
        'questions': [{'number': str(i), 'prompt': f'Blank {i}', 'options': [], 'evidence_pages': [evidence]}
                      for i in range(1, 11)]}], 'warnings': []})


def test_topic_preview_keeps_group_and_sends_only_selected_pages(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, 'topic-other@example.com')['access_token'])
    provider = setup(monkeypatch, [topic_output()])
    monkeypatch.setattr('app.services.ai.vision_topic.get_provider', lambda: provider)
    url = f'/api/v1/books/{book}/vision-topic/preview'
    payload = {'page_numbers': [2, 1], 'topic': 'Present Forms', 'consent_images_to_provider': True}
    assert client.post(url, headers=other, json=payload).status_code == 404
    assert client.post(url, headers=h, json={**payload, 'consent_images_to_provider': False}).status_code == 422
    assert not provider.calls
    res = client.post(url, headers=h, json=payload)
    assert res.status_code == 200, res.text
    result = res.json()
    assert result['sampled_pages'] == [1, 2] and result['partial']
    assert len(result['exercises']) == 1 and len(result['exercises'][0]['questions']) == 10
    assert result['exercises'][0]['context'] == 'Shared passage'
    assert len(provider.calls[0][0][1].images) == 2
    assert db.scalar(select(func.count()).select_from(Exercise)) == 0
    assert db.scalar(select(func.count()).select_from(StudentAnswer)) == 0
    assert db.scalar(select(UsageEvent)).feature == 'vision_topic_preview'


def test_topic_rejects_out_of_scope_sources(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [topic_output(evidence=3)])
    monkeypatch.setattr('app.services.ai.vision_topic.get_provider', lambda: provider)
    res = client.post(f'/api/v1/books/{book}/vision-topic/preview', headers=h,
                      json={'page_numbers': [1, 2], 'topic': '', 'consent_images_to_provider': True})
    assert res.status_code == 502 and res.json()['error']['code'] == 'AI_BAD_OUTPUT'
    assert len(provider.calls) == 2
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 2
