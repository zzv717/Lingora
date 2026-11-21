"""books: record how the vocabulary was found, and why it may be incomplete

The Lug'at screen could only report "no vocabulary found", which is indistinguishable
from a broken parser. Two columns make the book explain itself: how many entries the text
parser recovered at analysis time, and a ready-made Uzbek note (vision fallback used, AI
not configured, no word lists in the book).

Revision ID: e4b7c2d90a15
Revises: d8e2f5a1c734
Create Date: 2026-11-21 06:30:00.000000
"""
from alembic import context, op
import sqlalchemy as sa

revision = 'e4b7c2d90a15'
down_revision = 'd8e2f5a1c734'
branch_labels = None
depends_on = None


def _existing_columns() -> set[str] | None:
    """Column names, or None when generating offline SQL (no connection to inspect)."""
    if context.is_offline_mode():
        return None
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("books"):
        return None
    return {column["name"] for column in inspector.get_columns("books")}


def upgrade() -> None:
    # Both columns may already exist: deployments that cannot run Alembic add them at
    # startup (app/db/schema_upgrade.py), and the two paths must be safe in any order.
    existing = _existing_columns()
    with op.batch_alter_table('books', schema=None) as batch_op:
        if existing is None or "text_vocabulary_count" not in existing:
            batch_op.add_column(sa.Column('text_vocabulary_count', sa.Integer(),
                                          nullable=False, server_default="0"))
        if existing is None or "vocabulary_note_uz" not in existing:
            batch_op.add_column(sa.Column('vocabulary_note_uz', sa.Text(),
                                          nullable=False, server_default=""))


def downgrade() -> None:
    existing = _existing_columns() or set()
    with op.batch_alter_table('books', schema=None) as batch_op:
        if "vocabulary_note_uz" in existing:
            batch_op.drop_column('vocabulary_note_uz')
        if "text_vocabulary_count" in existing:
            batch_op.drop_column('text_vocabulary_count')
