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


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pdf_url: str
    contract_family: str
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
