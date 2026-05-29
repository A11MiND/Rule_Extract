import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { debounce } from "./utils/debounce";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Check,
  Download,
  Edit3,
  FileText,
  GitBranch,
  History as HistoryIcon,
  Loader2,
  Play,
  Plus,
  Save,
  SearchCheck,
  Settings,
  X,
  XCircle,
  Zap,
  Clock,
  Library
} from "lucide-react";
import {
  createDocument,
  extractRules,
  exportUrl,
  getDocument,
  getDocumentStats,
  getDocuments,
  getOutline,
  getRuleGraph,
  getRules,
  getRuntimeConfig,
  saveRule,
  saveRuntimeConfig,
  saveSection
} from "./api";
import { KBWorkspace } from "./components/KBWorkspace";
import type {
  DocumentJob,
  DocumentStats,
  Rule,
  RuleGraph,
  RuntimeConfig,
  RuntimeConfigUpdate,
  Section
} from "./types";

const READY_STATUSES = new Set([
  "markdown_ready",
  "rule_extraction_queued",
  "extracting_rules",
  "rules_extracted",
  "rule_extraction_failed"
]);
const TERMINAL_STATUSES = new Set(["mineru_failed", "rule_extraction_failed", "rules_extracted"]);
const VIEWS = ["import", "processing", "review", "map", "kb"] as const;
type View = (typeof VIEWS)[number];

export function App() {
  const [documentJob, setDocumentJob] = useState<DocumentJob | null>(null);
  const [documents, setDocuments] = useState<DocumentJob[]>([]);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null);
  const [stats, setStats] = useState<DocumentStats | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [graph, setGraph] = useState<RuleGraph>({ nodes: [], edges: [] });
  const [activeView, setActiveView] = useState<View>("import");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState<{ text: string; type: "success" | "info" } | null>(null);
  const previousStatusRef = useRef<string | null>(null);

  function showToast(text: string, type: "success" | "info" = "success") {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  }

  const loadDocuments = useCallback(async () => {
    const nextDocuments = await getDocuments();
    setDocuments(nextDocuments);
    return nextDocuments;
  }, []);

  useEffect(() => {
    getRuntimeConfig().then(setRuntimeConfig).catch(() => undefined);
    loadDocuments()
      .then((documents) => {
        if (documents.length) {
          const latestDocument = documents[0];
          setDocumentJob(latestDocument);
          setActiveView(defaultViewForStatus(latestDocument.status));
        }
      })
      .catch(() => undefined);
  }, [loadDocuments]);

  useEffect(() => {
    if (!documentJob || TERMINAL_STATUSES.has(documentJob.status)) {
      return;
    }
    let stopped = false;
    let failureCount = 0;
    const poll = async () => {
      const jitter = (Math.random() - 0.5) * 1000;
      const next = await getDocument(documentJob.id).catch((err) => {
        failureCount++;
        setError(err.message);
        return null;
      });
      if (stopped) return;
      if (next) {
        failureCount = 0;
        setDocumentJob(next);
        setDocuments((current) => current.map((document) => (document.id === next.id ? next : document)));
      }
    };
    const baseInterval = 2500;
    let currentInterval = baseInterval;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const jitter = (Math.random() - 0.5) * 1000;
      timer = window.setTimeout(async () => {
        await poll();
        if (!stopped) {
          currentInterval = Math.min(currentInterval * (failureCount > 0 ? 2 : 1), 30000);
          schedule();
        }
      }, currentInterval + jitter);
    };
    schedule();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [documentJob?.id, documentJob?.status]);

  useEffect(() => {
    if (!documentJob || !READY_STATUSES.has(documentJob.status)) {
      return;
    }
    refreshDocumentData(documentJob.id);
  }, [documentJob?.id, documentJob?.status]);

  useEffect(() => {
    const previousStatus = previousStatusRef.current;
    const nextStatus = documentJob?.status ?? null;
    if (previousStatus && previousStatus !== "markdown_ready" && nextStatus === "markdown_ready") {
      setActiveView("review");
    }
    previousStatusRef.current = nextStatus;
  }, [documentJob?.status]);

  useEffect(() => {
    if (!documentJob || TERMINAL_STATUSES.has(documentJob.status)) {
      return;
    }
    let stopped = false;
    let failureCount = 0;
    let currentInterval = 2000;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = () => {
      getDocumentStats(documentJob.id).then(setStats).catch((err: Error) => {
        failureCount++;
        setError((prev) => prev || err.message);
      });
    };
    const schedule = () => {
      const jitter = (Math.random() - 0.5) * 600;
      timer = window.setTimeout(() => {
        poll();
        if (!stopped) {
          currentInterval = Math.min(currentInterval * (failureCount > 0 ? 2 : 1), 30000);
          schedule();
        }
      }, currentInterval + jitter);
    };
    schedule();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [documentJob?.id, documentJob?.status]);

  useEffect(() => {
    if (
      !documentJob ||
      !["rule_extraction_queued", "extracting_rules"].includes(documentJob.status)
    ) {
      return;
    }
    let stopped = false;
    let failureCount = 0;
    let currentInterval = 2500;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refreshRuleOutputs = async () => {
      try {
        const [nextRules, nextGraph, nextStats] = await Promise.all([
          getRules(documentJob.id).catch(() => []),
          getRuleGraph(documentJob.id).catch(() => ({ nodes: [], edges: [] })),
          getDocumentStats(documentJob.id).catch(() => null)
        ]);
        failureCount = 0;
        setRules(nextRules);
        setGraph(nextGraph);
        if (nextStats) setStats(nextStats);
      } catch {
        failureCount++;
      }
    };
    const schedule = () => {
      const jitter = (Math.random() - 0.5) * 1000;
      timer = window.setTimeout(() => {
        refreshRuleOutputs().then(() => {
          if (!stopped) {
            currentInterval = Math.min(currentInterval * (failureCount > 0 ? 2 : 1), 30000);
            schedule();
          }
        });
      }, currentInterval + jitter);
    };
    schedule();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [documentJob?.id, documentJob?.status]);

  async function refreshDocumentData(documentId: number) {
    const [outline, nextRules, nextGraph, nextStats] = await Promise.all([
      getOutline(documentId),
      getRules(documentId).catch(() => []),
      getRuleGraph(documentId).catch(() => ({ nodes: [], edges: [] })),
      getDocumentStats(documentId).catch(() => null)
    ]);
    setSections(outline);
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

  async function handleCreate(payload: { name: string; pdf_url: string; grouping_level?: number }) {
    setBusy(true);
    setError("");
    try {
      const created = await createDocument(payload);
      setDocumentJob(created);
      setDocuments((current) => [created, ...current.filter((document) => document.id !== created.id)]);
      setActiveView("processing");
      setSections([]);
      setRules([]);
      setGraph({ nodes: [], edges: [] });
      setStats(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create document");
    } finally {
      setBusy(false);
    }
  }

  async function handleExtract() {
    if (!documentJob) return;
    setBusy(true);
    setError("");
    setRules([]);
    setGraph({ nodes: [], edges: [] });
    try {
      await extractRules(documentJob.id);
      showToast("Rule extraction started — tracking progress below", "info");
      setActiveView("processing");
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

  async function handleSelectDocument(documentId: number) {
    if (!documentId) return;
    setBusy(true);
    setError("");
    try {
      const selected = await getDocument(documentId);
      setDocumentJob(selected);
      previousStatusRef.current = selected.status;
      setActiveView(defaultViewForStatus(selected.status));
      setSections([]);
      setRules([]);
      setGraph({ nodes: [], edges: [] });
      setStats(null);
      if (READY_STATUSES.has(selected.status)) {
        refreshDocumentData(selected.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load document history");
    } finally {
      setBusy(false);
    }
  }

  function handleNewWork() {
    setDocumentJob(null);
    setActiveView("import");
    setSections([]);
    setRules([]);
    setGraph({ nodes: [], edges: [] });
    setStats(null);
    setError("");
    previousStatusRef.current = null;
    loadDocuments().catch(() => undefined);
  }

  const canExtractRules =
    documentJob &&
    activeView !== "import" &&
    (documentJob.status === "markdown_ready" ||
      documentJob.status === "rule_extraction_failed" ||
      (documentJob.status === "rules_extracted" && (stats?.rules_extracted ?? rules.length) === 0));
  const extractButtonLabel = documentJob?.status === "markdown_ready" ? "Extract Rules" : "Retry Extract Rules";

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">NEC Public Works Practice Notes</p>
          <h1>Rule Extraction Portal</h1>
        </div>
        <div className="topbar-actions">
          <button className="secondary-button" type="button" onClick={handleNewWork}>
            <Plus size={16} />
            New Work
          </button>
          <label className="history-picker">
            <HistoryIcon size={16} />
            <select
              aria-label="Document history"
              disabled={!documents.length || busy}
              value={documentJob?.id ?? ""}
              onChange={(event) => handleSelectDocument(Number(event.target.value))}
            >
              <option value="">History</option>
              {documents.map((document) => (
                <option key={document.id} value={document.id}>
                  #{document.id} {document.name} - {labelStatus(document.status)}
                </option>
              ))}
            </select>
          </label>
          <StatusBadge status={documentJob?.status ?? "idle"} />
        </div>
      </header>

      <nav className="view-tabs" aria-label="Portal navigation">
        {VIEWS.map((view) => (
          <button
            className={activeView === view ? "active" : ""}
            key={view}
            onClick={() => setActiveView(view)}
            type="button"
          >
            {viewLabel(view)}
          </button>
        ))}
      </nav>

      {documentJob ? <TopProgressBar documentJob={documentJob} stats={stats} /> : null}

      {toast ? (
        <div className={`toast-banner toast-${toast.type}`} role="status">
          {toast.type === "success" ? <CheckCircle2 size={18} /> : <Zap size={18} />}
          <span>{toast.text}</span>
          <button className="toast-dismiss" onClick={() => setToast(null)} type="button" aria-label="Dismiss">
            <X size={16} />
          </button>
        </div>
      ) : null}
      {error ? (
        <div className="alert" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
          <button className="toast-dismiss" onClick={() => setError("")} type="button" aria-label="Dismiss">
            <X size={16} />
          </button>
        </div>
      ) : null}

      {activeView === "import" ? (
        <section className="portal-page import-page">
          <RuntimeConfigPanel runtimeConfig={runtimeConfig} onSave={handleSaveRuntimeConfig} busy={busy} />
          <ImportPanel onCreate={handleCreate} busy={busy} runtimeConfig={runtimeConfig} />
          <ExtractionSettingsPanel runtimeConfig={runtimeConfig} onSave={handleSaveRuntimeConfig} busy={busy} />
        </section>
      ) : null}

      {activeView === "processing" ? (
        <section className="portal-page">
          <ProgressPanel documentJob={documentJob} stats={stats} />
          {documentJob ? <ExportPanel documentId={documentJob.id} kinds={["mineru-request", "mineru-result", "llm-windows"]} /> : null}
        </section>
      ) : null}

      {activeView === "review" && documentJob && READY_STATUSES.has(documentJob.status) ? (
        <section className="portal-page">
          <MarkdownReview
            documentId={documentJob.id}
            pdfUrl={`/api/documents/${documentJob.id}/source-pdf`}
            sections={sections}
            onSectionsChange={setSections}
          />
          <ExportPanel documentId={documentJob.id} kinds={["source-pdf", "markdown"]} />
        </section>
      ) : null}

      {activeView === "map" && documentJob && READY_STATUSES.has(documentJob.status) ? (
        <section className="portal-page">
          <RuleMap documentId={documentJob.id} graph={graph} rules={rules} sections={sections} onRulesChange={setRules} />
        </section>
      ) : null}

      {activeView === "kb" ? (
        <section className="portal-page">
          <KBWorkspace />
        </section>
      ) : null}

      {canExtractRules ? (
        <div className="action-bar">
          <button className="primary-button" onClick={handleExtract} disabled={busy}>
            {busy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            {extractButtonLabel}
          </button>
        </div>
      ) : null}
    </main>
  );
}

function ImportPanel({
  onCreate,
  busy,
  runtimeConfig
}: {
  onCreate: (payload: { name: string; pdf_url: string; grouping_level?: number }) => void;
  busy: boolean;
  runtimeConfig: RuntimeConfig | null;
}) {
  const [name, setName] = useState("NEC Practice Note Demo");
  const [pdfUrl, setPdfUrl] = useState("");
  const [groupingLevel, setGroupingLevel] = useState(runtimeConfig?.default_grouping_level ?? 2);

  return (
    <section className="panel">
      <div className="panel-title">
        <FileText size={20} />
        <h2>Import PDF</h2>
      </div>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          onCreate({ name, pdf_url: pdfUrl, grouping_level: groupingLevel });
        }}
      >
        <label>
          Document name
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          Public PDF URL
          <input
            value={pdfUrl}
            onChange={(event) => setPdfUrl(event.target.value)}
            placeholder="https://example.com/nec-practice-note.pdf"
            required
            type="url"
          />
        </label>
        <label>
          Group by
          <select value={groupingLevel} onChange={(event) => setGroupingLevel(Number(event.target.value))}>
            <option value={1}>Part (H1)</option>
            <option value={2}>Chapter (H2)</option>
            <option value={3}>Sub-chapter (H3)</option>
          </select>
          <span className="hint">Split document at this heading level for rule extraction.</span>
        </label>
        <button className="primary-button" type="submit" disabled={busy}>
          {busy ? <Loader2 className="spin" size={18} /> : <ChevronRight size={18} />}
          Start MinerU
        </button>
        {!runtimeConfig?.mineru_configured ? <p className="error-text">MinerU token is required before import.</p> : null}
      </form>
    </section>
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
        <h2>Runtime API Config</h2>
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
          {saved ? "Config Saved" : "Save API Config"}
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
        <h2>Processing</h2>
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

function PhaseBadge({ status }: { status: string }) {
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

function TopProgressBar({ documentJob, stats }: { documentJob: DocumentJob; stats: DocumentStats | null }) {
  const steps = ["mineru_queued","mineru_processing","markdown_ready","extracting_rules","rules_extracted"];
  const idx = Math.max(0, steps.indexOf(documentJob.status));
  const pct = documentJob.status.includes("failed")
    ? 100
    : Math.round(((idx + 1) / steps.length) * 100);

  const windowsDone = stats?.llm_windows_completed ?? 0;
  const windowsTotal = stats?.llm_windows_total ?? 0;
  const isLLMPhase = documentJob.status === "extracting_rules";

  return (
    <section className="top-progress" aria-label="Document processing progress">
      <div className="top-progress-meta">
        <span>Document #{documentJob.id}</span>
        {isLLMPhase && windowsTotal > 0 ? (
          <span className="top-progress-windows">{windowsDone}/{windowsTotal} windows</span>
        ) : null}
        <span>{labelStatus(documentJob.status)}</span>
      </div>
      <div className={`top-progress-bar ${documentJob.status.includes("failed") ? "failed" : ""}`}>
        <span style={{ width: `${pct}%` }} />
      </div>
    </section>
  );
}

function MarkdownReview({
  documentId,
  pdfUrl,
  sections,
  onSectionsChange
}: {
  documentId: number;
  pdfUrl: string;
  sections: Section[];
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
  onSaved
}: {
  documentId: number;
  section: Section;
  onSaved: (section: Section) => void;
}) {
  const [draft, setDraft] = useState(section.content || section.title);
  const [saving, setSaving] = useState(false);
  const paragraphLike = isClauseParagraph(section);

  useEffect(() => setDraft(section.content || section.title), [section.content, section.title]);

  const debouncedSave = useCallback(
    debounce(async (nextContent: string) => {
      const normalized = nextContent.trim();
      if (normalized === section.content.trim()) return;
      setSaving(true);
      try {
        const saved = await saveSection(documentId, section.id, normalized);
        onSaved(saved);
      } finally {
        setSaving(false);
      }
    }, 300),
    [documentId, section.id, section.content, onSaved]
  );

  if (paragraphLike) {
    return (
      <div className={`doc-block doc-depth-${Math.min(section.level, 6)}`} data-section-id={section.id}>
        <EditableParagraph
          documentId={documentId}
          value={draft}
          saving={saving}
          onChange={setDraft}
          onSave={debouncedSave}
          className="doc-clause"
        />
        {section.children.map((child) => (
          <SectionPreview key={child.id} documentId={documentId} section={child} onSaved={onSaved} />
        ))}
      </div>
    );
  }

  const HeadingTag = `h${Math.min(section.level, 4)}` as keyof JSX.IntrinsicElements;

  return (
    <section className={`doc-block doc-depth-${Math.min(section.level, 6)}`} data-section-id={section.id}>
      <HeadingTag className={`doc-heading doc-heading-${Math.min(section.level, 4)}`}>
        {section.title}
      </HeadingTag>
      {section.content.trim() ? (
        <EditableParagraph
          documentId={documentId}
          value={draft}
          saving={saving}
          onChange={setDraft}
          onSave={debouncedSave}
          className="doc-body"
        />
      ) : null}
      {section.children.map((child) => (
        <SectionPreview key={child.id} documentId={documentId} section={child} onSaved={onSaved} />
      ))}
    </section>
  );
}

function EditableParagraph({
  documentId,
  value,
  saving,
  onChange,
  onSave,
  className
}: {
  documentId: number;
  value: string;
  saving: boolean;
  onChange: (value: string) => void;
  onSave: (value: string) => void;
  className: string;
}) {
  const [editing, setEditing] = useState(false);
  const blocks = useMemo(() => parseRichBlocks(value), [value]);
  const hasRichBlocks = blocks.some((block) => block.type !== "text");

  if (hasRichBlocks) {
    return (
      <div className="editable-block">
        <div className={`${className} rich-content`}>{renderRichBlocks(blocks, documentId)}</div>
        <span className="edit-state" aria-label={saving ? "Saving" : "Rendered"}>
          {saving ? <Loader2 className="spin" size={14} /> : <Check size={14} />}
        </span>
      </div>
    );
  }

  return (
    <div className="editable-block">
      <div
        className={className}
        contentEditable
        role="textbox"
        spellCheck={false}
        suppressContentEditableWarning
        onFocus={() => setEditing(true)}
        onBlur={(event) => {
          setEditing(false);
          const next = event.currentTarget.innerText;
          if (next.trim() === value.trim()) return;
          onChange(next);
          void onSave(next);
        }}>
        {renderInlineReferences(value)}
      </div>
      <span className="edit-state" aria-label={saving ? "Saving" : editing ? "Editing" : "Editable"}>
        {saving ? <Loader2 className="spin" size={14} /> : editing ? <Edit3 size={14} /> : <Check size={14} />}
      </span>
    </div>
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
  const [hoveredXrefCode, setHoveredXrefCode] = useState<string | null>(null);
  const prevRuleIdsRef = useRef<Set<string>>(new Set());
  const [newRuleIds, setNewRuleIds] = useState<Set<string>>(new Set());

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

  const totalRules = filteredRules.length;
  const typeCounts: Record<string, number> = {};
  for (const t of Object.keys(RULE_TYPE_COLORS)) {
    typeCounts[t] = filteredRules.filter((r) => r.type === t).length;
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
    const nextDraft = { ...ruleDraft, review_status: status };
    setRuleDraft(nextDraft);
    try {
      const saved = await saveRule(nextDraft);
      onRulesChange(rules.map((r) => (r.id === saved.id ? saved : r)));
      setSelectedRule(saved);
    } catch { /* keep draft state on error */ }
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
      <div className="panel-title">
        <GitBranch size={20} />
        <h2>Rule Logic Review</h2>
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
            reviewed: "Rules marked as accepted"
          };
          const label = item === "all" ? "All" : item.charAt(0).toUpperCase() + item.slice(1);
          const count = item === "all" ? totalRules : item === "low" ? filteredRules.filter((r) => r.confidence < 0.65).length : item === "reviewed" ? filteredRules.filter((r) => r.review_status === "reviewed").length : (typeCounts[item] || 0);
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
        <div className="mm-workspace">
          <div className="mm-tree-column">
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
          <div className="mm-edit-panel">
            {selectedRule && ruleDraft ? (
              <>
                <div className="mm-edit-panel-header">
                  <div>
                    <span className="mm-rule-type" style={{ background: RULE_TYPE_COLORS[ruleDraft.type] || "#6b7280", fontSize: 11 }}>{ruleDraft.type}</span>
                    <span style={{ marginLeft: 8, fontSize: 13, color: "#64748b" }}>
                      {Math.round(ruleDraft.confidence * 100)}% confidence
                    </span>
                  </div>
                  <button className="toast-dismiss" onClick={closeEditPanel} type="button" aria-label="Close editor">
                    <X size={18} />
                  </button>
                </div>

                {/* Review status banner */}
                {ruleDraft.review_status === "reviewed" ? (
                  <div className="review-banner approved">✓ This rule has been accepted</div>
                ) : ruleDraft.review_status === "rejected" ? (
                  <div className="review-banner rejected">✗ This rule has been rejected</div>
                ) : (
                  <div className="review-banner draft">⚑ This rule needs review</div>
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
                      <span className="mm-detail-label">Depends on</span>
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
                      Accept
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
              <div className="mm-edit-empty">
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

function MindmapSectionNode({
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
}

function MindmapRuleNode({
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
        className="mm-rule-header clickable"
        onClick={() => onSelectRule(rule)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelectRule(rule); } }}
      >
        <span
          className={`mm-toggle small ${expanded ? "open" : ""}`}
          onClick={(e) => { e.stopPropagation(); hasDetails && setExpanded(!expanded); }}
          title={hasDetails ? "Toggle details" : undefined}
        >
          {hasDetails ? (expanded ? "▾" : "▸") : "·"}
        </span>
        <span className="mm-rule-status-pill" style={{
          background: rule.review_status === "reviewed" ? "#f0fdf4" : rule.review_status === "rejected" ? "#fef2f2" : "#fffbeb",
          color: rule.review_status === "reviewed" ? "#16a34a" : rule.review_status === "rejected" ? "#dc2626" : "#d97706",
          borderColor: rule.review_status === "reviewed" ? "#bbf7d0" : rule.review_status === "rejected" ? "#fecaca" : "#fde68a"
        }}>
          {rule.review_status === "reviewed" ? "OK" : rule.review_status === "rejected" ? "NO" : "..."}
        </span>
        <span className="mm-rule-type" style={{ background: typeColor }}>{rule.type}</span>
        <span className="mm-rule-subject">{rule.subject || rule.action || rule.id}</span>
        <span className="mm-confidence">{Math.round(rule.confidence * 100)}%</span>
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
              <span className="mm-detail-label">Depends on</span>
              <span className="mm-detail-value">
                {rule.dependencies.map((d, i) => (
                  <span key={i} className="mm-dep">{d.type}: {d.reason || d.rule_id}</span>
                ))}
              </span>
            </div>
          )}
          {relatedEdges.length > 0 && (
            <div className="mm-detail-row">
              <span className="mm-detail-label">Graph edges</span>
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
}

function StatusBadge({ status }: { status: string }) {
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

function visibleStats(stats: DocumentStats | null, status?: string): [string, string | number][] {
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
  if (stats.low_confidence_rules > 0) all.push(["Low confidence", stats.low_confidence_rules]);
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

function labelStatus(status: string) {
  return status.replaceAll("_", " ");
}

function defaultViewForStatus(status: string): View {
  if (status === "markdown_ready") return "review";
  if (["rule_extraction_queued", "extracting_rules"].includes(status)) return "processing";
  if (["rules_extracted", "rule_extraction_failed"].includes(status)) return "map";
  return "processing";
}

function viewLabel(view: View) {
  const labels: Record<View, string> = {
    import: "Import PDF",
    processing: "Processing",
    review: "Document Review",
    map: "Rule Logic Review",
    kb: "Knowledge Base"
  };
  return labels[view];
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
    "rule-graph": "Rule Logic JSON",
  };
  return labels[kind] ?? kind.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function isClauseParagraph(section: Section) {
  const title = section.title.trim();
  const hasLongNumberedLead = /^([A-Z]\d+(?:\.\d+)+|\d+(?:\.\d+)+)\s+.{24,}/.test(title);
  const hasClauseContent = section.content.trim().startsWith(title.slice(0, 24));
  return hasLongNumberedLead || hasClauseContent;
}

function renderInlineReferences(value: string) {
  const parts = value.split(/((?:Section\s+)?(?:[A-Z]\d+|\d+)(?:\.\d+){1,4})/g);
  return parts.map((part, index) => {
    if (/^(?:Section\s+)?(?:[A-Z]\d+|\d+)(?:\.\d+){1,4}$/.test(part)) {
      return (
        <mark className="xref" key={`${part}-${index}`}>
          {part}
        </mark>
      );
    }
    return part;
  });
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

function renderRichBlocks(blocks: RichBlock[], documentId: number) {
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
    return renderTextParagraphs(block.value, index);
  });
}

function renderTextParagraphs(value: string, keyPrefix: number) {
  return value
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part, index) => (
      <p className="rich-paragraph" key={`text-${keyPrefix}-${index}`}>
        {renderInlineReferences(part)}
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
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/\s+on[a-z]+\s*=\s*"[^"]*"/gi, "")
    .replace(/\s+on[a-z]+\s*=\s*'[^']*'/gi, "");
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
