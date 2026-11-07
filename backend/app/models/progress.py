"""Learning progress, activity, revision sessions and AI usage/chat models."""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mixins import Timestamps, UuidPk
from app.db.session import Base


class LearningProgress(Base, UuidPk, Timestamps):
    __tablename__ = "learning_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_learning_progress"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="not_started", nullable=False)
    # not_started | in_progress | exercises_done | completed
    exercises_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exercises_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vocab_gate_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_visited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class ActivityDay(Base, UuidPk):
    __tablename__ = "activity_days"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_activity_day"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD (user tz)
    seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exercises_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answers_submitted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    words_reviewed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RevisionSession(Base, UuidPk, Timestamps):
    __tablename__ = "revision_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[Optional[str]] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), default=None)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)  # active|completed
    focus: Mapped[str] = mapped_column(String(255), default="", nullable=False)  # human-readable uz focus label
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    items: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class RevisionItem(Base, UuidPk):
    __tablename__ = "revision_items"

    session_id: Mapped[str] = mapped_column(ForeignKey("revision_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    item_type: Mapped[str] = mapped_column(String(24), default="vocab", nullable=False)  # vocab|exercise|question
    word_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vocabulary_words.id", ondelete="CASCADE"), default=None)
    question_id: Mapped[Optional[str]] = mapped_column(ForeignKey("exercise_questions.id", ondelete="CASCADE"), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[Optional[bool]] = mapped_column(Boolean, default=None, nullable=True)


class AIConversation(Base, UuidPk, Timestamps):
    __tablename__ = "ai_conversations"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[Optional[str]] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), default=None)
    lesson_id: Mapped[Optional[str]] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"), default=None)
    exercise_id: Mapped[Optional[str]] = mapped_column(ForeignKey("exercises.id", ondelete="SET NULL"), default=None)
    title: Mapped[str] = mapped_column(String(255), default="Yangi suhbat", nullable=False)

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.created_at"
    )


class AIMessage(Base, UuidPk, Timestamps):
    __tablename__ = "ai_messages"
    __table_args__ = (Index("ix_ai_messages_conv", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant|system
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class UsageEvent(Base, UuidPk):
    """Every AI call is measured here — powers plan limits and cost monitoring."""

    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_user_day", "user_id", "day"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # UTC YYYY-MM-DD
    feature: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    # analyze | grading | tutor | extra_exercises | vocab_translate
    provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
