"""Progress analytics: dashboard stats, topic strength/weakness, streaks, activity."""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ActivityDay,
    Book,
    Exercise,
    ExerciseAttempt,
    LearningProgress,
    Lesson,
    VocabularyProgress,
    VocabularyWord,
)


def _streak(days: list[str]) -> int:
    day_set = set(days)
    streak = 0
    cursor = date.today()
    if cursor.strftime("%Y-%m-%d") not in day_set:
        cursor -= timedelta(days=1)
    while cursor.strftime("%Y-%m-%d") in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def dashboard(db: Session, user_id: str, daily_goal_minutes: int = 20) -> dict:
    books_total = int(db.scalar(select(func.count(Book.id)).where(Book.user_id == user_id)) or 0)
    books_ready = int(db.scalar(select(func.count(Book.id)).where(
        Book.user_id == user_id, Book.status == "ready")) or 0)

    lessons_total = int(db.scalar(
        select(func.count(Lesson.id)).join(Book).where(Book.user_id == user_id)) or 0)
    lessons_completed = int(db.scalar(
        select(func.count(LearningProgress.id)).where(
            LearningProgress.user_id == user_id, LearningProgress.status == "completed")) or 0)

    attempts = list(db.scalars(
        select(ExerciseAttempt).where(ExerciseAttempt.user_id == user_id)
        .order_by(ExerciseAttempt.created_at.desc()).limit(500)).all())
    exercises_checked = len(attempts)
    percents = [a.percent for a in attempts if a.max_score > 0]
    avg_accuracy = round(sum(percents) / len(percents), 1) if percents else 0.0

    vocab_total = int(db.scalar(select(func.count(VocabularyProgress.id)).where(
        VocabularyProgress.user_id == user_id)) or 0)
    vocab_mastered = int(db.scalar(select(func.count(VocabularyProgress.id)).where(
        VocabularyProgress.user_id == user_id, VocabularyProgress.status == "mastered")) or 0)
    vocab_learning = vocab_total - vocab_mastered
    vocab_due = int(db.scalar(select(func.count(VocabularyProgress.id)).where(
        VocabularyProgress.user_id == user_id, VocabularyProgress.due_at <= datetime.utcnow())) or 0)

    today = date.today()
    activity = list(db.scalars(select(ActivityDay).where(
        ActivityDay.user_id == user_id,
        ActivityDay.day >= (today - timedelta(days=13)).strftime("%Y-%m-%d"))).all())
    by_day = {a.day: a for a in activity}
    empty = ActivityDay(day="0", seconds=0, exercises_checked=0, answers_submitted=0, words_reviewed=0)
    activity_last_14d = [
        {
            "day": (today - timedelta(days=offset)).strftime("%Y-%m-%d"),
            "minutes": round((by_day.get((today - timedelta(days=offset)).strftime("%Y-%m-%d"), empty).seconds or 0) / 60, 1),
            "exercises": by_day.get((today - timedelta(days=offset)).strftime("%Y-%m-%d"), empty).exercises_checked or 0,
        }
        for offset in range(13, -1, -1)
    ]
    study_minutes_total = round((int(db.scalar(
        select(func.coalesce(func.sum(ActivityDay.seconds), 0)).where(ActivityDay.user_id == user_id)) or 0)) / 60)
    today_row = by_day.get(today.strftime("%Y-%m-%d"))
    today_minutes = round((today_row.seconds if today_row else 0) / 60, 1)

    weak, strong = topic_breakdown(db, user_id)

    return {
        "books_total": books_total,
        "books_ready": books_ready,
        "lessons_completed": lessons_completed,
        "lessons_total": lessons_total,
        "exercises_checked": exercises_checked,
        "avg_accuracy": avg_accuracy,
        "vocab_words_total": vocab_total,
        "vocab_mastered": vocab_mastered,
        "vocab_learning": vocab_learning,
        "vocab_due": vocab_due,
        "study_minutes_total": study_minutes_total,
        "streak_days": _streak([a.day for a in activity]),
        "daily_goal_minutes": daily_goal_minutes,
        "today_minutes": today_minutes,
        "activity_last_14d": activity_last_14d,
        "weak_topics": weak[:5],
        "strong_topics": strong[:5],
    }


def topic_breakdown(db: Session, user_id: str, min_attempts: int = 2) -> tuple[list[dict], list[dict]]:
    rows = db.execute(
        select(Exercise.topic, func.count(ExerciseAttempt.id),
               func.avg(func.nullif(ExerciseAttempt.percent, -1.0)))
        .join(ExerciseAttempt, ExerciseAttempt.exercise_id == Exercise.id)
        .where(ExerciseAttempt.user_id == user_id, Exercise.topic != "")
        .group_by(Exercise.topic)
    ).all()
    topics = [
        {"topic": t or "Umumiy", "attempts": int(n), "accuracy": round(float(acc or 0), 1)}
        for t, n, acc in rows if int(n) >= min_attempts
    ]
    weak = sorted([t for t in topics if t["accuracy"] < 75], key=lambda x: x["accuracy"])
    strong = sorted([t for t in topics if t["accuracy"] >= 75], key=lambda x: -x["accuracy"])
    return weak, strong


def heartbeat(db: Session, user_id: str, seconds: int, lesson_id: str | None = None,
              page: int | None = None) -> None:
    seconds = max(0, min(int(seconds), 120))
    if seconds == 0 and not lesson_id:
        return
    day = datetime.now().strftime("%Y-%m-%d")
    row = db.scalar(select(ActivityDay).where(ActivityDay.user_id == user_id, ActivityDay.day == day))
    if not row:
        row = ActivityDay(user_id=user_id, day=day, seconds=0,
                          exercises_checked=0, answers_submitted=0, words_reviewed=0)
        db.add(row)
        db.flush()
    row.seconds += seconds
    if lesson_id:
        lesson = db.get(Lesson, lesson_id)
        if lesson:
            lp = db.scalar(select(LearningProgress).where(
                LearningProgress.user_id == user_id, LearningProgress.lesson_id == lesson_id))
            if not lp:
                lp = LearningProgress(user_id=user_id, lesson_id=lesson_id, book_id=lesson.book_id)
                db.add(lp)
                db.flush()
            lp.time_spent_seconds += seconds
            lp.last_visited_at = datetime.utcnow()
            if page:
                lp.last_page = int(page)
            if lp.status == "not_started":
                lp.status = "in_progress"
    db.commit()
