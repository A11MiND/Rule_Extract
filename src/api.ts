import type {
  DocumentJob,
  DocumentMarker,
  DocumentStats,
  DocumentStatus,
  CheckResult,
  AuditEvent,
  DashboardSummary,
  DocumentCollection,
  FieldRuleMapping,
  LibrarySlot,
  MappingRun,
  ProcedureSet,
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

export function deleteDocument(id: number) {
  return request<{ deleted: boolean }>(`/api/documents/${id}`, { method: "DELETE" });
}

export function getOutline(id: number) {
  return request<Section[]>(`/api/documents/${id}/outline`);
}

export function getDocumentMarkers(id: number, role = "auto") {
  const qs = new URLSearchParams({ role });
  return request<DocumentMarker[]>(`/api/documents/${id}/markers?${qs.toString()}`);
}

export function saveSection(documentId: number, sectionId: string, content: string) {
  return request<Section>(`/api/documents/${documentId}/sections/${sectionId}`, {
    method: "PUT",
    body: JSON.stringify({ content })
  });
}

export function patchSection(documentId: number, sectionId: string, data: { title?: string; content?: string }) {
  return request<Section>(`/api/documents/${documentId}/sections/${sectionId}`, {
    method: "PATCH",
    body: JSON.stringify(data)
  });
}

export function extractRules(documentId: number) {
  return request<{ document_id: number; status: DocumentStatus; rules_created: number }>(
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
  slot_id?: string | null;
  description?: string;
  pdf_url?: string;
  linked_document_id?: number | null;
}) {
  return request<SourceDocument>("/api/source-documents", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function importSourceDocumentUrl(payload: {
  collection_id: string;
  name: string;
  doc_type: SourceDocument["doc_type"];
  pdf_url: string;
  description?: string;
  slot_id?: string | null;
  grouping_level?: number;
}) {
  return request<SourceDocument>("/api/source-documents/import-url", {
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

export function getSourceDocument(id: string) {
  return request<SourceDocument>(`/api/source-documents/${id}`);
}

export function updateSourceDocument(id: string, data: Partial<Pick<SourceDocument, "name" | "description" | "doc_type" | "slot_id">>) {
  return request<SourceDocument>(`/api/source-documents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data)
  });
}

export function confirmSourceText(id: string) {
  return request<SourceDocument>(`/api/source-documents/${id}/confirm-text`, { method: "POST" });
}

export function bulkReviewSourceRules(id: string, reviewStatus: Rule["review_status"]) {
  return request<{ updated: number; review_status: Rule["review_status"] }>(`/api/source-documents/${id}/rules/bulk-review`, {
    method: "POST",
    body: JSON.stringify({ review_status: reviewStatus })
  });
}

export function bulkReviewSourceFields(id: string, reviewStatus: TemplateField["review_status"]) {
  return request<{ updated: number; review_status: TemplateField["review_status"] }>(`/api/source-documents/${id}/fields/bulk-review`, {
    method: "POST",
    body: JSON.stringify({ field_ids: [], review_status: reviewStatus })
  });
}

export function deleteSourceDocument(id: string) {
  return request<{ deleted: boolean }>(`/api/source-documents/${id}`, { method: "DELETE" });
}

export function verifySourceDocument(id: string) {
  return request<{ source_document_id: string; rules_reviewed?: number; fields_approved?: number; fields_rejected?: number }>(
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

export function createTemplateField(payload: Omit<TemplateField, "id" | "created_at" | "updated_at">) {
  return request<TemplateField>("/api/template-fields", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateTemplateField(id: string, data: Partial<TemplateField>) {
  return request<TemplateField>(`/api/template-fields/${id}`, {
    method: "PUT",
    body: JSON.stringify(data)
  });
}

export function bulkReviewTemplateFields(fieldIds: string[], reviewStatus: TemplateField["review_status"]) {
  return request<{ updated: number; review_status: TemplateField["review_status"] }>("/api/template-fields/bulk-review", {
    method: "POST",
    body: JSON.stringify({ field_ids: fieldIds, review_status: reviewStatus })
  });
}

export function deleteTemplateField(id: string) {
  return request<{ deleted: boolean }>(`/api/template-fields/${id}`, { method: "DELETE" });
}

export function createMappingRun(collectionId: string, templateSourceIds: string[] = [], ruleSourceIds: string[] = []) {
  return request<MappingRun>("/api/mapping-runs", {
    method: "POST",
    body: JSON.stringify({ collection_id: collectionId, template_source_ids: templateSourceIds, rule_source_ids: ruleSourceIds })
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

export function createFieldRuleMapping(payload: Omit<FieldRuleMapping, "id" | "field_label" | "rule_subject" | "created_at" | "updated_at">) {
  return request<FieldRuleMapping>("/api/field-rule-mappings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function deleteFieldRuleMapping(id: string) {
  return request<{ deleted: boolean }>(`/api/field-rule-mappings/${id}`, { method: "DELETE" });
}

export function getLibrarySlots(collectionId?: string) {
  const query = collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : "";
  return request<LibrarySlot[]>(`/api/library-slots${query}`);
}

export function createLibrarySlot(payload: Omit<LibrarySlot, "id" | "created_at" | "updated_at">) {
  return request<LibrarySlot>("/api/library-slots", { method: "POST", body: JSON.stringify(payload) });
}

export function updateLibrarySlot(id: string, data: Partial<LibrarySlot>) {
  return request<LibrarySlot>(`/api/library-slots/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export function deleteLibrarySlot(id: string) {
  return request<{ deleted: boolean }>(`/api/library-slots/${id}`, { method: "DELETE" });
}

export function getProcedureSets(collectionId?: string) {
  const query = collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : "";
  return request<ProcedureSet[]>(`/api/procedure-sets${query}`);
}

export function createProcedureSet(payload: Pick<ProcedureSet, "collection_id" | "name" | "template_source_ids" | "rule_source_ids" | "mapping_ids">) {
  return request<ProcedureSet>("/api/procedure-sets", { method: "POST", body: JSON.stringify(payload) });
}

export function updateProcedureSet(id: string, data: Partial<ProcedureSet>) {
  return request<ProcedureSet>(`/api/procedure-sets/${id}`, { method: "PATCH", body: JSON.stringify(data) });
}

export function approveProcedureSet(id: string) {
  return request<ProcedureSet>(`/api/procedure-sets/${id}/approve`, { method: "POST" });
}

export function cloneProcedureSet(id: string) {
  return request<ProcedureSet>(`/api/procedure-sets/${id}/clone`, { method: "POST" });
}

export function getAuditEvents(limit = 100) {
  return request<AuditEvent[]>(`/api/audit-events?limit=${limit}`);
}

export function getDashboardSummary(collectionId?: string) {
  const query = collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : "";
  return request<DashboardSummary>(`/api/dashboard-summary${query}`);
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
