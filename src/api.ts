import type { ContractFamily, DocumentJob, Rule, RuleGraph, Section } from "./types";

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
