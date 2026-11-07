"""Vocabulary words, attempts, SRS progress and challenge sessions."""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mixins import Timestamps, UuidPk
from app.db.session import Base

VOCAB_QUESTION_TYPES = (
    "choice_en_uz",    # English word -> pick Uzbek translation
    "choice_uz_en",    # Uzbek translation -> pick English word
    "written_en_uz",   # type the Uzbek translation (recall)
    "written_uz_en",   # type the English word (recall)
    "spelling",        # hear/see hint -> type English word exactly
    "listening",       # TTS pronounces word -> pick/type it
    "sentence_blank",  # fill missing word in example sentence
)


class VocabularyWord(Base, UuidPk, Timestamps):
    __tablename__ = "vocabulary_words"
    __table_args__ = (UniqueConstraint("book_id", "term", name="uq_vocab_term"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[Optional[str]] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"), default=None)
    chapter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), default=None)
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    translation_uz: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    definition_en: Mapped[str] = mapped_column(Text, default="", nullable=False)
    example_sentence: Mapped[str] = mapped_column(Text, default="", nullable=False)
    part_of_speech: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="book", nullable=False)  # book|ai|manual
    needs_translation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    book: Mapped["Book"] = relationship(back_populates="vocabulary")  # noqa: F821


class VocabularySession(Base, UuidPk, Timestamps):
    """A generated challenge (lesson gate, revision or custom practice)."""

    __tablename__ = "vocabulary_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[Optional[str]] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), default=None)
    lesson_id: Mapped[Optional[str]] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), default=None)
    kind: Mapped[str] = mapped_column(String(24), default="practice", nullable=False)
    # lesson_gate | review | custom
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)  # active|passed|failed
    required_score: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # first-attempt percent
    items: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    results: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class VocabularyAttempt(Base, UuidPk):
    __tablename__ = "vocabulary_attempts"
    __table_args__ = (Index("ix_vocab_attempts_user_word", "user_id", "word_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    word_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_words.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vocabulary_sessions.id", ondelete="SET NULL"), default=None)
    question_type: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=None, nullable=False, default=datetime.utcnow
    )


class VocabularyProgress(Base, UuidPk, Timestamps):
    """SM-2 spaced repetition state per (user, word)."""

    __tablename__ = "vocabulary_progress"
    __table_args__ = (UniqueConstraint("user_id", "word_id", name="uq_vocab_progress"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    word_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_words.id", ondelete="CASCADE"), index=True, nullable=False)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="learning", nullable=False)  # learning|review|mastered
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
