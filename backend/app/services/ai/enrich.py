"""Optional AI enrichment of the deterministic structure detection.

Runs ONLY when an AI provider is configured. It refines/extends the rule-based result
(lesson grammar explanations, missing answers, vocabulary translations) and every
response is schema-validated. On any failure the deterministic result is kept and a
warning is recorded — AI never silently overwrites verified book content.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Book, Lesson, VocabularyWord
from app.services.ai import usage as usage_service
from app.services.ai.provider import ChatMessage, structured, get_provider
from app.services.structure_detector import DetectedStructure

log = logging.getLogger("lingora.ai.enrich")


class EnrichAnswersOut(BaseModel):
    answers: list[dict] = Field(description="[{question_number, answers: [...]}]")


class TranslateVocabOut(BaseModel):
    translations: list[dict] = Field(description="[{term, translation_uz, part_of_speech, example_sentence}]")


class GrammarExplanationsOut(BaseModel):
    explanations: list[dict] = Field(description="[{lesson_title, explanation_uz, summary_uz}]")


def enrichment_available() -> bool:
    return settings.ai_configured


ProgressCb = Callable[[float], None]


def _report(progress_cb: ProgressCb | None, fraction: float) -> None:
    if progress_cb:
        progress_cb(max(0.0, min(1.0, fraction)))


def _wave_size(db: Session, user_id: str, requested: int) -> int:
    """Never let a parallel wave spend more calls than the remaining daily quota."""
    if settings.ai_daily_token_limit > 0:
        # Token budget is shared across features and only checked per call;
        # stay strictly sequential when it is enforced.
        return 1
    if settings.ai_daily_request_limits_enabled:
        limits = settings.plan_limits(usage_service.get_user_plan(db, user_id))
        allowance = limits["ai_calls_per_day"]
        if allowance:
            remaining = allowance - usage_service.ai_calls_today(db, user_id)
            return max(0, min(requested, remaining))
    return requested


def _translate_batch_request(batch: list[dict[str, str]]) -> tuple[TranslateVocabOut, Any]:
    """One provider round trip; runs in a worker thread, never touches the DB."""
    return structured(
        TranslateVocabOut,
        [ChatMessage(role="system", content=(
            "Suzlarni inglizchadan o'zbekchaga tarjima qiling. FAQAT JSON: "
            "{\"translations\":[{\"term\":\"go\",\"translation_uz\":\"borish, ketish\","
            "\"part_of_speech\":\"verb\",\"example_sentence\":\"I go to school every day.\"}]} "
            "Tarjima qisqa va umumiy ma'noni berishi kerak."
        )),
         ChatMessage(role="user", content=json.dumps(batch, ensure_ascii=False))],
    )


def enrich_answer_gaps(db: Session, user_id: str, book_title: str,
                       structure: DetectedStructure, max_questions: int = 60) -> int:
    """For exercises whose answers are unknown, ask AI to solve them from context.
    These are marked answer_source='ai' (never presented as the textbook key)."""
    if not settings.ai_configured:
        return 0
    gaps = []
    for ex in structure.exercises:
        for q in ex.questions:
            if not q.correct_answers and len(gaps) < max_questions:
                gaps.append({
                    "exercise_ref": ex.ref, "page": ex.page_number, "type": ex.exercise_type,
                    "instructions": ex.instructions[:300],
                    "question_number": q.number or str(q.order_index + 1),
                    "prompt": q.prompt[:500],
                    "options": [o["text"] for o in q.options],
                })
    if not gaps:
        return 0
    usage_service.enforce_ai_quota(db, user_id, "analyze")
    schema, resp = structured(
        EnrichAnswersOut,
        [ChatMessage(role="system", content=(
            "Siz ingliz tili grammatikasi bo'yicha ekspert'siz. Berilgan mashqlarga to'g'ri javoblarni yozing. "
            "FAQAT JSON qaytaring: {\"answers\":[{\"question_number\":\"1\",\"answers\":[\"goes\"]}]}. "
            "Aniq ishonchingiz bo'lmasa, eng ehtimolli javobni bering, lekin answers ichida alternativlarni ham ko'rsating."
        )),
         ChatMessage(role="user", content=f"Kitob: {book_title}\n\n" + json.dumps(gaps, ensure_ascii=False))],
        max_tokens=4000,
    )
    usage_service.record_usage(db, user_id, "analyze", get_provider().name, resp.model,
                               resp.tokens_in, resp.tokens_out)
    key_by_ref_q = {(g["exercise_ref"], g["question_number"]): g for g in gaps}
    count = 0
    for item in schema.answers:
        qn = str(item.get("question_number", ""))
        answers = [str(a) for a in (item.get("answers") or []) if str(a).strip()]
        if not qn or not answers:
            continue
        for ex in structure.exercises:
            if ex.ref != item.get("exercise_ref") and (ex.ref, qn) not in key_by_ref_q:
                continue
            for q in ex.questions:
                if (q.number or str(q.order_index + 1)) == qn and not q.correct_answers:
                    q.correct_answers = answers
                    q.answer_source = "ai"
                    count += 1
    return count


def enrich_vocabulary_translations(db: Session, user_id: str, words: list[VocabularyWord],
                                   progress_cb: ProgressCb | None = None) -> int:
    """Translate English terms to Uzbek; mark result as AI (needs_translation=False).

    Provider calls are network-bound, so batches are issued in bounded waves.
    Quota checks, usage accounting and ORM writes stay on the calling thread —
    only the HTTP request is parallelized. A dictionary-sized word list no longer
    waits for one provider round trip per 40 words.
    """
    if not settings.ai_configured or not words:
        _report(progress_cb, 1.0)
        return 0
    batch_size = 40
    batches = [words[i:i + batch_size] for i in range(0, len(words), batch_size)]
    workers = min(settings.ai_enrich_workers, len(batches))
    provider_name = get_provider().name
    done = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lingora-ai-enrich") as pool:
        start = 0
        while start < len(batches):
            size = _wave_size(db, user_id, workers)
            wave = batches[start:start + size] if size else batches[start:start + 1]
            # Reserve every call in the wave before launching it: a daily quota
            # must never be bypassed by concurrency.
            for _ in wave:
                usage_service.enforce_ai_quota(db, user_id, "vocab_translate")
            payloads = [[{"term": w.term, "context": w.definition_en or w.example_sentence}
                         for w in batch] for batch in wave]
            futures = {pool.submit(_translate_batch_request, payload): batch
                       for payload, batch in zip(payloads, wave)}
            for future in as_completed(futures):
                batch = futures[future]
                schema, resp = future.result()
                usage_service.record_usage(db, user_id, "vocab_translate", provider_name,
                                           resp.model, resp.tokens_in, resp.tokens_out)
                by_term = {t.get("term", "").lower(): t for t in schema.translations}
                for w in batch:
                    t = by_term.get(w.term.lower())
                    if t and t.get("translation_uz"):
                        w.translation_uz = str(t["translation_uz"])[:512]
                        w.part_of_speech = str(t.get("part_of_speech", ""))[:32]
                        w.example_sentence = str(t.get("example_sentence", ""))[:500]
                        w.needs_translation = False
                        w.source = "ai"
                        done += 1
                completed += 1
            _report(progress_cb, completed / len(batches))
            start += len(wave)
    db.commit()
    return done


def _grammar_request(book_title: str, payload: list[dict[str, str]]) -> tuple[GrammarExplanationsOut, Any]:
    """One provider round trip for a group of lessons; no DB access in the worker."""
    return structured(
        GrammarExplanationsOut,
        [ChatMessage(role="system", content=(
            "Siz tajribali ingliz tili o'qituvchisisz (o'zbek tilida tushuntirasiz). Har bir dars uchun "
            "qisqa grammatik tushuntirish yozing (5-8 gap, sodda tilda, misollar inglizcha). FAQAT JSON: "
            "{\"explanations\":[{\"lesson_title\":\"...\",\"explanation_uz\":\"...\",\"summary_uz\":\"1-2 gap dars xulosasi\"}]}"
        )),
         ChatMessage(role="user", content=f"Kitob: {book_title}\n" + json.dumps(payload, ensure_ascii=False))],
        max_tokens=4000,
    )


def enrich_grammar_explanations(db: Session, user_id: str, book_title: str, lessons: list[Lesson],
                                progress_cb: ProgressCb | None = None) -> int:
    """Generate short Uzbek grammar explanations per lesson (topic + pages text excerpt)."""
    if not settings.ai_configured or not lessons:
        _report(progress_cb, 1.0)
        return 0
    chunks = [lessons[i:i + 20] for i in range(0, len(lessons), 20)]
    workers = min(settings.ai_enrich_workers, len(chunks))
    provider_name = get_provider().name
    done = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lingora-ai-enrich") as pool:
        start = 0
        while start < len(chunks):
            size = _wave_size(db, user_id, workers)
            wave = chunks[start:start + size] if size else chunks[start:start + 1]
            for _ in wave:
                usage_service.enforce_ai_quota(db, user_id, "analyze")
            payloads = [[{"lesson_title": l.title, "topic": l.topic or "",
                          "excerpt": (l.summary or "")[:800]} for l in chunk] for chunk in wave]
            futures = {pool.submit(_grammar_request, book_title, payload): chunk
                       for payload, chunk in zip(payloads, wave)}
            for future in as_completed(futures):
                chunk = futures[future]
                schema, resp = future.result()
                usage_service.record_usage(db, user_id, "analyze", provider_name, resp.model,
                                           resp.tokens_in, resp.tokens_out)
                for item in schema.explanations:
                    title = item.get("lesson_title", "")
                    for l in chunk:
                        if l.title == title and item.get("explanation_uz"):
                            l.grammar_explanation_uz = str(item["explanation_uz"])[:6000]
                            done += 1
                completed += 1
            _report(progress_cb, completed / len(chunks))
            start += len(wave)
    db.commit()
    return done


def enrich_book(db: Session, book_id: str, progress_cb: ProgressCb | None = None) -> list[dict]:
    """Enrich persisted missing vocabulary and lesson notes without replacing textbook data.

    Each stage is independent: failures leave the extracted book usable and are
    returned to the job so the user is not told AI succeeded when it did not.
    ``progress_cb`` reports 0..1 across both stages so the UI can keep moving.
    """
    if not settings.ai_configured:
        _report(progress_cb, 1.0)
        return []
    book = db.get(Book, book_id)
    if not book:
        raise ValueError("Book not found")
    words = list(db.scalars(select(VocabularyWord).where(
        VocabularyWord.book_id == book_id, VocabularyWord.needs_translation.is_(True))).all())
    lessons = list(db.scalars(select(Lesson).where(
        Lesson.book_id == book_id, Lesson.grammar_explanation_uz == "")).all())
    warnings = []
    vocabulary_weight = 0.7 if words else 0.0
    grammar_weight = 0.3 if lessons else 0.0
    total_weight = vocabulary_weight + grammar_weight
    base = 0.0
    stages = (
        ("vocabulary", lambda cb: enrich_vocabulary_translations(db, book.user_id, words, cb)),
        ("grammar", lambda cb: enrich_grammar_explanations(db, book.user_id, book.title, lessons, cb)),
    )
    for stage, action in stages:
        weight = vocabulary_weight if stage == "vocabulary" else grammar_weight
        if not weight:
            continue
        try:
            action(lambda fraction, start=base, span=weight / total_weight:
                   _report(progress_cb, start + span * fraction))
            base += weight / total_weight
        except Exception as exc:
            db.rollback()
            log.warning("AI enrichment stage %s failed: %s", stage, type(exc).__name__)
            warnings.append({"page": 0, "code": "AI_ENRICHMENT_FAILED",
                             "message_uz": "AI qo'shimcha tahlili bajarilmadi; asosiy tahlil saqlandi."})
            base += weight / total_weight
    _report(progress_cb, 1.0)
    return warnings
