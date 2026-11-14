"""AI usage accounting: per-user daily call limits, token totals, cost estimates."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.models import Subscription, UsageEvent

# Rough public pricing (USD per 1M tokens in/out) — used only for cost monitoring, not billing.
COST_TABLE = {
    "default": (0.15, 0.60),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.5, 10.0),
    "claude-3-5-sonnet-latest": (3.0, 15.0),
    "claude-3-5-haiku-latest": (0.8, 4.0),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = COST_TABLE.get(model, COST_TABLE["default"])
    return round((tokens_in * pin + tokens_out * pout) / 1_000_000, 6)


def get_user_plan(db: Session, user_id: str) -> str:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    return sub.plan if sub else "free"


def record_usage(db: Session, user_id: str, feature: str, provider: str, model: str,
                 tokens_in: int, tokens_out: int, ok: bool = True) -> None:
    db.add(UsageEvent(
        user_id=user_id, day=_today(), feature=feature, provider=provider, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_estimate_usd=estimate_cost(model, tokens_in, tokens_out), ok=ok,
    ))
    db.commit()


# Heavy bulk features have their own daily limit (enforce_feature_quota) and must not eat the
# general per-plan call allowance that tutor/grading/review depend on.
SEPARATE_QUOTA_FEATURES = ("vision_exercises",)


def ai_calls_today(db: Session, user_id: str) -> int:
    return int(db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user_id, UsageEvent.day == _today(), UsageEvent.ok.is_(True),
            UsageEvent.feature.notin_(SEPARATE_QUOTA_FEATURES),
        )
    ) or 0)


def ai_tokens_today(db: Session, user_id: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0)).where(
            UsageEvent.user_id == user_id, UsageEvent.day == _today(), UsageEvent.ok.is_(True)
        )
    )
    return int(total or 0)


def enforce_ai_quota(db: Session, user_id: str, feature: str) -> None:
    plan = get_user_plan(db, user_id)
    limits = settings.plan_limits(plan)
    used_calls = ai_calls_today(db, user_id)
    if limits["ai_calls_per_day"] and used_calls >= limits["ai_calls_per_day"]:
        plan_names = {"free": "Bepul", "pro": "Pro", "premium": "Premium"}
        raise ApiError(
            code="AI_QUOTA_EXCEEDED",
            message_uz=(
                f"Kunlik AI so'rovlar limitiga yetdingiz ({used_calls}/{limits['ai_calls_per_day']}). "
                f"{'{} rejasi'.format(plan_names.get(plan, plan))} limiti har kuni yangilanadi."
            ),
            http_status=429,
            details={"feature": feature, "used": used_calls, "limit": limits["ai_calls_per_day"]},
        )

    _enforce_token_quota(db, user_id, feature)


def _enforce_token_quota(db: Session, user_id: str, feature: str) -> None:
    # Daily token limit (if configured, e.g. > 0)
    if settings.ai_daily_token_limit > 0:
        used_tokens = ai_tokens_today(db, user_id)
        if used_tokens >= settings.ai_daily_token_limit:
            raise ApiError(
                code="AI_TOKEN_QUOTA_EXCEEDED",
                message_uz=(
                    f"Kunlik AI token limitiga yetdingiz ({used_tokens}/{settings.ai_daily_token_limit}). "
                    "Limit ertaga yangilanadi."
                ),
                http_status=429,
                details={"feature": feature, "used_tokens": used_tokens, "limit_tokens": settings.ai_daily_token_limit},
            )


def feature_calls_today(db: Session, user_id: str, feature: str) -> int:
    return int(db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user_id, UsageEvent.day == _today(),
            UsageEvent.feature == feature, UsageEvent.ok.is_(True)
        )
    ) or 0)


def enforce_feature_quota(db: Session, user_id: str, feature: str, daily_limit: int) -> None:
    """Separate daily limit for one heavy feature (e.g. whole-book vision scanning).

    The general per-plan call limit is intentionally not applied here: scanning a 100-page book would
    exhaust a 20-calls-per-day plan limit after 20 pages. daily_limit <= 0 means unlimited.
    The global daily token limit (if configured) still applies.
    """
    used = feature_calls_today(db, user_id, feature)
    if daily_limit > 0 and used >= daily_limit:
        raise ApiError(
            code="AI_FEATURE_QUOTA_EXCEEDED",
            message_uz=f"Bugungi sahifa tahlili limitiga yetdingiz ({used}/{daily_limit}). Limit ertaga yangilanadi.",
            http_status=429,
            details={"feature": feature, "used": used, "limit": daily_limit},
        )
    _enforce_token_quota(db, user_id, feature)
