"""Exercises, questions, options, student answers and attempts."""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mixins import Timestamps, UuidPk
from app.db.session import Base

EXERCISE_TYPES = (
    "fill_blank",            # She _____ to school every day.
    "multiple_choice",
    "matching",
    "translation",
    "sentence_construction",  # word-order / build a sentence
    "writing",                # open-ended longer answers
    "reading_comprehension",
    "true_false",
)


class Exercise(Base, UuidPk, Timestamps):
    __tablename__ = "exercises"
    __table_args__ = (Index("ix_exercises_lesson_order", "lesson_id", "order_index"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[Optional[str]] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"), default=None)
    chapter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), default=None)
    exercise_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ref: Mapped[str] = mapped_column(String(64), default="", nullable=False)  # e.g. "Exercise 5"
    page_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="book", nullable=False)  # book|ai_tutor
    bbox: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=None)  # {x0,y0,x1,y1} in PDF points
    topic: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    explanation_uz: Mapped[str] = mapped_column(Text, default="", nullable=False)  # AI-generated lesson note
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detection: Mapped[str] = mapped_column(String(16), default="rule", nullable=False)  # rule|ai|manual
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lesson: Mapped[Optional["Lesson"]] = relationship(back_populates="exercises")  # noqa: F821
    questions: Mapped[list["ExerciseQuestion"]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan", order_by="ExerciseQuestion.order_index"
    )


class ExerciseQuestion(Base, UuidPk):
    __tablename__ = "exercise_questions"

    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    number: Mapped[str] = mapped_column(String(16), default="", nullable=False)  # textbook numbering "1", "2a"
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    passage: Mapped[str] = mapped_column(Text, default="", nullable=False)  # reading text if any
    # blanks: [{"id":"b1","bbox":{...}|null,"hint":""}] — bbox in PDF points for reader overlay
    blanks: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    matching_pairs: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)  # [{"left":"","right":""}]
    correct_answers: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)  # accepted answers
    answer_source: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    # key | ai | inferred | unknown
    explanation_uz: Mapped[str] = mapped_column(Text, default="", nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    exercise: Mapped[Exercise] = relationship(back_populates="questions")
    options: Mapped[list["ExerciseOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="ExerciseOption.letter"
    )


class ExerciseOption(Base, UuidPk):
    __tablename__ = "exercise_options"

    question_id: Mapped[str] = mapped_column(
        ForeignKey("exercise_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    letter: Mapped[str] = mapped_column(String(4), default="", nullable=False)  # A/B/C/D
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, default=None, nullable=True)  # null = unknown yet

    question: Mapped[ExerciseQuestion] = relationship(back_populates="options")


class StudentAnswer(Base, UuidPk, Timestamps):
    """Latest saved answer per (user, question). Autosaved, resumable."""

    __tablename__ = "student_answers"
    __table_args__ = (UniqueConstraint("user_id", "question_id", name="uq_student_answer"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("exercise_questions.id", ondelete="CASCADE"), index=True, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # {"text": "..."} | {"selection": "B"} | {"pairs": {"l1": "r2"}} | {"blanks": {"b1": "goes"}} | {"text": "..."} for writing
    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ExerciseAttempt(Base, UuidPk, Timestamps):
    __tablename__ = "exercise_attempts"
    __table_args__ = (Index("ix_attempts_user_ex", "user_id", "exercise_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[Optional[str]] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"), default=None)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)      # graded points
    max_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    # [{"question_id","number","correct":bool|null,"confidence","given","expected","explanation_uz","source"}]
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
