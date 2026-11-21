"""Lingora API configuration.

All secrets come from environment variables (see .env.example at repo root).
Never hardcode credentials in code.
"""
import os
import sys
from functools import lru_cache
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_PLACEHOLDER = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- App ---
    app_name: str = "Lingora API"
    # Support APP_ENV as an alias for ENV
    env: Literal["dev", "prod", "test"] = Field(
        default="dev",
        validation_alias="ENV",
    )
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:3000"

    # --- Security ---
    secret_key: str = Field(default=INSECURE_SECRET_PLACEHOLDER)
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Trusted proxies for rate limiting: empty string = trust none (only direct client IP)
    # Comma-separated list of trusted proxy IPs or CIDRs, or "*" in controlled environments.
    trusted_proxies: str = ""

    # --- Database (PostgreSQL in prod, e.g. Supabase pooler URL; SQLite for local dev) ---
    database_url: str = "sqlite:///./data/lingora.db"
    # Direct (non-pooler) URL used ONLY for schema upgrades. A transaction-level advisory
    # lock taken through a pooler (PgBouncer transaction mode) can be released on a
    # different backend connection, which turns the upgrade lock into a no-op. When empty
    # the normal URL is used, so local and single-connection setups need no extra setting.
    database_migration_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle: int = 300   # seconds; a pooler may drop idle connections before this

    # --- Storage: local disk or Supabase Storage ---
    storage_backend: Literal["local", "supabase"] = "local"
    storage_dir: str = "./data/storage"
    supabase_url: str = ""
    supabase_service_key: str = ""
    # Public/anon key, safe to send to browsers. Never use a service key here.
    supabase_publishable_key: str = ""
    supabase_direct_upload_enabled: bool = False
    supabase_storage_bucket: str = "lingora-books"

    # --- Upload limits ---
    upload_max_mb: int = 100
    max_pages: int = 300

    # --- SMTP (password resets) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@lingora.app"

    # --- AI provider (provider-agnostic; see app/services/ai/) ---
    # none        -> AI features disabled, API returns explicit 503 AI_NOT_CONFIGURED
    # openai_compatible -> OpenAI, Groq, OpenRouter, vLLM, Ollama... (set ai_base_url)
    # anthropic   -> Claude
    # gemini      -> Google Gemini
    ai_provider: Literal["none", "openai_compatible", "anthropic", "gemini"] = "none"
    ai_api_key: str = ""
    ai_base_url: str = ""          # only for openai_compatible; default https://api.openai.com/v1
    ai_model: str = ""             # e.g. gpt-4o-mini / claude-3-5-sonnet-latest / gemini-2.0-flash
    ai_vision_model: str = ""      # optional model with image input, used for scanned-page OCR assist
    ai_timeout_seconds: int = 60
    ai_max_retries: int = 2
    # Temporarily disable application-level daily request/page quotas; set true to restore them.
    ai_daily_request_limits_enabled: bool = False
    ai_daily_token_limit: int = 0  # Separate token safety cap, 0 = unlimited (per user, per day)
    vision_exercise_pages_per_day: int = 150  # applied only when daily request limits are enabled

    # --- Exercise region detection (normalized 0..1 page boxes) ---
    # Page images sent to the vision model are rendered on demand and cached by
    # content hash, so an already analysed page never pays for a second call.
    vision_region_dpi: int = 200            # render resolution for region detection (150-300)
    vision_region_max_pixels: int = 2600    # longest edge sent to the provider (cost bound)
    vision_region_workers: int = 4          # pages processed in parallel (within rate limits)
    vision_region_cache_enabled: bool = True
    vision_region_cache_ttl_days: int = 30  # unused entries are pruned after this
    vision_region_verify_confidence: float = 0.7  # below this a crop is verified once
    vision_region_debug: bool = False       # save page images with drawn boxes
    vision_region_debug_dir: str = "./data/vision-debug"
    # Book enrichment batches (vocabulary translations, lesson notes) are network-bound;
    # run a small bounded pool so a dictionary with thousands of words does not wait
    # for one provider round trip at a time.
    ai_enrich_workers: int = 4

    # --- automatic vision fallback for vocabulary ---
    # A book whose text parser recovers fewer entries than this is treated as unreadable
    # by the rules: the vision pass then reads the pages itself, without the user having
    # to notice, tick a box and press a button. 0 disables the fallback entirely.
    vocab_vision_fallback_min_entries: int = 10
    # Pages the automatic pass may read in one analysis. Each page is a paid model call,
    # so this is a hard ceiling, not a target; the rest stays in the manual worklist.
    vocab_vision_fallback_pages: int = 24
    # A page that yields fewer entries than this did not really work, even though the
    # model answered: it is retried once at higher resolution before being accepted.
    vocab_vision_min_page_entries: int = 3
    # Wall-clock budget for one batch request. Pages not started within it are reported as
    # "deferred" and the client asks again, so a serverless timeout can never swallow a
    # batch that was already paid for.
    vocab_vision_batch_seconds: float = 45.0

    # --- Plan limits (subscription-ready; MVP is free, no payments anywhere) ---
    free_max_books: int = 3
    pro_max_books: int = 25
    premium_max_books: int = 100
    free_ai_calls_per_day: int = 20
    pro_ai_calls_per_day: int = 300
    premium_ai_calls_per_day: int = 2000

    # --- Background processing ---
    # "inline" -> ThreadPoolExecutor inside the API process (default, works everywhere)
    # "celery" -> enqueue to Celery workers (requires REDIS_URL + celery worker running)
    # "sync" -> run inside the request (serverless-compatible for short jobs only)
    task_backend: Literal["inline", "celery", "sync"] = "inline"
    # Enable for any deployment that does not run `alembic upgrade head` on release
    # (serverless functions, PaaS without a start command). It only ADDS what is missing.
    auto_schema_upgrade: bool = False
    redis_url: str = ""
    pipeline_max_pages: int = 300

    # OCR runs Tesseract as a subprocess and releases the GIL, so pages can be
    # recognized concurrently. Bound both the worker count and the extra PDF
    # memory held by worker documents (a large PDF must not multiply without limit).
    ocr_max_workers: int = 4
    ocr_max_parallel_mb: int = 256

    @field_validator("env", mode="before")
    @classmethod
    def _resolve_env(cls, v: str | None) -> str:
        raw = v or os.environ.get("APP_ENV") or os.environ.get("ENV") or "dev"
        raw = raw.lower().strip()
        if raw in ("production", "prod"):
            return "prod"
        if raw in ("testing", "test"):
            return "test"
        return "dev"

    @field_validator("ai_enrich_workers", "ocr_max_workers")
    @classmethod
    def _bounded_workers(cls, v: int) -> int:
        return max(1, min(16, v))

    @field_validator("ocr_max_parallel_mb")
    @classmethod
    def _bounded_ocr_memory(cls, v: int) -> int:
        return max(32, min(1024, v))

    @field_validator("cors_origins")
    @classmethod
    def _split_origins(cls, v: str) -> str:
        return ",".join(o.strip() for o in v.split(",") if o.strip())

    @property
    def cors_origin_list(self) -> List[str]:
        return [o for o in self.cors_origins.split(",") if o]

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider != "none" and bool(self.ai_api_key) and bool(self.ai_model)

    @property
    def ai_vision_configured(self) -> bool:
        """True when a page image can be sent: needs a key and an image-capable model.

        ``AI_VISION_MODEL`` may be set on its own — a deployment can have vision without
        wanting every other AI feature — so this must not require ``AI_MODEL``.
        """
        return (self.ai_provider != "none" and bool(self.ai_api_key)
                and bool((self.ai_vision_model or self.ai_model).strip()))

    def plan_limits(self, plan: str) -> dict:
        limits = {
            "free": {"max_books": self.free_max_books, "ai_calls_per_day": self.free_ai_calls_per_day},
            "pro": {"max_books": self.pro_max_books, "ai_calls_per_day": self.pro_ai_calls_per_day},
            "premium": {"max_books": self.premium_max_books, "ai_calls_per_day": self.premium_ai_calls_per_day},
        }.get(plan, {"max_books": self.free_max_books, "ai_calls_per_day": self.free_ai_calls_per_day})
        if not self.ai_daily_request_limits_enabled:
            limits["ai_calls_per_day"] = 0  # API convention: 0 means unlimited.
        return limits

    def validate_production_security(self) -> None:
        """Crash on startup in production if secret key is insecure or placeholder."""
        if self.env == "prod":
            if not self.secret_key or self.secret_key == INSECURE_SECRET_PLACEHOLDER or len(self.secret_key) < 32:
                raise RuntimeError(
                    "FATAL: Production mode requires a strong SECRET_KEY (at least 32 characters). "
                    "Insecure default or empty key detected."
                )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_production_security()
    return s


settings = get_settings()
