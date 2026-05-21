import type {
  ContractFamily,
  DocumentJob,
  DocumentStats,
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
  contract_family: ContractFamily;
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
  return `/api/documents/${documentId}/exports/${kind}`;
}
