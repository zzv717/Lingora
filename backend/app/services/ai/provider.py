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
                 json_mode: bool = False) -> AIResponse: ...


class OpenAICompatibleProvider(AIProvider):
    """Works with OpenAI and any compatible endpoint (Groq, OpenRouter, vLLM, Ollama)."""
    name = "openai_compatible"

    def __init__(self):
        self.base_url = (settings.ai_base_url or "https://api.openai.com/v1").rstrip("/")
        self.headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.2, json_mode=False):
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
        payload: dict[str, Any] = {
            "model": model or settings.ai_model,
            "messages": payload_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
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


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.2, json_mode=False):
        system = "\n\n".join(m.content for m in messages if m.role == "system")
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
    name = "gemini"

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.2, json_mode=False):
        mdl = model or settings.ai_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
        system_parts = [m.content for m in messages if m.role == "system"]
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            parts: list[dict] = [{"text": m.content}]
            for img in m.images:
                parts.append({"inline_data": {"mime_type": img["mime_type"], "data": img["data_base64"]}})
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": parts})
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        start = time.monotonic()
        last_err: Exception | None = None
        for attempt in range(settings.ai_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                    resp = client.post(url, json=payload, headers={"x-goog-api-key": settings.ai_api_key})
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ApiError("AI_PROVIDER_BUSY", f"AI provayder vaqtincha band ({resp.status_code}).", 503)
                resp.raise_for_status()
                data = resp.json()
                cands = data.get("candidates") or [{}]
                parts_out = (cands[0].get("content") or {}).get("parts") or [{}]
                content = "".join(p.get("text", "") for p in parts_out)
                usage = data.get("usageMetadata", {}) or {}
                return AIResponse(
                    content=content, model=mdl,
                    tokens_in=int(usage.get("promptTokenCount", 0)),
                    tokens_out=int(usage.get("candidatesTokenCount", 0)),
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
                last_err = e
                log.warning("Gemini attempt %s failed: %s", attempt + 1, type(e).__name__)
                if attempt < settings.ai_max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise ApiError("AI_PROVIDER_ERROR", "Gemini bilan aloqa amalga oshmadi. Keyinroq qayta urinib ko'ring.", 502)


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
