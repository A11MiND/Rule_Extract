"""Link source documents to converted documents.

Revision ID: 20260604_02
Revises: 20260604_01
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260604_02"
down_revision = "20260604_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_foreign_keys("source_documents")
    has_link = any(
        foreign_key.get("referred_table") == "documents"
        and foreign_key.get("constrained_columns") == ["linked_document_id"]
        for foreign_key in existing
    )
    if not has_link:
        with op.batch_alter_table("source_documents") as batch:
            batch.create_foreign_key(
                "fk_source_documents_linked_document_id",
                "documents",
                ["linked_document_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    with op.batch_alter_table("source_documents") as batch:
        batch.drop_constraint("fk_source_documents_linked_document_id", type_="foreignkey")
