import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Edit3,
  FileText,
  GitBranch,
  Loader2,
  Play,
  Save,
  SearchCheck,
  Settings,
  X,
  XCircle,
  Zap
} from "lucide-react";
import {
  bulkReviewSourceRules,
  confirmSourceText,
  createLibrarySlot,
  deleteLibrarySlot,
  extractTemplateFields,
  extractRules,
  exportUrl,
  getCollections,
  getDocument,
  getDocumentMarkers,
  getDocumentStats,
  getDocuments,
  getOutline,
  getRuleGraph,
  getRules,
  getRuntimeConfig,
  getLibrarySlots,
  getSourceDocuments,
  patchSection,
  saveRule,
  saveRuntimeConfig,
  updateLibrarySlot
} from "./api";
import { Sidebar } from "./components/Sidebar";
import type { NavPage } from "./components/Sidebar";
import { ReviewConfidence, ReviewStatusBadge, ReviewTypeChip } from "./components/ReviewPrimitives";
import { Alert, Button, Layout, Popconfirm } from "antd";
import { usePolling } from "./hooks/usePolling";
import { labelStatus } from "./utils/status";
import type {
  DocumentCollection,
  DocumentJob,
  DocumentMarker,
  DocumentStats,
  DocumentStatus,
  LibrarySlot,
  Rule,
  RuleGraph,
  RuntimeConfig,
  RuntimeConfigUpdate,
  Section,
  SourceDocument
} from "./types";

const READY_STATUSES = new Set([
  "markdown_ready",
  "rule_extraction_queued",
  "extracting_rules",
  "rules_extracted",
  "rule_extraction_failed"
]);
const TERMINAL_STATUSES = new Set(["mineru_failed", "rule_extraction_failed", "rules_extracted"]);
type View = NavPage;
type DocumentView = "queue" | "document-review" | "rule-review";
const WORKBENCH_VIEWS: View[] = ["dashboard", "sources", "queue", "field-review", "mapping-review", "submissions", "results", "activity"];
const ProfessionalWorkbench = lazy(() =>
  import("./components/ProfessionalWorkbench").then((module) => ({ default: module.ProfessionalWorkbench }))
);

export function App() {
  const [documentJob, setDocumentJob] = useState<DocumentJob | null>(null);
  const [documents, setDocuments] = useState<DocumentJob[]>([]);
  const [sourceDocuments, setSourceDocuments] = useState<SourceDocument[]>([]);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null);
  const [stats, setStats] = useState<DocumentStats | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [documentMarkers, setDocumentMarkers] = useState<DocumentMarker[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [graph, setGraph] = useState<RuleGraph>({ nodes: [], edges: [] });
  const initialRoute = useMemo(() => viewFromPath(window.location.pathname), []);
  const [activeView, setActiveView] = useState<View>(initialRoute.view);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [toasts, setToasts] = useState<Array<{ id: number; text: string; type: "success" | "info" }>>([]);
  const [workflowRefreshKey, setWorkflowRefreshKey] = useState(0);
  const toastIdRef = useRef(0);
  const previousStatusRef = useRef<string | null>(null);
  const routeSourceIdRef = useRef<string | null>(initialRoute.sourceId);

  function showToast(text: string, type: "success" | "info" = "success") {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, text, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }

  const loadDocuments = useCallback(async () => {
    const [nextDocuments, nextSourceDocuments] = await Promise.all([
      getDocuments(),
      getSourceDocuments().catch(() => [])
    ]);
    setDocuments(nextDocuments);
    setSourceDocuments(nextSourceDocuments);
    return nextDocuments;
  }, []);

  useEffect(() => {
    getRuntimeConfig().then(setRuntimeConfig).catch(() => undefined);
    loadDocuments()
      .then((documents) => {
        if (documents.length) {
          const latestDocument = documents[0];
          setDocumentJob(latestDocument);
        }
      })
      .catch(() => undefined)
      .finally(() => setInitialLoading(false));
  }, [loadDocuments]);

  useEffect(() => {
    const sourceId = routeSourceIdRef.current;
    if (!sourceId) return;
    const source = sourceDocuments.find((item) => item.id === sourceId);
    const selected = documents.find((item) => item.id === source?.linked_document_id);
    if (!selected || documentJob?.id === selected.id) return;
    setDocumentJob(selected);
    previousStatusRef.current = selected.status;
    if (READY_STATUSES.has(selected.status)) refreshDocumentData(selected.id);
  }, [documentJob?.id, documents, sourceDocuments]);

  // Poll document job status
  const isDocumentPolling = documentJob !== null && !TERMINAL_STATUSES.has(documentJob.status);
  usePolling({
    enabled: isDocumentPolling,
    fetcher: () => getDocument(documentJob!.id),
    onResult: (next) => {
      setDocumentJob(next);
      setDocuments((current) => current.map((doc) => (doc.id === next.id ? next : doc)));
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  useEffect(() => {
    if (!documentJob || !READY_STATUSES.has(documentJob.status)) {
      return;
    }
    refreshDocumentData(documentJob.id);
  }, [documentJob?.id, documentJob?.status]);

  useEffect(() => {
    const previousStatus = previousStatusRef.current;
    const nextStatus = documentJob?.status ?? null;
    if (activeView === "queue" && previousStatus && previousStatus !== "markdown_ready" && nextStatus === "markdown_ready") {
      setActiveView("document-review");
    }
    previousStatusRef.current = nextStatus;
  }, [activeView, documentJob?.status]);

  // Poll document stats
  const isStatsPolling = documentJob !== null && !TERMINAL_STATUSES.has(documentJob.status);
  usePolling({
    enabled: isStatsPolling,
    fetcher: () => getDocumentStats(documentJob!.id),
    onResult: setStats,
    onError: (err) => setError((prev) => prev || (err instanceof Error ? err.message : String(err))),
    interval: 2000,
    jitterRange: 600,
  });

  // Poll rules extraction progress
  const isExtractingRules = documentJob !== null && ["rule_extraction_queued", "extracting_rules"].includes(documentJob.status);
  usePolling({
    enabled: isExtractingRules,
    fetcher: async () => {
      const [nextRules, nextGraph, nextStats] = await Promise.all([
        getRules(documentJob!.id).catch(() => []),
        getRuleGraph(documentJob!.id).catch(() => ({ nodes: [], edges: [] })),
        getDocumentStats(documentJob!.id).catch(() => null),
      ]);
      return { nextRules, nextGraph, nextStats };
    },
    onResult: ({ nextRules, nextGraph, nextStats }) => {
      setRules(nextRules);
      setGraph(nextGraph);
      if (nextStats) setStats(nextStats);
    },
  });

  async function refreshDocumentData(documentId: number) {
    const [outline, nextRules, nextGraph, nextStats] = await Promise.all([
      getOutline(documentId),
      getRules(documentId).catch(() => []),
      getRuleGraph(documentId).catch(() => ({ nodes: [], edges: [] })),
      getDocumentStats(documentId).catch(() => null)
    ]);
    const markers = await getDocumentMarkers(documentId).catch(() => []);
    setSections(outline);
    setDocumentMarkers(markers);
    setRules(nextRules);
    setGraph(nextGraph);
    if (nextStats) setStats(nextStats);
  }

  async function handleSaveRuntimeConfig(payload: RuntimeConfigUpdate) {
    setBusy(true);
    setError("");
    try {
      const saved = await saveRuntimeConfig(payload);
      setRuntimeConfig(saved);
      showToast("API configuration saved", "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save runtime config");
    } finally {
      setBusy(false);
    }
  }

  const resetDocumentData = useCallback(() => {
    setSections([]);
    setDocumentMarkers([]);
    setRules([]);
    setGraph({ nodes: [], edges: [] });
    setStats(null);
  }, []);

  async function handleExtract() {
    if (!documentJob) return;
    if (!canExtractRulesForSource(sourceForDocument(documentJob.id, sourceDocuments))) {
      setError("This document is a tender template. Use Extract Fields in the Template workflow instead of rule extraction.");
      return;
    }
    setBusy(true);
    setError("");
    setRules([]);
    setGraph({ nodes: [], edges: [] });
    try {
      await extractRules(documentJob.id);
      showToast("Rule extraction started — tracking progress below", "info");
      setActiveView("queue");
      const [nextDocument, nextRules, nextGraph] = await Promise.all([
        getDocument(documentJob.id),
        getRules(documentJob.id),
        getRuleGraph(documentJob.id)
      ]);
      setDocumentJob(nextDocument);
      setRules(nextRules);
      setGraph(nextGraph);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rule extraction failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleOpenDocument(documentId: number, view: DocumentView) {
    if (!documentId) return;
    setBusy(true);
    setError("");
    try {
      const selected = await getDocument(documentId);
      routeSourceIdRef.current = sourceForDocument(documentId, sourceDocuments)?.id ?? null;
      setDocumentJob(selected);
      previousStatusRef.current = selected.status;
      setActiveView(view);
      resetDocumentData();
      if (READY_STATUSES.has(selected.status)) {
        refreshDocumentData(selected.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to open document");
    } finally {
      setBusy(false);
    }
  }

  const canExtractRules =
    documentJob &&
    !WORKBENCH_VIEWS.includes(activeView) &&
    canExtractRulesForSource(sourceForDocument(documentJob.id, sourceDocuments)) &&
    (documentJob.status === "markdown_ready" ||
      documentJob.status === "rule_extraction_failed" ||
      (documentJob.status === "rules_extracted" && (stats?.rules_extracted ?? rules.length) === 0));
  const extractButtonLabel = documentJob?.status === "markdown_ready" ? "Extract Rules" : "Retry Extract Rules";
  const apiReady = Boolean(runtimeConfig?.mineru_configured && runtimeConfig?.llm_configured);
  const currentSource = documentJob ? sourceForDocument(documentJob.id, sourceDocuments) : null;
  const currentDisplayStatus = documentJob ? displayStatusForDocument(documentJob, currentSource) : "idle";

  useEffect(() => {
    if (currentSource) routeSourceIdRef.current = currentSource.id;
    const nextPath = routeForView(activeView, currentSource?.id ?? routeSourceIdRef.current);
    if (window.location.pathname !== nextPath) window.history.replaceState({}, "", nextPath);
  }, [activeView, currentSource?.id]);

  async function handleConfirmAndContinue() {
    if (!currentSource || !documentJob) {
      setError("Select a source document before confirming the converted text.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await confirmSourceText(currentSource.id);
      if (currentSource.doc_type === "template") {
        if (!["fields_extracted", "fields_verified"].includes(currentSource.status)) {
          await extractTemplateFields(currentSource.id);
        }
        setActiveView("field-review");
        showToast("Document text confirmed and template fields prepared", "success");
      } else if (["rules_extracted", "rules_verified"].includes(currentSource.status) || rules.length > 0) {
        setActiveView("rule-review");
        showToast("Document text confirmed", "success");
      } else {
        await extractRules(documentJob.id);
        setActiveView("queue");
        showToast("Document text confirmed and rule extraction started", "info");
      }
      await loadDocuments();
      setWorkflowRefreshKey((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to confirm document text");
    } finally {
      setBusy(false);
    }
  }

  async function handleApproveAllRules() {
    if (!currentSource) return;
    setBusy(true);
    setError("");
    try {
      const result = await bulkReviewSourceRules(currentSource.id, "reviewed");
      await refreshDocumentData(documentJob!.id);
      await loadDocuments();
      setWorkflowRefreshKey((value) => value + 1);
      showToast(`${result.updated} outstanding rules approved`, "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to approve rules");
    } finally {
      setBusy(false);
    }
  }

  if (initialLoading) {
    return (
      <main className="app-shell" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div style={{ textAlign: "center", color: "#40566b" }}>
          <Loader2 className="spin" size={32} style={{ display: "block", margin: "0 auto 12px" }} />
          <p style={{ fontSize: 15, fontWeight: 600 }}>Loading workspace...</p>
        </div>
      </main>
    );
  }

  function handleSidebarNav(page: NavPage) {
    if (page === "document-review" || page === "rule-review") {
      const candidates = sourceDocuments.filter((source) =>
        source.linked_document_id && (page === "document-review" || canExtractRulesForSource(source))
      );
      const currentIsValid = documentJob && candidates.some((source) => source.linked_document_id === documentJob.id);
      if (!currentIsValid && candidates[0]?.linked_document_id) {
        handleOpenDocument(candidates[0].linked_document_id, page);
        return;
      }
    }
    setActiveView(page);
  }

  return (
    <Layout className="tv-app" style={{ minHeight: "100vh" }}>
      <Sidebar
        activePage={activeView}
        onNavigate={handleSidebarNav}
      />
      <Layout className="app-main-layout">
        <Layout.Header className="app-header">
          <div className="app-title-row">
            <strong>Tender Vetting</strong>
            {activeView !== "dashboard" && (
              <span>
                / {viewLabel(activeView)}
              </span>
            )}
          </div>
          <div className="topbar-actions">
            <Button className={`setup-button ${apiReady ? "ready" : "missing"}`} type="default" onClick={() => setActiveView("settings")} icon={<Settings size={16} />}>
              Settings
              <span className="setup-dot" aria-hidden="true" />
            </Button>
            <Button href="http://127.0.0.1:8000/docs" target="_blank">API Docs</Button>
          </div>
        </Layout.Header>

        <Layout.Content className="app-content">
          {WORKBENCH_VIEWS.includes(activeView) && runtimeConfig && !apiReady ? (
            <Alert
              className="setup-alert"
              type="info"
              showIcon
              message="Connect the conversion and rule extraction services first."
              description="API keys stay in this backend session and are not exported."
              action={<Button type="primary" size="small" onClick={() => setActiveView("settings")}>Open Settings</Button>}
            />
          ) : null}

          {toasts.map((t) => (
            <Alert
              className="toast-banner"
              type={t.type === "success" ? "success" : "info"}
              showIcon
              closable
              key={t.id}
              message={t.text}
              onClose={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            />
          ))}
          {error ? (
            <Alert
              className="app-alert"
              type="error"
              showIcon
              closable
              message={error}
              onClose={() => setError("")}
            />
          ) : null}

          {activeView === "document-review" || activeView === "rule-review" ? (
            <div className="document-context-bar">
              <div>
                <span>Active document</span>
                <strong>{currentSource?.name ?? "Select a document"}</strong>
              </div>
              <label>
                <span className="sr-only">Select document</span>
                <select
                  aria-label="Select document"
                  disabled={busy}
                  value={documentJob?.id ?? ""}
                  onChange={(event) => handleOpenDocument(Number(event.target.value), activeView)}
                >
                  <option value="">Select a document</option>
                  {sourceDocuments
                    .filter((source) => source.linked_document_id && (activeView === "document-review" || canExtractRulesForSource(source)))
                    .map((source) => (
                      <option key={source.id} value={source.linked_document_id ?? ""}>{source.name}</option>
                    ))}
                </select>
              </label>
              {documentJob ? <StatusBadge status={currentDisplayStatus} /> : null}
            </div>
          ) : null}

          {WORKBENCH_VIEWS.includes(activeView) ? (
            <Suspense fallback={<section className="panel workbench-loading"><Loader2 className="spin" size={24} /><span>Loading workspace view...</span></section>}>
              <ProfessionalWorkbench key={workflowRefreshKey} page={activeView as never} onPageChange={setActiveView} onOpenDocument={handleOpenDocument} />
            </Suspense>
          ) : null}

          {activeView === "settings" ? (
            <div className="page-stack">
              <div className="tv-page-header">
                <div>
                  <span className="tv-eyebrow">Administration</span>
                  <h2 className="ant-typography">Workspace settings</h2>
                  <span>Control services, extraction behavior, review policy, display defaults, and API access.</span>
                </div>
                <div className="tv-page-actions">
                  <Button href="http://127.0.0.1:8000/docs" target="_blank">Swagger API</Button>
                  <Button href="http://127.0.0.1:8000/redoc" target="_blank">ReDoc</Button>
                  <Button href="http://127.0.0.1:8000/openapi.json" target="_blank">OpenAPI JSON</Button>
                </div>
              </div>
              <div className="settings-overview-grid">
                <section><strong>Workspace profile</strong><span>Active collection, contract family, jurisdiction, and configurable library placeholders.</span></section>
                <section><strong>Review policy</strong><span>Human confirmation is required before extraction, bulk decisions preserve rejected records, and approved procedures are immutable.</span></section>
                <section><strong>Security</strong><span>Service API keys remain session-only and are redacted from audit events.</span></section>
              </div>
              <div className="settings-grid">
                <RuntimeConfigPanel runtimeConfig={runtimeConfig} onSave={handleSaveRuntimeConfig} busy={busy} />
                <ExtractionSettingsPanel runtimeConfig={runtimeConfig} onSave={handleSaveRuntimeConfig} busy={busy} />
                <LibrarySlotSettingsPanel />
              </div>
            </div>
          ) : null}

          {activeView === "document-review" && documentJob && READY_STATUSES.has(documentJob.status) ? (
            <div className="page-stack">
              <MarkdownReview
                documentId={documentJob.id}
                pdfUrl={`/api/documents/${documentJob.id}/source-pdf`}
                sections={sections}
                markers={documentMarkers}
                onSectionsChange={setSections}
              />
              <ExportPanel documentId={documentJob.id} kinds={["source-pdf", "markdown"]} />
              <div className="sticky-confirm-bar">
                <div>
                  <strong>Confirm the converted document text</strong>
                  <span>This records a content fingerprint and advances to the role-specific review stage.</span>
                </div>
                <Button type="primary" size="large" loading={busy} onClick={handleConfirmAndContinue} icon={<CheckCircle2 size={17} />}>
                  Confirm &amp; Continue
                </Button>
              </div>
            </div>
          ) : activeView === "document-review" ? (
            <EmptyDocumentState onGoAssets={() => setActiveView("sources")} />
          ) : null}

          {activeView === "rule-review" && documentJob && READY_STATUSES.has(documentJob.status) ? (
            <div className="page-stack">
              <div className="review-action-strip">
                <div><strong>{currentSource?.name}</strong><span>{rules.filter((rule) => rule.review_status !== "reviewed" && rule.review_status !== "rejected").length} outstanding rules</span></div>
                <Popconfirm title="Approve all outstanding rules while preserving rejected rules?" onConfirm={handleApproveAllRules}>
                  <Button type="primary" loading={busy}>Approve All Outstanding</Button>
                </Popconfirm>
              </div>
              <RuleMap documentId={documentJob.id} graph={graph} rules={rules} sections={sections} onRulesChange={setRules} />
            </div>
          ) : activeView === "rule-review" ? (
            <EmptyDocumentState onGoAssets={() => setActiveView("sources")} />
          ) : null}

          {canExtractRules ? (
            <div className="action-bar">
              <Button type="primary" onClick={handleExtract} disabled={busy} icon={busy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}>
                {extractButtonLabel}
              </Button>
            </div>
          ) : null}
        </Layout.Content>
      </Layout>
    </Layout>
  );
}

function RuntimeConfigPanel({
  runtimeConfig,
  onSave,
  busy
}: {
  runtimeConfig: RuntimeConfig | null;
  onSave: (payload: RuntimeConfigUpdate) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<RuntimeConfigUpdate>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!runtimeConfig) return;
    setDraft({
      mineru_api_base: runtimeConfig.mineru_api_base,
      mineru_model_version: runtimeConfig.mineru_model_version,
      llm_provider: runtimeConfig.llm_provider,
      llm_api_base: runtimeConfig.llm_api_base,
      llm_model: runtimeConfig.llm_model,
      llm_concurrency: runtimeConfig.llm_concurrency
    });
  }, [runtimeConfig]);

  const concurrency = Math.max(1, Math.min(20, Number(draft.llm_concurrency || 8)));

  return (
    <section className="panel">
      <div className="panel-title">
        <Settings size={20} />
        <h2>Service Settings</h2>
      </div>
      <div className="config-badges">
        <span className={runtimeConfig?.mineru_configured ? "configured" : "missing"}>MinerU {runtimeConfig?.mineru_configured ? "configured" : "missing"}</span>
        <span className={runtimeConfig?.llm_configured ? "configured" : "missing"}>LLM {runtimeConfig?.llm_configured ? "configured" : "missing"}</span>
      </div>
      <form
        className="form-stack config-grid"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({ ...draft, llm_concurrency: concurrency });
          setSaved(true);
          setTimeout(() => setSaved(false), 2500);
        }}
      >
        <label>
          MinerU API Token
          <input
            type="password"
            placeholder={runtimeConfig?.mineru_configured ? "Configured - leave blank to keep" : "Paste MinerU token"}
            onChange={(event) => setDraft({ ...draft, mineru_api_token: event.target.value })}
          />
        </label>
        <label>
          MinerU Base URL
          <input value={draft.mineru_api_base || ""} onChange={(event) => setDraft({ ...draft, mineru_api_base: event.target.value })} />
        </label>
        <label>
          MinerU Model Version
          <input
            value={draft.mineru_model_version || ""}
            onChange={(event) => setDraft({ ...draft, mineru_model_version: event.target.value })}
          />
        </label>
        <label>
          LLM Provider
          <input value={draft.llm_provider || ""} onChange={(event) => setDraft({ ...draft, llm_provider: event.target.value })} />
        </label>
        <label>
          LLM API Key
          <input
            type="password"
            placeholder={runtimeConfig?.llm_configured ? "Configured - leave blank to keep" : "Paste OpenAI-compatible key"}
            onChange={(event) => setDraft({ ...draft, llm_api_key: event.target.value })}
          />
        </label>
        <label>
          LLM Base URL
          <input value={draft.llm_api_base || ""} onChange={(event) => setDraft({ ...draft, llm_api_base: event.target.value })} />
        </label>
        <label>
          LLM Model
          <input
            list="llm-model-presets"
            value={draft.llm_model || ""}
            onChange={(event) => setDraft({ ...draft, llm_model: event.target.value })}
            placeholder="Select or type a model name"
          />
          <datalist id="llm-model-presets">
            <option value="doubao-seed-2-0-pro-260215" label="Pro (default)" />
            <option value="doubao-seed-2-0-flash-260215" label="Flash (fast)" />
            <option value="doubao-seed-2-0-lite-260215" label="Lite (cheap)" />
          </datalist>
        </label>
        <label>
          LLM Concurrency: {concurrency}
          <input
            max={runtimeConfig?.max_llm_concurrency || 20}
            min={1}
            type="range"
            value={concurrency}
            onChange={(event) => setDraft({ ...draft, llm_concurrency: Number(event.target.value) })}
          />
        </label>
        <button
          className={`primary-button${saved ? " saved-feedback" : ""}`}
          type="submit"
          disabled={busy}
        >
          {busy ? (
            <Loader2 className="spin" size={18} />
          ) : saved ? (
            <CheckCircle2 size={18} />
          ) : (
            <Save size={18} />
          )}
          {saved ? "Settings Saved" : "Save Settings"}
        </button>
      </form>
    </section>
  );
}

function ExtractionSettingsPanel({
  runtimeConfig,
  onSave,
  busy
}: {
  runtimeConfig: RuntimeConfig | null;
  onSave: (payload: RuntimeConfigUpdate) => void;
  busy: boolean;
}) {
  const [promptDraft, setPromptDraft] = useState(runtimeConfig?.extraction_prompt ?? "");
  const [groupingLevel, setGroupingLevel] = useState(runtimeConfig?.default_grouping_level ?? 2);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (runtimeConfig) {
      setPromptDraft(runtimeConfig.extraction_prompt || "");
      setGroupingLevel(runtimeConfig.default_grouping_level ?? 2);
    }
  }, [runtimeConfig]);

  return (
    <section className="panel">
      <div className="panel-title">
        <GitBranch size={20} />
        <h2>Extraction Settings</h2>
      </div>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({
            extraction_prompt: promptDraft,
            default_grouping_level: groupingLevel
          });
          setSaved(true);
          setTimeout(() => setSaved(false), 2500);
        }}
      >
        <label>
          Default Grouping Level
          <select value={groupingLevel} onChange={(event) => setGroupingLevel(Number(event.target.value))}>
            <option value={1}>Part (H1) — coarser, fewer windows</option>
            <option value={2}>Chapter (H2) — balanced</option>
            <option value={3}>Sub-chapter (H3) — finer, more windows</option>
          </select>
          <span className="hint">Applies to new documents. Each document keeps its own setting from import time.</span>
        </label>

        <hr />

        <label>
          Extraction System Prompt
          <textarea
            className="textarea-mono"
            value={promptDraft}
            onChange={(event) => setPromptDraft(event.target.value)}
            placeholder="Enter custom system prompt or leave empty for default..."
            rows={10}
            style={{ fontFamily: "monospace", fontSize: "0.82rem" }}
          />
          <span className="hint">
            Available variables: {"{{WINDOW_TITLE}}"}, {"{{HEADING_PATH}}"}, {"{{SECTIONS}}"}, {"{{DEFINITIONS}}"}, {"{{CROSS_REFERENCES}}"}.
            Leave empty to use the built-in default.
          </span>
        </label>

        <div className="flex-row gap-2">
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setPromptDraft("");
              setGroupingLevel(2);
            }}
          >
            Reset to Default
          </button>
          <button
            className={`primary-button${saved ? " saved-feedback" : ""}`}
            type="submit"
            disabled={busy}
          >
            {saved ? <CheckCircle2 size={18} /> : <Save size={18} />}
            {saved ? "Saved" : "Save Settings"}
          </button>
        </div>
      </form>
    </section>
  );
}

function LibrarySlotSettingsPanel() {
  const [collections, setCollections] = useState<DocumentCollection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [slots, setSlots] = useState<LibrarySlot[]>([]);
  const [drafts, setDrafts] = useState<Record<string, LibrarySlot>>({});
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<SourceDocument["doc_type"]>("rulebook");
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState("");

  useEffect(() => {
    getCollections()
      .then((rows) => {
        setCollections(rows);
        setCollectionId((current) => current || rows[0]?.id || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load workspaces"));
  }, []);

  useEffect(() => {
    if (!collectionId) return;
    getLibrarySlots(collectionId)
      .then((rows) => {
        setSlots(rows);
        setDrafts(Object.fromEntries(rows.map((slot) => [slot.id, slot])));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load placeholders"));
  }, [collectionId]);

  async function refresh() {
    const rows = await getLibrarySlots(collectionId);
    setSlots(rows);
    setDrafts(Object.fromEntries(rows.map((slot) => [slot.id, slot])));
  }

  async function run(id: string, action: () => Promise<unknown>) {
    setSavingId(id);
    setError("");
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update placeholder");
    } finally {
      setSavingId("");
    }
  }

  return (
    <section className="panel slot-settings-panel">
      <div className="panel-title">
        <FileText size={20} />
        <h2>Required Document Placeholders</h2>
      </div>
      <p className="muted">These configurable placeholders drive the gray cards in Source Library. Custom documents remain unlimited.</p>
      <label className="slot-collection-select">
        Workspace
        <select value={collectionId} onChange={(event) => setCollectionId(event.target.value)}>
          {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name} · {collection.id.slice(-6)}</option>)}
        </select>
      </label>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="slot-settings-list">
        {slots.map((slot) => {
          const draft = drafts[slot.id] ?? slot;
          return (
            <div className="slot-settings-row" key={slot.id}>
              <input aria-label={`Name for ${slot.name}`} value={draft.name} onChange={(event) => setDrafts({ ...drafts, [slot.id]: { ...draft, name: event.target.value } })} />
              <select aria-label={`Role for ${slot.name}`} value={draft.doc_type} onChange={(event) => setDrafts({ ...drafts, [slot.id]: { ...draft, doc_type: event.target.value as SourceDocument["doc_type"] } })}>
                <option value="rulebook">Rulebook</option>
                <option value="reference_clause">Reference clause</option>
                <option value="template">Template</option>
                <option value="tender_submission">Tender submission</option>
              </select>
              <label className="slot-required-check"><input type="checkbox" checked={draft.required} onChange={(event) => setDrafts({ ...drafts, [slot.id]: { ...draft, required: event.target.checked } })} /> Required</label>
              <Button loading={savingId === slot.id} onClick={() => run(slot.id, () => updateLibrarySlot(slot.id, { name: draft.name, doc_type: draft.doc_type, required: draft.required }))}>Save</Button>
              <Popconfirm title={`Delete placeholder ${slot.name}?`} onConfirm={() => run(slot.id, () => deleteLibrarySlot(slot.id))}>
                <Button danger>Delete</Button>
              </Popconfirm>
            </div>
          );
        })}
      </div>
      <form
        className="slot-add-row"
        onSubmit={(event) => {
          event.preventDefault();
          if (!newName.trim() || !collectionId) return;
          void run("new", () => createLibrarySlot({
            collection_id: collectionId,
            name: newName.trim(),
            short_name: newName.trim().slice(0, 20),
            description: "",
            doc_type: newType,
            required: false,
            grouping_level: newType === "template" ? 3 : 2,
            sort_order: slots.length,
          })).then(() => setNewName(""));
        }}
      >
        <input aria-label="New placeholder name" placeholder="New placeholder name" value={newName} onChange={(event) => setNewName(event.target.value)} />
        <select aria-label="New placeholder role" value={newType} onChange={(event) => setNewType(event.target.value as SourceDocument["doc_type"])}>
          <option value="rulebook">Rulebook</option>
          <option value="reference_clause">Reference clause</option>
          <option value="template">Template</option>
          <option value="tender_submission">Tender submission</option>
        </select>
        <Button type="primary" htmlType="submit" loading={savingId === "new"}>Add Placeholder</Button>
      </form>
    </section>
  );
}

function ProgressPanel({ documentJob, stats }: { documentJob: DocumentJob | null; stats: DocumentStats | null }) {
  const status = documentJob?.status ?? "";
  const isExtracting = status === "extracting_rules";
  const isLLMPhase = isExtracting;
  const isActive = status === "mineru_queued" || status === "mineru_processing" || status === "rule_extraction_queued" || isLLMPhase;

  const windowsCompleted = stats?.llm_windows_completed ?? 0;
  const windowsTotal = stats?.llm_windows_total ?? 0;
  const windowsPct = windowsTotal > 0 ? Math.round((windowsCompleted / windowsTotal) * 100) : 0;

  return (
    <section className="panel processing-hud">
      <div className="panel-title">
        {isActive ? <Loader2 className="spin" size={20} /> : <SearchCheck size={20} />}
        <h2>Progress</h2>
        {isActive ? <span className="live-dot" /> : null}
      </div>

      {isLLMPhase && windowsTotal > 0 ? (
        <div className="windows-progress-hero">
          <div className="windows-progress-label">
            <span>Extracting rules</span>
            <strong>
              {windowsCompleted} / {windowsTotal} windows
            </strong>
            <span>{windowsPct}%</span>
          </div>
          <div className="hud-progress hud-progress-large">
            <span style={{ width: `${windowsPct}%` }} />
          </div>
        </div>
      ) : null}

      {isLLMPhase && (stats?.rules_extracted ?? 0) > 0 ? (
        <div className="live-rules-count">
          <Zap size={16} />
          <span>{stats?.rules_extracted} rules extracted so far</span>
        </div>
      ) : null}

      <div className="processing-phase-badge">
        <PhaseBadge status={status} />
      </div>

      {isLLMPhase ? (
        <div className="mini-timeline">
          <span className={isExtracting ? "active" : "done"}>Extract</span>
        </div>
      ) : null}

      {documentJob ? (
        <div className="job-meta">
          <span>Document #{documentJob.id}</span>
          {documentJob.mineru_task_id ? <span>MinerU {documentJob.mineru_task_id}</span> : null}
        </div>
      ) : (
        <p className="muted">No document job yet.</p>
      )}

      {documentJob?.error_message ? <p className="error-text">{documentJob.error_message}</p> : null}
      <StatsGrid stats={stats} status={status} />
    </section>
  );
}

function EmptyDocumentState({ onGoAssets }: { onGoAssets: () => void }) {
  return (
    <section className="panel empty-document-state">
      <FileText size={34} strokeWidth={1.7} />
      <h2>No active document selected</h2>
      <p>Select a document in this page or import a source before opening the review workspace.</p>
      <Button type="primary" onClick={onGoAssets} icon={<FileText size={16} />}>
        Open Assets
      </Button>
    </section>
  );
}

function PhaseBadge({ status }: { status: DocumentStatus }) {
  if (status === "mineru_queued") return <span className="phase-tag phase-queued">Waiting for MinerU to start</span>;
  if (status === "mineru_processing") return <span className="phase-tag phase-mineru">MinerU is converting PDF to Markdown</span>;
  if (status === "rule_extraction_queued") return <span className="phase-tag phase-queued">Preparing rule extraction</span>;

  if (status === "extracting_rules") return <span className="phase-tag phase-extracting">LLM extracting rules from candidate sections</span>;
  if (status === "rules_extracted") return <span className="phase-tag phase-done">Extraction complete</span>;
  if (status === "markdown_ready") return <span className="phase-tag phase-ready">Markdown ready for review</span>;
  if (status === "rule_extraction_failed") return <span className="phase-tag phase-failed">Extraction failed</span>;
  if (status === "mineru_failed") return <span className="phase-tag phase-failed">MinerU conversion failed</span>;
  return null;
}

function MarkdownReview({
  documentId,
  pdfUrl,
  sections,
  markers,
  onSectionsChange
}: {
  documentId: number;
  pdfUrl: string;
  sections: Section[];
  markers: DocumentMarker[];
  onSectionsChange: (sections: Section[]) => void;
}) {
  return (
    <section className="panel tall-panel document-panel">
      <div className="panel-title">
        <FileText size={20} />
        <h2>Document Preview</h2>
      </div>
      <div className="review-split">
        <section className="pdf-review-pane" aria-label="Source PDF preview">
          <iframe src={pdfUrl} title="Source PDF" />
        </section>
        <div className="document-preview" aria-label="Patched MinerU Markdown preview">
          {sections.map((section) => (
            <SectionPreview
              key={section.id}
              documentId={documentId}
              section={section}
              markers={markers}
              onSaved={(next) => onSectionsChange(replaceSection(sections, next))}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function SectionPreview({
  documentId,
  section,
  markers,
  onSaved
}: {
  documentId: number;
  section: Section;
  markers: DocumentMarker[];
  onSaved: (section: Section) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState(section.title);
  const [contentDraft, setContentDraft] = useState(section.content);
  const [saving, setSaving] = useState(false);
  const paragraphLike = isClauseParagraph(section);
  const sectionMarkers = markers.filter((marker) => marker.section_id === section.id);
  const displayContent = paragraphLike ? (section.content || section.title) : section.content;
  const blocks = useMemo(() => parseRichBlocks(displayContent), [displayContent]);
  const hasRichBlocks = blocks.some((block) => block.type !== "text");

  useEffect(() => {
    setTitleDraft(section.title);
    setContentDraft(section.content);
  }, [section.content, section.title]);

  async function save() {
    setSaving(true);
    try {
      const saved = await patchSection(documentId, section.id, {
        title: titleDraft.trim() || section.title,
        content: contentDraft
      });
      onSaved(saved);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  const HeadingTag = `h${Math.min(section.level, 4)}` as keyof JSX.IntrinsicElements;

  return (
    <section className={`doc-block doc-depth-${Math.min(section.level, 6)}`} data-section-id={section.id}>
      {editing ? (
        <div className="section-editor">
          <label>
            Heading
            <input value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} />
          </label>
          <label>
            Source Markdown
            <textarea rows={Math.min(18, Math.max(7, contentDraft.split("\n").length + 2))} value={contentDraft} onChange={(event) => setContentDraft(event.target.value)} />
          </label>
          <div className="section-editor-preview">
            <span>Preview</span>
            <HeadingTag className={`doc-heading doc-heading-${Math.min(section.level, 4)}`}>{titleDraft}</HeadingTag>
            {contentDraft ? <div className={paragraphLike ? "doc-clause" : "doc-body"}>{renderRichBlocks(parseRichBlocks(contentDraft), documentId, sectionMarkers)}</div> : null}
          </div>
          <div className="section-editor-actions">
            <Button onClick={() => { setEditing(false); setTitleDraft(section.title); setContentDraft(section.content); }}>Cancel</Button>
            <Button type="primary" loading={saving} onClick={save} icon={<Save size={15} />}>Save Section</Button>
          </div>
        </div>
      ) : (
        <>
          <div className="section-heading-row">
            {!paragraphLike ? (
              <HeadingTag className={`doc-heading doc-heading-${Math.min(section.level, 4)}`}>
                {renderInlineMarkers(section.title, sectionMarkers)}
              </HeadingTag>
            ) : null}
            <Button type="text" size="small" onClick={() => setEditing(true)} icon={<Edit3 size={14} />}>Edit</Button>
          </div>
          {displayContent.trim() ? (
            <div className={paragraphLike ? "doc-clause rich-content" : "doc-body rich-content"}>
              {hasRichBlocks ? renderRichBlocks(blocks, documentId, sectionMarkers) : renderInlineMarkers(displayContent, sectionMarkers)}
            </div>
          ) : null}
        </>
      )}
      {section.children.map((child) => (
        <SectionPreview key={child.id} documentId={documentId} section={child} markers={markers} onSaved={onSaved} />
      ))}
    </section>
  );
}

function RuleMap({
  documentId,
  graph,
  rules,
  sections,
  onRulesChange
}: {
  documentId: number;
  graph: RuleGraph;
  rules: Rule[];
  sections: Section[];
  onRulesChange: (rules: Rule[]) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [selectedRule, setSelectedRule] = useState<Rule | null>(null);
  const [ruleDraft, setRuleDraft] = useState<Rule | null>(null);
  const [savingRuleId, setSavingRuleId] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState("");
  const [hoveredXrefCode, setHoveredXrefCode] = useState<string | null>(null);
  const prevRuleIdsRef = useRef<Set<string>>(new Set());
  const [newRuleIds, setNewRuleIds] = useState<Set<string>>(new Set());
  const selectedRulePage = Number.parseInt(ruleDraft?.source.page_range?.split("-")[0] ?? "1", 10) || 1;

  useEffect(() => {
    const currentIds = new Set(rules.map((r) => r.id));
    const added = new Set([...currentIds].filter((id) => !prevRuleIdsRef.current.has(id)));
    if (added.size > 0) {
      setNewRuleIds((prev) => new Set([...prev, ...added]));
      const timer = setTimeout(() => {
        setNewRuleIds((prev) => {
          const next = new Set(prev);
          added.forEach((id) => next.delete(id));
          return next;
        });
      }, 2500);
      prevRuleIdsRef.current = currentIds;
      return () => clearTimeout(timer);
    }
    prevRuleIdsRef.current = currentIds;
  }, [rules]);

  const flatSections = useMemo(() => flattenSections(sections), [sections]);
  const sectionById = useMemo(
    () => flatSections.reduce((map, s) => map.set(s.id, s), new Map<string, Section>()),
    [flatSections]
  );
  const sectionByCode = useMemo(() => {
    const map = new Map<string, Section>();
    for (const s of flatSections) {
      const code = sectionCode(s);
      if (code) map.set(code.toUpperCase(), s);
    }
    return map;
  }, [flatSections]);
  const rulesBySectionId = useMemo(() => {
    const map = new Map<string, Rule[]>();
    for (const rule of rules) {
      const sid = rule.section_id || rule.source.section_id || "unknown";
      map.set(sid, [...(map.get(sid) ?? []), rule]);
    }
    return map;
  }, [rules]);

  const filteredRules = useMemo(() => {
    return rules.filter((rule) => {
      if (filter === "all") return true;
      if (filter === "low") return rule.confidence < 0.65;
      if (filter === "reviewed") return rule.review_status === "reviewed";
      if (filter === "reference") return rule.dependencies.some((d) => d.type === "references");
      return rule.type === filter;
    });
  }, [rules, filter]);
  const filteredRuleIds = useMemo(() => new Set(filteredRules.map((r) => r.id)), [filteredRules]);

  const totalRules = rules.length;
  const typeCounts: Record<string, number> = {};
  for (const t of Object.keys(RULE_TYPE_COLORS)) {
    typeCounts[t] = rules.filter((r) => r.type === t).length;
  }
  const allRuleTypes = Object.keys(RULE_TYPE_COLORS);

  async function handleRuleSave() {
    if (!ruleDraft) return;
    setSavingRuleId(ruleDraft.id);
    try {
      const saved = await saveRule(ruleDraft);
      onRulesChange(rules.map((r) => (r.id === saved.id ? saved : r)));
      setSelectedRule(saved);
      setRuleDraft(saved);
    } finally {
      setSavingRuleId(null);
    }
  }

  async function handleReviewAction(status: Rule["review_status"]) {
    if (!ruleDraft) return;
    const previousDraft = ruleDraft;
    const nextDraft = { ...ruleDraft, review_status: status };
    setReviewError("");
    setRuleDraft(nextDraft);
    try {
      const saved = await saveRule(nextDraft);
      onRulesChange(rules.map((r) => (r.id === saved.id ? saved : r)));
      setSelectedRule(saved);
      setRuleDraft(saved);
    } catch (error) {
      setRuleDraft(previousDraft);
      setReviewError(error instanceof Error ? error.message : "Unable to update rule review status");
    }
  }

  function openRuleForEdit(rule: Rule) {
    setSelectedRule(rule);
    setRuleDraft({ ...rule });
  }

  function closeEditPanel() {
    setSelectedRule(null);
    setRuleDraft(null);
  }

  return (
    <section className="panel tall-panel">
      {reviewError ? <Alert type="error" showIcon closable message={reviewError} onClose={() => setReviewError("")} /> : null}
      <div className="panel-title">
        <GitBranch size={20} />
        <h2>Rule Review</h2>
      </div>
      <div className="filter-row">
        {(["all", ...allRuleTypes, "low", "reviewed"] as const).map((item) => {
          const dotColor: Record<string, string> = {
            all: "#94a3b8", low: "#eab308", reviewed: "#16a34a",
            ...RULE_TYPE_COLORS,
          };
          const tooltips: Record<string, string> = {
            all: "Show every extracted rule",
            obligation: "Mandatory duties & requirements",
            prohibition: "Actions that must NOT be performed",
            permission: "Actions that are allowed or exempted",
            deadline: "Time limits or submission deadlines",
            definition: "Key terms and their definitions",
            procedure: "Step-by-step processes to follow",
            option: "Rules with conditional branches (Option A/B/C)",
            checklist: "Verification or submission checklists",
            background: "Contextual or background information",
            low: "Confidence below 65% — needs review",
            reviewed: "Rules marked as approved"
          };
          const label = item === "all" ? "All" : item.charAt(0).toUpperCase() + item.slice(1);
          const count = item === "all" ? rules.length : item === "low" ? rules.filter((r) => r.confidence < 0.65).length : item === "reviewed" ? rules.filter((r) => r.review_status === "reviewed").length : (typeCounts[item] || 0);
          return (
            <button
              className={`filter-btn ${filter === item ? "active" : ""}`}
              key={item}
              onClick={() => setFilter(item)}
              type="button"
            >
              <span className="filter-dot" style={{ background: dotColor[item] || "#94a3b8" }} />
              {label} ({count})
              <span className="filter-tooltip">{tooltips[item]}</span>
            </button>
          );
        })}
      </div>
      <ExportPanel documentId={documentId} kinds={["rules-json", "rules-csv", "llm-windows", "rule-graph"]} />
      {rules.length === 0 ? (
        <p className="muted">Rule logic will appear here after extraction.</p>
      ) : (
        <div className="mm-workspace review-workspace">
          <div className="mm-tree-column review-tree-column">
            <div className="mindmap-legend">
              {allRuleTypes.map((t) => (
                <span className="legend-item" key={t}>
                  <span className="legend-dot" style={{ background: RULE_TYPE_COLORS[t] }} /> {t.charAt(0).toUpperCase() + t.slice(1)} ({typeCounts[t]})
                </span>
              ))}
            </div>
            <div className="mindmap-tree">
              {sections.map((section) => (
                <MindmapSectionNode
                  key={section.id}
                  section={section}
                  sectionById={sectionById}
                  sectionByCode={sectionByCode}
                  rulesBySectionId={rulesBySectionId}
                  graph={graph}
                  depth={0}
                  selectedRuleId={selectedRule?.id ?? null}
                  newRuleIds={newRuleIds}
                  filteredRuleIds={filteredRuleIds}
                  hoveredXrefCode={hoveredXrefCode}
                  onSelectRule={openRuleForEdit}
                  onHoverXref={setHoveredXrefCode}
                />
              ))}
            </div>
          </div>
          <div className="mm-edit-panel review-inspector-panel">
            {selectedRule && ruleDraft ? (
              <>
                <div className="mm-edit-panel-header review-inspector-header">
                  <div>
                    <ReviewTypeChip label={ruleDraft.type} color={RULE_TYPE_COLORS[ruleDraft.type] || "#6b7280"} />
                    <ReviewStatusBadge status={ruleDraft.review_status} />
                    <ReviewConfidence value={ruleDraft.confidence} />
                  </div>
                  <button className="toast-dismiss" onClick={closeEditPanel} type="button" aria-label="Close editor">
                    <X size={18} />
                  </button>
                </div>

                {/* Review status banner */}
                {ruleDraft.review_status === "reviewed" ? (
                  <div className="review-banner approved">This rule has been approved</div>
                ) : ruleDraft.review_status === "rejected" ? (
                  <div className="review-banner rejected">This rule has been rejected</div>
                ) : (
                  <div className="review-banner draft">This rule needs review</div>
                )}

                {/* Breadcrumb */}
                <div className="mm-edit-breadcrumb">
                  {(ruleDraft.source.heading_path || []).length > 0
                    ? ruleDraft.source.heading_path.join(" > ")
                    : "Unknown section"}
                </div>

                {/* Evidence text */}
                {ruleDraft.source.evidence_text ? (
                  <details className="mm-edit-evidence">
                    <summary>Source evidence</summary>
                    <p>{ruleDraft.source.evidence_text}</p>
                    <a href={`/api/documents/${documentId}/source-pdf#page=${selectedRulePage}`} target="_blank" rel="noreferrer">
                      Open cited PDF page {selectedRulePage}
                    </a>
                    <iframe className="rule-evidence-pdf" title="Rule PDF evidence" src={`/api/documents/${documentId}/source-pdf#page=${selectedRulePage}`} />
                  </details>
                ) : null}

                <div className="form-stack" style={{ marginTop: 12 }}>
                  <label>
                    Subject
                    <input
                      value={ruleDraft.subject}
                      onChange={(e) => setRuleDraft({ ...ruleDraft, subject: e.target.value })}
                    />
                  </label>
                  <label>
                    Condition
                    <textarea
                      value={ruleDraft.condition}
                      onChange={(e) => setRuleDraft({ ...ruleDraft, condition: e.target.value })}
                      rows={3}
                    />
                  </label>
                  <label>
                    Action
                    <textarea
                      value={ruleDraft.action}
                      onChange={(e) => setRuleDraft({ ...ruleDraft, action: e.target.value })}
                      rows={3}
                    />
                  </label>

                  {/* Options as links */}
                  {ruleDraft.options.length > 0 ? (
                    <div className="mm-edit-section">
                      <span className="mm-detail-label">Options</span>
                      <div className="mm-edit-options">
                        {ruleDraft.options.map((opt, i) => {
                          const refSections = (opt.referenced_sections || [])
                            .map((code) => sectionByCode.get(code.toUpperCase()))
                            .filter(Boolean) as Section[];
                          return (
                            <div key={i} className="mm-edit-option-item">
                              <strong>{opt.label || `Path ${i + 1}`}</strong>
                              {opt.condition ? <span className="mm-option-condition">IF: {opt.condition}</span> : null}
                              {opt.action ? <span className="mm-option-action">THEN: {opt.action}</span> : null}
                              {refSections.length > 0 ? (
                                <span className="mm-option-refs">
                                  {refSections.map((sec) => (
                                    <span key={sec.id} className="mm-ref resolved" style={{ margin: 2 }}>
                                      {sectionCode(sec)} → {sec.title.slice(0, 50)}
                                    </span>
                                  ))}
                                </span>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}

                  {/* Dependencies */}
                  {ruleDraft.dependencies.length > 0 ? (
                    <div className="mm-edit-section">
                      <span className="mm-detail-label">Depends On</span>
                      <span className="mm-detail-value">
                        {ruleDraft.dependencies.map((d, i) => (
                          <span key={i} className="mm-dep">{d.type}: {d.reason || d.rule_id}</span>
                        ))}
                      </span>
                    </div>
                  ) : null}
                </div>

                {/* Review action buttons */}
                <div className="mm-edit-actions">
                  <span className="mm-detail-label" style={{ display: "block", marginBottom: 6 }}>Review status</span>
                  <div className="review-actions">
                    <button
                      type="button"
                      className={`review-action-btn approve${ruleDraft.review_status === "reviewed" ? " active" : ""}`}
                      onClick={() => handleReviewAction("reviewed")}
                    >
                      <CheckCircle2 size={16} />
                      Approve
                    </button>
                    <button
                      type="button"
                      className={`review-action-btn needs-work${ruleDraft.review_status === "draft" ? " active" : ""}`}
                      onClick={() => handleReviewAction("draft")}
                    >
                      <Edit3 size={16} />
                      Needs Work
                    </button>
                    <button
                      type="button"
                      className={`review-action-btn reject${ruleDraft.review_status === "rejected" ? " active" : ""}`}
                      onClick={() => handleReviewAction("rejected")}
                    >
                      <XCircle size={16} />
                      Reject
                    </button>
                  </div>
                </div>

                <div className="mm-edit-save-row">
                  <button
                    className="primary-button"
                    onClick={handleRuleSave}
                    disabled={savingRuleId === ruleDraft.id}
                  >
                    {savingRuleId === ruleDraft.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Save size={16} />
                    )}
                    Save Rule
                  </button>
                </div>
              </>
            ) : (
              <div className="mm-edit-empty review-inspector-empty">
                <Edit3 size={36} strokeWidth={1.5} />
                <p>Select a rule to edit</p>
                <p className="mm-edit-empty-hint">Click the edit icon on any rule in the tree to open it here.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

const RULE_TYPE_COLORS: Record<string, string> = {
  obligation: "#2563eb",
  prohibition: "#dc2626",
  permission: "#16a34a",
  deadline: "#ea580c",
  definition: "#7c3aed",
  procedure: "#6b7280",
  option: "#ca8a04",
  checklist: "#0891b2",
  background: "#9ca3af",
};

const MindmapSectionNode = memo(function MindmapSectionNode({
  section,
  sectionById,
  sectionByCode,
  rulesBySectionId,
  graph,
  depth,
  selectedRuleId,
  newRuleIds,
  filteredRuleIds,
  hoveredXrefCode,
  onSelectRule,
  onHoverXref,
}: {
  section: Section;
  sectionById: Map<string, Section>;
  sectionByCode: Map<string, Section>;
  rulesBySectionId: Map<string, Rule[]>;
  graph: RuleGraph;
  depth: number;
  selectedRuleId: string | null;
  newRuleIds: Set<string>;
  filteredRuleIds: Set<string>;
  hoveredXrefCode: string | null;
  onSelectRule: (rule: Rule) => void;
  onHoverXref: (code: string | null) => void;
}) {
  const sectionRules = rulesBySectionId.get(section.id) || [];
  const hasNewRules = sectionRules.some((r) => newRuleIds.has(r.id));
  const [expanded, setExpanded] = useState(depth < 2 || hasNewRules);
  const hasChildren = section.children.length > 0 || sectionRules.length > 0;
  const indentClass = depth > 0 ? `mm-indent-${Math.min(depth, 4)}` : "";
  const isXrefTarget = hoveredXrefCode && sectionCode(section) === hoveredXrefCode;

  return (
    <div className={`mm-section-node ${indentClass}`}>
      <div
        className={`mm-section-header ${hasChildren ? "clickable" : ""} ${sectionRules.length > 0 ? "has-rules" : ""} ${isXrefTarget ? "xref-target" : ""}`}
        onClick={() => hasChildren && setExpanded(!expanded)}
        role={hasChildren ? "button" : undefined}
        tabIndex={hasChildren ? 0 : undefined}
        aria-expanded={hasChildren ? expanded : undefined}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(!expanded); } }}
      >
        <span className={`mm-toggle ${expanded ? "open" : ""}`}>
          {hasChildren ? (expanded ? "▾" : "▸") : " "}
        </span>
        <span className="mm-section-code">{sectionCode(section) || `§${section.position}`}</span>
        <span className="mm-section-title">{section.title}</span>
        {sectionRules.length > 0 && (
          <span className="mm-rule-count">{sectionRules.length}</span>
        )}
      </div>
      {expanded && (
        <div className="mm-section-body">
          {sectionRules.map((rule) => (
            <MindmapRuleNode
              key={rule.id}
              rule={rule}
              sectionById={sectionById}
              sectionByCode={sectionByCode}
              graph={graph}
              isSelected={selectedRuleId === rule.id}
              isNew={newRuleIds.has(rule.id)}
              isFiltered={filteredRuleIds.has(rule.id)}
              hoveredXrefCode={hoveredXrefCode}
              onSelectRule={onSelectRule}
              onHoverXref={onHoverXref}
            />
          ))}
          {section.children.map((child) => (
            <MindmapSectionNode
              key={child.id}
              section={child}
              sectionById={sectionById}
              sectionByCode={sectionByCode}
              rulesBySectionId={rulesBySectionId}
              graph={graph}
              depth={depth + 1}
              selectedRuleId={selectedRuleId}
              newRuleIds={newRuleIds}
              filteredRuleIds={filteredRuleIds}
              hoveredXrefCode={hoveredXrefCode}
              onSelectRule={onSelectRule}
              onHoverXref={onHoverXref}
            />
          ))}
        </div>
      )}
    </div>
  );
});

const MindmapRuleNode = memo(function MindmapRuleNode({
  rule,
  sectionById,
  sectionByCode,
  graph,
  isSelected,
  isNew,
  isFiltered,
  hoveredXrefCode,
  onSelectRule,
  onHoverXref,
}: {
  rule: Rule;
  sectionById: Map<string, Section>;
  sectionByCode: Map<string, Section>;
  graph: RuleGraph;
  isSelected: boolean;
  isNew: boolean;
  isFiltered: boolean;
  hoveredXrefCode: string | null;
  onSelectRule: (rule: Rule) => void;
  onHoverXref: (code: string | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const typeColor = RULE_TYPE_COLORS[rule.type] || "#6b7280";
  const refs = useMemo(() => {
    const section = sectionById.get(rule.section_id || rule.source.section_id || "");
    return ruleReferences(rule, sectionByCode, section);
  }, [rule, sectionById, sectionByCode]);
  const relatedEdges = graph.edges.filter((e) => e.source === rule.id || e.target === rule.id);
  const hasDetails = rule.condition || rule.action || rule.options.length > 0 || refs.length > 0 || rule.dependencies.length > 0 || relatedEdges.length > 0;
  const hasActiveXref = hoveredXrefCode && refs.some((r) => r.code === hoveredXrefCode);

  if (!isFiltered) return null;

  return (
    <div className={`mm-rule-node ${isNew ? "mm-rule-node--new" : ""} ${isSelected ? "mm-rule-node--selected" : ""} ${hasActiveXref ? "has-active-xref" : ""}`}>
      <div
        className="mm-rule-header clickable review-item-row"
        onClick={() => onSelectRule(rule)}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelectRule(rule); } }}
      >
        <span
          className={`mm-toggle small ${expanded ? "open" : ""}`}
          onClick={(e) => { e.stopPropagation(); hasDetails && setExpanded(!expanded); }}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); hasDetails && setExpanded(!expanded); } }}
          tabIndex={0}
          role="button"
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse rule details" : "Expand rule details"}
          title={hasDetails ? "Toggle details" : undefined}
        >
          {hasDetails ? (expanded ? "▾" : "▸") : "·"}
        </span>
        <ReviewStatusBadge status={rule.review_status} />
        <ReviewTypeChip label={rule.type} color={typeColor} />
        <span className="mm-rule-subject">{rule.subject || rule.action || rule.id}</span>
        <ReviewConfidence value={rule.confidence} />
        <button
          className="mm-rule-edit-btn"
          type="button"
          onClick={(e) => { e.stopPropagation(); onSelectRule(rule); }}
          title="Edit rule"
          aria-label="Edit rule"
        >
          <Edit3 size={16} />
        </button>
      </div>
      {expanded && (
        <div className="mm-rule-detail">
          {/* Heading path breadcrumb */}
          {(rule.source.heading_path || []).length > 0 && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Source</span>
              <span className="mm-detail-value" style={{ fontSize: 12, color: "#64748b" }}>
                {rule.source.heading_path.join(" > ")}
              </span>
            </div>
          )}
          {rule.condition && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Condition</span>
              <span className="mm-detail-value">{rule.condition}</span>
            </div>
          )}
          {rule.action && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Action</span>
              <span className="mm-detail-value">{rule.action}</span>
            </div>
          )}
          {rule.actor && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Actor</span>
              <span className="mm-detail-value">{rule.actor}</span>
            </div>
          )}
          {rule.deadline && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Deadline</span>
              <span className="mm-detail-value">{rule.deadline}</span>
            </div>
          )}
          {refs.length > 0 && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Refs</span>
              <span className="mm-detail-value">
                {refs.map((r) => (
                  <span
                    key={r.code}
                    className={`mm-ref ${r.resolved ? "" : "unresolved"}`}
                    onMouseEnter={() => onHoverXref(r.code)}
                    onMouseLeave={() => onHoverXref(null)}
                  >
                    {r.code} {r.resolved ? `→ ${r.title.slice(0, 60)}` : "(not yet extracted)"}
                  </span>
                ))}
              </span>
            </div>
          )}
          {rule.options.length > 0 && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Options</span>
              <div className="mm-options-list">
                {rule.options.map((opt, i) => (
                  <div key={i} className="mm-option-item">
                    <strong>{opt.label || `Path ${i + 1}`}</strong>
                    {opt.condition && <span className="mm-option-condition">IF: {opt.condition}</span>}
                    {opt.action && <span className="mm-option-action">THEN: {opt.action}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {rule.dependencies.length > 0 && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Depends On</span>
              <span className="mm-detail-value">
                {rule.dependencies.map((d, i) => (
                  <span key={i} className="mm-dep">{d.type}: {d.reason || d.rule_id}</span>
                ))}
              </span>
            </div>
          )}
          {relatedEdges.length > 0 && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Graph Edges</span>
              <span className="mm-detail-value">
                {relatedEdges.map((e, i) => (
                  <span key={i} className="mm-edge">
                    {e.source === rule.id ? `→ ${e.label}: ${e.target}` : `${e.source} ${e.label} →`}
                  </span>
                ))}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

function StatusBadge({ status }: { status: DocumentStatus }) {
  return <span className={`status-badge status-${status}`}>{labelStatus(status)}</span>;
}

function StatsGrid({ stats, status }: { stats: DocumentStats | null; status?: string }) {
  const items = visibleStats(stats, status);
  if (!items.length) return null;
  return (
    <div className="stats-grid">
      {items.map(([label, value]) => (
        <div className="stat-card" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function visibleStats(stats: DocumentStats | null, status?: DocumentStatus): [string, string | number][] {
  if (!stats) return [];
  if (status === "mineru_queued" || status === "mineru_processing") return [];
  if (status === "mineru_failed" || status === "rule_extraction_failed" || status === "rule_extraction_queued") return [];
  if (status === "markdown_ready") return [["Sections", stats.total_sections]];
  if (status === "extracting_rules") {
    const result: [string, string | number][] = [
      ["Windows", `${stats.llm_windows_completed}/${stats.llm_windows_total}`],
      ["Rules", stats.rules_extracted],
      ["Candidates", stats.candidate_sections]
    ];
    if (stats.option_rules > 0) result.push(["Options", stats.option_rules]);
    if (stats.dependency_links > 0) result.push(["Links", stats.dependency_links]);
    if (stats.partial_failures > 0) result.push(["Failures", stats.partial_failures]);
    return result;
  }
  const all: [string, string | number][] = [
    ["Sections", stats.total_sections],
    ["Classified", stats.classified_sections],
    ["Candidates", stats.candidate_sections],
    ["Windows", `${stats.llm_windows_completed}/${stats.llm_windows_total}`],
    ["Rules", stats.rules_extracted],
    ["Options", stats.option_rules],
    ["Links", stats.dependency_links]
  ];
  if (stats.low_confidence_rules > 0) all.push(["Low Confidence", stats.low_confidence_rules]);
  all.push(["Reviewed", stats.reviewed_rules]);
  all.push(["Draft", stats.draft_rules]);
  if (stats.rejected_rules > 0) all.push(["Rejected", stats.rejected_rules]);
  if (stats.partial_failures > 0) all.push(["Failures", stats.partial_failures]);
  return all;
}

function ExportPanel({ documentId, kinds }: { documentId: number; kinds: string[] }) {
  return (
    <div className="export-row">
      {kinds.map((kind) => (
        <a className="export-button" href={exportUrl(documentId, kind)} key={kind}>
          <Download size={15} />
          {exportLabel(kind)}
        </a>
      ))}
    </div>
  );
}

function sourceForDocument(documentId: number, sourceDocuments: SourceDocument[]) {
  return sourceDocuments.find((source) => source.linked_document_id === documentId) ?? null;
}

function canExtractRulesForSource(source: SourceDocument | null) {
  if (!source) return true;
  return source.doc_type === "rulebook" || source.doc_type === "reference_clause";
}

function displayStatusForDocument(document: DocumentJob, source: SourceDocument | null) {
  if (!source) return document.status;
  if (source.status === "rules_verified" || source.status === "fields_verified") return source.status;
  if (source.doc_type === "template") {
    if (source.status === "fields_extracted" || source.status === "fields_verified") {
      return source.status;
    }
    if (document.status === "mineru_queued" || document.status === "mineru_processing" || document.status === "mineru_failed") {
      return document.status;
    }
    if (document.status === "markdown_ready") return "markdown_ready";
    return source.status;
  }
  return document.status;
}

function viewLabel(view: View) {
  const labels: Record<View, string> = {
    dashboard: "Dashboard",
    sources: "Sources",
    queue: "Queue",
    "document-review": "Document Review",
    "rule-review": "Rule Review",
    "field-review": "Field Review",
    "mapping-review": "Mapping Review",
    submissions: "Submissions",
    results: "Results",
    activity: "Activity",
    settings: "Settings"
  };
  return labels[view];
}

function viewFromPath(pathname: string): { view: View; sourceId: string | null } {
  const documentRoute = pathname.match(/^\/documents\/([^/]+)\/(review|rules|fields)$/);
  if (documentRoute) {
    const view = documentRoute[2] === "review" ? "document-review" : documentRoute[2] === "rules" ? "rule-review" : "field-review";
    return { view, sourceId: decodeURIComponent(documentRoute[1]) };
  }
  const routes: Record<string, View> = {
    "/dashboard": "dashboard",
    "/sources": "sources",
    "/queue": "queue",
    "/mappings": "mapping-review",
    "/submissions": "submissions",
    "/results": "results",
    "/activity": "activity",
    "/settings": "settings",
  };
  return { view: routes[pathname] ?? "dashboard", sourceId: null };
}

function routeForView(view: View, sourceId: string | null) {
  if (view === "document-review") return sourceId ? `/documents/${encodeURIComponent(sourceId)}/review` : "/documents/review";
  if (view === "rule-review") return sourceId ? `/documents/${encodeURIComponent(sourceId)}/rules` : "/documents/rules";
  if (view === "field-review") return sourceId ? `/documents/${encodeURIComponent(sourceId)}/fields` : "/documents/fields";
  const routes: Record<Exclude<View, "document-review" | "rule-review" | "field-review">, string> = {
    dashboard: "/dashboard",
    sources: "/sources",
    queue: "/queue",
    "mapping-review": "/mappings",
    submissions: "/submissions",
    results: "/results",
    activity: "/activity",
    settings: "/settings",
  };
  return routes[view];
}

function exportLabel(kind: string) {
  const labels: Record<string, string> = {
    "source-pdf": "Source PDF",
    "mineru-request": "MinerU Request",
    "mineru-result": "MinerU Result",
    "markdown": "Markdown",
    "rules-json": "Rules JSON",
    "rules-csv": "Rules CSV",
    "llm-windows": "LLM Windows",
    "rule-graph": "Rule Review JSON",
  };
  return labels[kind] ?? kind.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function isClauseParagraph(section: Section) {
  const title = section.title.trim();
  const hasLongNumberedLead = /^([A-Z]\d+(?:\.\d+)+|\d+(?:\.\d+)+)\s+.{24,}/.test(title);
  const hasClauseContent = section.content.trim().startsWith(title.slice(0, 24));
  return hasLongNumberedLead || hasClauseContent;
}

function renderInlineMarkers(value: string, markers: DocumentMarker[] = []) {
  const uniqueMarkers = [...new Map(
    markers
      .filter((marker) => marker.text && value.includes(marker.text))
      .sort((a, b) => b.text.length - a.text.length)
      .map((marker) => [marker.text, marker])
  ).values()];

  if (!uniqueMarkers.length) {
    const parts = value.split(/((?:Section\s+)?(?:[A-Z]\d+|\d+)(?:\.\d+){1,4})/g);
    return parts.map((part, index) => {
      if (/^(?:Section\s+)?(?:[A-Z]\d+|\d+)(?:\.\d+){1,4}$/.test(part)) {
        return (
          <mark className="xref marker-yellow" key={`${part}-${index}`}>
            {part}
          </mark>
        );
      }
      return part;
    });
  }

  const tokens: ReactNode[] = [];
  let cursor = 0;
  while (cursor < value.length) {
    let next: { marker: DocumentMarker; index: number } | null = null;
    for (const marker of uniqueMarkers) {
      const index = value.indexOf(marker.text, cursor);
      if (index < 0) continue;
      if (!next || index < next.index || (index === next.index && marker.text.length > next.marker.text.length)) {
        next = { marker, index };
      }
    }
    if (!next) {
      tokens.push(value.slice(cursor));
      break;
    }
    if (next.index > cursor) tokens.push(value.slice(cursor, next.index));
    tokens.push(
      <mark
        className={`xref marker-${next.marker.color}`}
        key={`${next.marker.section_id}-${next.index}-${next.marker.text}`}
      >
        {next.marker.text}
      </mark>
    );
    cursor = next.index + next.marker.text.length;
  }
  return tokens;
}

type RichBlock =
  | { type: "text"; value: string }
  | { type: "media"; mediaType: string; subtype: string; path: string }
  | { type: "htmlTable"; html: string }
  | { type: "markdownTable"; subtype: string; markdown: string };

const RICH_TOKEN_RE =
  /\[\[MINERU_MEDIA\|([^|\]]*)\|([^|\]]*)\|([^\]]+)\]\]|\[\[MINERU_TABLE_HTML\]\]([\s\S]*?)\[\[\/MINERU_TABLE_HTML\]\]|\[\[MINERU_TABLE_MD\|?([^\]]*)\]\]([\s\S]*?)\[\[\/MINERU_TABLE_MD\]\]/g;

function parseRichBlocks(value: string): RichBlock[] {
  const blocks: RichBlock[] = [];
  let cursor = 0;

  for (const match of value.matchAll(RICH_TOKEN_RE)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      blocks.push({ type: "text", value: value.slice(cursor, index) });
    }
    if (match[1] !== undefined) {
      blocks.push({
        type: "media",
        mediaType: match[1],
        subtype: match[2],
        path: match[3]
      });
    } else if (match[4] !== undefined) {
      blocks.push({ type: "htmlTable", html: match[4].trim() });
    } else {
      blocks.push({ type: "markdownTable", subtype: match[5] || "data", markdown: (match[6] || "").trim() });
    }
    cursor = index + match[0].length;
  }

  if (cursor < value.length) {
    blocks.push({ type: "text", value: value.slice(cursor) });
  }
  return blocks.length ? blocks : [{ type: "text", value }];
}

function renderRichBlocks(blocks: RichBlock[], documentId: number, markers: DocumentMarker[]) {
  return blocks.map((block, index) => {
    if (block.type === "media") {
      const src = `/storage/documents/${documentId}/mineru/${block.path}`;
      const label = block.subtype || block.mediaType;
      return <img className="doc-media" src={src} alt={label} key={`${block.path}-${index}`} loading="lazy" />;
    }
    if (block.type === "htmlTable") {
      return (
        <div
          className="doc-table-wrap"
          dangerouslySetInnerHTML={{ __html: sanitizeTableHtml(block.html) }}
          key={`html-table-${index}`}
        />
      );
    }
    if (block.type === "markdownTable") {
      return (
        <details className="doc-details" key={`md-table-${index}`}>
          <summary>{block.subtype || "table"}</summary>
          {renderMarkdownTable(block.markdown)}
        </details>
      );
    }
    return renderTextParagraphs(block.value, index, markers);
  });
}

function renderTextParagraphs(value: string, keyPrefix: number, markers: DocumentMarker[] = []) {
  return value
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part, index) => (
      <p className="rich-paragraph" key={`text-${keyPrefix}-${index}`}>
        {renderInlineMarkers(part, markers)}
      </p>
    ));
}

function renderMarkdownTable(markdown: string) {
  const rows = markdown
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.includes("|"))
    .map((line) =>
      line
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim())
    );
  if (!rows.length) return <pre className="doc-code">{markdown}</pre>;

  const [header, maybeSeparator, ...rest] = rows;
  const hasSeparator = maybeSeparator?.every((cell) => /^:?-{3,}:?$/.test(cell));
  const bodyRows = hasSeparator ? rest : rows.slice(1);

  return (
    <div className="doc-table-wrap">
      <table>
        <thead>
          <tr>
            {header.map((cell, index) => (
              <th key={`${cell}-${index}`}>{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyRows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {row.map((cell, cellIndex) => (
                <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function sanitizeTableHtml(html: string) {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["table", "thead", "tbody", "tfoot", "tr", "th", "td",
      "caption", "colgroup", "col", "br", "p", "span", "strong", "em",
      "b", "i", "u", "sup", "sub", "a", "img", "div"],
    ALLOWED_ATTR: ["colspan", "rowspan", "style", "class", "align",
      "valign", "scope", "href", "src", "alt", "width", "height"],
  });
}

function flattenSections(sections: Section[]): Section[] {
  return sections.flatMap((section) => [section, ...flattenSections(section.children)]);
}

function sectionCode(section?: Section) {
  if (!section) return "";
  const candidates = [section.title, ...section.heading_path].reverse();
  for (const candidate of candidates) {
    const match = candidate.match(/\b([A-Z]?\d+(?:\.\d+){0,5})\b/i);
    if (match) return match[1].toUpperCase();
  }
  return "";
}

function ruleReferences(rule: Rule, sectionByCode: Map<string, Section>, currentSection?: Section) {
  const ownCode = sectionCode(currentSection);
  const text = [
    rule.subject,
    rule.condition,
    rule.action,
    rule.notes,
    rule.source.evidence_text,
    ...rule.options.flatMap((option) => [option.label, option.condition, option.action, ...option.referenced_sections]),
    ...rule.dependencies.map((dependency) => dependency.reason)
  ].join("\n");
  const refs = new Set<string>();
  for (const match of text.matchAll(/\b(?:Section\s+)?([A-Z]\d+(?:\.\d+){1,5}|\d+(?:\.\d+){1,5})\b/gi)) {
    const code = match[1].toUpperCase();
    if (code !== ownCode) refs.add(code);
  }
  return [...refs].map((code) => {
    const section = sectionByCode.get(code);
    return {
      code,
      resolved: Boolean(section),
      title: section?.title || ""
    };
  });
}

function replaceSection(sections: Section[], next: Section): Section[] {
  return sections.map((section) => {
    if (section.id === next.id) return { ...next, children: section.children };
    return { ...section, children: replaceSection(section.children, next) };
  });
}
