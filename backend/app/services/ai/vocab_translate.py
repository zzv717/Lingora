"""Machine translation of vocabulary entries into Uzbek.

The reference book prints English only, so every extracted word arrived with an empty
translation and ``needs_translation=True``. That boolean was doing two jobs at once: "we have
no Uzbek" and "do not trust this word in a test". The result was a Lug'at full of
"Tarjima tekshirilmagan" cards that could not be practised, even though a perfectly good
machine translation is enough to drill a word.

So translation is a small, bounded, idempotent job:

* entries are sent in batches of ``BATCH_SIZE`` with the headword, part of speech, English
  definition and example — the model needs the sense, not just the spelling;
* the answer is constrained by a strict JSON schema and matched back by ``id``, so a missing
  or reordered entry can never shift translations onto the wrong word;
* ``status="auto"`` means machine translated **and usable**; ``verified`` / ``edited`` mean a
  human touched it, and those are never overwritten;
* a batch never fails the whole job: failures are counted and retried on the next call.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.models import VocabularyWord
from app.services.ai import usage
from app.services.ai.provider import ChatMessage, extract_json, get_provider

log = logging.getLogger("lingora.vocab_translate")

FEATURE = "vocab_translate"
BATCH_SIZE = 25
MAX_TRANSLATION = 200

# Statuses a human owns: a bulk "translate missing" must not touch them.
HUMAN_STATUSES = ("verified", "edited")

PROMPT = """Siz ingliz tili o'quv kitobining lug'atini o'zbek tiliga tarjima qiluvchi muharrirsiz.

Har bir yozuv uchun: word (inglizcha so'z), part_of_speech, definition (inglizcha izoh),
example (inglizcha misol). Shu ma'lumotga qarab so'zning AYNAN shu ma'nodagi o'zbekcha
tarjimasini bering.

Qoidalar:
- Tarjima so'z turkumiga mos bo'lsin: verb -> fe'l (harakat nomi emas), adjective -> sifat,
  noun -> ot, adverb -> ravish. Masalan "brave" (adjective) -> "jasur", "to brave" (verb) ->
  "jasorat qilmoq" emas, balki fe'l shakli.
- Sodda, kundalik o'zbek so'zlaridan foydalaning. Izoh, qavs, tarif, misol yoki inglizcha
  so'z qo'shmang — faqat tarjima.
- Bir so'zning bir necha keng tarqalgan tarjimasi bo'lsa, eng mosini "translation_uz" ga,
  qolganlarini "alt_translations" ro'yxatiga yozing (2-3 tadan ko'p emas).
- Agar so'z o'zbek tilida bir so'z bilan berilmasa (masalan "a lot"), qisqa ibora yozing.
- Hech qachon tarjima o'ylab topmang: ma'no tushunarsiz bo'lsa, "translation_uz" ni bo'sh
  qoldiring.
- FAQAT JSON qaytaring, markdown yo'q:
{"translations":[{"id":"<berilgan id>","translation_uz":"jasur","alt_translations":["botir"]}]}"""

TRANSLATION_JSON_SCHEMA: dict[str, Any] = {
    "title": "vocabulary_translations",
    "type": "object",
    "additionalProperties": False,
    "required": ["translations"],
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "translation_uz", "alt_translations"],
                "properties": {
                    "id": {"type": "string"},
                    "translation_uz": {"type": "string"},
                    "alt_translations": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def _prompt_payload(batch: list[VocabularyWord]) -> list[dict[str, str]]:
    return [{"id": word.id, "word": word.term, "part_of_speech": word.part_of_speech or "",
             "definition": (word.definition_en or "")[:400],
             "example": (word.example_sentence or "")[:300]} for word in batch]


def clean_translation(raw: Any) -> str:
    """One short Uzbek word/phrase, without explanations, brackets or the English headword."""
    if raw is None or isinstance(raw, (dict, list)):
        return ""
    text = " ".join(str(raw).split())[:MAX_TRANSLATION]
    # A model that explains ("jasur — brave, qo'rqmas") would poison the drill cards, and
    # a part-of-speech tag in brackets ("(ot) kitob") is noise, not part of the answer.
    text = re.sub(r"\([^)]*\)", " ", text)
    for separator in (" — ", " – ", " - ", ";", ":"):
        if separator in text:
            text = text.split(separator)[0]
    text = " ".join(text.split()).strip(" .,;:!?\"'")
    if not text or len(text.split()) > 6:
        return ""
    if not any(ch.isalpha() for ch in text):
        return ""
    return text


def translate_words(db: Session, user_id: str, words: list[VocabularyWord],
                    batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    """Translate a list of entries in batches. Returns counts, never raises for one batch.

    Idempotent by construction: the caller passes words that still need a translation, and a
    word that already has one (in any status) is skipped here as well, so a retry after a
    partial failure costs nothing for the words already done.
    """
    pending = [w for w in words if not (w.translation_uz or "").strip()
               or (w.translation_status or "") not in HUMAN_STATUSES]
    # Only words with no translation at all are sent; a human-owned one is never overwritten.
    pending = [w for w in pending if not (w.translation_uz or "").strip()]
    stats: dict[str, Any] = {"requested": len(words), "translated": 0, "batches": 0,
                             "failed_batches": 0, "skipped": len(words) - len(pending)}
    if not pending:
        return stats
    try:
        provider = get_provider()
    except ApiError as exc:
        log.info("vocabulary translation skipped: %s", exc.code)
        stats["error"] = exc.code
        return stats
    model = (settings.ai_model or "").strip() or (settings.ai_vision_model or "").strip()
    if not model:
        stats["error"] = "AI_NOT_CONFIGURED"
        return stats

    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        stats["batches"] += 1
        try:
            stats["translated"] += _translate_batch(db, user_id, provider, model, batch)
        except ApiError as exc:
            # A quota/configuration problem will repeat on every batch: stop, keep what is done.
            log.warning("vocabulary translation batch failed (%s): %s", exc.code, exc.message_uz)
            stats["failed_batches"] += 1
            stats["error"] = exc.code
            if exc.http_status in (401, 402, 403):
                break
        except Exception:  # noqa: BLE001 - one batch must not lose the others
            log.warning("vocabulary translation batch crashed", exc_info=True)
            stats["failed_batches"] += 1
        db.commit()
    log.info("vocabulary translation: %s/%s words (%s batches, %s failed)",
             stats["translated"], len(pending), stats["batches"], stats["failed_batches"])
    return stats


def _translate_batch(db: Session, user_id: str, provider, model: str,
                     batch: list[VocabularyWord]) -> int:
    usage.enforce_feature_quota(db, user_id, FEATURE, settings.vision_exercise_pages_per_day)
    messages = [
        ChatMessage(role="system", content=PROMPT),
        ChatMessage(role="user", content=json.dumps(_prompt_payload(batch), ensure_ascii=False)),
    ]
    last_error = ""
    for attempt in range(2):
        response = provider.complete(messages, model=model, max_tokens=2000,
                                     temperature=0.2, json_mode=True,
                                     json_schema=TRANSLATION_JSON_SCHEMA)
        usage.record_usage(db, user_id, FEATURE, provider.name, response.model,
                           response.tokens_in, response.tokens_out)
        try:
            parsed = extract_json(response.content)
        except ValueError as exc:
            last_error = str(exc)[:200]
        else:
            by_id = {}
            for item in (parsed.get("translations") or []) if isinstance(parsed, dict) else []:
                if isinstance(item, dict) and item.get("id"):
                    by_id[str(item["id"])] = item
            if not by_id:
                last_error = "no usable translations in the answer"
            else:
                done = 0
                for word in batch:
                    item = by_id.get(word.id)
                    if not item:
                        continue
                    translation = clean_translation(item.get("translation_uz"))
                    if not translation:
                        continue
                    alts = [clean_translation(alt) for alt in (item.get("alt_translations") or [])]
                    word.translation_uz = translation
                    word.alt_translations = [alt for alt in alts if alt and alt != translation][:3]
                    word.translation_status = "auto"
                    # "auto" is immediately usable: the word enters tests, with a badge.
                    word.needs_translation = False
                    done += 1
                if done:
                    return done
                last_error = "answers did not match any entry id"
        log.warning("vocabulary translation bad output (attempt %s): %s", attempt + 1, last_error)
        if attempt == 0:
            messages = messages + [
                ChatMessage(role="assistant", content=response.content[:3000]),
                ChatMessage(role="user", content="Return ONLY the requested JSON, one object per "
                                                 f"given id. Problem: {last_error}"),
            ]
    return 0


def missing_translations(db: Session, book_id: str, limit: int = 400) -> list[VocabularyWord]:
    """Entries that still need a machine translation, in unit/page order."""
    return list(db.scalars(
        select(VocabularyWord)
        .where(VocabularyWord.book_id == book_id,
               or_(VocabularyWord.translation_uz == "", VocabularyWord.translation_uz.is_(None)))
        .order_by(VocabularyWord.page_number, VocabularyWord.position)
        .limit(limit)).all())
