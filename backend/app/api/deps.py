"""FastAPI dependencies: current user from JWT, DB session, ownership helpers."""
from typing import Any

import jwt as pyjwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Book, Profile, Subscription, User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError("UNAUTHORIZED", "Tizimga kirish talab qilinadi.", 401)
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token, "access")
    except pyjwt.ExpiredSignatureError:
        raise ApiError("TOKEN_EXPIRED", "Sessiya muddati tugadi. Qaytadan kiring.", 401)
    except pyjwt.PyJWTError:
        raise ApiError("UNAUTHORIZED", "Yaroqsiz token.", 401)
    user = db.get(User, payload.get("sub", ""))
    if not user or not user.is_active:
        raise ApiError("UNAUTHORIZED", "Foydalanuvchi topilmadi yoki bloklangan.", 401)
    return user


def get_current_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def get_user_plan(db: Session, user_id: str) -> str:
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    return sub.plan if sub else "free"


def owned_book(db: Session, user: User, book_id: str) -> Book:
    """Books are strictly private: any other user's book id is indistinguishable from nonexistent."""
    book = db.get(Book, book_id)
    if not book or book.user_id != user.id:
        raise ApiError("BOOK_NOT_FOUND", "Kitob topilmadi.", 404)
    return book


def json_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}
