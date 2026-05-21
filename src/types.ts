export type ContractFamily = "ECC" | "TSC" | "Generic";

export interface DocumentJob {
  id: number;
  name: string;
  pdf_url: string;
  contract_family: ContractFamily;
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
