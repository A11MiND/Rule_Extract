export interface DocumentJob {
  id: number;
  name: string;
  pdf_url: string;
  contract_family: string;
  grouping_level: number;
  status: string;
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

// ── Phase 0 — Knowledge Base ──────────────────────────────

export interface KnowledgeItem {
  id: string;
  source_type: string;
  source_document: string;
  source_url?: string | null;
  title: string;
  content: string;
  summary?: string | null;
  clause_number?: string | null;
  clause_category?: string | null;
  parent_document?: string | null;
  clause_remarks?: string | null;
  template_name?: string | null;
  section_number?: string | null;
  field_definitions?: string | null;
  circular_number?: string | null;
  issuing_body?: string | null;
  effective_date?: string | null;
  supersedes?: string | null;
  department?: string | null;
  chapter?: string | null;
  section_ref?: string | null;
  version: string;
  is_active: boolean;
  embedding_id?: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface KBStats {
  total: number;
  active: number;
  inactive: number;
  by_type: Record<string, number>;
}

// ── Phase 1 — Mappings ───────────────────────────────────

export interface Mapping {
  id: string;
  knowledge_item_id: string;
  knowledge_item_title: string;
  rule_id?: string | null;
  rule_subject?: string | null;
  template_section_id?: string | null;
  template_section_title: string;
  mapping_type: string;
  confidence: number;
  rationale: string;
  human_confirmed: boolean;
  human_decision?: string | null;
  created_at: string;
}

export interface MappingStats {
  total: number;
  confirmed: number;
  pending: number;
  rejected: number;
}

// ── Phase 2 — Vetting ────────────────────────────────────

export interface VettingRun {
  id: string;
  title: string;
  template_id: string;
  status: string;
  source_file_path?: string | null;
  source_file_type?: string | null;
  total_sections: number;
  completed_sections: number;
  total_findings: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface VettingFinding {
  id: string;
  vetting_run_id: string;
  section_id: string;
  skill: string;
  rule_id?: string | null;
  verdict: string;
  severity: string;
  title: string;
  detail: string;
  tender_excerpt?: string | null;
  rule_excerpt?: string | null;
  human_reviewed: boolean;
  human_verdict?: string | null;
  human_comment?: string | null;
  created_at: string;
}

// ── Phase 3 — Chat ───────────────────────────────────────

export interface ChatSession {
  id: string;
  title: string;
  messages?: ChatMessage[];
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations: Citation[];
  token_count?: number | null;
  created_at: string;
}

export interface Citation {
  kb_id: string;
  title: string;
  excerpt: string;
}
