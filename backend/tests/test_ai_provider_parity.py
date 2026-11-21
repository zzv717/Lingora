"""Every provider must accept the same `complete()` call, and translation must work on all.

The bug this file locks down: `vocab_translate` (and the vision/unit passes) call
``provider.complete(..., json_schema=...)``. The base class declared that argument and the
OpenAI-compatible provider accepted it, but ``GeminiProvider.complete`` did not — so with
``AI_PROVIDER=gemini`` translation died with

    TypeError: GeminiProvider.complete() got an unexpected keyword argument 'json_schema'

and the UI reported "AI sozlanmagan yoki javob bermadi" for a perfectly configured provider.
"""
import inspect
import json as jsonlib

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import ApiError
from app.models import VocabularyWord
from app.services.ai import vocab_translate
from app.services.ai.provider import (
    AIProvider,
    AnthropicProvider,
    ChatMessage,
    GeminiProvider,
    OpenAICompatibleProvider,
    parse_json_schema_content,
    to_gemini_schema,
)
from tests.test_vocabulary_units import _setup_book

PROVIDERS = [OpenAICompatibleProvider, AnthropicProvider, GeminiProvider]
FIVE_WORDS = [("afraid", "adjective", "When someone is afraid, they feel fear."),
              ("agree", "verb", "To agree is to say yes."),
              ("angry", "adjective", "When someone is angry, they want to fight."),
              ("arrive", "verb", "To arrive is to reach a place."),
              ("attack", "verb", "To attack is to try to hurt someone.")]
UZBEK = {"afraid": "qo'rqmoq", "agree": "rozi bo'lmoq", "angry": "jahli chiqqan",
         "arrive": "yetib kelmoq", "attack": "hujum qilmoq"}


# --- 1. one signature, everywhere --------------------------------------------------------------

def test_every_provider_has_the_same_complete_signature():
    """A caller must never need to know which provider is configured."""
    base = inspect.signature(AIProvider.complete)
    expected = ["self", "messages", "model", "max_tokens", "temperature", "json_mode", "json_schema"]
    assert [p for p in base.parameters] == expected
    assert base.parameters["json_schema"].default is None
    for cls in PROVIDERS:
        signature = inspect.signature(cls.complete)
        assert [p for p in signature.parameters] == expected, cls.__name__
        assert signature.parameters["json_schema"].default is None, cls.__name__
        # Same defaults for the optional arguments, so a call means the same thing everywhere.
        for name in ("max_tokens", "temperature", "json_mode"):
            assert signature.parameters[name].default == base.parameters[name].default, (
                cls.__name__, name)


def test_the_provider_accepts_json_schema_without_raising(monkeypatch):
    """The exact call that used to explode: keyword arguments plus a schema."""
    schema = vocab_translate.TRANSLATION_JSON_SCHEMA
    for cls in PROVIDERS:
        monkeypatch.setattr(httpx, "Client", _fake_client(_gemini_style_answer(schema)))
        # Constructing the call is what raised TypeError before; the answer itself is
        # provider-specific, so each provider gets a body its own parser understands.
        response = _call_with_schema(cls, schema)
        assert isinstance(response.content, str)


def _call_with_schema(cls, schema):
    if cls is GeminiProvider:
        return cls().complete([ChatMessage(role="user", content="translate")],
                              model="m", json_mode=True, json_schema=schema)
    if cls is AnthropicProvider:
        return cls().complete([ChatMessage(role="user", content="translate")],
                              model="m", json_mode=True, json_schema=schema)
    return cls().complete([ChatMessage(role="user", content="translate")],
                          model="m", json_mode=True, json_schema=schema)


def _gemini_style_answer(schema):
    return {"translations": [{"id": "1", "translation_uz": "x", "alt_translations": []}]}


def _fake_client(body):
    """A httpx.Client stand-in that returns a canned body for any provider."""
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002 - httpx uses `json`
            if "generativelanguage" in url:
                payload = {"candidates": [{"content": {"parts": [{"text": _json(body)}]},
                                           "finishReason": "STOP"}],
                           "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}
            elif "anthropic" in url:
                payload = {"content": [{"type": "text", "text": _json(body)}],
                           "usage": {"input_tokens": 10, "output_tokens": 5}}
            else:
                payload = {"choices": [{"message": {"content": _json(body)}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            return httpx.Response(200, request=httpx.Request("POST", url), json=payload)
    return FakeClient


def _json(body):
    return jsonlib.dumps({"translations": body.get("translations", [])}, ensure_ascii=False)


# --- 2. Gemini structured output --------------------------------------------------------------

def test_gemini_sends_a_converted_response_schema(monkeypatch):
    """Gemini's dialect: uppercase types, no additionalProperties, responseMimeType=json."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            captured.update(url=url, payload=json)
            text = '{"translations":[{"id":"1","translation_uz":"qo\'rqmoq","alt_translations":[]}]}'
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    GeminiProvider().complete([ChatMessage(role="system", content="sys"),
                               ChatMessage(role="user", content="translate")],
                              model="gemini-2.0-flash", json_mode=True,
                              json_schema=vocab_translate.TRANSLATION_JSON_SCHEMA)
    config = captured["payload"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    schema = config["responseSchema"]
    assert schema["type"] == "OBJECT"
    assert schema["properties"]["translations"]["type"] == "ARRAY"
    item = schema["properties"]["translations"]["items"]
    assert item["type"] == "OBJECT"
    assert item["required"] == ["id", "translation_uz", "alt_translations"]
    assert item["properties"]["id"]["type"] == "STRING"
    # Keys Gemini does not understand must be gone, or it answers 400.
    assert "additionalProperties" not in jsonlib.dumps(schema)
    assert "title" not in schema


def test_an_unconvertible_schema_falls_back_to_json_mode_with_an_instruction(monkeypatch):
    """A free-form object cannot be expressed in Gemini's dialect: ask in the prompt instead."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            captured.update(payload=json)
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]},
                                "finishReason": "STOP"}]})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    GeminiProvider().complete([ChatMessage(role="system", content="sys"),
                               ChatMessage(role="user", content="x")],
                              model="m", json_schema={"type": "object"})   # no properties
    payload = captured["payload"]
    assert "responseSchema" not in payload["generationConfig"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert "JSON Schema" in payload["systemInstruction"]["parts"][0]["text"]


def test_a_schema_rejected_by_the_model_is_retried_without_it(monkeypatch):
    """Some Gemini models 400 on responseSchema; the request must not be lost because of it."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_max_retries", 0)
    bodies = []

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            bodies.append(json)
            if "responseSchema" in json.get("generationConfig", {}):
                return httpx.Response(400, request=httpx.Request("POST", url),
                                      json={"error": {"message": "Invalid JSON payload received. "
                                                                 "Unknown name \"responseSchema\"."}})
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "candidates": [{"content": {"parts": [{"text": '{"translations": []}'}]},
                                "finishReason": "STOP"}]})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    response = GeminiProvider().complete([ChatMessage(role="user", content="x")],
                                         model="m", json_schema=vocab_translate.TRANSLATION_JSON_SCHEMA)
    assert response.content == '{"translations": []}'
    assert len(bodies) == 2 and "responseSchema" not in bodies[1]["generationConfig"]
    assert "JSON Schema" in bodies[1]["systemInstruction"]["parts"][0]["text"]


def test_gemini_reports_the_provider_message_instead_of_a_generic_error(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "bad-key")
    monkeypatch.setattr(settings, "ai_max_retries", 0)

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            return httpx.Response(400, request=httpx.Request("POST", url),
                                  json={"error": {"message": "API key not valid. Please pass a "
                                                            "valid API key."}})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(ApiError) as err:
        GeminiProvider().complete([ChatMessage(role="user", content="x")], model="m")
    assert err.value.code == "AI_PROVIDER_REJECTED"
    assert "Gemini xatosi (400)" in err.value.message_uz
    assert "API key not valid" in err.value.message_uz


def test_a_blocked_gemini_answer_says_so(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_max_retries", 0)

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            return httpx.Response(200, request=httpx.Request("POST", url),
                                  json={"promptFeedback": {"blockReason": "SAFETY"},
                                        "candidates": []})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(ApiError) as err:
        GeminiProvider().complete([ChatMessage(role="user", content="x")], model="m")
    assert "blockReason" in err.value.message_uz or "SAFETY" in err.value.message_uz


# --- 3. schema conversion and defensive parsing ------------------------------------------------

def test_schema_conversion_handles_the_real_schemas():
    from app.services.ai.vision_vocabulary import VOCABULARY_JSON_SCHEMA
    from app.services.ai.vocabulary_units import HEADINGS_JSON_SCHEMA

    for schema in (vocab_translate.TRANSLATION_JSON_SCHEMA, VOCABULARY_JSON_SCHEMA,
                   HEADINGS_JSON_SCHEMA):
        converted = to_gemini_schema(schema)
        assert converted is not None
        assert converted["type"] == "OBJECT"
        assert "additionalProperties" not in jsonlib.dumps(converted)


def test_schema_conversion_rejects_unions_and_free_form_objects():
    assert to_gemini_schema({"type": ["string", "number"]}) is None
    assert to_gemini_schema({"type": "object"}) is None            # no properties
    assert to_gemini_schema({"type": "object", "properties": {"a": {"type": "weird"}}}) is None
    assert to_gemini_schema({"type": "array", "items": {"type": "any"}}) is None
    assert to_gemini_schema({"type": ["string", "null"]})["nullable"] is True


def test_fenced_and_chatty_json_is_parsed_and_shape_checked():
    schema = vocab_translate.TRANSLATION_JSON_SCHEMA
    good = {"translations": [{"id": "1", "translation_uz": "qo'rqmoq", "alt_translations": []}]}
    assert parse_json_schema_content("```json\n" + jsonlib.dumps(good) + "\n```", schema) == good
    assert parse_json_schema_content("Mana javob:\n" + jsonlib.dumps(good), schema) == good
    # A fenced answer with a wrong shape must fail loudly, not silently produce nothing.
    with pytest.raises(ValueError) as err:
        parse_json_schema_content('{"translations": [{"translation_uz": "x"}]}', schema)
    assert "id" in str(err.value)
    with pytest.raises(ValueError):
        parse_json_schema_content("kechirasiz, tarjima qila olmayman", schema)


# --- 4. translation works on every provider ----------------------------------------------------

@pytest.mark.parametrize("provider_name", ["openai_compatible", "anthropic", "gemini"])
def test_five_words_are_translated_whichever_provider_is_configured(client, db, monkeypatch, provider_name):
    """The user's check: afraid, agree, angry, arrive, attack all get an Uzbek translation."""
    h, book = _setup_book(client, db, pages=2)
    for word, pos, definition in FIVE_WORDS:
        db.add(VocabularyWord(book_id=book, term=word, part_of_speech=pos,
                              definition_en=definition, source="vision",
                              needs_translation=True, translation_uz=""))
    db.commit()

    prompt_ids = []
    seen_kwargs = {}

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            seen_kwargs.update(kwargs)
            if "generativelanguage" in url:
                request = json["contents"][-1]["parts"][0]["text"]
                assert "responseMimeType" in json["generationConfig"]
            elif "anthropic" in url:
                request = json["messages"][-1]["content"]
            else:
                request = json["messages"][-1]["content"]
            payload = jsonlib.loads(request)
            prompt_ids.extend(item["id"] for item in payload)
            translations = [{"id": item["id"], "translation_uz": UZBEK[item["word"].lower()],
                             "alt_translations": []} for item in payload]
            text = "```json\n" + jsonlib.dumps({"translations": translations}) + "\n```"
            if "generativelanguage" in url:
                body = {"candidates": [{"content": {"parts": [{"text": text}]},
                                        "finishReason": "STOP"}]}
            elif "anthropic" in url:
                body = {"content": [{"type": "text", "text": text}]}
            else:
                body = {"choices": [{"message": {"content": text}}]}
            return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", provider_name)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_max_retries", 0)

    r = client.post(f"/api/v1/books/{book}/vocabulary/translate-missing", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["translated"] == 5, body
    assert body["error"] == "" and body["error_uz"] == ""
    assert body["provider"] == provider_name
    assert len(prompt_ids) == 5

    db.expire_all()
    rows = {w.term: w for w in db.scalars(
        select(VocabularyWord).where(VocabularyWord.book_id == book)).all()}
    for word, _pos, _definition in FIVE_WORDS:
        row = rows[word]
        assert row.translation_uz == UZBEK[word], word
        assert row.translation_status == "auto" and row.needs_translation is False


def test_a_failing_provider_reports_its_own_message_not_a_generic_sentence(client, db, monkeypatch):
    h, book = _setup_book(client, db, pages=2)
    db.add(VocabularyWord(book_id=book, term="afraid", source="vision",
                          needs_translation=True, translation_uz=""))
    db.commit()

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, json=None, headers=None, **kwargs):  # noqa: A002
            return httpx.Response(400, request=httpx.Request("POST", url),
                                  json={"error": {"message": "model gemini-x is not found"}})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "gemini-x")
    monkeypatch.setattr(settings, "ai_max_retries", 0)

    body = client.post(f"/api/v1/books/{book}/vocabulary/translate-missing", headers=h).json()
    assert body["translated"] == 0
    assert body["error"] == "AI_PROVIDER_REJECTED"
    assert "Gemini xatosi (400)" in body["error_uz"]
    assert "model gemini-x is not found" in body["error_uz"]
    assert "AI sozlanmagan" not in body["error_uz"]
