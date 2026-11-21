"""Deployments without `alembic upgrade head` must still get missing columns.

The production incident these tests cover: the code queried
``vocabulary_words.picture_page`` against a database that only had the previous
schema, so opening the vocabulary page answered 500 "column does not exist".
"""
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.schema_upgrade import ensure_schema
from app.db.session import Base
from app.models import VocabularyWord


def _engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'deploy.db'}")
    return engine


def _drop_picture_columns(engine):
    """Rebuild vocabulary_words exactly as the previous release created it (SQLite DDL)."""
    columns = [f"{column.name} {column.type.compile(engine.dialect)}"
               + (" PRIMARY KEY" if column.name == "id" else "")
               for column in VocabularyWord.__table__.columns
               if column.name not in ("picture_page", "picture_bbox")]
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS vocabulary_words"))
        connection.execute(sa.text(
            f"CREATE TABLE vocabulary_words ({', '.join(columns)})"))


def test_missing_column_is_added_to_an_existing_table(tmp_path):
    engine = _engine(tmp_path)
    # Simulate the OLD schema: the table exists, the new columns do not.
    _drop_picture_columns(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO vocabulary_words (id, term) VALUES ('w1', 'afraid')"))
    assert not {column["name"] for column in sa.inspect(engine).get_columns("vocabulary_words")} \
        .issuperset({"picture_page", "picture_bbox"})

    added = ensure_schema(engine, stamp=False)

    assert set(added) == {"vocabulary_words.picture_page", "vocabulary_words.picture_bbox"}
    columns = {column["name"] for column in sa.inspect(engine).get_columns("vocabulary_words")}
    assert {"picture_page", "picture_bbox"} <= columns
    # Existing rows are untouched: nothing is fabricated, the pictures are simply unknown.
    with Session(engine) as session:
        word = session.get(VocabularyWord, "w1")
        assert word.term == "afraid"
        assert word.picture_page is None
    # Running it again is a no-op (cold starts repeat this on every instance).
    assert ensure_schema(engine, stamp=False) == []


def test_ensure_schema_is_additive_only(tmp_path):
    engine = _engine(tmp_path)
    ensure_schema(engine, stamp=False)
    tables = sa.inspect(engine).get_table_names()
    before = {name: {column["name"] for column in sa.inspect(engine).get_columns(name)}
              for name in tables}
    assert ensure_schema(engine, stamp=False) == []
    after = {name: {column["name"] for column in sa.inspect(engine).get_columns(name)}
             for name in tables}
    assert after == before


def test_stamping_records_the_alembic_head(tmp_path, monkeypatch):
    """After an automatic upgrade, a later `alembic upgrade head` must not re-add columns."""
    engine = _engine(tmp_path)
    monkeypatch.chdir(__import__("pathlib").Path(__file__).resolve().parents[1])
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE vocabulary_words (id VARCHAR(36) PRIMARY KEY, term VARCHAR(255))"))
    added = ensure_schema(engine)
    assert "vocabulary_words.picture_page" in added
    with engine.connect() as connection:
        stamped = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert stamped == "e4b7c2d90a15", "the schema must be stamped at the newest revision"
