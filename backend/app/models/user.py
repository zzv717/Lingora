"""User, profile, refresh sessions and subscription models."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mixins import Timestamps, UuidPk, new_uuid
from app.db.session import Base


class User(Base, UuidPk, Timestamps):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    subscription: Mapped["Subscription"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Profile(Base, UuidPk, Timestamps):
    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    interface_language: Mapped[str] = mapped_column(String(8), default="uz", nullable=False)
    learning_language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    explanation_language: Mapped[str] = mapped_column(String(8), default="uz", nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="system", nullable=False)  # light|dark|system
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    vocab_pass_score: Mapped[int] = mapped_column(Integer, default=80, nullable=False)  # 0-100
    vocabulary_gating: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent", nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class RefreshToken(Base, UuidPk):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # sha256
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class PasswordReset(Base, UuidPk):
    __tablename__ = "password_resets"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class Subscription(Base, UuidPk, Timestamps):
    """Plan record. MVP ships with the free plan only; payment providers plug in later
    by writing provider refs here — no fake payments are implemented."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_subscription_user"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan: Mapped[str] = mapped_column(String(16), default="free", nullable=False)  # free|pro|premium
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active|canceled|past_due
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    payment_provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="subscription")
