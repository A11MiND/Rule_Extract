export type DocumentStatus =
  | "idle" | "created"
  | "mineru_queued" | "mineru_submitting" | "mineru_processing" | "markdown_ready"
  | "rule_extraction_queued" | "extracting_rules" | "rules_extracted"
  | "rules_verified" | "rule_extraction_failed" | "mineru_failed"
  | "fields_extracted" | "fields_verified"
  | "evidence_extracted" | "checked";

export interface DocumentJob {
  id: number;
  name: string;
  pdf_url: string;
  contract_family: string;
  grouping_level: number;
  status: DocumentStatus;
  mineru_task_id?: string | null;
  mineru_state?: string | null;
  error_message?: string | null;
  markdown_path?: string | null;
  artifact_manifest: Record<string, unknown>;
}

export interface RuntimeConfig {
  mineru_api_base: string;
  mineru_model_version: string;
  mineru_configured: boolean;
  llm_provider: string;
  llm_api_base: string;
  llm_model: string;
  llm_configured: boolean;
  llm_concurrency: number;
  max_llm_concurrency: number;
  extraction_prompt: string;
  default_grouping_level: number;
}

export interface RuntimeConfigUpdate {
  mineru_api_base?: string;
  mineru_api_token?: string;
  mineru_model_version?: string;
  llm_provider?: string;
  llm_api_base?: string;
  llm_api_key?: string;
  llm_model?: string;
  llm_concurrency?: number;
  extraction_prompt?: string;
  default_grouping_level?: number;
}

export interface DocumentStats {
  total_sections: number;
  classified_sections: number;
  candidate_sections: number;
  llm_windows_completed: number;
  llm_windows_total: number;
  rules_extracted: number;
  option_rules: number;
  dependency_links: number;
  low_confidence_rules: number;
  reviewed_rules: number;
  draft_rules: number;
  rejected_rules: number;
  partial_failures: number;
}

export interface Section {
  id: string;
  document_id: number;
  position: number;
  level: number;
  title: string;
  heading_path: string[];
  content: string;
  page_range?: string | null;
  coordinates: Record<string, unknown>[];
  classification?: string | null;
  classification_confidence?: number | null;
  children: Section[];
}

export interface RuleOption {
  label: string;
  condition: string;
  action: string;
  next_rule_ids: string[];
  referenced_sections: string[];
}

export interface RuleDependency {
  type: "requires" | "leads_to" | "alternative_to" | "references";
  rule_id: string;
  reason: string;
}

export interface RuleSource {
  heading_path: string[];
  section_id?: string | null;
  page_range?: string | null;
  evidence_text: string;
  coordinates: Record<string, unknown>[];
}

export interface Rule {
  id: string;
  document_id: number;
  section_id?: string | null;
  source: RuleSource;
  subject: string;
  condition: string;
  action: string;
  type: string;
  actor?: string | null;
  target?: string | null;
  deadline?: string | null;
  severity: string;
  applicability: Record<string, unknown>;
  evidence_requirements: Record<string, unknown>[];
  validation_method: string;
  references: Record<string, unknown>[];
  mapping_status: string;
  options: RuleOption[];
  dependencies: RuleDependency[];
  next_rule_ids: string[];
  confidence: number;
  review_status: "draft" | "reviewed" | "rejected";
  notes: string;
}

export interface RuleGraph {
  nodes: { id: string; label: string; type: string; confidence: number }[];
  edges: { source: string; target: string; label: string }[];
}


export interface DocumentCollection {
  id: string;
  name: string;
  contract_family: string;
  jurisdiction: string;
  version: string;
  status: DocumentStatus;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SourceDocument {
  id: string;
  collection_id: string;
  slot_id?: string | null;
  doc_type: "rulebook" | "reference_clause" | "template" | "tender_submission";
  name: string;
  description: string;
  pdf_url: string;
  status: DocumentStatus;
  text_review_status: string;
  text_verified_at?: string | null;
  content_fingerprint: string;
  mineru_artifacts: Record<string, unknown>;
  linked_document_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TemplateField {
  id: string;
  collection_id: string;
  source_document_id?: string | null;
  template_doc: string;
  field_key: string;
  label: string;
  anchor_text: string;
  input_type: string;
  required: boolean;
  section_ref?: string | null;
  extraction_hint: string;
  check_intent: string;
  structured_schema: Record<string, unknown>;
  normalization: Record<string, unknown>;
  evidence_locator: EvidenceLocator;
  part_ref: string;
  filled_by: string;
  confidence: number;
  rationale: string;
  source_window: Record<string, unknown>;
  review_status: "suggested" | "approved" | "rejected" | "needs_edit";
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DocumentMarker {
  section_id: string;
  marker_type: string;
  text: string;
  start: number;
  end: number;
  color: "yellow" | "blue";
  confidence: number;
}

export interface FieldRuleMapping {
  id: string;
  collection_id: string;
  template_field_id: string;
  rule_id?: string | null;
  source_type: string;
  check_type: "deterministic" | "llm" | "hybrid" | "manual";
  applicability_condition: string;
  confidence: number;
  rationale: string;
  review_status: "suggested" | "approved" | "rejected" | "needs_edit";
  review_notes: string;
  field_label: string;
  rule_subject?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MappingRun {
  id: string;
  collection_id: string;
  status: DocumentStatus;
  llm_model: string;
  windows_total: number;
  windows_completed: number;
  failures: number;
  error_message?: string | null;
  artifact_json: Record<string, unknown>;
  created_at?: string | null;
  completed_at?: string | null;
}

export interface TenderSubmission {
  id: string;
  collection_id: string;
  name: string;
  status: DocumentStatus;
  source_document_ids: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TenderFieldEvidence {
  id: string;
  submission_id: string;
  template_field_id: string;
  value: string;
  raw_text: string;
  source_document: string;
  page_or_section: string;
  confidence: number;
  review_status: string;
  created_at?: string | null;
}

export interface CheckResult {
  id: string;
  submission_id: string;
  template_field_id: string;
  mapping_id?: string | null;
  result: "pass" | "fail" | "needs_review" | "not_applicable";
  severity: string;
  reason: string;
  rule_evidence: string;
  tender_evidence: string;
  review_status: string;
  created_at?: string | null;
}

export interface EvidenceLocator {
  source_document_id?: string | null;
  document_id?: number | null;
  section_id?: string | null;
  page_range?: string | null;
  coordinates?: Record<string, unknown>[];
  anchor_text?: string;
}

export interface LibrarySlot {
  id: string;
  collection_id: string;
  name: string;
  short_name: string;
  description: string;
  doc_type: SourceDocument["doc_type"];
  required: boolean;
  grouping_level: number;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProcedureSet {
  id: string;
  collection_id: string;
  name: string;
  version: number;
  status: "draft" | "approved";
  template_source_ids: string[];
  rule_source_ids: string[];
  mapping_ids: string[];
  parent_id?: string | null;
  approved_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AuditEvent {
  id: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  summary: string;
  before_json: Record<string, unknown>;
  after_json: Record<string, unknown>;
  created_at?: string | null;
}

export interface DashboardSummary {
  total_documents: number;
  awaiting_text_review: number;
  awaiting_record_review: number;
  processing: number;
  failed: number;
  approved_procedure_sets: number;
  recent_activity: AuditEvent[];
}
