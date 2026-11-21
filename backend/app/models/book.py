"""Book, pages, structure (chapters/lessons), processing jobs and answer keys."""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mixins import Timestamps, UuidPk
from app.db.session import Base


class Book(Base, UuidPk, Timestamps):
    __tablename__ = "books"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="uploaded", nullable=False)
    # uploaded | processing | ready | failed
    consent_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_page: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # How many entries the text parser recovered at analysis time. Persisted instead of
    # recomputed because the fallback decision must survive a restart: a book whose text
    # layer yielded nothing is exactly the book that needs the vision pass, and the
    # question "why is my Lug'at empty" has to be answerable long after the upload.
    text_vocabulary_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                                       server_default="0")
    # Why the Lug'at is empty, in the user's language. Written by the pipeline so the
    # screen can explain itself instead of showing a bare "no vocabulary found".
    vocabulary_note_uz: Mapped[str] = mapped_column(Text, default="", nullable=False,
                                                    server_default="")

    pages: Mapped[list["BookPage"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="BookPage.page_number"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Chapter.order_index"
    )
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Lesson.order_index"
    )
    vocabulary: Mapped[list["VocabularyWord"]] = relationship(back_populates="book", cascade="all, delete-orphan")


class ProcessingJob(Base, UuidPk, Timestamps):
    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_jobs_book_status", "book_id", "status"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), default="analyze", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    # queued | running | completed | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0..100
    stage: Mapped[str] = mapped_column(String(48), default="", nullable=False)   # machine-readable stage
    stage_label_uz: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    logs: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class BookPage(Base, UuidPk):
    __tablename__ = "book_pages"
    __table_args__ = (UniqueConstraint("book_id", "page_number", name="uq_book_page"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    height: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    blocks: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)  # [{text,bbox,kind}]
    images: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # When a vision vocabulary pass read this page. A pass is paid per page, and a page
    # that is simply not a word list must not be offered again on every run.
    vocab_scanned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None)

    book: Mapped[Book] = relationship(back_populates="pages")


class Chapter(Base, UuidPk):
    __tablename__ = "chapters"

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="unit", nullable=False)  # unit|chapter|section
    number: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    book: Mapped[Book] = relationship(back_populates="chapters")
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class Lesson(Base, UuidPk, Timestamps):
    __tablename__ = "lessons"

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    chapter_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), index=True, default=None
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), default="", nullable=False)  # grammar topic slug/text
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grammar_explanation_uz: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    book: Mapped[Book] = relationship(back_populates="lessons")
    chapter: Mapped[Optional[Chapter]] = relationship(back_populates="lessons")
    exercises: Mapped[list["Exercise"]] = relationship(  # noqa: F821
        back_populates="lesson", cascade="all, delete-orphan", order_by="Exercise.order_index"
    )


class AnswerKey(Base, UuidPk):
    __tablename__ = "answer_keys"

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="book", nullable=False)  # book|ai|manual
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # entries: [{"exercise_ref": "Exercise 3" | "12", "question_number": "1", "answers": ["goes"], "page": 12}]
    entries: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
