"""Vocabulary Challenge engine.

Anti-cheating design (per spec): randomized order, randomized options, mixed question
types, mandatory written recall, reintroduction of failed words, configurable pass
score, tracked attempts. Question banks are generated from THIS book's vocabulary —
nothing is invented. TTS listening uses the browser's speech synthesis (no cloud).
"""
import random
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ActivityDay,
    Lesson,
    LearningProgress,
    VocabularyAttempt,
    VocabularyProgress,
    VocabularySession,
    VocabularyWord,
)
from app.services.grading import normalize, answers_match
from app.services import srs
from app.db.mixins import ensure_utc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _distractors(pool: list[str], correct: str, k: int = 3) -> list[str]:
    unique = [p for p in dict.fromkeys(pool) if p and normalize(p) != normalize(correct)]
    random.shuffle(unique)
    return unique[:k]


def _ensure_progress(db: Session, user_id: str, word_id: str) -> VocabularyProgress:
    vp = db.scalar(select(VocabularyProgress).where(
        VocabularyProgress.user_id == user_id, VocabularyProgress.word_id == word_id))
    if not vp:
        vp = VocabularyProgress(user_id=user_id, word_id=word_id)
        db.add(vp)
        db.flush()
    return vp


def generate_session(db: Session, *, user_id: str, book_id: str | None, lesson_id: str | None,
                     kind: str, required_score: int, limit: int = 12) -> VocabularySession:
    base_q = select(VocabularyWord).where(VocabularyWord.needs_translation.is_(False))
    if lesson_id:
        base_q = base_q.where(VocabularyWord.lesson_id == lesson_id)
    elif book_id:
        base_q = base_q.where(VocabularyWord.book_id == book_id)
    words = list(db.scalars(base_q.order_by(VocabularyWord.term)).all())
    if not words:
        return VocabularySession(user_id=user_id, book_id=book_id, lesson_id=lesson_id,
                                 kind=kind, required_score=required_score, items=[])
    words = words[:60]

    # Prioritize: due (SRS) first, then never-seen, then rest; randomized inside groups
    now = _utcnow()
    progress = {p.word_id: p for p in db.scalars(select(VocabularyProgress).where(
        VocabularyProgress.user_id == user_id,
        VocabularyProgress.word_id.in_([w.id for w in words]))).all()}
    due = [w for w in words if w.id in progress and ensure_utc(progress[w.id].due_at) <= now]
    fresh = [w for w in words if w.id not in progress]
    rest = [w for w in words if w.id in progress and ensure_utc(progress[w.id].due_at) > now]
    random.shuffle(due); random.shuffle(fresh); random.shuffle(rest)
    chosen = (due + fresh + rest)[:limit]

    all_terms = [w.term for w in words]
    all_translations = [w.translation_uz.split(",")[0].strip() for w in words]

    items = []
    for w in chosen:
        qtype = _pick_type(w, seen=set(i["type"] for i in items))
        item = _build_item(w, qtype, all_terms, all_translations, pool_words=words)
        items.append(item)

    # interleave types so sequences are never predictable
    random.shuffle(items)
    session = VocabularySession(
        user_id=user_id, book_id=book_id, lesson_id=lesson_id, kind=kind,
        required_score=required_score,
        items=[{**it, "queue": 0} for it in items],
    )
    db.add(session)
    db.flush()
    return session


def _pick_type(w: VocabularyWord, seen: set[str]) -> str:
    choices = ["written_en_uz", "choice_uz_en", "written_uz_en", "sentence_blank", "choice_en_uz", "spelling"]
    if w.example_sentence:
        choices = ["sentence_blank"] + choices
    for c in random.sample(choices, len(choices)):
        if c not in seen or len(seen) >= len(choices):
            return c
    return "written_en_uz"


def _build_item(w: VocabularyWord, qtype: str, all_terms: list[str],
                all_translations: list[str], pool_words: list[VocabularyWord]) -> dict:
    base = {"word_id": w.id, "type": qtype, "answered": False, "first_correct": None,
            "attempts": 0, "item_id": secrets.token_hex(8)}
    main_uz = w.translation_uz.split(",")[0].strip() or w.translation_uz
    if qtype == "choice_en_uz":
        opts = _distractors(all_translations, main_uz)
        opts.append(main_uz)
        random.shuffle(opts)
        return {**base, "prompt": w.term, "options": [{"key": o, "text": o} for o in opts],
                "expected": main_uz, "audio_text": w.term}
    if qtype == "choice_uz_en":
        opts = _distractors(all_terms, w.term)
        opts.append(w.term)
        random.shuffle(opts)
        return {**base, "prompt": main_uz, "options": [{"key": o, "text": o} for o in opts],
                "expected": w.term, "hint": "Inglizcha so'zni tanlang"}
    if qtype == "written_en_uz":
        return {**base, "prompt": w.term, "expected": w.translation_uz,
                "hint": "O'zbekcha tarjimasini yozing", "audio_text": w.term}
    if qtype == "written_uz_en":
        return {**base, "prompt": main_uz, "expected": w.term,
                "hint": "Inglizcha so'zni yozing"}
    if qtype == "spelling":
        return {**base, "prompt": w.translation_uz, "expected": w.term,
                "hint": f"Tinglang va yozing ({len(w.term)} harf)", "audio_text": w.term, "exact": True}
    if qtype == "listening":
        opts = _distractors(all_terms, w.term)
        opts.append(w.term)
        random.shuffle(opts)
        return {**base, "prompt": "🔊 So'zni tinglang va tanlang", "options": [{"key": o, "text": o} for o in opts],
                "expected": w.term, "audio_text": w.term}
    if qtype == "sentence_blank":
        sentence = w.example_sentence
        pattern = re.compile(re.escape(w.term), re.IGNORECASE)
        if pattern.search(sentence):
            blanked = pattern.sub("_____", sentence, count=1)
        else:
            blanked = f"_____ — {w.translation_uz}"
            base["type"] = "written_uz_en"
        return {**base, "prompt": blanked, "expected": w.term,
                "hint": "Bo'sh joyga mos so'zni yozing", "audio_text": w.term, "sentence": blanked}
    return base


def answer_item(db: Session, session: VocabularySession, item: dict, response: str) -> dict:
    word = db.get(VocabularyWord, item["word_id"])
    exact = bool(item.get("exact"))
    expected = item.get("expected", "")
    if item["type"].startswith("choice") or item["type"] == "listening":
        correct = normalize(response) == normalize(expected)
    else:
        correct = answers_match(response, [expected], exact=exact) if not exact else \
            (normalize(response) == normalize(expected))
    # For multi-variant translations accept any listed comma variant
    if not correct and "," in expected and not item["type"].startswith("choice"):
        correct = any(answers_match(response, [v.strip()]) for v in expected.split(",") if v.strip())

    first = item.get("first_correct")
    first_correct = correct if first is None else first
    updated_item = {**item, "attempts": item.get("attempts", 0) + 1, "first_correct": first_correct}

    db.add(VocabularyAttempt(
        user_id=session.user_id, word_id=word.id, session_id=session.id,
        question_type=item["type"], response=response[:500], is_correct=bool(correct),
    ))
    vp = _ensure_progress(db, session.user_id, word.id)
    quality = srs.quality_from_answer(correct=correct, question_type=item["type"])
    state = srs.schedule_sm2(ease_factor=vp.ease_factor, interval_days=vp.interval_days,
                             repetitions=vp.repetitions, lapses=vp.lapses, quality=quality)
    for k, v in state.items():
        setattr(vp, k, v)
    vp.total_reviews += 1
    vp.correct_count += 1 if correct else 0
    vp.wrong_count += 0 if correct else 1
    vp.last_reviewed_at = _utcnow()

    # rebuild the JSON list (in-place mutation is not tracked by SQLAlchemy)
    new_items = [updated_item if it["item_id"] == item["item_id"] else it for it in session.items]
    # failed words are reintroduced at the end of the session
    if not correct and not item.get("requeued"):
        re_item = {**item, "item_id": secrets.token_hex(8), "attempts": 0,
                   "first_correct": None, "requeued": True}
        new_items.append(re_item)
    session.items = new_items

    _bump_activity(db, session.user_id, words_reviewed=1)
    db.commit()
    return {"correct": bool(correct), "expected": expected,
            "term": word.term, "translation_uz": word.translation_uz, "word_id": word.id}


def first_attempt_score(session: VocabularySession) -> float:
    scored = [i for i in session.items if not i.get("requeued") and i.get("first_correct") is not None]
    if not scored:
        return 0.0
    return round(100.0 * sum(1 for i in scored if i["first_correct"]) / len(scored), 1)


def complete_session(db: Session, session: VocabularySession) -> dict:
    score = first_attempt_score(session)
    session.score = score
    passed = score >= session.required_score
    session.status = "passed" if passed else "failed"
    session.finished_at = _utcnow()
    gate_opened = False
    if session.kind == "lesson_gate" and passed and session.lesson_id:
        lp = db.scalar(select(LearningProgress).where(
            LearningProgress.user_id == session.user_id, LearningProgress.lesson_id == session.lesson_id))
        if not lp:
            lesson = db.get(Lesson, session.lesson_id)
            lp = LearningProgress(user_id=session.user_id, lesson_id=session.lesson_id,
                                  book_id=lesson.book_id if lesson else "")
            db.add(lp)
        lp.vocab_gate_passed = True
        gate_opened = True
    db.commit()
    if passed:
        msg = "Tabriklaymiz! Lug'at testi muvaffaqiyatli yakunlandi. 🎉"
    else:
        msg = (f"Natija: {score}% (kerak: {session.required_score}%). "
               "Xato so'zlar yana takrorlandi — yana bir marta urinib ko'ring.")
    return {"status": session.status, "score": score, "required_score": session.required_score,
            "passed": passed, "gate_opened": gate_opened, "message_uz": msg}


def _bump_activity(db: Session, user_id: str, *, words_reviewed: int = 0,
                   exercises_checked: int = 0, seconds: int = 0) -> None:
    day = datetime.now().strftime("%Y-%m-%d")
    from app.models import ActivityDay as AD
    row = db.scalar(select(AD).where(AD.user_id == user_id, AD.day == day))
    if not row:
        row = AD(user_id=user_id, day=day, seconds=0,
                 exercises_checked=0, answers_submitted=0, words_reviewed=0)
        db.add(row)
        db.flush()
    row.words_reviewed += words_reviewed
    row.exercises_checked += exercises_checked
    row.seconds += seconds
