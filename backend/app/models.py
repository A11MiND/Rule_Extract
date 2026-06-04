from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
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
    page_range: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    coordinates: Mapped[list[dict]] = mapped_column(JsonType, nullable=False, default=list)
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
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="recommended")
    applicability: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    evidence_requirements: Mapped[list[dict]] = mapped_column(JsonType, nullable=False, default=list)
    validation_method: Mapped[str] = mapped_column(String(32), nullable=False, default="llm_judgement")
    references: Mapped[list[dict]] = mapped_column(JsonType, nullable=False, default=list)
    mapping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unmapped")
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



class DocumentCollection(Base):
    __tablename__ = "document_collections"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contract_family: Mapped[str] = mapped_column(String(32), nullable=False, default="ECC")
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False, default="Hong Kong")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="2024")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_documents: Mapped[list["SourceDocument"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    template_fields: Mapped[list["TemplateField"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    field_rule_mappings: Mapped[list["FieldRuleMapping"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    mapping_runs: Mapped[list["MappingRun"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    tender_submissions: Mapped[list["TenderSubmission"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    library_slots: Mapped[list["LibrarySlot"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    procedure_sets: Mapped[list["VettingProcedureSet"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class LibrarySlot(Base):
    __tablename__ = "library_slots"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    short_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rulebook", index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grouping_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="library_slots")


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    slot_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("library_slots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created", index=True)
    text_review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    text_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mineru_artifacts: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    linked_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="source_documents")
    template_fields: Mapped[list["TemplateField"]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )


class TemplateField(Base):
    __tablename__ = "template_fields"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    source_document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_doc: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    field_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    section_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extraction_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    check_intent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    structured_schema: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    normalization: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    evidence_locator: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    part_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filled_by: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_window: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="suggested", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="template_fields")
    source_document: Mapped[Optional[SourceDocument]] = relationship(back_populates="template_fields")
    mappings: Mapped[list["FieldRuleMapping"]] = relationship(
        back_populates="template_field", cascade="all, delete-orphan"
    )


class FieldRuleMapping(Base):
    __tablename__ = "field_rule_mappings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    template_field_id: Mapped[str] = mapped_column(
        ForeignKey("template_fields.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rule")
    check_type: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
    applicability_condition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="suggested", index=True)
    review_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="field_rule_mappings")
    template_field: Mapped[TemplateField] = relationship(back_populates="mappings")


class VettingProcedureSet(Base):
    __tablename__ = "vetting_procedure_sets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    template_source_ids: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    rule_source_ids: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    mapping_ids: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    parent_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="procedure_sets")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80), nullable=False, default="Demo User", index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    before_json: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    after_json: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class MappingRun(Base):
    __tablename__ = "mapping_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    windows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    windows_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artifact_json: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    collection: Mapped[DocumentCollection] = relationship(back_populates="mapping_runs")


class TenderSubmission(Base):
    __tablename__ = "tender_submissions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("document_collections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    source_document_ids: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped[DocumentCollection] = relationship(back_populates="tender_submissions")
    evidence: Mapped[list["TenderFieldEvidence"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )
    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class TenderFieldEvidence(Base):
    __tablename__ = "tender_field_evidence"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("tender_submissions.id", ondelete="CASCADE"), index=True
    )
    template_field_id: Mapped[str] = mapped_column(
        ForeignKey("template_fields.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_document: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_or_section: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="suggested", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submission: Mapped[TenderSubmission] = relationship(back_populates="evidence")


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("tender_submissions.id", ondelete="CASCADE"), index=True
    )
    template_field_id: Mapped[str] = mapped_column(
        ForeignKey("template_fields.id", ondelete="CASCADE"), index=True
    )
    mapping_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("field_rule_mappings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    result: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review", index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rule_evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tender_evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submission: Mapped[TenderSubmission] = relationship(back_populates="results")
