"""vocabulary word illustrations (normalized PDF boxes)

Vocabulary words may carry the location of their illustration on the original PDF
page: ``picture_page`` plus a normalized ``picture_bbox`` ([x1, y1, x2, y2], 0..1).
The picture itself is cropped in the browser from the authenticated PDF, so nothing
is generated and the crop stays sharp at any size.

Revision ID: c4f7a1b9d2e5
Revises: b7c1d2e4f9a3
Create Date: 2026-11-19 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4f7a1b9d2e5'
down_revision = 'b7c1d2e4f9a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('vocabulary_words', schema=None) as batch_op:
        batch_op.add_column(sa.Column('picture_page', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('picture_bbox', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('vocabulary_words', schema=None) as batch_op:
        batch_op.drop_column('picture_bbox')
        batch_op.drop_column('picture_page')
