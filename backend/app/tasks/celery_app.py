"""Celery worker entrypoint (optional, production). Enable with:
  TASK_BACKEND=celery  REDIS_URL=redis://...
  celery -A app.tasks.celery_app worker --loglevel=info
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery("lingora", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, broker_connection_retry_on_startup=True)


@celery_app.task(name="lingora.analyze_book")
def analyze_book(book_id: str, user_id: str):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import ProcessingJob
    from app.services.pipeline import Pipeline

    db = SessionLocal()
    try:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.book_id == book_id)
                        .order_by(ProcessingJob.created_at.desc()).limit(1))
        if not job:
            job = ProcessingJob(book_id=book_id, user_id=user_id, status="running")
            db.add(job)
            db.commit()
        job.status = "running"
        db.commit()
        Pipeline(db, job).run()
    finally:
        db.close()
