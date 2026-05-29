import type {
  DocumentJob,
  DocumentStats,
  KBStats,
  KnowledgeItem,
  Rule,
  RuleGraph,
  RuntimeConfig,
  RuntimeConfigUpdate,
  Section
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

// ── Knowledge Base (Phase 0) ─────────────────────────────

export function getKnowledgeItems(params?: {
  source_type?: string;
  parent_document?: string;
  template_name?: string;
  is_active?: boolean;
  search?: string;
  offset?: number;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    });
  }
  const query = qs.toString();
  return request<KnowledgeItem[]>(`/api/knowledge${query ? `?${query}` : ""}`);
}

export function getKnowledgeStats() {
  return request<KBStats>("/api/knowledge/stats");
}

export function getKnowledgeItem(id: string) {
  return request<KnowledgeItem>(`/api/knowledge/${id}`);
}

export function updateKnowledgeItem(id: string, data: Partial<KnowledgeItem>) {
  return request<KnowledgeItem>(`/api/knowledge/${id}`, {
    method: "PUT",
    body: JSON.stringify(data)
  });
}

export function triggerIngestion() {
  return request<{ status: string; task_id?: string }>("/api/knowledge/ingest", {
    method: "POST"
  });
}
