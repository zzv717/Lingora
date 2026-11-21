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


class VocabularyUnit(Base, UuidPk, Timestamps):
    """One unit/lesson of a book's word list, as the book prints it.

    Units are a first-class row rather than a string on each word: the Lug'at screen groups
    by them, edits move words between them, and a unit's page range has to survive a
    re-extraction. ``number`` is the printed unit number when there is one; a book that
    numbers chapters differently keeps its own label in ``title``.
    """

    __tablename__ = "vocabulary_units"
    __table_args__ = (UniqueConstraint("book_id", "number", name="uq_vocab_unit_number"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 0..1 from the heading pass; kept so a low-confidence unit can be flagged in the UI.
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    words: Mapped[list["VocabularyWord"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan")


class VocabularyWord(Base, UuidPk, Timestamps):
    __tablename__ = "vocabulary_words"
    # A book may legitimately list the same spelling twice under two units ("well" as an
    # adverb in one unit, as a noun in another), so uniqueness is per unit, not per book.
    __table_args__ = (UniqueConstraint("book_id", "unit_id", "term", name="uq_vocab_term"),)

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
    # Where the word's illustration sits on the ORIGINAL PDF page, as a normalized
    # [x1, y1, x2, y2] box (0..1). Cropped in the browser from the authenticated PDF,
    # never re-generated, so the picture stays sharp at any screen size.
    picture_page: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    picture_bbox: Mapped[Optional[Any]] = mapped_column(JSON, default=None)
    # --- extraction quality, all optional so old rows stay valid ---
    unit_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vocabulary_units.id", ondelete="SET NULL"), index=True, default=None)
    # Where the entry sits on its page, top-to-bottom (and left column before right).
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # "auto" = machine translation (usable in tests), "verified" = user confirmed,
    # "edited" = user changed it, "" = nothing translated yet.
    translation_status: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    alt_translations: Mapped[Optional[Any]] = mapped_column(JSON, default=None)

    book: Mapped["Book"] = relationship(back_populates="vocabulary")  # noqa: F821
    unit: Mapped[Optional[VocabularyUnit]] = relationship(back_populates="words")


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
