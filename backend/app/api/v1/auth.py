"""Authentication: register, login, refresh rotation, profile, password reset."""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
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

log = logging.getLogger("lingora.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "lingora_refresh"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    is_prod = settings.env == "prod"
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.env == "prod",
        samesite="lax",
        path="/",
    )


def _issue_tokens(db: Session, user: User, user_agent: str = "", response: Response | None = None) -> TokenPair:
    access = create_access_token(user.id)
    refresh, refresh_hash, expires = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_hash=refresh_hash,
                        expires_at=expires, user_agent=user_agent[:255]))
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    if response is not None:
        _set_refresh_cookie(response, refresh)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=TokenPair, status_code=201)
def register(data: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
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
    return _issue_tokens(db, user, request.headers.get("user-agent", ""), response=response)


@router.post("/login", response_model=TokenPair)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request, "auth", 20, 60)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user or not verify_password(data.password, user.password_hash):
        raise ApiError("BAD_CREDENTIALS", "Email yoki parol xato.", 401)
    return _issue_tokens(db, user, request.headers.get("user-agent", ""), response=response)


@router.post("/refresh", response_model=TokenPair)
def refresh(request: Request, response: Response, data: RefreshIn | None = None, db: Session = Depends(get_db)):
    """Refresh token rotation with atomic consumption (anti race-condition / single-use guarantee).
    Accepts token in JSON body or in HttpOnly cookie (cookie takes fallback)."""
    limit(request, "auth", 60, 60)
    token_str = (data.refresh_token if data and data.refresh_token else "") or request.cookies.get(REFRESH_COOKIE_NAME, "")
    if not token_str:
        raise ApiError("UNAUTHORIZED", "Refresh token taqdim etilmadi.", 401)

    try:
        payload = decode_token(token_str, "refresh")
    except Exception:
        raise ApiError("UNAUTHORIZED", "Sessiya yaroqsiz. Qaytadan kiring.", 401)

    t_hash = hash_token(token_str)
    now = datetime.now(timezone.utc)

    # Atomic conditional update: only 1 concurrent caller can transition revoked_at from None -> now
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == t_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
    )
    result = db.execute(stmt)
    db.commit()

    if result.rowcount == 0:
        # Either nonexistent, already revoked (replay attempt), or expired!
        # If it was already revoked, we log warning (token reuse indicator)
        log.warning("Refresh token replay or invalid token rejected for sub=%s", payload.get("sub"))
        raise ApiError("UNAUTHORIZED", "Sessiya bekor qilingan yoki muddati tugagan. Qaytadan kiring.", 401)

    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise ApiError("UNAUTHORIZED", "Foydalanuvchi topilmadi.", 401)

    return _issue_tokens(db, user, request.headers.get("user-agent", ""), response=response)


@router.post("/logout", response_model=OkOut)
def logout(request: Request, response: Response, data: RefreshIn | None = None, db: Session = Depends(get_db)):
    token_str = (data.refresh_token if data and data.refresh_token else "") or request.cookies.get(REFRESH_COOKIE_NAME, "")
    if token_str:
        stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token_str)))
        if stored and not stored.revoked_at:
            stored.revoked_at = datetime.now(timezone.utc)
            db.commit()
    _clear_refresh_cookie(response)
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

    # Invalidate any existing unused reset tokens for this user first
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .values(used_at=datetime.now(timezone.utc))
    )

    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(
        user_id=user.id, token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.commit()

    smtp_host = settings.smtp_host or os.environ.get("SMTP_HOST", "")
    if smtp_host:
        try:
            _send_reset_email(user.email, token)
            return ForgotPasswordOut(delivered=True, reset_link=None,
                                     message_uz="Parolni tiklash havolasi emailingizga yuborildi.")
        except Exception:
            log.exception("SMTP delivery failed for email")
            raise ApiError("SMTP_ERROR", "Email yuborishda xatolik. Keyinroq urinib ko'ring.", 502)

    # In production, NEVER expose the token or reset link in the response or logs!
    if settings.env == "prod":
        log.warning("Password reset requested in prod but SMTP_HOST is not configured.")
        return ForgotPasswordOut(
            delivered=False,
            reset_link=None,
            message_uz="Email xizmati sozlanmaganligi sababli havola yuborilmadi. Administratorga murojaat qiling.",
        )

    # Dev/test mode: surface link explicitly for local development/testing without SMTP
    frontend = settings.frontend_url or os.environ.get("FRONTEND_URL", "http://localhost:3000")
    link = f"{frontend}/reset-password?token={token}"
    return ForgotPasswordOut(delivered=False, reset_link=link,
                             message_uz="SMTP sozlanmagan (dev rejim): havola quyida.")


def _send_reset_email(to: str, token: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    frontend = settings.frontend_url or os.environ.get("FRONTEND_URL", "http://localhost:3000")
    link = f"{frontend}/reset-password?token={token}"
    msg = MIMEText(
        f"Parolni tiklash uchun havola (1 soat amal qiladi):\n\n{link}\n\n"
        "Agar siz so'rov yubormagan bo'lsangiz, bu xabarni e'tiborsiz qoldiring.",
        "plain", "utf-8")
    msg["Subject"] = "Lingora — parolni tiklash"
    msg["From"] = settings.smtp_from or os.environ.get("SMTP_FROM", "noreply@lingora.app")
    msg["To"] = to

    port = settings.smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    host = settings.smtp_host or os.environ.get("SMTP_HOST", "")
    user = settings.smtp_user or os.environ.get("SMTP_USER", "")
    password = settings.smtp_password or os.environ.get("SMTP_PASSWORD", "")

    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls()
        if user and password:
            s.login(user, password)
        s.send_message(msg)


@router.post("/reset-password", response_model=OkOut)
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)):
    t_hash = hash_token(data.token)
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == t_hash))
    if not row or row.used_at or ensure_utc(row.expires_at) < datetime.now(timezone.utc):
        raise ApiError("BAD_RESET_TOKEN", "Havola yaroqsiz yoki muddati tugagan.", 400)
    user = db.get(User, row.user_id)
    if not user:
        raise ApiError("BAD_RESET_TOKEN", "Foydalanuvchi topilmadi.", 400)

    # Invalidate token atomically
    row.used_at = datetime.now(timezone.utc)
    user.password_hash = hash_password(data.new_password)
    # Revoke all existing refresh sessions for this user
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)).all():
        t.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return OkOut(message_uz="Parol tiklandi. Endi yangi parol bilan kiring.")


@router.delete("/account", response_model=OkOut)
def delete_account(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Full GDPR-style deletion: books, answers, vocabulary, progress — everything cascades.
    Storage is verified before DB commits deletion."""
    from app.services.storage import get_storage, direct_upload_token_active
    from app.models import Book

    books = db.scalars(select(Book).where(Book.user_id == user.id)).all()
    if any(direct_upload_token_active(b) for b in books):
        raise ApiError("UPLOAD_ACTIVE", "Hisobni o'chirish uchun oxirgi yuklashdan keyin 2 soat kuting.", 409)
    storage = get_storage()
    for b in books:
        if b.storage_path:
            storage.delete(b.storage_path)

    db.delete(user)
    db.commit()
    return OkOut(message_uz="Hisob va barcha shaxsiy ma'lumotlar o'chirildi.")
