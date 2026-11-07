"""Book analysis pipeline: extract -> OCR (if available) -> structure detection ->
persist -> optional AI enrichment -> validate -> ready.

Progress is tracked on the processing_jobs table so users see live status in Uzbek.
Failures are explicit and surfaced; nothing is silently skipped.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

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
        # wipe any previous analysis (re-analyze)
        for model in (BookPage, Chapter, Lesson, Exercise, VocabularyWord, AnswerKey):
            for row in self.db.query(model).filter(model.book_id == book.id).all():
                self.db.delete(row)
        self.db.commit()

        self.job.started_at = datetime.now(timezone.utc)
        book.status = "processing"
        self.progress(2, "extracting")

        content = get_storage().read(book.storage_path)
        doc = validate_and_open(content)
        book.page_count = doc.page_count

        pages, warnings = extract_document(
            doc,
            progress_cb=lambda v, s: self.progress(2 + v * 0.18, "extracting"),
            start=0.0, end=100.0,
        )
        doc.close()

        self.progress(22, "ocr")
        ocr_unavailable = any(w["code"] == "OCR_UNAVAILABLE" for w in warnings)
        if ocr_unavailable:
            warnings.append({
                "page": 0, "code": "OCR_UNAVAILABLE",
                "message_uz": ("OCR (skaner matnni o'qish) xizmati serverda sozlanmagan. "
                               "Skanerlangan sahifalar tahlil qilinmadi. Tesseract o'rnatish bo'yicha "
                               "README.deploy.md ga qarang."),
            })

        for p in pages:
            self.db.add(BookPage(
                book_id=book.id, page_number=p["page_number"], width=p["width"], height=p["height"],
                text=p["text"][:60000], blocks=p["lines"], images=p["images"],
                needs_ocr=p["needs_ocr"], ocr_used=p["ocr_used"],
                has_warning=any(w.get("page") == p["page_number"] for w in warnings),
            ))
        self.db.commit()

        self.progress(32, "structuring")
        structure = detect_structure(pages)

        # ---- persist chapters & lessons ----
        chapter_map: dict[int, Chapter] = {}
        for ch in structure.chapters:
            row = Chapter(book_id=book.id, title=ch["title"], kind=ch["kind"], number=ch["number"],
                          page_start=ch["page_start"], page_end=ch["page_end"], order_index=ch["order_index"])
            self.db.add(row)
            chapter_map[ch["order_index"]] = row
        self.db.flush()

        lesson_rows: list[Lesson] = []
        for li, l in enumerate(structure.lessons):
            ch = chapter_map.get(l["chapter_index"])
            row = Lesson(book_id=book.id, chapter_id=ch.id if ch else None, title=l["title"],
                         topic=l.get("topic", ""), page_start=l["page_start"], page_end=l["page_end"],
                         order_index=li, summary="")
            self.db.add(row)
            lesson_rows.append(row)
        if not lesson_rows:
            ch0 = list(chapter_map.values())[0]
            row = Lesson(book_id=book.id, chapter_id=ch0.id, title=book.title,
                         page_start=1, page_end=book.page_count, order_index=0, topic="")
            self.db.add(row)
            lesson_rows.append(row)
        self.db.flush()

        # ---- persist exercises ----
        def lesson_for_page(pnum: int) -> Lesson:
            for l in lesson_rows:
                if l.page_start <= pnum <= l.page_end:
                    return l
            return lesson_rows[0]

        self.progress(45, "exercises")
        for ei, ex in enumerate(structure.exercises):
            lesson = lesson_for_page(ex.page_number)
            ex_row = Exercise(
                book_id=book.id, lesson_id=lesson.id, chapter_id=lesson.chapter_id,
                exercise_type=ex.exercise_type, title=ex.title, ref=ex.ref,
                instructions=ex.instructions, page_number=ex.page_number,
                bbox={"x0": ex.bbox[0], "y0": ex.bbox[1], "x1": ex.bbox[2], "y1": ex.bbox[3]} if ex.bbox else None,
                topic=ex.topic, order_index=ei, detection="rule",
                needs_review=ex.needs_review,
            )
            self.db.add(ex_row)
            self.db.flush()
            for qi, q in enumerate(ex.questions):
                q_row = ExerciseQuestion(
                    exercise_id=ex_row.id, order_index=qi, number=q.number, prompt=q.prompt,
                    blanks=[{**b, "bbox": list(b["bbox"]) if b.get("bbox") else None} for b in q.blanks],
                    matching_pairs=q.matching_pairs,
                    correct_answers=q.correct_answers,
                    answer_source=q.answer_source,
                    needs_review=(q.answer_source == "unknown"),
                )
                self.db.add(q_row)
                self.db.flush()
                for o in q.options:
                    self.db.add(ExerciseOption(question_id=q_row.id, letter=o["letter"], text=o["text"]))
        self.db.flush()

        # lesson summaries (book text excerpts) for AI context
        page_text_by_num = {p["page_number"]: p["text"] for p in pages}
        for l in lesson_rows:
            texts = [page_text_by_num.get(n, "") for n in range(l.page_start, min(l.page_end, l.page_start + 6) + 1)]
            l.summary = " ".join(t for t in texts if t)[:4000]

        # ---- vocabulary ----
        self.progress(65, "vocabulary")
        vocab_rows: list[VocabularyWord] = []
        seen_terms: set[str] = set()
        for v in structure.vocabulary:
            term = v["term"].strip().strip(".,;:")
            if not term or len(term) < 2 or term.lower() in seen_terms:
                continue
            seen_terms.add(term.lower())
            lesson = lesson_for_page(v["page_number"])
            vocab_rows.append(VocabularyWord(
                book_id=book.id, lesson_id=lesson.id, chapter_id=lesson.chapter_id,
                term=term[:255], translation_uz=(v.get("translation_uz") or "")[:512],
                page_number=v["page_number"],
                needs_translation=not (v.get("translation_uz") or "").strip(),
            ))
        self.db.add_all(vocab_rows)
        self.db.commit()

        # ---- answer keys ----
        if structure.answer_key_entries:
            raw_pages = sorted({e["page"] for e in structure.answer_key_entries})
            self.db.add(AnswerKey(
                book_id=book.id, page_number=raw_pages[0], source="book", verified=True,
                raw_text="", entries=[{k: e[k] for k in ("exercise_ref", "question_number", "answers", "page")}
                                      for e in structure.answer_key_entries],
            ))
        self.db.commit()

        # ---- optional AI enrichment ----
        self.progress(75, "ai_enrich")
        if settings.ai_configured:
            try:
                n_answers = ai_enrich.enrich_answer_gaps(self.db, self.job.user_id, book.title, structure)
                if n_answers:
                    self._persist_ai_answers(book, structure)
                ai_enrich.enrich_grammar_explanations(self.db, self.job.user_id, book.title, lesson_rows)
                untranslated = [v for v in vocab_rows if v.needs_translation]
                if untranslated:
                    ai_enrich.enrich_vocabulary_translations(self.db, self.job.user_id, untranslated)
                structure.warnings.append({
                    "page": 0, "code": "AI_ENRICHED",
                    "message_uz": f"AI tahlili qo'shildi: {n_answers} ta savolga javob, "
                                  f"{len(lesson_rows)} ta dars tushuntirishi tayyorlandi.",
                })
            except Exception as e:
                log.warning("AI enrichment failed (kept rule-based result): %s", e)
                structure.warnings.append({
                    "page": 0, "code": "AI_ENRICH_SKIPPED",
                    "message_uz": f"AI boyitmasi bajarilmadi ({getattr(e, 'message_uz', e)}). "
                                  "Kitob deterministik tahlil asosida tayyor.",
                })
        else:
            untranslated = [v for v in vocab_rows if v.needs_translation]
            if untranslated:
                structure.warnings.append({
                    "page": 0, "code": "VOCAB_NEEDS_AI",
                    "message_uz": f"{len(untranslated)} ta so'z tarjimasisiz qoldi — avtomatik tarjima uchun "
                                  "AI provayder sozlanishi kerak (AI_PROVIDER, AI_API_KEY, AI_MODEL).",
                })

        # ---- validate & finish ----
        self.progress(92, "validating")
        n_questions = sum(len(ex.questions) for ex in structure.exercises)
        no_answer_count = 0
        for ex in structure.exercises:
            for q in ex.questions:
                if not q.correct_answers and q.answer_source == "unknown":
                    no_answer_count += 1
        if no_answer_count:
            structure.warnings.append({
                "page": 0, "code": "ANSWERS_UNKNOWN",
                "message_uz": (f"{no_answer_count}/{n_questions} savol uchun kitobda javob topilmadi. "
                               "Bunday savollar AI yoki deterministik qoidalar bilan baholanadi; "
                               "aniqlashtirib bo'lmasa 'tekshiruv kerak' belgilanadi."),
            })

        # combine extraction warnings (OCR etc.) with structure warnings, dedupe by code+page
        seen: set[tuple] = set()
        combined: list[dict] = []
        for w in warnings + structure.warnings:
            key = (w.get("code"), w.get("page"), w.get("message_uz"))
            if key not in seen:
                seen.add(key)
                combined.append(w)
        self.job.warnings = combined[:100]
        book.status = "ready"
        self.job.status = "completed"
        self.job.progress = 100.0
        self.job.stage = "ready"
        self.job.stage_label_uz = "O'qishga tayyor!"
        self.job.finished_at = datetime.now(timezone.utc)
        self.db.commit()

    def _persist_ai_answers(self, book: Book, structure) -> None:
        """AI-sourced answers were applied to the DetectedStructure; sync them into DB questions."""
        from app.services.structure_detector import DetectedStructure

        assert isinstance(structure, DetectedStructure)
        q_rows = self.db.query(ExerciseQuestion).join(Exercise).filter(
            Exercise.book_id == book.id).all()
        by_key = {}
        for ex in structure.exercises:
            for q in ex.questions:
                by_key[(ex.page_number, q.number or str(q.order_index + 1))] = q
        for q_row in q_rows:
            det = by_key.get((q_row.exercise.page_number, q_row.number or str(q_row.order_index + 1)))
            if det and det.correct_answers and not q_row.correct_answers:
                q_row.correct_answers = det.correct_answers
                q_row.answer_source = "ai"
                q_row.needs_review = False
        self.db.commit()
