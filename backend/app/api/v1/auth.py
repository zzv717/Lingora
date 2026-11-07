"""Authentication: register, login, refresh rotation, profile, password reset."""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.session import get_db
from app.db.mixins import ensure_utc
from app.models import PasswordReset, Profile, RefreshToken, Subscription, User
from app.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    ForgotPasswordOut,
    LoginIn,
    MeOut,
    OkOut,
    ProfileOut,
    ProfileUpdateIn,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenPair,
)
from fastapi.responses import JSONResponse

log = logging.getLogger("lingora.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(db: Session, user: User, user_agent: str = "") -> TokenPair:
    access = create_access_token(user.id)
    refresh, refresh_hash, expires = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_hash=refresh_hash,
                        expires_at=expires, user_agent=user_agent[:255]))
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=TokenPair, status_code=201)
def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    limit(request, "auth", 20, 60)
    email = data.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise ApiError("EMAIL_TAKEN", "Bu email allaqachon ro'yxatdan o'tgan.", 409)
    user = User(email=email, password_hash=hash_password(data.password), full_name=data.full_name.strip())
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id))
    db.add(Subscription(user_id=user.id, plan="free", status="active"))
    db.commit()
    return _issue_tokens(db, user, request.headers.get("user-agent", ""))


@router.post("/login", response_model=TokenPair)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    limit(request, "auth", 20, 60)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user or not verify_password(data.password, user.password_hash):
        raise ApiError("BAD_CREDENTIALS", "Email yoki parol xato.", 401)
    return _issue_tokens(db, user, request.headers.get("user-agent", ""))


@router.post("/refresh", response_model=TokenPair)
def refresh(data: RefreshIn, request: Request, db: Session = Depends(get_db)):
    limit(request, "auth", 60, 60)
    try:
        payload = decode_token(data.refresh_token, "refresh")
    except Exception:
        raise ApiError("UNAUTHORIZED", "Sessiya yaroqsiz. Qaytadan kiring.", 401)
    stored = db.scalar(select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(data.refresh_token)))
    if not stored or stored.revoked_at or ensure_utc(stored.expires_at) < datetime.now(timezone.utc):
        raise ApiError("UNAUTHORIZED", "Sessiya bekor qilingan. Qaytadan kiring.", 401)
    # rotate: revoke old, issue new pair
    stored.revoked_at = datetime.now(timezone.utc)
    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise ApiError("UNAUTHORIZED", "Foydalanuvchi topilmadi.", 401)
    return _issue_tokens(db, user, request.headers.get("user-agent", ""))


@router.post("/logout", response_model=OkOut)
def logout(data: RefreshIn, db: Session = Depends(get_db)):
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(data.refresh_token)))
    if stored:
        stored.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return OkOut(message_uz="Tizimdan chiqdingiz.")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/me/profile", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
        db.commit()
    return profile


@router.patch("/me/profile", response_model=ProfileOut)
def update_profile(data: ProfileUpdateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
    if data.full_name is not None:
        user.full_name = data.full_name.strip()
    for field in ("theme", "daily_goal_minutes", "vocab_pass_score", "vocabulary_gating",
                  "timezone", "interface_language"):
        val = getattr(data, field)
        if val is not None:
            setattr(profile, field, val)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/change-password", response_model=OkOut)
def change_password(data: ChangePasswordIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(data.current_password, user.password_hash):
        raise ApiError("BAD_PASSWORD", "Joriy parol xato.", 400)
    user.password_hash = hash_password(data.new_password)
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id,
                                                   RefreshToken.revoked_at.is_(None))).all():
        t.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return OkOut(message_uz="Parol yangilandi. Boshqa qurilmalarda sessiya bekor qilindi.")


@router.post("/forgot-password", response_model=ForgotPasswordOut)
def forgot_password(data: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    limit(request, "forgot", 5, 300)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user:
        # Do not reveal whether the email exists.
        return ForgotPasswordOut(delivered=False, reset_link=None,
                                 message_uz="Agar bunday email mavjud bo'lsa, tiklash havolasi yuborildi.")
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(
        user_id=user.id, token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.commit()
    smtp_host = os.environ.get("SMTP_HOST", "")
    if smtp_host:
        # Real SMTP delivery (configured via env); keep implementation dependency-free.
        try:
            _send_reset_email(user.email, token)
            return ForgotPasswordOut(delivered=True, reset_link=None,
                                     message_uz="Parolni tiklash havolasi emailingizga yuborildi.")
        except Exception:
            log.exception("SMTP delivery failed for %s", user.email)
            raise ApiError("SMTP_ERROR", "Email yuborishda xatolik. Keyinroq urinib ko'ring.", 502)
    # Dev mode: no SMTP configured — surface link explicitly (never pretend an email was sent).
    link = f"{os.environ.get('FRONTEND_URL', 'http://localhost:3000')}/reset-password?token={token}"
    log.info("SMTP not configured; reset link for %s: %s", user.email, link)
    return ForgotPasswordOut(delivered=False, reset_link=link,
                             message_uz="SMTP sozlanmagan (dev rejim): havola quyida.")


def _send_reset_email(to: str, token: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    link = f"{os.environ.get('FRONTEND_URL', 'http://localhost:3000')}/reset-password?token={token}"
    msg = MIMEText(
        f"Parolni tiklash uchun havola (1 soat amal qiladi):\n\n{link}\n\n"
        "Agar siz so'rov yubormagan bo'lsangiz, bu xabarni e'tiborsiz qoldiring.",
        "plain", "utf-8")
    msg["Subject"] = "Lingora — parolni tiklash"
    msg["From"] = os.environ.get("SMTP_FROM", "noreply@lingora.app")
    msg["To"] = to
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=20) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


@router.post("/reset-password", response_model=OkOut)
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)):
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(data.token)))
    if not row or row.used_at or ensure_utc(row.expires_at) < datetime.now(timezone.utc):
        raise ApiError("BAD_RESET_TOKEN", "Havola yaroqsiz yoki muddati tugagan.", 400)
    user = db.get(User, row.user_id)
    if not user:
        raise ApiError("BAD_RESET_TOKEN", "Foydalanuvchi topilmadi.", 400)
    user.password_hash = hash_password(data.new_password)
    row.used_at = datetime.now(timezone.utc)
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)).all():
        t.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return OkOut(message_uz="Parol tiklandi. Endi yangi parol bilan kiring.")


@router.delete("/account", response_model=OkOut)
def delete_account(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Full GDPR-style deletion: books, answers, vocabulary, progress — everything cascades."""
    from app.services.storage import get_storage

    from app.models import Book

    books = db.scalars(select(Book).where(Book.user_id == user.id)).all()
    storage = get_storage()
    for b in books:
        if b.storage_path:
            try:
                storage.delete(b.storage_path)
            except Exception:
                log.warning("Could not delete storage object for book %s", b.id)
    db.delete(user)
    db.commit()
    return OkOut(message_uz="Hisob va barcha shaxsiy ma'lumotlar o'chirildi.")
