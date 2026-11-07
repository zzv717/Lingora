"""Misc endpoints: health, AI status (public-safe), user plan/usage."""
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


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.env}


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
