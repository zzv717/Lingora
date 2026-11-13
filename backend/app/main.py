"""Lingora API entrypoint.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
import os
import time
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure local storage and data directories exist
    if settings.storage_backend == "local":
        os.makedirs(settings.storage_dir, exist_ok=True)
    if settings.database_url.startswith("sqlite:///./data"):
        os.makedirs("./data", exist_ok=True)

    # Dev convenience: create tables when Alembic hasn't run (prod uses alembic upgrade head).
    if settings.env != "prod":
        from app.db.session import Base, engine
        import app.models  # noqa: F401 register tables

        Base.metadata.create_all(engine)

    # A serverless cold start can coincide with a job running in another instance.
    # Global startup recovery would incorrectly mark that active job as failed.
    if not os.environ.get("VERCEL") and settings.env != "prod" and settings.task_backend == "inline":
        try:
            from app.services.tasks import recover_stuck_jobs

            recover_stuck_jobs()
        except Exception:
            log.exception("Job recovery failed at startup")

    yield


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
    lifespan=lifespan,
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
    # Request body size limit check (e.g. 55MB to protect against huge payload DOS)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            cl = int(content_length)
            max_allowed = (settings.upload_max_mb + 10) * 1024 * 1024
            if cl > max_allowed:
                return JSONResponse(
                    status_code=413,
                    content={"error": {"code": "PAYLOAD_TOO_LARGE", "message_uz": "So'rov hajmi juda katta.", "details": None}},
                )
        except ValueError:
            pass

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


@app.get("/")
def root():
    return {"name": settings.app_name, "docs": "/docs", "api": settings.api_prefix}


@app.get("/health")
def health():
    """Liveness probe: verifies web server is alive."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/ready")
def readiness():
    """Readiness probe: verifies DB connectivity and storage availability."""
    from app.db.session import engine
    from sqlalchemy import text

    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        log.error("Readiness DB check failed: %s", e)

    storage_ok = False
    try:
        if settings.storage_backend == "local":
            storage_ok = os.path.exists(settings.storage_dir) and os.access(settings.storage_dir, os.W_OK)
        else:
            storage_ok = bool(settings.supabase_url and settings.supabase_service_key)
    except Exception as e:
        log.error("Readiness storage check failed: %s", e)

    ready = db_ok and storage_ok
    status_code = 200 if ready else 503
    return JSONResponse(
        status_code=status_code,
        content={"ready": ready, "db": db_ok, "storage": storage_ok, "ai_configured": settings.ai_configured},
    )
