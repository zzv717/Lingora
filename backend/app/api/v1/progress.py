"""Progress dashboard, heartbeats, smart revision sessions."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_profile, get_current_user
from app.db.session import get_db
from app.models import Profile, RevisionSession, User
from app.schemas import DashboardOut
from app.services import revision as revision_service
from app.services.progress_service import dashboard, heartbeat, topic_breakdown

router = APIRouter(tags=["progress"])


@router.get("/progress/dashboard", response_model=DashboardOut)
def progress_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user),
                       profile: Profile = Depends(get_current_profile)):
    return dashboard(db, user.id, daily_goal_minutes=profile.daily_goal_minutes)


class HeartbeatIn(BaseModel):
    seconds: int = 0
    lesson_id: str | None = None
    page: int | None = None


@router.post("/progress/heartbeat")
def heartbeat_endpoint(data: HeartbeatIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    heartbeat(db, user.id, data.seconds, data.lesson_id, data.page)
    return {"ok": True}


@router.get("/progress/topics")
def progress_topics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    weak, strong = topic_breakdown(db, user.id, min_attempts=1)
    return {"weak": weak, "strong": strong}


@router.post("/revision/sessions", status_code=201)
def create_revision(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = revision_service.build_revision(db, user.id)
    if not session:
        return {"created": False,
                "message_uz": "Hozircha takrorlash kerak bo'lgan material topilmadi. "
                              "Avval mashqlar va lug'at testlarida qatnashing — keyin tizim "
                              "shaxsiy takrorlash seansini tuzadi."}
    return {"created": True, "session_id": session.id, "focus": session.focus,
            "items": [{"item_id": str(i), "item_type": it["item_type"],
                       "payload": it["payload"], "word_id": it.get("word_id"),
                       "question_id": it.get("question_id")}
                      for i, it in enumerate(session.items)]}


class RevisionResultIn(BaseModel):
    results: list[dict]


@router.post("/revision/sessions/{session_id}/complete")
def complete_revision(session_id: str, data: RevisionResultIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    session = db.get(RevisionSession, session_id)
    if not session or session.user_id != user.id:
        return {"ok": False, "message_uz": "Seans topilmadi."}
    session = revision_service.complete_revision(db, session, data.results)
    return {"ok": True, "score": session.score, "status": session.status}
