"""Spaced repetition scheduling (SM-2 adaptation with question-type awareness)."""
from datetime import datetime, timedelta, timezone


def quality_from_answer(*, correct: bool, question_type: str = "written_en_uz", time_seconds: float = 0.0) -> int:
    """SM-2 quality grade (0..5):
    5: perfect response on active recall (written recall or spelling).
    4: correct response on recognition (multiple choice / listening), or with hesitation.
    3: correct with difficulty.
    2: incorrect, but correct was easy to recall upon seeing answer.
    1: incorrect, wrong recall.
    0: total blackout.
    """
    if not correct:
        return 1

    if question_type in ("written_uz_en", "written_en_uz", "spelling", "sentence_blank"):
        return 5
    elif question_type in ("choice_en_uz", "choice_uz_en", "listening"):
        return 3
    return 4


def schedule_sm2(
    *,
    ease_factor: float,
    interval_days: float,
    repetitions: int,
    lapses: int,
    quality: int,  # 0..5
    now: datetime | None = None,
) -> dict:
    """Pure SM-2 spaced repetition calculation.
    Returns: {ease_factor, interval_days, repetitions, lapses, status, due_at}.
    """
    now = now or datetime.now(timezone.utc)
    q = max(0, min(quality, 5))

    # EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(1.3, round(new_ef, 2))

    if q < 3:
        # lapse
        new_reps = 0
        new_interval = 0.0  # reset to review immediately
        new_lapses = lapses + 1
        status = "learning"
    else:
        new_reps = repetitions + 1
        new_lapses = lapses
        if new_reps == 1:
            new_interval = 1.0
        elif new_reps == 2:
            new_interval = 6.0
        else:
            new_interval = round(interval_days * new_ef, 1)
        status = "mastered" if new_interval >= 21.0 else "review"

    due_at = now + timedelta(days=new_interval)
    return {
        "ease_factor": new_ef,
        "interval_days": new_interval,
        "repetitions": new_reps,
        "lapses": new_lapses,
        "status": status,
        "due_at": due_at,
    }
