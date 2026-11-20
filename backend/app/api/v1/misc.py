"""Misc endpoints: health, AI status (public-safe), user plan/usage."""
import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.schemas import PlanOut
from app.services.ai import usage as usage_service
from app.services.pdf_extractor import ocr_available

router = APIRouter(tags=["misc"])


def _build_revision() -> str:
    """The commit this process was built from, when the host provides it.

    The question "is the fix live yet?" came up repeatedly and could not be answered from
    the UI, so the running build identifies itself instead of being guessed from screenshots.
    """
    for name in ("VERCEL_GIT_COMMIT_SHA", "GIT_COMMIT", "SOURCE_VERSION", "GITHUB_SHA",
                 "CF_PAGES_COMMIT_SHA", "COMMIT_SHA"):
        value = os.environ.get(name, "").strip()
        if value:
            return value[:12]
    return ""


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.env,
            "revision": _build_revision()}


@router.get("/ai/status")
def ai_status():
    """Safe status: never leaks the key. Tells the frontend which features are available."""
    return {
        "ai_configured": settings.ai_configured,
        "provider": settings.ai_provider if settings.ai_configured else "none",
        "ocr_available": ocr_available(),
    }


@router.get("/me/plan", response_model=PlanOut)
def my_plan(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    plan = usage_service.get_user_plan(db, user.id)
    limits = settings.plan_limits(plan)
    return PlanOut(
        plan=plan, status="active",
        max_books=limits["max_books"],
        ai_calls_per_day=limits["ai_calls_per_day"],
        ai_calls_today=usage_service.ai_calls_today(db, user.id),
        ai_configured=settings.ai_configured,
        ai_provider=settings.ai_provider,
    )
