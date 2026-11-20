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
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("lingora.schema")

# Locks the schema check for the duration of one transaction (PostgreSQL only).
_LOCK_KEY = 918273645


def _alembic_revision(connection) -> str | None:
    """Current revision, or None when the database has no Alembic history at all."""
    if not inspect(connection).has_table("alembic_version"):
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _column_additions() -> list[tuple[str, str, str]]:
    """(table, column, SQL type) pairs added after the initial release.

    Keep this list append-only and in step with the Alembic revisions: it is the
    fallback path for platforms that do not run Alembic.
    """
    return [("vocabulary_words", "picture_page", "INTEGER"),
            ("vocabulary_words", "picture_bbox", "JSON")]


def ensure_schema(engine: Engine, stamp: bool = True) -> list[str]:
    """Create missing tables and columns; return the columns that had to be added."""
    from app import models  # noqa: F401 — register every table on Base.metadata
    from app.db.session import Base

    with engine.begin() as connection:
        if engine.url.get_backend_name() == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
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
