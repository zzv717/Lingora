"""Schema upgrades for deployments that cannot run ``alembic upgrade head``.

Serverless platforms (Vercel Services, a plain ``uvicorn`` on a PaaS that ignores a
start command) never run the Alembic command, so an instance can start against a
database that is missing the columns the code now queries — the API then fails at
runtime with ``column ... does not exist``. This module upgrades such a database at
startup and records the Alembic revision, so a later ``alembic upgrade head`` sees a
consistent state instead of trying to add the same columns again.

``create_all`` alone is not enough for that: it creates missing TABLES but never adds a
column to a table that already exists, which is exactly how a deployment ends up with
code that queries ``vocabulary_words.picture_page`` against a database without it.

It is deliberately conservative: it only ADDS what is missing, never drops or rewrites,
and it runs in one transaction with a lock so concurrent cold starts cannot race.
"""
import logging
import time
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

log = logging.getLogger("lingora.schema")

# Locks the schema check for the duration of one transaction (PostgreSQL only).
_LOCK_KEY = 918273645

# A cold start can race the database's own readiness: Supabase answers with
# "the database system is starting up" / a refused connection for a few seconds.
_ATTEMPTS = 4
_BACKOFF = (0.5, 1.5, 3.0)


def _alembic_revision(connection) -> str | None:
    """Current revision, or None when the database has no Alembic history at all."""
    if not inspect(connection).has_table("alembic_version"):
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _is_pooler_url(engine: Engine) -> bool:
    """True when the URL points at a connection pooler rather than the database itself."""
    host = (engine.url.host or "").lower()
    port = engine.url.port
    return "pooler" in host or port in (6543,) or "pgbouncer" in host


def _column_additions() -> list[tuple[str, str, str]]:
    """(table, column, SQL type) pairs added after the initial release.

    Keep this list append-only and in step with the Alembic revisions: it is the
    fallback path for platforms that do not run Alembic.
    """
    return [("vocabulary_words", "picture_page", "INTEGER"),
            ("vocabulary_words", "picture_bbox", "JSON"),
            ("book_pages", "vocab_scanned_at", "TIMESTAMP WITH TIME ZONE"),
            ("books", "text_vocabulary_count", "INTEGER NOT NULL DEFAULT 0"),
            ("books", "vocabulary_note_uz", "TEXT NOT NULL DEFAULT ''")]


def ensure_schema(engine: Engine, stamp: bool = True) -> list[str]:
    """Create missing tables and columns; return the columns that had to be added.

    Retries on ``OperationalError``: a serverless cold start frequently reaches the
    database before it accepts connections, and failing here used to crash startup or
    leave the instance running against a schema with no columns.
    """
    last_error: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            return _ensure_schema_once(engine, stamp)
        except OperationalError as exc:
            last_error = exc
            if attempt == _ATTEMPTS - 1:
                break
            delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            log.warning("Schema upgrade attempt %s/%s failed (%s); retrying in %.1fs",
                        attempt + 1, _ATTEMPTS, type(exc).__name__, delay)
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def _ensure_schema_once(engine: Engine, stamp: bool) -> list[str]:
    from app import models  # noqa: F401 — register every table on Base.metadata
    from app.db.session import Base

    with engine.begin() as connection:
        # A transaction-level advisory lock taken through a transaction pooler is not
        # guaranteed to belong to the same backend that runs the ALTERs, which silently
        # defeats it. Lock only on a direct connection; a pooler URL means a managed
        # database that already serializes its own DDL.
        if engine.url.get_backend_name() == "postgresql" and not _is_pooler_url(engine):
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
        elif engine.url.get_backend_name() == "postgresql":
            log.info("Schema upgrade on a pooled connection: skipping the advisory lock")
        Base.metadata.create_all(connection)
        inspector = inspect(connection)
        added: list[str] = []
        for table, column, sql_type in _column_additions():
            if not inspector.has_table(table):
                continue
            existing = {item["name"] for item in inspector.get_columns(table)}
            if column in existing:
                continue
            connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))
            added.append(f"{table}.{column}")
        if added:
            log.warning("Schema upgraded at startup (missing Alembic migration): %s",
                        ", ".join(added))
            if stamp:
                _stamp_head(connection)
    return added


def _stamp_head(connection) -> None:
    """Record the newest revision so a later ``alembic upgrade head`` is a no-op."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        # Serverless runtimes do not always start in the backend directory.
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        head = ScriptDirectory.from_config(config).get_current_head()
    except Exception:
        log.exception("Could not resolve the Alembic head; version table left untouched")
        return
    if not inspect(connection).has_table("alembic_version"):
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    connection.execute(text("DELETE FROM alembic_version"))
    connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
                       {"head": head})
    log.warning("Database stamped as Alembic revision %s", head)
