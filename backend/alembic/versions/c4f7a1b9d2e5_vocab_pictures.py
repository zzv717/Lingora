"""vocabulary word illustrations (normalized PDF boxes)

Vocabulary words may carry the location of their illustration on the original PDF
page: ``picture_page`` plus a normalized ``picture_bbox`` ([x1, y1, x2, y2], 0..1).
The picture itself is cropped in the browser from the authenticated PDF, so nothing
is generated and the crop stays sharp at any size.

Revision ID: c4f7a1b9d2e5
Revises: b7c1d2e4f9a3
Create Date: 2026-11-19 12:00:00.000000
"""
from alembic import context, op
import sqlalchemy as sa

revision = 'c4f7a1b9d2e5'
down_revision = 'b7c1d2e4f9a3'
branch_labels = None
depends_on = None


def _existing_columns() -> set[str] | None:
    """Column names, or None when generating offline SQL (no connection to inspect)."""
    if context.is_offline_mode():
        return None
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("vocabulary_words")}


def upgrade() -> None:
    # The columns may already exist: the API adds them at startup on deployments that
    # cannot run Alembic (see app/db/schema_upgrade.py), and both paths must be safe.
    existing = _existing_columns()
    with op.batch_alter_table('vocabulary_words', schema=None) as batch_op:
        if existing is None or "picture_page" not in existing:
            batch_op.add_column(sa.Column('picture_page', sa.Integer(), nullable=True))
        if existing is None or "picture_bbox" not in existing:
            batch_op.add_column(sa.Column('picture_bbox', sa.JSON(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns() or set()
    with op.batch_alter_table('vocabulary_words', schema=None) as batch_op:
        if "picture_bbox" in existing:
            batch_op.drop_column('picture_bbox')
        if "picture_page" in existing:
            batch_op.drop_column('picture_page')
