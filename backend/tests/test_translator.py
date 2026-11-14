"""Translation is opt-in, bounded, quota-accounted and never sends page images."""
import json

from sqlalchemy import func, select
from app.models import UsageEvent
from app.services.ai.provider import AIResponse
from app.core.errors import ApiError
from tests.conftest import auth_headers, make_user


class Provider:
    name = 'fake'
    def __init__(self):
        self.calls = []
        self.content = json.dumps({'translation': 'olma'})
    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return AIResponse(content=self.content, model='test-model', tokens_in=10, tokens_out=4)


def test_translation_consent_validation_and_accounting(client, db, monkeypatch):
    h = auth_headers(make_user(client, 'translator@example.com')['access_token'])
    provider = Provider()
    monkeypatch.setattr('app.services.ai.translator.get_provider', lambda: provider)
    url = '/api/v1/tutor/translate'
    data = {'text': 'apple', 'direction': 'en-uz', 'consent_text_to_provider': True}
    assert client.post(url, json=data).status_code == 401
    assert client.post(url, headers=h, json={**data, 'consent_text_to_provider': False}).status_code == 422
    assert client.post(url, headers=h, json={**data, 'text': '  '}).status_code == 422
    assert client.post(url, headers=h, json={**data, 'text': 'a' * 1001}).status_code == 422
    assert client.post(url, headers=h, json={**data, 'direction': 'fr-en'}).status_code == 422
    assert not provider.calls
    r = client.post(url, headers=h, json=data)
    assert r.status_code == 200 and r.json()['translation'] == 'olma'
    messages, args = provider.calls[0]
    assert json.loads(messages[1].content) == {'text': 'apple', 'direction': 'en-uz'}
    assert all(not m.images for m in messages)
    assert args['json_mode'] is True
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 1
    assert db.scalar(select(UsageEvent)).feature == 'translator'
    r = client.post(url, headers=h, json={**data, 'text': 'olma', 'direction': 'uz-en'})
    assert r.status_code == 200
    assert json.loads(provider.calls[1][0][1].content)['direction'] == 'uz-en'


def test_invalid_response_and_quota_failure_are_not_success(client, db, monkeypatch):
    h = auth_headers(make_user(client, 'translator-fail@example.com')['access_token'])
    provider = Provider()
    monkeypatch.setattr('app.services.ai.translator.get_provider', lambda: provider)
    url = '/api/v1/tutor/translate'
    data = {'text': 'test', 'direction': 'en-uz', 'consent_text_to_provider': True}
    for output in ('not json', json.dumps({'translation': '  '}), json.dumps({'translation': 'x', 'extra': 'x'})):
        provider.content = output
        r = client.post(url, headers=h, json=data)
        assert r.status_code == 502 and r.json()['error']['code'] == 'AI_BAD_OUTPUT'
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 3
    def limit(*args):
        raise ApiError('AI_QUOTA_EXCEEDED', 'Limit', 429)
    monkeypatch.setattr('app.services.ai.translator.usage.enforce_ai_quota', limit)
    r = client.post(url, headers=h, json=data)
    assert r.status_code == 429 and len(provider.calls) == 3
