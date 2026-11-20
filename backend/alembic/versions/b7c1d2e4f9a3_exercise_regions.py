"""exercise regions, page region cache, correction log

Normalized (0..1) exercise boxes replace pixel-based guesses, the page cache keyed by
the page image hash prevents paying twice for an unchanged page, and every manual
correction is logged for later accuracy analysis.

Revision ID: b7c1d2e4f9a3
Revises: 9db76b54bf80
Create Date: 2026-11-19 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c1d2e4f9a3'
down_revision = '9db76b54bf80'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vision_exercise_regions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('book_id', sa.String(length=36), nullable=False),
        sa.Column('exercise_id', sa.String(length=36), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('number', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('bbox', sa.JSON(), nullable=False),
        sa.Column('original_bbox', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('needs_review', sa.Boolean(), nullable=False),
        sa.Column('continues_from_previous_page', sa.Boolean(), nullable=False),
        sa.Column('continues_on_next_page', sa.Boolean(), nullable=False),
        sa.Column('continued_from_region_id', sa.String(length=36), nullable=True),
        sa.Column('flags', sa.JSON(), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('image_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('vision_exercise_regions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vision_exercise_regions_book_id'), ['book_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_vision_exercise_regions_exercise_id'), ['exercise_id'], unique=False)
        batch_op.create_index('ix_vision_regions_book_page', ['book_id', 'page_number'], unique=False)
        batch_op.create_index('ix_vision_regions_book_order', ['book_id', 'page_number', 'order_index'], unique=False)

    op.create_table(
        'vision_page_region_cache',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('cache_key', sa.String(length=128), nullable=False),
        sa.Column('book_id', sa.String(length=36), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('image_sha256', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('hits', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('vision_page_region_cache', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vision_page_region_cache_book_id'), ['book_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_vision_page_region_cache_cache_key'), ['cache_key'], unique=True)
        batch_op.create_index('ix_vision_cache_book_page', ['book_id', 'page_number'], unique=False)

    op.create_table(
        'vision_region_corrections',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('book_id', sa.String(length=36), nullable=False),
        sa.Column('region_id', sa.String(length=36), nullable=True),
        sa.Column('exercise_id', sa.String(length=36), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('number', sa.String(length=16), nullable=False),
        sa.Column('previous_source', sa.String(length=16), nullable=False),
        sa.Column('previous_bbox', sa.JSON(), nullable=False),
        sa.Column('corrected_bbox', sa.JSON(), nullable=False),
        sa.Column('note', sa.String(length=300), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['region_id'], ['vision_exercise_regions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('vision_region_corrections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vision_region_corrections_book_id'), ['book_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_vision_region_corrections_user_id'), ['user_id'], unique=False)
        batch_op.create_index('ix_vision_corrections_book_page', ['book_id', 'page_number'], unique=False)
        batch_op.create_index('ix_vision_corrections_user', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('vision_region_corrections')
    op.drop_table('vision_page_region_cache')
    op.drop_table('vision_exercise_regions')
