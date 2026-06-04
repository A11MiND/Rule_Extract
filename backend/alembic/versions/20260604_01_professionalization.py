"""Add document-based review, procedures, library slots, and audit history.

Revision ID: 20260604_01
Revises:
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from backend.app import models  # noqa: F401
from backend.app.database import Base


revision = "20260604_01"
down_revision = None
branch_labels = None
depends_on = None


UPGRADE_COLUMNS: dict[str, dict[str, sa.Column]] = {
    "sections": {
        "page_range": sa.Column("page_range", sa.String(64), nullable=True),
        "coordinates": sa.Column("coordinates", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    },
    "rules": {
        "severity": sa.Column("severity", sa.String(32), nullable=False, server_default="recommended"),
        "applicability": sa.Column("applicability", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        "evidence_requirements": sa.Column("evidence_requirements", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        "validation_method": sa.Column("validation_method", sa.String(32), nullable=False, server_default="llm_judgement"),
        "references": sa.Column("references", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        "mapping_status": sa.Column("mapping_status", sa.String(32), nullable=False, server_default="unmapped"),
    },
    "source_documents": {
        "slot_id": sa.Column("slot_id", sa.Text(), nullable=True),
        "description": sa.Column("description", sa.Text(), nullable=False, server_default=""),
        "text_review_status": sa.Column("text_review_status", sa.String(32), nullable=False, server_default="pending"),
        "text_verified_at": sa.Column("text_verified_at", sa.DateTime(timezone=True), nullable=True),
        "content_fingerprint": sa.Column("content_fingerprint", sa.Text(), nullable=False, server_default=""),
    },
    "template_fields": {
        "check_intent": sa.Column("check_intent", sa.Text(), nullable=False, server_default=""),
        "structured_schema": sa.Column("structured_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        "normalization": sa.Column("normalization", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        "evidence_locator": sa.Column("evidence_locator", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    # This first migration doubles as a non-destructive baseline for fresh and existing demo databases.
    Base.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)
    for table_name, columns in UPGRADE_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column in columns.items():
            if column_name not in existing:
                op.add_column(table_name, column)


def downgrade() -> None:
    # The demo database contains extracted artifacts that must not be destroyed by downgrade.
    pass
