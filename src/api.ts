import type {
  DocumentJob,
  DocumentStats,
  CheckResult,
  DocumentCollection,
  FieldRuleMapping,
  MappingRun,
  Rule,
  RuleGraph,
  RuntimeConfig,
  RuntimeConfigUpdate,
  Section,
  SourceDocument,
  TemplateField,
  TenderSubmission
} from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function createDocument(payload: {
  name: string;
  pdf_url: string;
  grouping_level?: number;
}) {
  return request<DocumentJob>("/api/documents", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getRuntimeConfig() {
  return request<RuntimeConfig>("/api/runtime-config");
}

export function saveRuntimeConfig(payload: RuntimeConfigUpdate) {
  return request<RuntimeConfig>("/api/runtime-config", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getDocuments() {
  return request<DocumentJob[]>("/api/documents");
}

export function getDocument(id: number) {
  return request<DocumentJob>(`/api/documents/${id}`);
}

export function getOutline(id: number) {
  return request<Section[]>(`/api/documents/${id}/outline`);
}

export function saveSection(documentId: number, sectionId: string, content: string) {
  return request<Section>(`/api/documents/${documentId}/sections/${sectionId}`, {
    method: "PUT",
    body: JSON.stringify({ content })
  });
}

export function extractRules(documentId: number) {
  return request<{ document_id: number; status: string; rules_created: number }>(
    `/api/documents/${documentId}/extract-rules`,
    { method: "POST" }
  );
}

export function getRules(documentId: number) {
  return request<Rule[]>(`/api/documents/${documentId}/rules`);
}

export function saveRule(rule: Rule) {
  return request<Rule>(`/api/rules/${rule.id}`, {
    method: "PUT",
    body: JSON.stringify(rule)
  });
}

export function getRuleGraph(documentId: number) {
  return request<RuleGraph>(`/api/documents/${documentId}/rule-graph`);
}

export function getDocumentStats(documentId: number) {
  return request<DocumentStats>(`/api/documents/${documentId}/stats`);
}

export function exportUrl(documentId: number, kind: string) {
  if (kind === "source-pdf") return `/api/documents/${documentId}/source-pdf?download=true`;
  return `/api/documents/${documentId}/exports/${kind}`;
}

export function createCollection(payload: {
  name: string;
  contract_family?: string;
  jurisdiction?: string;
  version?: string;
  status?: string;
}) {
  return request<DocumentCollection>("/api/collections", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getCollections() {
  return request<DocumentCollection[]>("/api/collections");
}

export function deleteCollection(id: string) {
  return request<{ deleted: boolean }>(`/api/collections/${id}`, { method: "DELETE" });
}

export function createSourceDocument(payload: {
  collection_id: string;
  doc_type: SourceDocument["doc_type"];
  name: string;
  pdf_url?: string;
  linked_document_id?: number | null;
}) {
  return request<SourceDocument>("/api/source-documents", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getSourceDocuments(params?: { collection_id?: string; doc_type?: string }) {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    });
  }
  const query = qs.toString();
  return request<SourceDocument[]>(`/api/source-documents${query ? `?${query}` : ""}`);
}

export function deleteSourceDocument(id: string) {
  return request<{ deleted: boolean }>(`/api/source-documents/${id}`, { method: "DELETE" });
}

export function verifySourceDocument(id: string) {
  return request<{ source_document_id: string; rules_reviewed?: number; fields_approved?: number }>(
    `/api/source-documents/${id}/verify`,
    { method: "POST" }
  );
}

export function extractTemplateFields(documentId: string) {
  return request<{ document_id: string; fields_created: number }>(`/api/templates/${documentId}/extract-fields`, {
    method: "POST"
  });
}

export function getTemplateFields(params?: { collection_id?: string; template_doc?: string; review_status?: string }) {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    });
  }
  const query = qs.toString();
  return request<TemplateField[]>(`/api/template-fields${query ? `?${query}` : ""}`);
}

export function updateTemplateField(id: string, data: Partial<TemplateField>) {
  return request<TemplateField>(`/api/template-fields/${id}`, {
    method: "PUT",
    body: JSON.stringify(data)
  });
}

export function deleteTemplateField(id: string) {
  return request<{ deleted: boolean }>(`/api/template-fields/${id}`, { method: "DELETE" });
}

export function createMappingRun(collectionId: string) {
  return request<MappingRun>("/api/mapping-runs", {
    method: "POST",
    body: JSON.stringify({ collection_id: collectionId })
  });
}

export function getFieldRuleMappings(params?: { collection_id?: string; field_id?: string; review_status?: string }) {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    });
  }
  const query = qs.toString();
  return request<FieldRuleMapping[]>(`/api/field-rule-mappings${query ? `?${query}` : ""}`);
}

export function updateFieldRuleMapping(id: string, data: Partial<FieldRuleMapping>) {
  return request<FieldRuleMapping>(`/api/field-rule-mappings/${id}`, {
    method: "PUT",
    body: JSON.stringify(data)
  });
}

export function createTenderSubmission(payload: {
  collection_id: string;
  name: string;
  source_document_ids: string[];
}) {
  return request<TenderSubmission>("/api/tender-submissions", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getTenderSubmissions(params?: { collection_id?: string }) {
  const qs = new URLSearchParams();
  if (params?.collection_id) qs.set("collection_id", params.collection_id);
  const query = qs.toString();
  return request<TenderSubmission[]>(`/api/tender-submissions${query ? `?${query}` : ""}`);
}

export function extractTenderEvidence(id: string) {
  return request<{ submission_id: string; evidence_created: number }>(
    `/api/tender-submissions/${id}/extract-evidence`,
    { method: "POST" }
  );
}

export function runTenderChecks(id: string) {
  return request<{ submission_id: string; results_created: number }>(
    `/api/tender-submissions/${id}/run-checks`,
    { method: "POST" }
  );
}

export function getTenderResults(id: string) {
  return request<CheckResult[]>(`/api/tender-submissions/${id}/results`);
}

export function deleteTenderSubmission(id: string) {
  return request<{ deleted: boolean }>(`/api/tender-submissions/${id}`, { method: "DELETE" });
}
