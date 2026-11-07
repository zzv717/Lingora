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


def ai_calls_today(db: Session, user_id: str) -> int:
    return int(db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user_id, UsageEvent.day == _today(), UsageEvent.ok.is_(True)
        )
    ) or 0)


def enforce_ai_quota(db: Session, user_id: str, feature: str) -> None:
    plan = get_user_plan(db, user_id)
    limits = settings.plan_limits(plan)
    used = ai_calls_today(db, user_id)
    if limits["ai_calls_per_day"] and used >= limits["ai_calls_per_day"]:
        plan_names = {"free": "Bepul", "pro": "Pro", "premium": "Premium"}
        raise ApiError(
            code="AI_QUOTA_EXCEEDED",
            message_uz=(
                f"Kunlik AI limitiga yetdingiz ({used}/{limits['ai_calls_per_day']}). "
                f"{'{} rejasi'.format(plan_names.get(plan, plan))} limiti har kuni yangilanadi."
            ),
            http_status=429,
            details={"feature": feature, "used": used, "limit": limits["ai_calls_per_day"]},
        )
