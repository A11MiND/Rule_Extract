from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ContractFamily = Literal["ECC", "TSC", "Generic"]
RuleType = Literal[
    "obligation",
    "prohibition",
    "permission",
    "definition",
    "procedure",
    "deadline",
    "option",
    "checklist",
    "background",
]


class DocumentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    pdf_url: HttpUrl
    contract_family: ContractFamily = "Generic"
    grouping_level: int = Field(default=2, ge=1, le=3)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pdf_url: str
    contract_family: str
    grouping_level: int = 2
    status: str
    mineru_task_id: str | None = None
    mineru_state: str | None = None
    error_message: str | None = None
    markdown_path: str | None = None
    artifact_manifest: dict[str, Any] = Field(default_factory=dict)


class RuntimeConfigUpdate(BaseModel):
    mineru_api_base: str | None = None
    mineru_api_token: str | None = None
    mineru_model_version: str | None = None
    llm_provider: str | None = None
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_concurrency: int | None = Field(default=None, ge=1, le=20)
    extraction_prompt: str | None = None
    default_grouping_level: int | None = Field(default=None, ge=1, le=3)


class RuntimeConfigRead(BaseModel):
    mineru_api_base: str
    mineru_model_version: str
    mineru_configured: bool
    llm_provider: str
    llm_api_base: str
    llm_model: str
    llm_configured: bool
    llm_concurrency: int
    max_llm_concurrency: int
    extraction_prompt: str = ""
    default_grouping_level: int = 2


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: int
    position: int
    level: int
    title: str
    heading_path: list[str]
    content: str
    page_range: str | None = None
    coordinates: list[dict[str, Any]] = Field(default_factory=list)
    classification: str | None = None
    classification_confidence: float | None = None
    children: list["SectionRead"] = Field(default_factory=list)


class SectionUpdate(BaseModel):
    content: str


class SectionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = None


class RuleOption(BaseModel):
    label: str = ""
    condition: str = ""
    action: str = ""
    next_rule_ids: list[str] = Field(default_factory=list)
    referenced_sections: list[str] = Field(default_factory=list)


class RuleDependency(BaseModel):
    type: Literal["requires", "leads_to", "alternative_to", "references"] = "references"
    rule_id: str = ""
    reason: str = ""


class RuleSource(BaseModel):
    heading_path: list[str] = Field(default_factory=list)
    section_id: str | None = None
    page_range: str | None = None
    evidence_text: str = ""
    coordinates: list[dict[str, Any]] = Field(default_factory=list)


class RuleBase(BaseModel):
    source: RuleSource = Field(default_factory=RuleSource)
    subject: str = ""
    condition: str = ""
    action: str = ""
    type: RuleType = "procedure"
    actor: str | None = None
    target: str | None = None
    deadline: str | None = None
    severity: str = "recommended"
    applicability: dict[str, Any] = Field(default_factory=dict)
    evidence_requirements: list[dict[str, Any]] = Field(default_factory=list)
    validation_method: str = "llm_judgement"
    references: list[dict[str, Any]] = Field(default_factory=list)
    mapping_status: str = "unmapped"
    options: list[RuleOption] = Field(default_factory=list)
    dependencies: list[RuleDependency] = Field(default_factory=list)
    next_rule_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    review_status: Literal["draft", "reviewed", "rejected"] = "draft"
    notes: str = ""


class RuleRead(RuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: int
    section_id: str | None = None


class RuleUpdate(RuleBase):
    pass


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    confidence: float


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str


class RuleGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class DocumentStats(BaseModel):
    total_sections: int = 0
    classified_sections: int = 0
    candidate_sections: int = 0
    llm_windows_completed: int = 0
    llm_windows_total: int = 0
    rules_extracted: int = 0
    option_rules: int = 0
    dependency_links: int = 0
    low_confidence_rules: int = 0
    reviewed_rules: int = 0
    draft_rules: int = 0
    rejected_rules: int = 0
    partial_failures: int = 0


class ExtractRulesResponse(BaseModel):
    document_id: int
    status: str
    rules_created: int


SectionRead.model_rebuild()


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1)
    contract_family: str = "ECC"
    jurisdiction: str = "Hong Kong"
    version: str = "2024"
    status: str = "active"


class CollectionRead(CollectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SourceDocumentCreate(BaseModel):
    collection_id: str
    doc_type: Literal["rulebook", "reference_clause", "template", "tender_submission"]
    name: str = Field(min_length=1)
    slot_id: str | None = None
    description: str = ""
    pdf_url: str = ""
    linked_document_id: int | None = None


class SourceDocumentRead(SourceDocumentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    text_review_status: str = "pending"
    text_verified_at: datetime | None = None
    content_fingerprint: str = ""
    mineru_artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TemplateFieldCreate(BaseModel):
    collection_id: str
    source_document_id: str | None = None
    template_doc: str
    field_key: str
    label: str
    anchor_text: str = ""
    input_type: str = "text"
    required: bool = True
    section_ref: str | None = None
    extraction_hint: str = ""
    check_intent: str = ""
    structured_schema: dict[str, Any] = Field(default_factory=dict)
    normalization: dict[str, Any] = Field(default_factory=dict)
    evidence_locator: dict[str, Any] = Field(default_factory=dict)
    part_ref: str = ""
    filled_by: str = "unknown"
    confidence: float = Field(default=0.0, ge=0, le=1)
    rationale: str = ""
    source_window: dict[str, Any] = Field(default_factory=dict)
    review_status: Literal["suggested", "approved", "rejected", "needs_edit"] = "suggested"


class TemplateFieldUpdate(BaseModel):
    label: str | None = None
    anchor_text: str | None = None
    input_type: str | None = None
    required: bool | None = None
    section_ref: str | None = None
    extraction_hint: str | None = None
    check_intent: str | None = None
    structured_schema: dict[str, Any] | None = None
    normalization: dict[str, Any] | None = None
    evidence_locator: dict[str, Any] | None = None
    part_ref: str | None = None
    filled_by: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = None
    source_window: dict[str, Any] | None = None
    review_status: Literal["suggested", "approved", "rejected", "needs_edit"] | None = None


class TemplateFieldRead(TemplateFieldCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExtractFieldsResponse(BaseModel):
    document_id: str
    fields_created: int


class TemplateFieldBulkReview(BaseModel):
    field_ids: list[str] = Field(default_factory=list)
    review_status: Literal["suggested", "approved", "rejected", "needs_edit"]


class RuleBulkReview(BaseModel):
    review_status: Literal["draft", "reviewed", "rejected"]


class DocumentMarkerRead(BaseModel):
    section_id: str
    marker_type: str
    text: str
    start: int
    end: int
    color: Literal["yellow", "blue"]
    confidence: float = Field(default=1.0, ge=0, le=1)


class FieldRuleMappingCreate(BaseModel):
    collection_id: str
    template_field_id: str
    rule_id: str | None = None
    source_type: str = "rule"
    check_type: Literal["deterministic", "llm", "hybrid", "manual"] = "llm"
    applicability_condition: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    rationale: str = ""
    review_status: Literal["suggested", "approved", "rejected", "needs_edit"] = "suggested"
    review_notes: str = ""


class FieldRuleMappingUpdate(BaseModel):
    check_type: Literal["deterministic", "llm", "hybrid", "manual"] | None = None
    applicability_condition: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = None
    review_status: Literal["suggested", "approved", "rejected", "needs_edit"] | None = None
    review_notes: str | None = None


class FieldRuleMappingRead(FieldRuleMappingCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    field_label: str = ""
    rule_subject: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class MappingRunCreate(BaseModel):
    collection_id: str
    template_source_ids: list[str] = Field(default_factory=list)
    rule_source_ids: list[str] = Field(default_factory=list)


class MappingRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    status: str
    llm_model: str
    windows_total: int
    windows_completed: int
    failures: int
    error_message: str | None = None
    artifact_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    completed_at: datetime | None = None


class TenderSubmissionCreate(BaseModel):
    collection_id: str
    name: str = Field(min_length=1)
    source_document_ids: list[str] = Field(default_factory=list)


class TenderSubmissionRead(TenderSubmissionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenderFieldEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    submission_id: str
    template_field_id: str
    value: str
    raw_text: str
    source_document: str
    page_or_section: str
    confidence: float
    review_status: str
    created_at: datetime | None = None


class EvidenceExtractionResponse(BaseModel):
    submission_id: str
    evidence_created: int


class CheckResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    submission_id: str
    template_field_id: str
    mapping_id: str | None = None
    result: str
    severity: str
    reason: str
    rule_evidence: str
    tender_evidence: str
    review_status: str
    created_at: datetime | None = None


class RunChecksResponse(BaseModel):
    submission_id: str
    results_created: int


class LibrarySlotCreate(BaseModel):
    collection_id: str
    name: str = Field(min_length=1, max_length=255)
    short_name: str = Field(default="", max_length=80)
    description: str = ""
    doc_type: Literal["rulebook", "reference_clause", "template", "tender_submission"] = "rulebook"
    required: bool = False
    grouping_level: int = Field(default=2, ge=1, le=3)
    sort_order: int = 0


class LibrarySlotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    short_name: str | None = Field(default=None, max_length=80)
    description: str | None = None
    doc_type: Literal["rulebook", "reference_clause", "template", "tender_submission"] | None = None
    required: bool | None = None
    grouping_level: int | None = Field(default=None, ge=1, le=3)
    sort_order: int | None = None


class LibrarySlotRead(LibrarySlotCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SourceDocumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    doc_type: Literal["rulebook", "reference_clause", "template", "tender_submission"] | None = None
    slot_id: str | None = None


class SourceImportUrl(BaseModel):
    collection_id: str
    name: str = Field(min_length=1, max_length=255)
    doc_type: Literal["rulebook", "reference_clause", "template", "tender_submission"]
    pdf_url: HttpUrl
    description: str = ""
    slot_id: str | None = None
    grouping_level: int = Field(default=2, ge=1, le=3)


class FieldRuleMappingCreateRequest(FieldRuleMappingCreate):
    pass


class ProcedureSetCreate(BaseModel):
    collection_id: str
    name: str = Field(min_length=1, max_length=255)
    template_source_ids: list[str] = Field(default_factory=list)
    rule_source_ids: list[str] = Field(default_factory=list)
    mapping_ids: list[str] = Field(default_factory=list)


class ProcedureSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    template_source_ids: list[str] | None = None
    rule_source_ids: list[str] | None = None
    mapping_ids: list[str] | None = None


class ProcedureSetRead(ProcedureSetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    status: str
    parent_id: str | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    summary: str
    before_json: dict[str, Any] = Field(default_factory=dict)
    after_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class DashboardSummary(BaseModel):
    total_documents: int = 0
    awaiting_text_review: int = 0
    awaiting_record_review: int = 0
    processing: int = 0
    failed: int = 0
    approved_procedure_sets: int = 0
    recent_activity: list[AuditEventRead] = Field(default_factory=list)
