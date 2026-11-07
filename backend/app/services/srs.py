"""SM-2 spaced repetition scheduler."""
import math
from datetime import datetime, timedelta, timezone


def schedule_sm2(*, ease_factor: float, interval_days: float, repetitions: int, lapses: int,
                 quality: int) -> dict:
    """Classic SM-2. quality: 0-5 (we map from answer correctness/type).
    Returns updated state (no DB access — pure function, unit-testable)."""
    ease = ease_factor
    interval = interval_days
    reps = repetitions
    laps = lapses

    if quality < 3:
        reps = 0
        interval = 0
        laps += 1
        ease = max(1.3, ease - 0.2)
    else:
        ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        ease = max(1.3, min(2.8, ease))
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = math.ceil(interval * ease)

    return {
        "ease_factor": round(ease, 4),
        "interval_days": float(interval),
        "repetitions": reps,
        "lapses": laps,
        "due_at": datetime.now(timezone.utc) + timedelta(days=interval or 0),
        "status": "learning" if reps < 2 else ("review" if interval < 21 else "mastered"),
    }


def quality_from_answer(*, correct: bool, question_type: str) -> int:
    """Map an answer to SM-2 quality. Recall-based types count more than recognition."""
    if not correct:
        return 1
    if question_type in ("written_en_uz", "written_uz_en", "spelling", "sentence_blank"):
        return 5
    if question_type in ("listening",):
        return 4
    return 3  # multiple-choice recognition
