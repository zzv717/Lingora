"""Whole-book vocabulary extraction: units first, then pages, then translations.

Called once from the pipeline (and from the explicit "read with AI" endpoints). The order
matters and is the whole point of this module:

1. **Pass 1 — units.** ``detect_units`` looks at every page at low resolution and answers one
   question: which unit does this page belong to, and what is it called. The result is stored
   in ``vocabulary_units`` with a page range that runs from a unit's heading to the page before
   the next unit's heading — never a single page, which is what produced the "9–9" ranges.
2. **Pass 2 — words.** Each page is read at full resolution *with its unit as context*, so a
   continuation page keeps its unit and a stray glyph can never become a title.
3. **Pass 3 — translations.** Entries are translated into Uzbek in batches, status ``auto``,
   usable in tests immediately.

Re-extraction **replaces** the book's previous vision rows instead of appending to them: the
old behaviour of "skip the word if the book already knows it" is what made a fixed extractor
look like an unfixed one, because the first, broken extraction stayed in the database forever.
Words a human edited or verified are kept as they are.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, DisconnectionError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.models import Book, BookPage, VocabularyUnit, VocabularyWord
from app.services.ai import vocab_translate
from app.services.ai import vision_vocabulary
from app.services.ai.vision_vocabulary import analyse_page, mark_scanned, save_words
from app.services.ai.vision_vocabulary import pending_pages as vision_pending_pages

log = logging.getLogger("lingora.vocab_extract")

# Statuses that belong to a human: replacing the extraction must not delete them.
PROTECTED_STATUSES = ("verified", "edited")

# Failures that are a property of the configuration, not of one page: stop the run and report.
REPEATING_FAILURES = ("AI_NOT_CONFIGURED", "AI_VISION_NOT_CONFIGURED", "AI_PROVIDER_REJECTED",
                      "AI_QUOTA_EXCEEDED", "AI_FEATURE_QUOTA_EXCEEDED", "AI_TOKEN_QUOTA_EXCEEDED")

# Connection-level failures a retry on a fresh connection can fix (server closed an idle
# pooled connection, pooler recycled it, TLS dropped). A bad statement is not in this list.
_TRANSIENT_DB_MARKERS = ("server closed the connection", "connection was closed",
                         "connection already closed", "ssl connection has been closed",
                         "terminating connection", "connection reset", "broken pipe",
                         "could not connect", "server has gone away",
                         "no connection to the server")


def is_transient_db_error(exc: BaseException) -> bool:
    """True when the database connection died, not when the statement was wrong."""
    if isinstance(exc, (DisconnectionError, OperationalError)):
        return True
    if isinstance(exc, DBAPIError):
        text = str(exc).lower()
        return any(marker in text for marker in _TRANSIENT_DB_MARKERS)
    return False


def clear_extraction(db: Session, book: Book) -> dict[str, int]:
    """Remove the previous *machine* extraction of this book.

    Words a human verified or edited are kept, together with their unit (so a re-extraction
    cannot silently drop somebody's work); everything else from the vision extractor goes.
    Progress rows cascade with the words, which is correct: the word they pointed at is gone.
    """
    kept_terms = {term.strip().lower() for term in db.scalars(
        select(VocabularyWord.term).where(VocabularyWord.book_id == book.id,
                                          VocabularyWord.translation_status.in_(PROTECTED_STATUSES))).all()}
    stale = list(db.scalars(select(VocabularyWord).where(
        VocabularyWord.book_id == book.id,
        VocabularyWord.source == "vision")).all())
    removed_words = 0
    for word in stale:
        if word.translation_status in PROTECTED_STATUSES or word.term.strip().lower() in kept_terms:
            continue
        db.delete(word)
        removed_words += 1
    db.flush()

    removed_units = 0
    for unit in list(db.scalars(select(VocabularyUnit).where(VocabularyUnit.book_id == book.id)).all()):
        remaining = db.scalar(select(VocabularyWord.id).where(
            VocabularyWord.unit_id == unit.id).limit(1))
        if remaining is None:
            db.delete(unit)
            removed_units += 1
    db.commit()
    if removed_words or removed_units:
        log.info("vocabulary extraction: cleared %s words / %s units of %s",
                 removed_words, removed_units, book.id)
    return {"words_removed": removed_words, "units_removed": removed_units}


def pending_pages(db: Session, book: Book, include_text_pages: bool = False) -> list[int]:
    """Thin re-export so callers do not need to know which pass owns the worklist."""
    return vision_pending_pages(db, book, include_text_pages=include_text_pages)


def all_pages(db: Session, book: Book) -> list[int]:
    """Every page of the book, in order — the worklist for a deliberate full re-extraction."""
    return [p.page_number for p in db.scalars(
        select(BookPage).where(BookPage.book_id == book.id).order_by(BookPage.page_number)).all()]


def clear_extraction_flags(db: Session, book: Book) -> int:
    """Forget which pages were already read, so a cleared book can be read again."""
    pages = list(db.scalars(select(BookPage).where(BookPage.book_id == book.id)).all())
    touched = 0
    for page in pages:
        if page.vocab_scanned_at is not None:
            page.vocab_scanned_at = None
            touched += 1
    db.commit()
    return touched


def _unit_payload(span) -> dict[str, Any]:
    return {"unit_number": span.number, "title": span.title,
            "page_start": span.page_start, "page_end": span.page_end,
            "confidence": span.confidence}


def _page_range(span) -> range:
    return range(span.page_start, span.page_end + 1)


def extract_book(db: Session, book: Book,
                 pages: list[int] | None = None,
                 progress_cb: Callable[[float, str], None] | None = None,
                 translate: bool = True,
                 replace: bool = True,
                 clear_only: bool = False,
                 unitize: bool = True,
                 max_seconds: float | None = None) -> dict[str, Any]:
    """Run all three passes for one book and return a report of what happened.

    ``pages`` limits Pass 2 (a batch call reads a handful of pages); Pass 1 always covers the
    whole book because a unit range is a property of the whole book, not of one batch.

    ``max_seconds`` is the serverless guard: a function killed at its timeout loses every page
    in the request, including the ones already paid for. Once the budget is spent the loop
    stops *starting* new pages and reports them as ``deferred``; the client calls again. At
    least one page always runs, so a batch can never make no progress.
    """
    report: dict[str, Any] = {"units": 0, "pages_read": 0, "words_added": 0,
                              "rejected": 0, "deferred": 0, "duplicates": 0,
                              "translated": 0, "translation_error": "", "unit_list": [],
                              "warnings": [], "per_page": [],
                              "cleared": {"words_removed": 0, "units_removed": 0}}
    if not settings.ai_vision_configured:
        report["warnings"].append({"page": 0, "code": "AI_VISION_NOT_CONFIGURED",
                                   "message_uz": "AI (vision) sozlanmagan — lug'at o'qilmadi."})
        return report

    all_pages = [p.page_number for p in db.scalars(
        select(BookPage).where(BookPage.book_id == book.id).order_by(BookPage.page_number)).all()]
    book.page_count = book.page_count or len(all_pages)

    # ---- 1. units over the whole book ----
    from app.services.ai.vocabulary_units import detect_units

    # A caller that already ran the heading pass passes ``unitize=False``: the unit rows and
    # page ranges it just stored are the truth, and re-reading every page at low resolution
    # for each batch would multiply the cost of one extraction by the number of batches.
    spans = detect_units(db, book.user_id, book, all_pages or None) if unitize else []
    if replace or clear_only:
        report["cleared"] = clear_extraction(db, book)
    if clear_only:
        # "Start over" is its own step: the next batches re-read pages that were previously
        # marked as scanned, so their words come back under the new units.
        return report
    for span in spans:
        unit = save_span(db, book, span)
        report["unit_list"].append({"number": unit.number, "title": unit.title,
                                    "page_start": unit.page_start, "page_end": unit.page_end})
    # Units that already exist (a batch run that skipped the heading pass) still have to be
    # visible in the report, otherwise ``detect_vocabulary_units`` would answer "0 units".
    for unit in db.scalars(select(VocabularyUnit).where(VocabularyUnit.book_id == book.id)
                           .order_by(VocabularyUnit.number)).all():
        if any(item["number"] == unit.number for item in report["unit_list"]):
            continue
        report["unit_list"].append({"number": unit.number, "title": unit.title,
                                    "page_start": unit.page_start,
                                    "page_end": unit.page_end})
    db.commit()
    report["units"] = len(report["unit_list"])
    if not report["units"]:
        report["warnings"].append({
            "page": 0, "code": "VOCABULARY_UNITS_FALLBACK",
            "message_uz": ("Bo'limlar (unit) sarlavhalari o'qilmadi — so'zlar kitob tuzilishi "
                           "asosida guruhlanadi.")})
    if progress_cb:
        progress_cb(0.15, "vocabulary_units")

    # ---- 2. words, page by page, with the unit as context ----
    targets = pages if pages is not None else (all_pages or [])
    clock = time.monotonic()
    for index, page_number in enumerate(targets):
        if max_seconds is not None and index and time.monotonic() - clock > max_seconds:
            report["per_page"].append({"page": page_number, "status": "deferred",
                                       "unit": None, "words_found": 0, "words_added": 0,
                                       "reason": "request budget spent; call the batch again"})
            report["deferred"] += 1
            continue
        span = next((s for s in spans if page_number in _page_range(s)), None)
        hint = _unit_payload(span) if span else None
        try:
            parsed, _provider, _model = analyse_page(
                db, book.user_id, book, page_number, unit_hint=hint,
                retries=settings.ai_max_retries)
        except ApiError as exc:
            log.warning("vocabulary extraction: page %s failed (%s)", page_number, exc.code)
            report["per_page"].append({"page": page_number, "status": "error", "code": exc.code,
                                       "unit": hint.get("unit_number") if hint else None,
                                       "words_found": 0, "words_added": 0,
                                       "message": exc.message_uz})
            report["warnings"].append({
                "page": page_number, "code": "VOCABULARY_PAGE_FAILED",
                "message_uz": f"{page_number}-sahifani AI o'qiy olmadi."})
            # Problems that will repeat identically on every remaining page: an invalid key,
            # an unknown model, a spent quota. Continuing would pay for the same failure
            # hundreds of times (and, on a bad base URL, wait out a timeout each time).
            if exc.http_status in (401, 402, 403) or exc.code in REPEATING_FAILURES:
                report["deferred"] = len(targets) - index
                break
            continue
        except Exception:  # noqa: BLE001 - one page must not lose the book
            log.warning("vocabulary extraction: page %s crashed", page_number, exc_info=True)
            report["per_page"].append({"page": page_number, "status": "error",
                                       "code": "PAGE_FAILED",
                                       "unit": hint.get("unit_number") if hint else None,
                                       "words_found": 0, "words_added": 0,
                                       "message": "Sahifa o'qilmadi."})
            continue
        report["pages_read"] += 1
        if parsed.is_word_list and parsed.words:
            saved = _save_page(db, book, page_number, parsed, hint, replace, report)
            report["words_added"] += saved["words_added"]
            report["duplicates"] += len(saved["duplicates"])
            report["rejected"] += len(saved["rejected"])
            report["per_page"][-1].update({"status": "ok",
                                              "unit": "" if saved.get("unit_number") is None
                                                      else str(saved["unit_number"]),
                                              "words_found": saved["words_found"],
                                              "words_added": saved["words_added"],
                                              "duplicates": saved["duplicates"],
                                              "rejected": saved["rejected"]})
        else:
            report["rejected"] += len(parsed.rejected)
            report["per_page"].append({"page": page_number, "status": "not_a_word_list",
                                       "unit": hint.get("unit_number") if hint else None,
                                       "words_found": 0, "words_added": 0,
                                       "rejected": parsed.rejected})
        _mark_scanned(db, book, page_number, report)
        if progress_cb:
            progress_cb(0.15 + 0.7 * (index + 1) / max(1, len(targets)), "vocabulary")

    # Pages that were not read this run still deserve their unit row, otherwise the Lug'at
    # hides a unit until every one of its pages has been re-read.
    sync_units_from_words(db, book)

    # ---- 3. Uzbek translations for whatever has none ----
    # A whole book has hundreds of entries, so this walks the missing ones in chunks instead
    # of one giant request: the same idempotent pass, repeated until nothing is left (or the
    # budget is spent, in which case the UI's "translate missing" finishes the rest).
    if translate:
        stats: dict[str, Any] = {}
        for _ in range(settings.vocab_translate_max_rounds):
            pending = vocab_translate.missing_translations(db, book.id,
                                                           limit=vocab_translate.BATCH_SIZE * 8)
            if not pending:
                break
            round_stats = vocab_translate.translate_words(db, book.user_id, pending)
            stats = round_stats or stats
            report["translated"] += round_stats.get("translated", 0)
            if not round_stats.get("translated") or round_stats.get("error"):
                break
        if stats.get("error"):
            # The provider's own message, not a generic sentence: "AI sozlanmagan yoki javob
            # bermadi" was shown even when the AI was configured and had returned an error.
            report["warnings"].append({
                "page": 0, "code": f"VOCABULARY_TRANSLATION_{stats['error']}",
                "message_uz": (stats.get("error_uz")
                               or f"Tarjima bajarilmadi ({stats['error']}); so'zlar «tarjimasiz» qoldi.")})
            report["translation_error"] = stats.get("error_uz", "")
    if progress_cb:
        progress_cb(1.0, "vocabulary")

    log.info("vocabulary extraction for %s: %s units, %s words, %s rejected, %s translated",
             book.id, report["units"], report["words_added"], report["rejected"],
             report["translated"])
    return report


def _mark_scanned(db: Session, book: Book, page_number: int, report: dict[str, Any]) -> None:
    """Record the page as read, retrying a dropped connection; never lose the words over it."""
    for attempt in range(3):
        try:
            # Called through the module so a test (or a future wrapper) can intercept the
            # stamp without having to patch this module's import as well.
            vision_vocabulary.mark_scanned(db, book, page_number)
            if attempt:
                # The words are safe and the stamp needed a retry: say so, so a client log
                # can tell this apart from a page that was never touched.
                report["stamp_retried"] = True
            return
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            if not is_transient_db_error(exc) or attempt == 2:
                log.warning("vocabulary extraction: page %s stamp failed: %s", page_number, exc)
                report["warnings"].append({
                    "page": page_number, "code": "VOCABULARY_STAMP_FAILED",
                    "message_uz": f"{page_number}-sahifa «o'qildi» deb belgilanmadi; qayta urinishda takrorlanadi."})
                return
            time.sleep(0.5 * (attempt + 1))


def _save_page(db: Session, book: Book, page_number: int, parsed, hint, replace: bool,
               report: dict[str, Any]) -> dict[str, Any]:
    """Write one page's words, retrying on a fresh connection if the pooled one died.

    The model call is already paid for, so losing its answer to a recycled socket is a real
    loss. ``save_words`` is idempotent for the same page (same terms, same unit), so the write
    can simply be repeated; a non-connection error is returned as-is.
    """
    report["per_page"].append({"page": page_number, "status": "pending", "unit": None,
                               "words_found": 0, "words_added": 0})
    for attempt in range(3):
        try:
            return save_words(db, book, page_number, parsed, unit_hint=hint, replace=replace)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            if not is_transient_db_error(exc) or attempt == 2:
                log.warning("vocabulary extraction: page %s could not be saved: %s", page_number, exc)
                return {"words_added": 0, "words_found": len(parsed.words), "duplicates": [],
                        "rejected": parsed.rejected, "unit_number": None}
            time.sleep(0.5 * (attempt + 1))
    return {"words_added": 0, "words_found": 0, "duplicates": [], "rejected": [],
            "unit_number": None}


def save_span(db: Session, book: Book, span) -> VocabularyUnit:
    """Create/update the unit row for one detected span."""
    from app.services.ai.vision_vocabulary import upsert_unit

    unit = upsert_unit(db, book, span.number, title=span.title,
                       page_start=span.page_start, page_end=span.page_end,
                       confidence=span.confidence)
    unit.page_start = span.page_start or unit.page_start
    unit.page_end = span.page_end or unit.page_end
    return unit


def sync_units_from_words(db: Session, book: Book) -> int:
    """Make sure every unit that owns a word has a page range covering it."""
    created = 0
    units = list(db.scalars(select(VocabularyUnit).where(VocabularyUnit.book_id == book.id)).all())
    by_id = {unit.id: unit for unit in units}
    for word in db.scalars(select(VocabularyWord).where(VocabularyWord.book_id == book.id)).all():
        unit = by_id.get(word.unit_id)
        if unit is None:
            continue
        page = word.page_number or 0
        if unit.page_start == 0 or (page and page < unit.page_start):
            unit.page_start = page
        if page > unit.page_end:
            unit.page_end = page
    db.commit()
    return created
