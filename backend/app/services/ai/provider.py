"""Provider-independent AI integration layer.

- Providers: openai_compatible (OpenAI/Groq/OpenRouter/vLLM/Ollama...), anthropic, gemini.
- All calls: configurable timeout, retries with backoff, token usage tracking, structured JSON outputs.
- If no provider is configured the caller gets AINotConfigured — the app never fakes AI output.
"""
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.errors import AINotConfigured, ApiError

log = logging.getLogger("lingora.ai")

T = TypeVar("T", bound=BaseModel)


@dataclass
class AIResponse:
    content: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str
    images: list[dict[str, str]] = field(default_factory=list)  # [{"mime_type","data_base64"}]


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[ChatMessage], model: str | None = None,
                 max_tokens: int = 3000, temperature: float = 0.2,
                 json_mode: bool = False, json_schema: dict[str, Any] | None = None) -> AIResponse: ...


_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    """OpenAI reasoning-style models: they reject `max_tokens` and a custom `temperature`."""
    m = (model or "").lower().split("/")[-1]
    return m.startswith(_REASONING_PREFIXES)


class OpenAICompatibleProvider(AIProvider):
    """Works with OpenAI and any compatible endpoint (Groq, OpenRouter, vLLM, Ollama)."""
    name = "openai_compatible"

    def __init__(self):
        self.base_url = (settings.ai_base_url or "https://api.openai.com/v1").rstrip("/")
        self.headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _schema_payload(schema: dict[str, Any]) -> dict[str, Any]:
        """Strict `response_format` for a hard JSON schema (OpenAI structured outputs)."""
        return {"type": "json_schema",
                "json_schema": {"name": schema.get("title") or "response", "schema": schema, "strict": True}}

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.2, json_mode=False,
                 json_schema=None):
        try:
            return self._complete(messages, model, max_tokens, temperature, json_mode, json_schema)
        except ApiError as exc:
            # Many OpenAI-compatible servers only support {"type":"json_object"}.
            # Retry once with plain JSON mode so a schema request never breaks a working provider.
            if json_schema and exc.code == "AI_PROVIDER_REJECTED":
                log.warning("Provider rejected the JSON schema; retrying with plain JSON mode")
                return self._complete(messages, model, max_tokens, temperature, True, None)
            raise

    def _complete(self, messages, model, max_tokens, temperature, json_mode, json_schema):
        payload_msgs: list[dict] = []
        for m in messages:
            if m.images:
                content: list[dict] = [{"type": "text", "text": m.content}]
                for img in m.images:
                    content.append({"type": "image_url", "image_url": {
                        "url": f"data:{img['mime_type']};base64,{img['data_base64']}"}})
                payload_msgs.append({"role": m.role, "content": content})
            else:
                payload_msgs.append({"role": m.role, "content": m.content})
        mdl = model or settings.ai_model
        payload: dict[str, Any] = {"model": mdl, "messages": payload_msgs}
        official_openai = "api.openai.com" in self.base_url
        if official_openai or _is_reasoning_model(mdl):
            # Newer OpenAI models (gpt-5.x, o-series) reject `max_tokens`; `max_completion_tokens` is accepted
            # by current OpenAI chat models. Third-party compatible servers (Groq, vLLM, Ollama...) keep max_tokens.
            # Reasoning tokens count against this limit, so give them room or the visible answer can be empty.
            payload["max_completion_tokens"] = min(max_tokens * 4, 16000) if _is_reasoning_model(mdl) else max_tokens
        else:
            payload["max_tokens"] = max_tokens
        if not _is_reasoning_model(mdl):
            payload["temperature"] = temperature  # reasoning models only accept the default value
        if json_schema:
            payload["response_format"] = self._schema_payload(json_schema)
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._send(f"{self.base_url}/chat/completions", payload)

    def _send(self, url: str, payload: dict) -> AIResponse:
        start = time.monotonic()
        last_err: Exception | None = None
        for attempt in range(settings.ai_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                    resp = client.post(url, json=payload, headers=self.headers)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ApiError("AI_PROVIDER_BUSY", f"AI provayder vaqtincha band ({resp.status_code}).", 503)
                if 400 <= resp.status_code < 500:
                    # Misconfiguration (bad key, unknown model, unsupported parameter): retrying cannot help and the
                    # generic message hides the cause. Surface the provider's own short message.
                    try:
                        detail = str((resp.json().get("error") or {}).get("message", ""))[:200]
                    except Exception:
                        detail = ""
                    log.error("AI provider rejected request: %s %s", resp.status_code, detail)
                    raise ApiError("AI_PROVIDER_REJECTED",
                                   f"AI provayder so'rovni rad etdi ({resp.status_code}): {detail or 'sozlamalarni tekshiring'}", 502)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage", {}) or {}
                return AIResponse(
                    content=content,
                    model=data.get("model", payload["model"]),
                    tokens_in=int(usage.get("prompt_tokens", 0)),
                    tokens_out=int(usage.get("completion_tokens", 0)),
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
                last_err = e
                log.warning("AI call attempt %s failed: %s", attempt + 1, e)
                if attempt < settings.ai_max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise ApiError(
            "AI_PROVIDER_ERROR",
            f"AI provayder bilan aloqa amalga oshmadi: {type(last_err).__name__}. Keyinroq qayta urinib ko'ring.",
            502,
        )


# ---------------------------------------------------------------------------------------------
# JSON-schema support across providers
#
# The callers (vocabulary extraction, unit detection, translation, region detection) all ask for
# a strict schema. Only OpenAI-compatible servers implement that natively; Gemini has its own
# schema dialect and Anthropic has none. The provider layer is therefore responsible for
# translating the request, not the callers: a caller must never need to know which provider is
# configured, and must never crash because one of them has a different signature.
# ---------------------------------------------------------------------------------------------
# Gemini accepts an OpenAPI subset: these are the only keys its Schema object understands.
_GEMINI_SCHEMA_KEYS = {"type", "format", "description", "nullable", "enum", "items", "properties",
                       "required", "minItems", "maxItems", "propertyOrdering", "minimum",
                       "maximum", "pattern", "example"}
_GEMINI_TYPES = {"object": "OBJECT", "array": "ARRAY", "string": "STRING", "number": "NUMBER",
                 "integer": "INTEGER", "boolean": "BOOLEAN", "null": "NULL"}


def to_gemini_schema(schema: Any) -> dict[str, Any] | None:
    """Convert a JSON schema into Gemini's ``responseSchema`` dialect.

    Returns ``None`` when the schema cannot be expressed (then the caller falls back to plain
    JSON mode plus an instruction in the prompt). Nothing is silently dropped that would change
    the answer's meaning: unsupported *constraint* keys (``additionalProperties``, ``$schema``,
    ``title``, defaults) are removed because Gemini has no equivalent.
    """
    if not isinstance(schema, dict):
        return None
    out: dict[str, Any] = {}
    raw_type = schema.get("type")
    if isinstance(raw_type, list):          # ["string", "null"] -> nullable string
        kinds = [t for t in raw_type if t in _GEMINI_TYPES and t != "null"]
        if len(kinds) != 1:
            return None
        out["type"] = _GEMINI_TYPES[kinds[0]]
        out["nullable"] = True
    elif isinstance(raw_type, str):
        if raw_type not in _GEMINI_TYPES:
            return None
        out["type"] = _GEMINI_TYPES[raw_type]
    elif "properties" in schema:
        out["type"] = "OBJECT"
    elif "items" in schema:
        out["type"] = "ARRAY"
    else:
        return None

    if "enum" in schema:
        values = [v for v in schema["enum"] if isinstance(v, (str, int, float))]
        if not values or len(values) != len(schema["enum"]):
            return None
        out["enum"] = [str(v) for v in values]

    if out["type"] == "ARRAY":
        items = to_gemini_schema(schema.get("items") or {})
        if items is None:
            return None
        out["items"] = items
        for key in ("minItems", "maxItems"):
            if isinstance(schema.get(key), int):
                out[key] = schema[key]

    if out["type"] == "OBJECT":
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            # Gemini rejects an OBJECT without properties, and a free-form object cannot be
            # expressed at all: let the caller fall back to JSON mode.
            return None
        converted: dict[str, Any] = {}
        for name, sub in properties.items():
            child = to_gemini_schema(sub)
            if child is None:
                return None
            converted[name] = child
        out["properties"] = converted
        required = [name for name in (schema.get("required") or []) if name in converted]
        if required:
            out["required"] = required

    for key in ("format", "description", "nullable", "minimum", "maximum", "pattern"):
        if key in schema and key not in out and isinstance(schema[key], (str, int, float, bool)):
            out[key] = schema[key]
    if "propertyOrdering" in schema and isinstance(schema["propertyOrdering"], list):
        out["propertyOrdering"] = [str(k) for k in schema["propertyOrdering"]]
    return out


def schema_instruction(schema: dict[str, Any] | None) -> str:
    """A prompt-level fallback for providers without native schema support."""
    if not schema:
        return ""
    return ("\n\nReturn ONLY valid JSON that matches this JSON Schema exactly, with no markdown "
            "fences and no commentary:\n" + json.dumps(schema, ensure_ascii=False)[:4000])


def _provider_error_detail(resp: httpx.Response) -> str:
    """The provider's own short explanation of a rejection, for the user and the log."""
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 - never fail while explaining a failure
        return (resp.text or "")[:300]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or "")[:300]
    if isinstance(error, str):
        return error[:300]
    return (resp.text or "")[:300]


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.2, json_mode=False,
                 json_schema=None):
        """Anthropic has no native response schema: the schema is stated in the prompt.

        The parameter exists on every provider so a caller can always pass it; here it turns
        into an instruction, which is why the callers also parse defensively.
        """
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        if json_schema:
            system = (system + schema_instruction(json_schema)).strip()
            json_mode = True
        payload_msgs: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.images:
                content: list[dict] = [{"type": "text", "text": m.content}]
                for img in m.images:
                    content.append({"type": "image", "source": {
                        "type": "base64", "media_type": img["mime_type"], "data": img["data_base64"]}})
                payload_msgs.append({"role": m.role, "content": content})
            else:
                payload_msgs.append({"role": m.role, "content": m.content})
        payload: dict[str, Any] = {
            "model": model or settings.ai_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system or None,
            "messages": payload_msgs,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        start = time.monotonic()
        last_err: Exception | None = None
        for attempt in range(settings.ai_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                    resp = client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": settings.ai_api_key, "anthropic-version": "2023-06-01",
                                 "Content-Type": "application/json"},
                        json=payload,
                    )
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ApiError("AI_PROVIDER_BUSY", f"AI provayder vaqtincha band ({resp.status_code}).", 503)
                if 400 <= resp.status_code < 500:
                    detail = _provider_error_detail(resp)
                    log.error("Anthropic rejected request: %s %s", resp.status_code, detail)
                    raise ApiError("AI_PROVIDER_REJECTED",
                                   f"Anthropic xatosi ({resp.status_code}): {detail or 'sozlamalarni tekshiring'}",
                                   502)
                resp.raise_for_status()
                data = resp.json()
                content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
                usage = data.get("usage", {}) or {}
                return AIResponse(
                    content=content, model=data.get("model", payload["model"]),
                    tokens_in=int(usage.get("input_tokens", 0)), tokens_out=int(usage.get("output_tokens", 0)),
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
                last_err = e
                log.warning("Anthropic attempt %s failed: %s", attempt + 1, e)
                if attempt < settings.ai_max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise ApiError("AI_PROVIDER_ERROR", f"Anthropic bilan aloqa amalga oshmadi: {last_err}", 502)


class GeminiProvider(AIProvider):
    """Google Gemini.

    Gemini implements structured output with its own ``generationConfig`` keys —
    ``responseMimeType`` and ``responseSchema`` — and its schema dialect is an OpenAPI subset
    (uppercase types, no ``additionalProperties``). Asking it for ``json_schema`` used to raise
    ``TypeError`` because this method did not accept the argument at all, which surfaced as a
    bare "AI sozlanmagan yoki javob bermadi" in the UI.
    """
    name = "gemini"

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.2, json_mode=False,
                 json_schema=None):
        mdl = model or settings.ai_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
        system_parts = [m.content for m in messages if m.role == "system"]
        gemini_schema = to_gemini_schema(json_schema) if json_schema else None
        if json_schema and gemini_schema is None:
            # The schema cannot be expressed in Gemini's dialect: ask for JSON in the prompt
            # instead. The caller still parses defensively, so nothing silently degrades.
            log.info("Gemini: schema not convertible, falling back to JSON mode with an instruction")
            instruction = schema_instruction(json_schema)
            system_parts = [p + instruction for p in system_parts] or [instruction.strip()]
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            parts: list[dict] = [{"text": m.content}]
            for img in m.images:
                parts.append({"inline_data": {"mime_type": img["mime_type"], "data": img["data_base64"]}})
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": parts})
        generation: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_schema or json_mode:
            generation["responseMimeType"] = "application/json"
        if gemini_schema is not None:
            generation["responseSchema"] = gemini_schema
        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        def send(body: dict[str, Any]) -> AIResponse | None:
            start = time.monotonic()
            last_err: Exception | None = None
            for attempt in range(settings.ai_max_retries + 1):
                try:
                    with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                        resp = client.post(url, json=body, headers={"x-goog-api-key": settings.ai_api_key})
                    if resp.status_code in (429, 500, 502, 503, 504):
                        raise ApiError("AI_PROVIDER_BUSY",
                                       f"Gemini vaqtincha band ({resp.status_code}).", 503)
                    if 400 <= resp.status_code < 500:
                        # A bad key, an unknown model or an unsupported parameter will fail
                        # identically on every attempt: report the provider's own words.
                        detail = _provider_error_detail(resp)
                        log.error("Gemini rejected request: %s %s", resp.status_code, detail)
                        raise ApiError(
                            "AI_PROVIDER_REJECTED",
                            f"Gemini xatosi ({resp.status_code}): {detail or 'sozlamalarni tekshiring'}",
                            502)
                    resp.raise_for_status()
                    data = resp.json()
                    cands = data.get("candidates") or []
                    blocked = (data.get("promptFeedback") or {}).get("blockReason")
                    if not cands:
                        reason = blocked or data.get("error", {}).get("message") or "bo'sh javob"
                        raise ApiError("AI_PROVIDER_REJECTED", f"Gemini javob qaytarmadi: {reason}", 502)
                    finish = cands[0].get("finishReason") or ""
                    parts_out = (cands[0].get("content") or {}).get("parts") or []
                    content = "".join(p.get("text", "") for p in parts_out)
                    if not content.strip():
                        reason = ("javob bloklandi" if finish == "SAFETY"
                                  else f"javob bo'sh (finishReason={finish or 'unknown'})")
                        raise ApiError("AI_PROVIDER_REJECTED", f"Gemini: {reason}", 502)
                    usage = data.get("usageMetadata", {}) or {}
                    return AIResponse(
                        content=content, model=mdl,
                        tokens_in=int(usage.get("promptTokenCount", 0)),
                        tokens_out=int(usage.get("candidatesTokenCount", 0)),
                        latency_ms=int((time.monotonic() - start) * 1000),
                    )
                except ApiError:
                    raise
                except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
                    last_err = e
                    log.warning("Gemini attempt %s failed: %s: %s", attempt + 1, type(e).__name__, e)
                    if attempt < settings.ai_max_retries:
                        time.sleep(1.5 * (attempt + 1))
            raise ApiError("AI_PROVIDER_ERROR",
                           f"Gemini bilan aloqa amalga oshmadi: {type(last_err).__name__ if last_err else 'xato'}. "
                           "Keyinroq qayta urinib ko'ring.", 502)

        if gemini_schema is not None:
            try:
                return send(payload)
            except ApiError as exc:
                # Older models (and some schema corners) reject ``responseSchema`` with 400.
                # Retry once in plain JSON mode rather than losing the request.
                if exc.code != "AI_PROVIDER_REJECTED" or "schema" not in str(exc.message_uz).lower():
                    raise
                log.warning("Gemini rejected responseSchema; retrying in plain JSON mode: %s",
                            exc.message_uz)
                fallback = dict(payload)
                fallback["generationConfig"] = {k: v for k, v in generation.items()
                                                if k != "responseSchema"}
                instruction = schema_instruction(json_schema)
                fallback["systemInstruction"] = {"parts": [{
                    "text": ("\n\n".join(system_parts) + instruction).strip()}]}
                return send(fallback)
        result = send(payload)
        assert result is not None
        return result


def get_provider() -> AIProvider:
    if not settings.ai_configured:
        raise AINotConfigured()
    providers: dict[str, Type[AIProvider]] = {
        "openai_compatible": OpenAICompatibleProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
    }
    return providers[settings.ai_provider]()


# ---------- Structured JSON helpers ----------

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(content: str) -> Any:
    """Parse JSON out of an LLM response: bare JSON, fenced block, or first {...}/[...] span."""
    text = content.strip()
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Javobda topiladigan JSON yo'q")


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def validate_shape(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Check a parsed answer against a JSON schema, shallowly but honestly.

    Only what the callers rely on is enforced — required keys, JSON types, array items — because
    a full validator here would reject legitimate extra detail a model adds. The point is to
    turn "the answer was useless" into "the answer was missing translations[0].id at $".
    """
    problems: list[str] = []
    if not isinstance(schema, dict):
        return problems
    expected = schema.get("type")
    if isinstance(expected, str) and expected in _TYPE_CHECKS:
        if not _TYPE_CHECKS[expected](value):
            return [f"{path}: expected {expected}, got {type(value).__name__}"]
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                problems.append(f"{path}.{key}: missing")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                problems.extend(validate_shape(value[key], sub, f"{path}.{key}"))
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value[:5]):
            problems.extend(validate_shape(item, schema["items"], f"{path}[{index}]"))
    return problems


def parse_json_schema_content(content: str, schema: dict[str, Any] | None,
                              label: str = "AI javobi") -> Any:
    """Parse a model answer, tolerating fences/prose, and check it against the schema.

    Providers differ: some return bare JSON, some wrap it in ```json fences, some prefix a
    sentence. ``extract_json`` already handles all three; this adds the shape check so a
    well-formed but wrong answer fails here with a specific reason instead of half-working
    deeper in the caller.
    """
    try:
        parsed = extract_json(content or "")
    except ValueError as exc:
        snippet = (content or "").strip()[:200]
        raise ValueError(f"{label} JSON emas ({exc}). Boshi: {snippet!r}") from None
    problems = validate_shape(parsed, schema or {})
    if problems:
        raise ValueError(f"{label} shakli kutilganga mos emas: " + "; ".join(problems[:4]))
    return parsed


def structured(
    schema: Type[T],
    prompt_messages: list[ChatMessage],
    model: str | None = None,
    max_tokens: int = 3000,
    temperature: float = 0.1,
    max_attempts: int = 2,
) -> tuple[T, AIResponse]:
    """Ask the provider for a response matching `schema`; validate; one repair retry on bad JSON."""
    provider = get_provider()
    last_resp, last_err = None, None
    for attempt in range(max(max_attempts, 1)):
        attempt_messages = list(prompt_messages)
        if attempt > 0 and last_resp is not None:
            attempt_messages = attempt_messages + [
                ChatMessage(role="assistant", content=last_resp.content[:4000]),
                ChatMessage(role="user", content=(
                    "Oldingi javobingizdagi JSON format noto'g'ri edi. Iltimos, FAQAT to'g'ri, "
                    f"buzuq bo'lmagan JSON qaytaring. Xatolik: {last_err}")),
            ]
        resp = provider.complete(attempt_messages, model=model, max_tokens=max_tokens,
                                 temperature=temperature, json_mode=True)
        last_resp = resp
        try:
            return schema.model_validate(extract_json(resp.content)), resp
        except (ValueError, ValidationError) as e:
            last_err = str(e)[:500]
            log.warning("Structured output validation failed (attempt %s): %s", attempt + 1, last_err)
    raise ApiError(
        "AI_BAD_OUTPUT",
        "AI javobi kutilgan formatga mos kelmadi. Qayta urinib ko'ring yoki boshqa model tanlang.",
        502,
    )
