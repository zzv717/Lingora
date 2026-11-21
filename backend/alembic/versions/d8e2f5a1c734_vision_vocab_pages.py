"""book page state: mark which pages a vision vocabulary pass has already read

A vision pass is paid per page and cannot be repeated blindly, so the server must know
which pages were already attempted. Without this a page that simply is not a word list
("Unit 1: exercises") is offered again on every run, forever.

Revision ID: d8e2f5a1c734
Revises: c4f7a1b9d2e5
Create Date: 2026-11-20 18:00:00.000000
"""
from alembic import context, op
import sqlalchemy as sa

revision = 'd8e2f5a1c734'
down_revision = 'c4f7a1b9d2e5'
branch_labels = None
depends_on = None


def _existing_columns() -> set[str] | None:
    """Column names, or None when generating offline SQL (no connection to inspect)."""
    if context.is_offline_mode():
        return None
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("book_pages"):
        return None
    return {column["name"] for column in inspector.get_columns("book_pages")}


def upgrade() -> None:
    # The column may already exist: deployments that cannot run Alembic add it at startup
    # (app/db/schema_upgrade.py), and both paths must be safe to run in any order.
    existing = _existing_columns()
    with op.batch_alter_table('book_pages', schema=None) as batch_op:
        if existing is None or "vocab_scanned_at" not in existing:
            batch_op.add_column(sa.Column('vocab_scanned_at', sa.DateTime(timezone=True),
                                          nullable=True))


def downgrade() -> None:
    existing = _existing_columns() or set()
    with op.batch_alter_table('book_pages', schema=None) as batch_op:
        if "vocab_scanned_at" in existing:
            batch_op.drop_column('vocab_scanned_at')
