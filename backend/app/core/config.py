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

    # --- Storage: local disk or Supabase Storage ---
    storage_backend: Literal["local", "supabase"] = "local"
    storage_dir: str = "./data/storage"
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = "lingora-books"

    # --- Upload limits ---
    upload_max_mb: int = 50
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
    ai_daily_token_limit: int = 0  # 0 = unlimited (per user, per day)

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
    task_backend: Literal["inline", "celery"] = "inline"
    redis_url: str = ""
    pipeline_max_pages: int = 300

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

    def plan_limits(self, plan: str) -> dict:
        return {
            "free": {"max_books": self.free_max_books, "ai_calls_per_day": self.free_ai_calls_per_day},
            "pro": {"max_books": self.pro_max_books, "ai_calls_per_day": self.pro_ai_calls_per_day},
            "premium": {"max_books": self.premium_max_books, "ai_calls_per_day": self.premium_ai_calls_per_day},
        }.get(plan, {"max_books": self.free_max_books, "ai_calls_per_day": self.free_ai_calls_per_day})

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
