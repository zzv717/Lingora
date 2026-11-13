"""Conservative guard until analysis versions and answer migration are implemented."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnswerKey, BookPage, Chapter, Exercise, Lesson, VocabularyWord


def has_book_content(db: Session, book_id: str) -> bool:
    return any(db.scalar(select(model.id).where(model.book_id == book_id).limit(1)) is not None
               for model in (BookPage, Chapter, Lesson, Exercise, VocabularyWord, AnswerKey))
