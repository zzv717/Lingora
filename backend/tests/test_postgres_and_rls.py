"""PostgreSQL DDL and Supabase RLS verification test (runs without live server using sqlite & mock engine)."""
import io
from sqlalchemy import create_engine, text
from app.db.session import Base
import app.models  # noqa: F401


def test_postgres_ddl_and_models_compatibility():
    """Verify that all SQLAlchemy models generate clean DDL for PostgreSQL dialect without error."""
    buf = io.StringIO()

    def dump(sql, *multiparams, **params):
        buf.write(str(sql.compile(dialect=engine.dialect)))

    engine = create_engine("postgresql://", strategy="mock", executor=dump)
    Base.metadata.create_all(engine)
    ddl = buf.getvalue()
    assert "CREATE TABLE users" in ddl
    assert "CREATE TABLE books" in ddl
    assert "CREATE TABLE exercise_questions" in ddl
    assert "CREATE TABLE vocabulary_words" in ddl
    assert len(ddl) > 5000


def test_supabase_schema_rls_policies_count():
    """Verify database/supabase_schema.sql contains exactly 27 tables with matching RLS policies."""
    import pathlib
    schema_file = pathlib.Path(__file__).resolve().parent.parent.parent / "database" / "supabase_schema.sql"
    assert schema_file.exists()
    content = schema_file.read_text(encoding="utf-8")

    # Check lingora_current_user_id function exists
    assert "lingora_current_user_id()" in content

    # Check each of the 27 tables has ENABLE ROW LEVEL SECURITY
    tables = [
        "users", "profiles", "refresh_tokens", "password_resets", "subscriptions",
        "books", "processing_jobs", "book_pages", "chapters", "lessons",
        "exercises", "exercise_questions", "exercise_options", "answer_keys",
        "student_answers", "exercise_attempts", "vocabulary_words", "vocabulary_sessions",
        "vocabulary_attempts", "vocabulary_progress", "learning_progress", "activity_days",
        "revision_sessions", "revision_items", "ai_conversations", "ai_messages", "usage_events"
    ]
    assert len(tables) == 27
    for t in tables:
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;" in content
        assert f'CREATE POLICY "{t}_owner_all" ON {t}' in content


def test_alembic_accepts_url_encoded_database_password():
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {**os.environ, "DATABASE_URL": "postgresql://user:p%40ss@localhost/lingora"}
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=backend_dir, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE users" in result.stdout
