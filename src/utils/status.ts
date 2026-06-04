import type { DocumentStatus } from "../types";

const STATUS_LABELS: Record<DocumentStatus, string> = {
  idle: "Idle",
  created: "Created",
  mineru_queued: "PDF Queued",
  mineru_submitting: "Submitting PDF",
  mineru_processing: "Converting PDF",
  markdown_ready: "Text Ready",
  rule_extraction_queued: "Extracting Rules",
  extracting_rules: "Extracting Rules",
  rules_extracted: "Rules Extracted",
  rules_verified: "Rules Confirmed",
  rule_extraction_failed: "Rule Extraction Failed",
  mineru_failed: "PDF Conversion Failed",
  fields_extracted: "Fields Extracted",
  fields_verified: "Fields Confirmed",
  evidence_extracted: "Evidence Extracted",
  checked: "Checked",
};

export function labelStatus(status: DocumentStatus): string {
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
