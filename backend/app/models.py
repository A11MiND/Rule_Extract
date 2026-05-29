from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .database import Base


JsonType = JSON


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
    contract_family: Mapped[str] = mapped_column(String(32), nullable=False, default="Generic")
    grouping_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    mineru_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mineru_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    markdown_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zip_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artifact_manifest: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sections: Mapped[list["Section"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Section.position"
    )
    rules: Mapped[list["Rule"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    classification: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    document: Mapped[Document] = relationship(back_populates="sections")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    condition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="procedure")
    actor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    options: Mapped[list[dict]] = mapped_column(JsonType, nullable=False, default=list)
    dependencies: Mapped[list[dict]] = mapped_column(JsonType, nullable=False, default=list)
    next_rule_ids: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="rules")


# ──────────────────────────────────────────────
# Phase 0 — Knowledge Base & Mapping
# ──────────────────────────────────────────────


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_document: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Clause-specific
    clause_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    clause_category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    parent_document: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    clause_remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Template-specific
    template_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    section_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    field_definitions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Policy-specific
    circular_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    issuing_body: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    effective_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    supersedes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Department-rule specific
    department: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    chapter: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    section_ref: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    version: Mapped[str] = mapped_column(String(16), default="1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Mapping(Base):
    __tablename__ = "mappings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    knowledge_item_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("rules.id", ondelete="CASCADE"), nullable=True, index=True
    )
    template_section_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    mapping_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    human_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    human_decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ──────────────────────────────────────────────
# Phase 2 — Vetting Pipeline
# ──────────────────────────────────────────────


class VettingRun(Base):
    __tablename__ = "vetting_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="created", index=True
    )
    source_file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_file_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    total_sections: Mapped[int] = mapped_column(Integer, default=0)
    completed_sections: Mapped[int] = mapped_column(Integer, default=0)
    total_findings: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    low_count: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[Optional[dict]] = mapped_column(JsonType, nullable=True, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class VettingFinding(Base):
    __tablename__ = "vetting_findings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    vetting_run_id: Mapped[str] = mapped_column(
        ForeignKey("vetting_runs.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    tender_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    human_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    human_verdict: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    human_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ──────────────────────────────────────────────
# Phase 3 — Chatbot
# ──────────────────────────────────────────────


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New Chat")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict] = mapped_column(JsonType, default=list)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# ──────────────────────────────────────────────
# Phase 0 — Ingestion Audit
# ──────────────────────────────────────────────


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_document: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
