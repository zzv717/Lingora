"""Exercise region maps, page-level vision cache and manual crop corrections.

* ``VisionExerciseRegion`` — one detected exercise location on one page, in NORMALIZED
  coordinates (0..1). Pixel positions are computed only when a crop is rendered, so a
  different DPI or canvas size can never shift the crop.
* ``VisionPageRegionCache`` — raw detection result keyed by the page image hash. A page
  whose pixels did not change is never sent to the vision provider twice.
* ``VisionRegionCorrection`` — audit log of manual corrections (AI box, manual box, who,
  when, why). It is the data source for later accuracy analysis; the newest manual box
  wins over the AI result for its exercise.

All three are per-user content that references a book the user owns.
"""
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mixins import Timestamps, UuidPk
from app.db.session import Base


class VisionExerciseRegion(Base, UuidPk, Timestamps):
    __tablename__ = "vision_exercise_regions"
    __table_args__ = (
        Index("ix_vision_regions_book_page", "book_id", "page_number"),
        Index("ix_vision_regions_book_order", "book_id", "page_number", "order_index"),
    )

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    exercise_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("exercises.id", ondelete="SET NULL"), default=None, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    number: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    # [x1, y1, x2, y2] normalized to 0..1 of the rendered page, top-left origin.
    bbox: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    # Box exactly as the model first returned it (before clamping/padding/correction).
    original_bbox: Mapped[Optional[list[Any]]] = mapped_column(JSON, default=None)
    # ai | manual | verification
    source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    continues_from_previous_page: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    continues_on_next_page: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Lower index of the partner region when an exercise continues across pages.
    continued_from_region_id: Mapped[Optional[str]] = mapped_column(String(36), default=None)
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class VisionPageRegionCache(Base, UuidPk, Timestamps):
    __tablename__ = "vision_page_region_cache"
    __table_args__ = (Index("ix_vision_cache_book_page", "book_id", "page_number"),)

    # "<page image sha256>:<pdf page>:<book page count>" — provider independent on purpose.
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class VisionRegionCorrection(Base, UuidPk, Timestamps):
    __tablename__ = "vision_region_corrections"
    __table_args__ = (
        Index("ix_vision_corrections_book_page", "book_id", "page_number"),
        Index("ix_vision_corrections_user", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False)
    region_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vision_exercise_regions.id", ondelete="SET NULL"), default=None)
    exercise_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("exercises.id", ondelete="SET NULL"), default=None)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    # ai | manual — what the box was before the edit.
    previous_source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)
    previous_bbox: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    corrected_bbox: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)
