"""Background task execution.

- `inline` (default): ThreadPoolExecutor inside the API process. Survives everywhere
  (sandbox, small VPS). Jobs live in the processing_jobs table, so the UI tracks them.
- `celery`: real distributed queue (REDIS_URL + celery worker). Same task signature.
- `sync`: execute during the request for short serverless jobs. Subject to request timeouts.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Book, ProcessingJob

log = logging.getLogger("lingora.tasks")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lingora-job")
        return _executor


def _run_pipeline_job(book_id: str, user_id: str) -> None:
    """Own DB session — runs in a worker thread."""
    from app.services.pipeline import Pipeline

    db = SessionLocal()
    try:
        job = db.scalar(select(ProcessingJob).where(
            ProcessingJob.book_id == book_id).order_by(ProcessingJob.created_at.desc()).limit(1))
        if not job:
            job = ProcessingJob(book_id=book_id, user_id=user_id, status="running")
            db.add(job)
            db.commit()
        job.status = "running"
        job.stage_label_uz = "Boshlanmoqda..."
        db.commit()
        Pipeline(db, job).run()
    except Exception:
        log.exception("Job for book %s crashed", book_id)
        try:
            db.rollback()
            job = db.scalar(select(ProcessingJob).where(
                ProcessingJob.book_id == book_id).order_by(ProcessingJob.created_at.desc()).limit(1))
            if job and job.status in ("queued", "running"):
                job.status = "failed"
                job.error_code = "PIPELINE_ERROR"
                job.error_message = "Kitobni tahlil qilishda xatolik yuz berdi. Qayta urinib ko'ring."
                job.finished_at = datetime.now(timezone.utc)
            book = db.get(Book, book_id)
            if book and book.status in ("uploaded", "processing"):
                book.status = "failed"
            db.commit()
        except Exception:
            log.exception("Could not record failure for book %s", book_id)
    finally:
        db.close()


def enqueue_book_analysis(book_id: str, user_id: str) -> None:
    if settings.task_backend == "sync":
        _run_pipeline_job(book_id, user_id)
        return
    if settings.task_backend == "celery" and settings.redis_url:
        from app.tasks.celery_app import analyze_book  # optional module

        analyze_book.delay(book_id, user_id)
        return
    _get_executor().submit(_run_pipeline_job, book_id, user_id)


def recover_stuck_jobs() -> None:
    """On API startup: jobs marked running but orphaned (process restart) are marked failed
    so users can re-analyze. Honest state, no silent hangs."""
    db = SessionLocal()
    try:
        stuck = db.scalars(select(ProcessingJob).where(ProcessingJob.status.in_(["queued", "running"]))).all()
        for job in stuck:
            job.status = "failed"
            job.error_code = "INTERRUPTED"
            job.error_message = "Server qayta ishga tushgan — tahlil to'xtagan. 'Qayta tahlil' tugmasini bosing."
            job.finished_at = datetime.now(timezone.utc)
            book = db.get(Book, job.book_id)
            if book and book.status in ("processing", "uploaded"):
                book.status = "failed"
        db.commit()
    finally:
        db.close()
