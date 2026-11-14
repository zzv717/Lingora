"""Daily request limits can be restored without losing usage or disabling other safeguards."""
import pytest
from sqlalchemy import select

from app.core.config import Settings, settings
from app.core.errors import ApiError
from app.models import User
from app.services.ai import usage
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan
from tests.test_vision_exercises import page_output, setup, url


def test_daily_request_switch_default_and_env(monkeypatch):
    monkeypatch.delenv('AI_DAILY_REQUEST_LIMITS_ENABLED', raising=False)
    assert Settings(_env_file=None).ai_daily_request_limits_enabled is False
    monkeypatch.setenv('AI_DAILY_REQUEST_LIMITS_ENABLED', 'true')
    assert Settings(_env_file=None).ai_daily_request_limits_enabled is True


def test_request_limits_disabled_then_reenabled_with_accounting(client, db, monkeypatch):
    h = auth_headers(make_user(client, 'quota-switch@example.com')['access_token'])
    user_id = db.scalar(select(User.id).where(User.email == 'quota-switch@example.com'))
    monkeypatch.setattr(settings, 'ai_daily_request_limits_enabled', False)
    monkeypatch.setattr(settings, 'free_ai_calls_per_day', 1)
    monkeypatch.setattr(settings, 'ai_daily_token_limit', 0)
    usage.record_usage(db, user_id, 'tutor', 'test', 'test', 10, 10)
    usage.enforce_ai_quota(db, user_id, 'translator')
    usage.record_usage(db, user_id, 'translator', 'test', 'test', 10, 10)
    usage.enforce_feature_quota(db, user_id, 'vision_exercises', 1)
    usage.record_usage(db, user_id, 'vision_exercises', 'test', 'test', 10, 10)
    usage.enforce_feature_quota(db, user_id, 'vision_exercises', 1)
    assert usage.ai_calls_today(db, user_id) == 2
    assert usage.feature_calls_today(db, user_id, 'vision_exercises') == 1
    assert client.get('/api/v1/me/plan', headers=h).json()['ai_calls_per_day'] == 0

    monkeypatch.setattr(settings, 'ai_daily_request_limits_enabled', True)
    assert client.get('/api/v1/me/plan', headers=h).json()['ai_calls_per_day'] == 1
    with pytest.raises(ApiError) as general:
        usage.enforce_ai_quota(db, user_id, 'translator')
    assert general.value.code == 'AI_QUOTA_EXCEEDED'
    with pytest.raises(ApiError) as vision:
        usage.enforce_feature_quota(db, user_id, 'vision_exercises', 1)
    assert vision.value.code == 'AI_FEATURE_QUOTA_EXCEEDED'


def test_separate_token_cap_still_applies(client, db, monkeypatch):
    make_user(client, 'token-cap@example.com')
    user_id = db.scalar(select(User.id).where(User.email == 'token-cap@example.com'))
    monkeypatch.setattr(settings, 'ai_daily_request_limits_enabled', False)
    monkeypatch.setattr(settings, 'ai_daily_token_limit', 1)
    usage.record_usage(db, user_id, 'tutor', 'test', 'test', 1, 1)
    for enforce in (lambda: usage.enforce_ai_quota(db, user_id, 'translator'),
                    lambda: usage.enforce_feature_quota(db, user_id, 'vision_exercises', 1)):
        with pytest.raises(ApiError) as error:
            enforce()
        assert error.value.code == 'AI_TOKEN_QUOTA_EXCEEDED'


def test_vision_page_daily_request_cap_is_disabled(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_output(), page_output('95')])
    monkeypatch.setattr(settings, 'ai_daily_request_limits_enabled', False)
    monkeypatch.setattr(settings, 'vision_exercise_pages_per_day', 1)
    ok = {'consent_images_to_provider': True}
    assert client.post(url(book, 1), headers=h, json=ok).status_code == 200
    assert client.post(url(book, 2), headers=h, json=ok).status_code == 200
    assert len(provider.calls) == 2
