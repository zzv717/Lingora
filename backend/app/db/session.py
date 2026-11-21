"""SQLAlchemy engine / session setup. PostgreSQL (Supabase) in prod, SQLite in dev."""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str, *, for_migrations: bool = False):
    """Build an engine that survives a pooler in front of PostgreSQL.

    ``pool_pre_ping`` discards a connection the server closed while it sat idle in the
    pool — without it the first request after a quiet period fails with
    "server closed the connection unexpectedly". ``pool_recycle`` closes connections
    *before* PgBouncer/Supabase can drop them, which is the same failure one step earlier.

    A migration engine uses ``NullPool``: schema upgrades are a handful of statements that
    must run on ONE connection, and a pool would hand the advisory lock and the ALTERs to
    different backends.
    """
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_pre_ping=True, pool_recycle=settings.db_pool_recycle,
                      pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow)
    if for_migrations:
        from sqlalchemy.pool import NullPool

        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
        kwargs["poolclass"] = NullPool
    return create_engine(url, **kwargs)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def migration_url() -> str:
    """The URL schema upgrades use: the direct one when configured, else the normal one."""
    return (settings.database_migration_url or "").strip() or settings.database_url


def schema_engine():
    """A dedicated, unpooled engine for schema upgrades (see ``migration_url``)."""
    return _make_engine(migration_url(), for_migrations=True)


if engine.url.get_backend_name() == "sqlite":

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):  # enforce FKs on SQLite
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
