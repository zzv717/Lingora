"""Optional AI enrichment of the deterministic structure detection.

Runs ONLY when an AI provider is configured. It refines/extends the rule-based result
(lesson grammar explanations, missing answers, vocabulary translations) and every
response is schema-validated. On any failure the deterministic result is kept and a
warning is recorded — AI never silently overwrites verified book content.
"""
import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AnswerKey, Lesson, VocabularyWord
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


def enrich_vocabulary_translations(db: Session, user_id: str, words: list[VocabularyWord]) -> int:
    """Translate English terms to Uzbek; mark result as AI (needs_translation=False)."""
    if not settings.ai_configured or not words:
        return 0
    usage_service.enforce_ai_quota(db, user_id, "vocab_translate")
    done = 0
    B = 40
    for i in range(0, len(words), B):
        batch = words[i:i + B]
        schema, resp = structured(
            TranslateVocabOut,
            [ChatMessage(role="system", content=(
                "Suzlarni inglizchadan o'zbekchaga tarjima qiling. FAQAT JSON: "
                "{\"translations\":[{\"term\":\"go\",\"translation_uz\":\"borish, ketish\","
                "\"part_of_speech\":\"verb\",\"example_sentence\":\"I go to school every day.\"}]} "
                "Tarjima qisqa va umumiy ma'noni berishi kerak."
            )),
             ChatMessage(role="user", content=json.dumps(
                 [{"term": w.term, "context": w.definition_en or w.example_sentence} for w in batch],
                 ensure_ascii=False))],
        )
        usage_service.record_usage(db, user_id, "vocab_translate", get_provider().name, resp.model,
                                   resp.tokens_in, resp.tokens_out)
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
    db.commit()
    return done


def enrich_grammar_explanations(db: Session, user_id: str, book_title: str, lessons: list[Lesson]) -> int:
    """Generate short Uzbek grammar explanations per lesson (topic + pages text excerpt)."""
    if not settings.ai_configured or not lessons:
        return 0
    usage_service.enforce_ai_quota(db, user_id, "analyze")
    payload = []
    for l in lessons:
        payload.append({"lesson_title": l.title, "topic": l.topic or "",
                        "excerpt": (l.summary or "")[:800]})
    schema, resp = structured(
        GrammarExplanationsOut,
        [ChatMessage(role="system", content=(
            "Siz tajribali ingliz tili o'qituvchisisz (o'zbek tilida tushuntirasiz). Har bir dars uchun "
            "qisqa grammatik tushuntirish yozing (5-8 gap, sodda tilda, misollar inglizcha). FAQAT JSON: "
            "{\"explanations\":[{\"lesson_title\":\"...\",\"explanation_uz\":\"...\",\"summary_uz\":\"1-2 gap dars xulosasi\"}]}"
        )),
         ChatMessage(role="user", content=f"Kitob: {book_title}\n" + json.dumps(payload, ensure_ascii=False))],
        max_tokens=4000,
    )
    usage_service.record_usage(db, user_id, "analyze", get_provider().name, resp.model,
                               resp.tokens_in, resp.tokens_out)
    done = 0
    for item in schema.explanations:
        title = item.get("lesson_title", "")
        for l in lessons:
            if l.title == title and item.get("explanation_uz"):
                l.grammar_explanation_uz = str(item["explanation_uz"])[:6000]
                l.summary = str(item.get("summary_uz", l.summary))[:1000]
                done += 1
    db.commit()
    return done
