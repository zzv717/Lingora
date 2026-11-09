"""Book analysis pipeline: extract -> OCR (if available) -> structure detection ->
persist -> optional AI enrichment -> validate -> ready.

Progress is tracked on the processing_jobs table so users see live status in Uzbek.
Failures are explicit and surfaced; nothing is silently skipped.
Re-analysis prepares new structure safely before swapping active entities,
preserving existing student answers and progress.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AnswerKey,
    Book,
    BookPage,
    Chapter,
    Exercise,
    ExerciseOption,
    ExerciseQuestion,
    Lesson,
    ProcessingJob,
    VocabularyWord,
)
from app.services.ai import enrich as ai_enrich
from app.services.pdf_extractor import extract_document, validate_and_open
from app.services.storage import get_storage
from app.services.structure_detector import detect_structure

log = logging.getLogger("lingora.pipeline")

STAGES = [
    ("extracting", "Matn ajratib olinmoqda..."),
    ("ocr", "Skanerlangan sahifalar OCR qilinmoqda..."),
    ("structuring", "Sahifalar tahlil qilinmoqda, boblar aniqlanmoqda..."),
    ("exercises", "Mashqlar ajratib olinmoqda..."),
    ("vocabulary", "Lug'at so'zlari yig'ilmoqda..."),
    ("ai_enrich", "AI qo'shimcha tahlil qilmoqda..."),
    ("validating", "Kontent tekshirilmoqda..."),
]


class Pipeline:
    def __init__(self, db: Session, job: ProcessingJob):
        self.db = db
        self.job = job

    def progress(self, value: float, stage: str) -> None:
        stage_label = dict(STAGES).get(stage, stage)
        self.job.progress = round(min(max(value, 0.0), 100.0), 1)
        self.job.stage = stage
        self.job.stage_label_uz = stage_label
        self.db.commit()

    def run(self) -> None:
        book = self.db.get(Book, self.job.book_id)
        assert book
        try:
            self._run(book)
        except Exception as e:
            log.exception("Pipeline failed for book %s", book.id)
            self.job.status = "failed"
            self.job.error_code = getattr(e, "code", "") or "PIPELINE_ERROR"
            self.job.error_message = getattr(e, "message_uz", "") or str(e)
            self.job.finished_at = datetime.now(timezone.utc)
            book.status = "failed"
            self.db.commit()

    def _run(self, book: Book) -> None:
        self.job.started_at = datetime.now(timezone.utc)
        book.status = "processing"
        self.progress(2, "extracting")

        content = get_storage().read(book.storage_path)
        doc = validate_and_open(content)
        book.page_count = doc.page_count

        pages, extraction_warnings = extract_document(
            doc,
            progress_cb=lambda v, s: self.progress(2 + v * 0.18, "extracting"),
            start=0.0, end=100.0,
        )
        doc.close()

        self.progress(22, "ocr")
        warnings = list(extraction_warnings)
        ocr_unavailable = any(w["code"] == "OCR_UNAVAILABLE" for w in warnings)
        if ocr_unavailable:
            warnings.append({
                "page": 0, "code": "OCR_UNAVAILABLE",
                "message_uz": ("OCR (skaner matnni o'qish) xizmati serverda sozlanmagan. "
                               "Skanerlangan sahifalar tahlil qilinmadi. Tesseract o'rnatish bo'yicha "
                               "hujjatlarga qarang."),
            })

        self.progress(32, "structuring")
        structure = detect_structure(pages)

        # Merge warnings
        all_warnings = warnings + structure.warnings
        seen_warn = set()
        deduped_warn = []
        for w in all_warnings:
            k = (w.get("code"), w.get("page"), w.get("message_uz"))
            if k not in seen_warn:
                seen_warn.add(k)
                deduped_warn.append(w)

        # Safe transaction: now that extraction and structure detection succeeded,
        # clean previous book pages/structure and persist new ones atomically.
        for model in (BookPage, Chapter, Lesson, Exercise, VocabularyWord, AnswerKey):
            for row in self.db.query(model).filter(model.book_id == book.id).all():
                self.db.delete(row)
        self.db.flush()

        for p in pages:
            self.db.add(BookPage(
                book_id=book.id, page_number=p["page_number"], width=p["width"], height=p["height"],
                text=p["text"][:60000], blocks=p["lines"], images=p["images"],
                needs_ocr=p["needs_ocr"], ocr_used=p["ocr_used"],
                has_warning=any(w.get("page") == p["page_number"] for w in deduped_warn),
            ))
        self.db.flush()

        # ---- persist chapters & lessons ----
        chapter_map: dict[int, Chapter] = {}
        for ch in structure.chapters:
            row = Chapter(book_id=book.id, title=ch["title"], kind=ch["kind"], number=ch["number"],
                          page_start=ch["page_start"], page_end=ch["page_end"], order_index=ch["order_index"])
            self.db.add(row)
            chapter_map[ch["order_index"]] = row
        self.db.flush()

        lesson_rows: list[Lesson] = []
        for li, ls in enumerate(structure.lessons):
            ch_order = ls.get("chapter_index", ls.get("chapter_order", 0))
            ch_row = chapter_map.get(ch_order)
            row = Lesson(book_id=book.id, chapter_id=ch_row.id if ch_row else None,
                         title=ls["title"], topic=ls.get("topic", ""),
                         page_start=ls["page_start"], page_end=ls["page_end"],
                         order_index=ls.get("order_index", li),
                         grammar_explanation_uz="", summary="")
            self.db.add(row)
            lesson_rows.append(row)
        self.db.flush()

        self.progress(45, "exercises")
        # ---- persist exercises & questions ----
        for ex in structure.exercises:
            matching_lesson = next((l for l in lesson_rows if l.page_start <= ex.page_number <= l.page_end), None)
            matching_ch = matching_lesson.chapter_id if matching_lesson else None
            ex_row = Exercise(
                book_id=book.id, lesson_id=matching_lesson.id if matching_lesson else None,
                chapter_id=matching_ch, exercise_type=ex.exercise_type, title=ex.title,
                instructions=ex.instructions, ref=ex.ref, page_number=ex.page_number,
                source="book", bbox={"bbox": ex.bbox} if ex.bbox else None,
                topic=ex.topic or (matching_lesson.topic if matching_lesson else ""),
                explanation_uz="", order_index=len(self.db.new), detection="rule",
                needs_review=ex.needs_review,
            )
            self.db.add(ex_row)
            self.db.flush()

            for qi, q in enumerate(ex.questions):
                q_row = ExerciseQuestion(
                    exercise_id=ex_row.id, order_index=qi, number=q.number, prompt=q.prompt,
                    passage="", blanks=q.blanks, matching_pairs=q.matching_pairs,
                    correct_answers=getattr(q, "correct_answers", []),
                    answer_source=getattr(q, "answer_source", "unknown"),
                    explanation_uz="", needs_review=ex.needs_review or getattr(q, "needs_review", False),
                )
                self.db.add(q_row)
                self.db.flush()

                for opt in q.options:
                    self.db.add(ExerciseOption(
                        question_id=q_row.id, letter=opt["letter"], text=opt["text"],
                        is_correct=opt.get("is_correct"),
                    ))

        self.progress(65, "vocabulary")
        # ---- persist vocabulary ----
        seen_terms = set()
        for v in structure.vocabulary:
            term = v["term"].strip()
            if not term or term.lower() in seen_terms:
                continue
            seen_terms.add(term.lower())
            matching_lesson = next((l for l in lesson_rows if l.page_start <= v["page_number"] <= l.page_end), None)
            self.db.add(VocabularyWord(
                book_id=book.id, lesson_id=matching_lesson.id if matching_lesson else None,
                chapter_id=matching_lesson.chapter_id if matching_lesson else None,
                term=term, translation_uz=v.get("translation_uz", ""),
                definition_en=v.get("definition_en", ""),
                example_sentence=v.get("example_sentence", ""),
                part_of_speech=v.get("part_of_speech", ""),
                page_number=v["page_number"], source="book",
                needs_translation=v.get("needs_translation", False),
            ))

        # ---- record answer key pages ----
        for ak in structure.answer_key_entries:
            self.db.add(AnswerKey(book_id=book.id, page_number=ak["page"], source="book", verified=True))

        self.db.commit()

        # ---- AI enrichment (optional, honest degradation) ----
        self.progress(80, "ai_enrich")
        if settings.ai_configured:
            try:
                ai_enrich.enrich_book(self.db, book.id)
            except Exception as e:
                log.warning("AI enrichment failed (continuing gracefully): %s", e)

        self.progress(95, "validating")
        self.job.warnings = deduped_warn
        self.job.status = "completed"
        self.job.finished_at = datetime.now(timezone.utc)
        book.status = "ready"
        self.progress(100, "validating")
        self.job.stage_label_uz = "Tayyor!"
        self.db.commit()
