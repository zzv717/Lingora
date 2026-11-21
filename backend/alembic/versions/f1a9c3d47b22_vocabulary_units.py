"""vocabulary units, per-unit word order, translations with a status

The Lug'at was a flat list: words had no unit, no position on the page and no record of
where a translation came from. That is why the screen could only show one long list, why a
stray character could become a "unit title", and why a translated word was still excluded
from tests (``needs_translation`` was a boolean with no notion of "machine translated but
usable").

This revision adds:
  * ``vocabulary_units`` — the unit as the book prints it (number, title, page range);
  * ``vocabulary_words.unit_id`` / ``position`` — grouping and page order;
  * ``vocabulary_words.translation_status`` / ``alt_translations`` — "auto" translations are
    usable immediately, "verified"/"edited" mean a human touched them;
  * the book-wide unique index on ``term`` is dropped: the same spelling can appear in two
    units with different senses, and uniqueness now belongs to (book, unit, term).

Every step inspects the live schema first, so the revision is safe to run against a
database where the startup path (``app/db/schema_upgrade.py``) already added a piece.

Revision ID: f1a9c3d47b22
Revises: e4b7c2d90a15
Create Date: 2026-11-21 09:00:00.000000
"""
from alembic import context, op
import sqlalchemy as sa

revision = 'f1a9c3d47b22'
down_revision = 'e4b7c2d90a15'
branch_labels = None
depends_on = None


def _inspector():
    """Inspector, or None when generating offline SQL (no connection to inspect)."""
    if context.is_offline_mode():
        return None
    return sa.inspect(op.get_bind())


def _columns(insp, table: str) -> set[str] | None:
    if insp is None or not insp.has_table(table):
        return None
    return {column["name"] for column in insp.get_columns(table)}


def _indexes(insp, table: str) -> set[str]:
    if insp is None or not insp.has_table(table):
        return set()
    return {index["name"] for index in insp.get_indexes(table)}


def upgrade() -> None:
    insp = _inspector()
    if insp is None or not insp.has_table("vocabulary_units"):
        op.create_table(
            "vocabulary_units",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("book_id", sa.String(length=36), sa.ForeignKey("books.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("number", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("page_start", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("page_end", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.UniqueConstraint("book_id", "number", name="uq_vocab_unit_number"),
        )
        op.create_index("ix_vocabulary_units_book_id", "vocabulary_units", ["book_id"])

    columns = _columns(insp, "vocabulary_words")
    with op.batch_alter_table("vocabulary_words", schema=None) as batch_op:
        if columns is None or "unit_id" not in columns:
            batch_op.add_column(sa.Column("unit_id", sa.String(length=36), nullable=True))
        if columns is None or "position" not in columns:
            batch_op.add_column(sa.Column("position", sa.Integer(), nullable=False,
                                          server_default="0"))
        if columns is None or "translation_status" not in columns:
            batch_op.add_column(sa.Column("translation_status", sa.String(length=16),
                                          nullable=False, server_default=""))
        if columns is None or "alt_translations" not in columns:
            batch_op.add_column(sa.Column("alt_translations", sa.JSON(), nullable=True))
        # The old book-wide uniqueness has to go: two units may teach the same spelling.
        if insp is None or "uq_vocab_term" in _indexes(insp, "vocabulary_words") or \
                "uq_vocab_term" in {c["name"] for c in (insp.get_unique_constraints("vocabulary_words"))}:
            batch_op.drop_constraint("uq_vocab_term", type_="unique")
        if columns is None or "unit_id" not in columns:
            batch_op.create_foreign_key("fk_vocab_words_unit", "vocabulary_units",
                                        ["unit_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    insp = _inspector()
    columns = _columns(insp, "vocabulary_words") or set()
    with op.batch_alter_table("vocabulary_words", schema=None) as batch_op:
        if "alt_translations" in columns:
            batch_op.drop_column("alt_translations")
        if "translation_status" in columns:
            batch_op.drop_column("translation_status")
        if "position" in columns:
            batch_op.drop_column("position")
        if "unit_id" in columns:
            batch_op.drop_column("unit_id")
    if insp is None or insp.has_table("vocabulary_units"):
        op.drop_table("vocabulary_units")
