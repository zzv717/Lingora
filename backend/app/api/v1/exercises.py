"""Exercises: fetch lesson exercises (without leaking answer keys), autosave answers, check & grade."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_profile, get_current_user, owned_book
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limit
from app.db.session import get_db
from app.models import (
    ActivityDay,
    Book,
    Exercise,
    ExerciseAttempt,
    ExerciseOption,
    ExerciseQuestion,
    LearningProgress,
    Lesson,
    Profile,
    StudentAnswer,
    User,
    VocabularyWord,
)
from app.schemas import (
    AnswersSaveIn,
    AnswerSaveIn,
    CheckOut,
    ExerciseOut,
    OkOut,
    OptionOut,
    QuestionOut,
    VerdictOut,
)
from app.services import grading as grading_engine
from app.services.ai.provider import get_provider
from app.services.progress_service import heartbeat as progress_heartbeat

log = logging.getLogger("lingora.exercises")
router = APIRouter(tags=["exercises"])


def _check_lesson_gate(db: Session, user: User, profile: Profile, lesson: Lesson) -> None:
    """Enforce vocabulary gating rule on the backend:
    A lesson is locked if the previous lesson in the same book has vocabulary and the user has not passed its vocab gate.
    If profile.vocabulary_gating is False, gating is disabled.
    """
    if not profile or not profile.vocabulary_gating:
        return

    # Find immediate previous lesson in this book
    prev_lesson = db.scalar(
        select(Lesson)
        .where(Lesson.book_id == lesson.book_id, Lesson.order_index < lesson.order_index)
        .order_by(Lesson.order_index.desc())
        .limit(1)
    )
    if not prev_lesson:
        return

    # Check if previous lesson has vocabulary
    has_vocab = db.query(VocabularyWord.id).filter(VocabularyWord.lesson_id == prev_lesson.id, VocabularyWord.needs_translation.is_(False)).count() > 0
    if not has_vocab:
        return

    lp = db.scalar(
        select(LearningProgress).where(
            LearningProgress.user_id == user.id,
            LearningProgress.lesson_id == prev_lesson.id,
        )
    )
    if not (lp and lp.vocab_gate_passed):
        raise ApiError(
            "LESSON_LOCKED",
            "Bu dars qulflangan. Avval oldingi darsning lug'at testini muvaffaqiyatli topshirishingiz kerak.",
            403,
        )


def _owned_exercise(db: Session, user: User, exercise_id: str, profile: Profile | None = None) -> Exercise:
    ex = db.get(Exercise, exercise_id)
    if not ex:
        raise ApiError("EXERCISE_NOT_FOUND", "Mashq topilmadi.", 404)
    book = db.get(Book, ex.book_id)
    if not book or book.user_id != user.id:
        raise ApiError("EXERCISE_NOT_FOUND", "Mashq topilmadi.", 404)

    # Check gating if exercise belongs to a lesson
    if ex.lesson_id and profile is not None:
        lesson = db.get(Lesson, ex.lesson_id)
        if lesson:
            _check_lesson_gate(db, user, profile, lesson)

    return ex


def _exercise_out(ex: Exercise, include_questions: bool = True) -> ExerciseOut:
    data = ExerciseOut.model_validate(ex)
    if include_questions:
        data.questions = [
            QuestionOut(
                id=q.id, number=q.number, order_index=q.order_index, prompt=q.prompt,
                passage=q.passage, blanks=q.blanks, matching_pairs=q.matching_pairs,
                options=[OptionOut.model_validate(o) for o in q.options],
            ) for q in sorted(ex.questions, key=lambda x: x.order_index)
        ]
    return data


@router.get("/lessons/{lesson_id}/exercises", response_model=list[ExerciseOut])
def lesson_exercises(
    lesson_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    profile: Profile = Depends(get_current_profile),
):
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)
    book = db.get(Book, lesson.book_id)
    if not book or book.user_id != user.id:
        raise ApiError("LESSON_NOT_FOUND", "Dars topilmadi.", 404)

    # Gating enforcement on exercises retrieval
    _check_lesson_gate(db, user, profile, lesson)

    exercises = list(db.scalars(
        select(Exercise).where(Exercise.lesson_id == lesson_id)
        .options(joinedload(Exercise.questions).joinedload(ExerciseQuestion.options))
        .order_by(Exercise.order_index)).unique().all())
    return [_exercise_out(ex) for ex in exercises]


@router.get("/exercises/{exercise_id}", response_model=ExerciseOut)
def get_exercise(
    exercise_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    profile: Profile = Depends(get_current_profile),
):
    ex = _owned_exercise(db, user, exercise_id, profile=profile)
    db.refresh(ex)
    return _exercise_out(ex)


@router.put("/exercises/{exercise_id}/answers", response_model=OkOut)
def save_answers(
    exercise_id: str,
    data: AnswersSaveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    profile: Profile = Depends(get_current_profile),
):
    """Autosave — called on every change (debounced). Students never lose progress."""
    limit(request, "answers_save", 300, 60, user.id)
    ex = _owned_exercise(db, user, exercise_id, profile=profile)
    q_ids = {q.id for q in ex.questions}
    for ans in data.answers:
        if ans.question_id not in q_ids:
            raise ApiError("BAD_QUESTION", "Savol bu mashqqa tegishli emas.", 400)
    for ans in data.answers:
        row = db.scalar(select(StudentAnswer).where(
            StudentAnswer.user_id == user.id, StudentAnswer.question_id == ans.question_id))
        if not row:
            row = StudentAnswer(user_id=user.id, question_id=ans.question_id)
            db.add(row)
        row.content = ans.content
        if data.submit:
            row.is_submitted = True
    db.commit()
    return OkOut(message_uz="Javoblar saqlandi.")


@router.get("/exercises/{exercise_id}/answers", response_model=list[AnswerSaveIn])
def get_saved_answers(
    exercise_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    profile: Profile = Depends(get_current_profile),
):
    ex = _owned_exercise(db, user, exercise_id, profile=profile)
    rows = db.scalars(select(StudentAnswer).where(
        StudentAnswer.user_id == user.id,
        StudentAnswer.question_id.in_([q.id for q in ex.questions] or [""]))).all()
    return [AnswerSaveIn(question_id=r.question_id, content=r.content) for r in rows]


@router.post("/exercises/{exercise_id}/check", response_model=CheckOut)
def check_exercise(
    exercise_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    profile: Profile = Depends(get_current_profile),
):
    """Grade with priority: book key -> deterministic rules -> AI -> uncertain/needs review."""
    limit(request, "check", 120, 3600, user.id)
    ex = _owned_exercise(db, user, exercise_id, profile=profile)
    if not ex.questions:
        raise ApiError("EXERCISE_EMPTY", "Bu mashqda savollar yo'q.", 400)

    saved = {r.question_id: r.content for r in db.scalars(select(StudentAnswer).where(
        StudentAnswer.user_id == user.id,
        StudentAnswer.question_id.in_([q.id for q in ex.questions] or [""]))).all()}

    verdicts: dict[str, dict] = {}
    pending_for_ai: list[ExerciseQuestion] = []
    for q in ex.questions:
        answer = saved.get(q.id, {})
        has_key = bool(q.correct_answers) and q.answer_source in ("key", "manual")
        det_correct, given_repr = grading_engine.grade_question_deterministic(q, answer)
        # Only an explicitly verified key/manual answer is authoritative. Never
        # score generated, inferred or unknown answers as deterministic truth.
        # Ask AI for an evaluation or leave the response ungraded instead.
        if q.answer_source not in ("key", "manual"):
            det_correct = None
        if det_correct is not None:
            expected = _expected_repr(q)
            verdicts[q.id] = {
                "correct": det_correct, "confidence": 1.0, "expected": expected,
                "explanation_uz": q.explanation_uz or _default_explanation(ex, det_correct),
                "source": "key" if has_key else "deterministic", "given": given_repr,
                "grammar_note_uz": _grammar_note(ex),
            }
        else:
            pending_for_ai.append(q)

    ai_used = False
    uncertain = False
    if pending_for_ai and settings.ai_configured:
        try:
            ai_verdicts, ai_uncertain, _ = grading_engine.grade_with_ai(
                db, user.id, ex, {q.id: saved.get(q.id, {}) for q in pending_for_ai})
            ai_used = True
            uncertain = uncertain or ai_uncertain
            for q in pending_for_ai:
                v = ai_verdicts.get(q.id)
                if not v:
                    continue
                verdicts[q.id] = {
                    "correct": v["correct"], "confidence": v["confidence"],
                    "expected": v.get("expected") or (_expected_repr(q) if q.answer_source in ("key", "manual") else ""),
                    "explanation_uz": v.get("explanation_uz") or _default_explanation(ex, v["correct"]),
                    "source": "ai", "given": _flatten_answer(saved.get(q.id, {})),
                    "grammar_note_uz": v.get("grammar_note_uz", ""),
                }
        except Exception as e:
            log.warning("AI grading unavailable: %s", getattr(e, "message_uz", e))
    elif pending_for_ai and not settings.ai_configured:
        pass  # honest fallback below

    for q in pending_for_ai:
        if q.id not in verdicts:
            uncertain = True
            verdicts[q.id] = {
                "correct": None, "confidence": 0.0,
                "expected": _expected_repr(q) if q.answer_source in ("key", "manual") else "",
                "explanation_uz": (
                    ("AI baholash hozir ishlamadi. " if settings.ai_configured else
                     "Bu javobni avtomatik baholash uchun AI kerak, lekin AI sozlanmagan. ") +
                    "Javobingiz saqlandi — murabbiy bilan tekshiring yoki keyin qayta urinib ko'ring."
                ),
                "source": "unverified", "given": _flatten_answer(saved.get(q.id, {})),
                "grammar_note_uz": "",
            }

    graded = [v for v in verdicts.values() if v["correct"] is not None]
    max_score = float(len(graded)) if graded else 0.0
    score = float(sum(1 for v in graded if v["correct"]))
    percent = round(100.0 * score / max_score, 1) if max_score else 0.0
    if not graded:
        percent = 0.0

    attempt = ExerciseAttempt(
        user_id=user.id, exercise_id=ex.id, lesson_id=ex.lesson_id,
        score=score, max_score=max_score, percent=percent,
        ai_used=ai_used, uncertain=uncertain,
        details=[{"question_id": qid, **v} for qid, v in verdicts.items()],
        checked_at=datetime.now(timezone.utc),
    )
    db.add(attempt)

    for qid in verdicts:
        row = db.scalar(select(StudentAnswer).where(
            StudentAnswer.user_id == user.id, StudentAnswer.question_id == qid))
        if row:
            row.is_submitted = True

    if ex.lesson_id:
        lp = db.scalar(select(LearningProgress).where(
            LearningProgress.user_id == user.id, LearningProgress.lesson_id == ex.lesson_id))
        if not lp:
            lp = LearningProgress(user_id=user.id, lesson_id=ex.lesson_id, book_id=ex.book_id)
            db.add(lp)
            db.flush()
        checked_ex = len({a.exercise_id for a in db.scalars(select(ExerciseAttempt).where(
            ExerciseAttempt.user_id == user.id, ExerciseAttempt.lesson_id == ex.lesson_id)).all()})
        total_ex = int(db.scalar(select(func.count(Exercise.id)).where(
            Exercise.lesson_id == ex.lesson_id)) or 0)
        lp.exercises_checked = checked_ex
        lp.exercises_total = total_ex
        if total_ex and checked_ex >= total_ex and lp.status != "completed":
            lp.status = "exercises_done"

    day = datetime.now().strftime("%Y-%m-%d")
    act = db.scalar(select(ActivityDay).where(ActivityDay.user_id == user.id, ActivityDay.day == day))
    if not act:
        act = ActivityDay(user_id=user.id, day=day, seconds=0,
                          exercises_checked=0, answers_submitted=0, words_reviewed=0)
        db.add(act)
        db.flush()
    act.exercises_checked += 1
    act.answers_submitted += len(verdicts)

    db.commit()

    out_verdicts = sorted(
        [VerdictOut(
            question_id=qid,
            number=next((q.number or str(i + 1) for i, q in enumerate(ex.questions) if q.id == qid), "?"),
            correct=v["correct"], confidence=v["confidence"], given=v["given"],
            expected=v["expected"], explanation_uz=v["explanation_uz"],
            source=v["source"], grammar_note_uz=v.get("grammar_note_uz", ""),
        ) for qid, v in verdicts.items()],
        key=lambda v: v.number,
    )
    n_correct = int(score)
    if max_score == 0:
        feedback = ("Javoblar saqlandi, lekin ularni ishonchli avtomatik baholash hozircha mumkin bo'lmadi."
                    if settings.ai_configured else
                    "Javoblar saqlandi, lekin avtomatik baholash hozircha mavjud emas (AI sozlanmagan).")
    elif percent >= 90:
        feedback = f"Ajoyib natija! {n_correct}/{int(max_score)} to'g'ri. 🎉"
    elif percent >= 60:
        feedback = f"Yaxshi! {n_correct}/{int(max_score)} to'g'ri. Xatolaringizni ko'rib chiqing."
    else:
        feedback = f"{n_correct}/{int(max_score)} to'g'ri. Xatolar ustida ishlash kerak — AI murabbiydan so'rang."
    return CheckOut(
        attempt_id=attempt.id, score=score, max_score=max_score, percent=percent,
        uncertain=uncertain, ai_used=ai_used, verdicts=out_verdicts, overall_feedback_uz=feedback,
    )


@router.get("/exercises/{exercise_id}/attempts")
def exercise_attempts(
    exercise_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    profile: Profile = Depends(get_current_profile),
):
    ex = _owned_exercise(db, user, exercise_id, profile=profile)
    rows = db.scalars(select(ExerciseAttempt).where(
        ExerciseAttempt.user_id == user.id, ExerciseAttempt.exercise_id == ex.id)
        .order_by(ExerciseAttempt.created_at.desc()).limit(20)).all()
    return [{"id": a.id, "percent": a.percent, "score": a.score, "max_score": a.max_score,
             "uncertain": a.uncertain, "checked_at": a.checked_at} for a in rows]


def _expected_repr(q: ExerciseQuestion) -> str:
    if q.correct_answers:
        return ", ".join(str(a) for a in q.correct_answers)
    for o in q.options:
        if o.is_correct:
            return f"{o.letter}) {o.text}"
    if q.matching_pairs:
        return "; ".join(f"{p.get('left','?')} — {p.get('right','?')}" for p in q.matching_pairs)
    return "Kalit kitobda topilmadi"


def _flatten_answer(answer: dict) -> str:
    if not isinstance(answer, dict):
        return str(answer)
    if answer.get("text"):
        return str(answer["text"])
    if answer.get("selection"):
        return str(answer["selection"])
    if answer.get("blanks"):
        return " ".join(str(v) for v in answer["blanks"].values())
    return str(answer)


def _default_explanation(ex: Exercise, correct: bool) -> str:
    if correct:
        return "To'g'ri! Javobingiz kalitga mos keldi."
    return (f"Noto'g'ri. {ex.topic + ' mavzusini' if ex.topic else 'Qoidani'} yana bir bor ko'rib chiqing — "
            "AI murabbiydan bu mavzuni tushuntirishini so'rashingiz mumkin.")


def _grammar_note(ex: Exercise) -> str:
    return ex.explanation_uz or ""
