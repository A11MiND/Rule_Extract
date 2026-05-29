from __future__ import annotations

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
    classification: str | None = None
    classification_confidence: float | None = None
    children: list["SectionRead"] = Field(default_factory=list)


class SectionUpdate(BaseModel):
    content: str


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


# ──────────────────────────────────────────────
# Phase 0 — Knowledge Base
# ──────────────────────────────────────────────

SourceType = Literal["clause", "template_spec", "policy", "department_rule"]
MappingType = Literal["rule_to_section", "clause_to_section", "policy_to_section"]


class KnowledgeItemCreate(BaseModel):
    id: str = Field(min_length=1)
    source_type: SourceType
    source_document: str = Field(min_length=1)
    source_url: str | None = None
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    summary: str | None = None
    clause_number: str | None = None
    clause_category: str | None = None
    parent_document: str | None = None
    clause_remarks: str | None = None
    template_name: str | None = None
    section_number: str | None = None
    field_definitions: str | None = None
    circular_number: str | None = None
    issuing_body: str | None = None
    effective_date: str | None = None
    supersedes: str | None = None
    department: str | None = None
    chapter: str | None = None
    section_ref: str | None = None
    version: str = "1.0"
    is_active: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class KnowledgeItemUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    is_active: bool | None = None
    metadata_json: dict[str, Any] | None = None


class KnowledgeItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_document: str
    source_url: str | None = None
    title: str
    content: str
    summary: str | None = None
    clause_number: str | None = None
    clause_category: str | None = None
    parent_document: str | None = None
    clause_remarks: str | None = None
    template_name: str | None = None
    section_number: str | None = None
    field_definitions: str | None = None
    circular_number: str | None = None
    issuing_body: str | None = None
    effective_date: str | None = None
    supersedes: str | None = None
    department: str | None = None
    chapter: str | None = None
    section_ref: str | None = None
    version: str = "1.0"
    is_active: bool = True
    embedding_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class KnowledgeItemStats(BaseModel):
    total: int = 0
    active: int = 0
    inactive: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    status: str
    task_id: str | None = None


class IngestStatus(BaseModel):
    status: str
    progress: str = ""
    errors: int = 0


# ──────────────────────────────────────────────
# Phase 1 — Mappings
# ──────────────────────────────────────────────


class MappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    knowledge_item_id: str
    knowledge_item_title: str = ""
    rule_id: str | None = None
    rule_subject: str | None = None
    template_section_id: str | None = None
    template_section_title: str = ""
    mapping_type: str
    confidence: float
    rationale: str = ""
    human_confirmed: bool = False
    human_decision: str | None = None
    created_at: str | None = None


class MappingUpdate(BaseModel):
    human_confirmed: bool
    human_decision: Literal["confirmed", "rejected"]
    confirmed_by: str | None = None


class MappingStats(BaseModel):
    total: int = 0
    confirmed: int = 0
    pending: int = 0
    rejected: int = 0


# ──────────────────────────────────────────────
# Phase 2 — Vetting
# ──────────────────────────────────────────────


class VettingRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    template_id: str
    status: str
    source_file_path: str | None = None
    source_file_type: str | None = None
    total_sections: int = 0
    completed_sections: int = 0
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class VettingFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    vetting_run_id: str
    section_id: str
    skill: str
    rule_id: str | None = None
    verdict: str
    severity: str
    title: str
    detail: str
    tender_excerpt: str | None = None
    rule_excerpt: str | None = None
    human_reviewed: bool = False
    human_verdict: str | None = None
    human_comment: str | None = None
    created_at: str | None = None


class VettingFindingUpdate(BaseModel):
    human_reviewed: bool | None = None
    human_verdict: Literal["confirmed", "dismissed", "commented"] | None = None
    human_comment: str | None = None


class VettingRunListParams(BaseModel):
    status: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class VettingFindingsParams(BaseModel):
    skill: str | None = None
    severity: str | None = None
    section_id: str | None = None
    verdict: str | None = None
    human_reviewed: bool | None = None
    limit: int = Field(default=200, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# ──────────────────────────────────────────────
# Phase 3 — Chat
# ──────────────────────────────────────────────


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None


class ChatSessionDetail(ChatSessionRead):
    messages: list["ChatMessageRead"] = Field(default_factory=list)


class Citation(BaseModel):
    kb_id: str
    title: str
    excerpt: str = ""


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    token_count: int | None = None
    created_at: str | None = None


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1)


# ──────────────────────────────────────────────
# Phase 0 — Ingestion Log
# ──────────────────────────────────────────────


class IngestionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_document: str
    source_type: str
    status: str
    items_created: int = 0
    items_updated: int = 0
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
