"""Lingora API entrypoint.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import ApiError, install_error_handlers
from app.core.rate_limit import check_rate_limit, client_ip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("lingora")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Lingora — AI-powered interactive learning platform API. "
        "Transforms educational PDF books into interactive, auto-graded learning experiences. "
        "All AI features require a configured provider; without one the API reports "
        "AI_NOT_CONFIGURED instead of faking responses."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type"],
)


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    # global abuse guard (per-IP, generous); endpoint-specific limits are stricter
    if request.url.path.startswith(settings.api_prefix):
        try:
            check_rate_limit(f"global:{client_ip(request)}", 300, 60)
        except ApiError as e:
            return JSONResponse(status_code=e.http_status,
                                content={"error": {"code": e.code, "message_uz": e.message_uz, "details": None}})
    t0 = time.monotonic()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith(settings.api_prefix):
        response.headers["Server-Timing"] = f"app;dur={int((time.monotonic() - t0) * 1000)}"
    return response


install_error_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


@app.on_event("startup")
def on_startup():
    # Dev convenience: create tables when Alembic hasn't run (prod uses alembic upgrade head).
    if settings.env != "prod":
        from app.db.session import Base, engine

        import app.models  # noqa: F401 register tables

        Base.metadata.create_all(engine)
    try:
        from app.services.tasks import recover_stuck_jobs

        recover_stuck_jobs()
    except Exception:
        log.exception("Job recovery failed at startup")


@app.get("/")
def root():
    return {"name": settings.app_name, "docs": "/docs", "api": settings.api_prefix}
