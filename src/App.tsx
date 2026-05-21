import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Check,
  Download,
  Edit3,
  FileText,
  GitBranch,
  Loader2,
  Play,
  Save,
  SearchCheck,
  Settings
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

const READY_STATUSES = new Set([
  "markdown_ready",
  "rule_extraction_queued",
  "classifying_sections",
  "extracting_rules",
  "rules_extracted"
]);
const TERMINAL_STATUSES = new Set(["mineru_failed", "rule_extraction_failed", "rules_extracted"]);
const VIEWS = ["import", "processing", "review", "rules", "map"] as const;
type View = (typeof VIEWS)[number];

export function App() {
  const [documentJob, setDocumentJob] = useState<DocumentJob | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null);
  const [stats, setStats] = useState<DocumentStats | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [graph, setGraph] = useState<RuleGraph>({ nodes: [], edges: [] });
  const [activeView, setActiveView] = useState<View>("import");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const previousStatusRef = useRef<string | null>(null);

  useEffect(() => {
    getRuntimeConfig().then(setRuntimeConfig).catch(() => undefined);
    getDocuments()
      .then((documents) => {
        if (documents.length) {
          const latestDocument = documents[0];
          setDocumentJob(latestDocument);
          setActiveView(latestDocument.status === "markdown_ready" ? "review" : "processing");
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!documentJob || TERMINAL_STATUSES.has(documentJob.status)) {
      return;
    }
    const timer = window.setInterval(async () => {
      const next = await getDocument(documentJob.id).catch((err) => {
        setError(err.message);
        return null;
      });
      if (next) {
        setDocumentJob(next);
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [documentJob]);

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
    const timer = window.setInterval(() => {
      getDocumentStats(documentJob.id).then(setStats).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save runtime config");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate(payload: { name: string; pdf_url: string; contract_family: ContractFamily }) {
    setBusy(true);
    setError("");
    try {
      const created = await createDocument(payload);
      setDocumentJob(created);
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
    try {
      await extractRules(documentJob.id);
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

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">NEC Public Works Practice Notes</p>
          <h1>Rule Extraction Portal</h1>
        </div>
        <div className="topbar-actions">
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

      {documentJob ? <TopProgressBar documentJob={documentJob} /> : null}

      {error ? (
        <div className="alert" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      {activeView === "import" ? (
        <section className="portal-page import-page">
          <RuntimeConfigPanel runtimeConfig={runtimeConfig} onSave={handleSaveRuntimeConfig} busy={busy} />
          <ImportPanel onCreate={handleCreate} busy={busy} runtimeConfig={runtimeConfig} />
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
            pdfUrl={documentJob.pdf_url}
            sections={sections}
            onSectionsChange={setSections}
          />
          <ExportPanel documentId={documentJob.id} kinds={["markdown"]} />
        </section>
      ) : null}

      {activeView === "rules" && documentJob && READY_STATUSES.has(documentJob.status) ? (
        <section className="portal-page">
          <RulesPanel documentId={documentJob.id} rules={rules} stats={stats} onRulesChange={setRules} />
        </section>
      ) : null}

      {activeView === "map" && documentJob && READY_STATUSES.has(documentJob.status) ? (
        <section className="portal-page">
          <RuleMap documentId={documentJob.id} graph={graph} rules={rules} sections={sections} />
        </section>
      ) : null}

      {documentJob?.status === "markdown_ready" && activeView !== "import" ? (
        <div className="action-bar">
          <button className="primary-button" onClick={handleExtract} disabled={busy}>
            {busy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            Extract Rules
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
  onCreate: (payload: { name: string; pdf_url: string; contract_family: ContractFamily }) => void;
  busy: boolean;
  runtimeConfig: RuntimeConfig | null;
}) {
  const [name, setName] = useState("NEC Practice Note Demo");
  const [pdfUrl, setPdfUrl] = useState("");
  const [contractFamily, setContractFamily] = useState<ContractFamily>("Generic");

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
          onCreate({ name, pdf_url: pdfUrl, contract_family: contractFamily });
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
          Contract family
          <select value={contractFamily} onChange={(event) => setContractFamily(event.target.value as ContractFamily)}>
            <option value="Generic">Generic</option>
            <option value="ECC">ECC</option>
            <option value="TSC">TSC</option>
          </select>
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
          <input value={draft.llm_model || ""} onChange={(event) => setDraft({ ...draft, llm_model: event.target.value })} />
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
        <button className="primary-button" type="submit" disabled={busy}>
          {busy ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
          Save API Config
        </button>
      </form>
    </section>
  );
}

function ProgressPanel({ documentJob, stats }: { documentJob: DocumentJob | null; stats: DocumentStats | null }) {
  const steps = [
    "mineru_queued",
    "mineru_processing",
    "markdown_ready",
    "classifying_sections",
    "extracting_rules",
    "rules_extracted"
  ];
  const currentIndex = documentJob ? steps.indexOf(documentJob.status) : -1;
  const progress = currentIndex < 0 ? 0 : Math.round(((currentIndex + 1) / steps.length) * 100);

  return (
    <section className="panel processing-hud">
      <div className="panel-title">
        <SearchCheck size={20} />
        <h2>Processing</h2>
      </div>
      <div className="hud-progress" aria-label="Processing progress">
        <span style={{ width: `${progress}%` }} />
      </div>
      <ol className="timeline horizontal">
        {steps.map((step, index) => (
          <li key={step} className={index <= currentIndex ? "done" : ""}>
            {index <= currentIndex ? <CheckCircle2 size={18} /> : <span className="step-dot" />}
            <span>{labelStatus(step)}</span>
          </li>
        ))}
      </ol>
      {documentJob ? (
        <div className="job-meta">
          <span>Document #{documentJob.id}</span>
          <span>{documentJob.contract_family}</span>
          {documentJob.mineru_task_id ? <span>MinerU {documentJob.mineru_task_id}</span> : null}
        </div>
      ) : (
        <p className="muted">No document job yet.</p>
      )}
      {documentJob?.error_message ? <p className="error-text">{documentJob.error_message}</p> : null}
      <StatsGrid stats={stats} />
    </section>
  );
}

function TopProgressBar({ documentJob }: { documentJob: DocumentJob }) {
  const steps = [
    "mineru_queued",
    "mineru_processing",
    "markdown_ready",
    "classifying_sections",
    "extracting_rules",
    "rules_extracted"
  ];
  const currentIndex = Math.max(0, steps.indexOf(documentJob.status));
  const progress = documentJob.status.includes("failed")
    ? 100
    : Math.round(((currentIndex + 1) / steps.length) * 100);

  return (
    <section className="top-progress" aria-label="Document processing progress">
      <div className="top-progress-meta">
        <span>Document #{documentJob.id}</span>
        <span>{labelStatus(documentJob.status)}</span>
      </div>
      <div className={`top-progress-bar ${documentJob.status.includes("failed") ? "failed" : ""}`}>
        <span style={{ width: `${progress}%` }} />
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

  async function handleSave(nextContent: string) {
    const normalized = nextContent.trim();
    if (normalized === section.content.trim()) return;
    setSaving(true);
    try {
      const saved = await saveSection(documentId, section.id, normalized);
      onSaved(saved);
    } finally {
      setSaving(false);
    }
  }

  if (paragraphLike) {
    return (
      <div className={`doc-block doc-depth-${Math.min(section.level, 6)}`} data-section-id={section.id}>
        <EditableParagraph
          documentId={documentId}
          value={draft}
          saving={saving}
          onChange={setDraft}
          onSave={handleSave}
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
          onSave={handleSave}
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
        suppressContentEditableWarning
        role="textbox"
        spellCheck={false}
        onFocus={() => setEditing(true)}
        onBlur={(event) => {
          setEditing(false);
          const next = event.currentTarget.innerText;
          onChange(next);
          void onSave(next);
        }}
      >
        {renderInlineReferences(value)}
      </div>
      <span className="edit-state" aria-label={saving ? "Saving" : editing ? "Editing" : "Editable"}>
        {saving ? <Loader2 className="spin" size={14} /> : editing ? <Edit3 size={14} /> : <Check size={14} />}
      </span>
    </div>
  );
}

function RulesPanel({
  documentId,
  rules,
  stats,
  onRulesChange
}: {
  documentId: number;
  rules: Rule[];
  stats: DocumentStats | null;
  onRulesChange: (rules: Rule[]) => void;
}) {
  const [filter, setFilter] = useState("all");
  const filteredRules = rules.filter((rule) => {
    if (filter === "all") return true;
    if (filter === "low") return rule.confidence < 0.65;
    if (filter === "reviewed") return rule.review_status === "reviewed";
    if (filter === "reference") return rule.dependencies.some((dependency) => dependency.type === "references");
    return rule.type === filter;
  });

  return (
    <section className="panel tall-panel">
      <div className="panel-title">
        <CheckCircle2 size={20} />
        <h2>Rule Cards</h2>
      </div>
      <StatsGrid stats={stats} />
      <div className="filter-row">
        {["all", "obligation", "option", "reference", "low", "reviewed"].map((item) => (
          <button className={filter === item ? "active" : ""} key={item} onClick={() => setFilter(item)} type="button">
            {item}
          </button>
        ))}
      </div>
      <ExportPanel documentId={documentId} kinds={["rules-json", "rules-csv", "llm-windows"]} />
      <div className="rule-list">
        {rules.length === 0 ? <p className="muted">Extracted rules will appear here.</p> : null}
        {filteredRules.map((rule) => (
          <RuleCard key={rule.id} rule={rule} onSaved={(next) => onRulesChange(rules.map((r) => (r.id === next.id ? next : r)))} />
        ))}
      </div>
    </section>
  );
}

function RuleCard({ rule, onSaved }: { rule: Rule; onSaved: (rule: Rule) => void }) {
  const [draft, setDraft] = useState(rule);
  const [saving, setSaving] = useState(false);

  useEffect(() => setDraft(rule), [rule]);

  async function handleSave() {
    setSaving(true);
    try {
      const saved = await saveRule(draft);
      onSaved(saved);
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="rule-card">
      <div className="rule-card-header">
        <span className="rule-type">{draft.type}</span>
        <span>{Math.round(draft.confidence * 100)}%</span>
      </div>
      <label>
        Subject
        <input value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} />
      </label>
      <label>
        Condition
        <textarea
          value={draft.condition}
          onChange={(event) => setDraft({ ...draft, condition: event.target.value })}
          rows={3}
        />
      </label>
      <label>
        Action
        <textarea value={draft.action} onChange={(event) => setDraft({ ...draft, action: event.target.value })} rows={3} />
      </label>
      <p className="evidence">{draft.source.evidence_text || "No evidence text supplied."}</p>
      {draft.options.length ? (
        <ul className="option-list">
          {draft.options.map((option) => (
            <li key={`${draft.id}-${option.label}`}>{option.label}: {option.condition || option.action}</li>
          ))}
        </ul>
      ) : null}
      <div className="row-actions">
        <select
          value={draft.review_status}
          onChange={(event) => setDraft({ ...draft, review_status: event.target.value as Rule["review_status"] })}
        >
          <option value="draft">Draft</option>
          <option value="reviewed">Reviewed</option>
          <option value="rejected">Rejected</option>
        </select>
        <button onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
          Save rule
        </button>
      </div>
    </article>
  );
}

function RuleMap({
  documentId,
  graph,
  rules,
  sections
}: {
  documentId: number;
  graph: RuleGraph;
  rules: Rule[];
  sections: Section[];
}) {
  const nodeById = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const sectionTitleById = useMemo(() => flattenSections(sections).reduce((map, section) => map.set(section.id, section.title), new Map<string, string>()), [sections]);

  return (
    <section className="panel tall-panel">
      <div className="panel-title">
        <GitBranch size={20} />
        <h2>Rule Map</h2>
      </div>
      <ExportPanel documentId={documentId} kinds={["rule-graph"]} />
      {graph.nodes.length === 0 ? <p className="muted">Dependencies and option paths will appear here.</p> : null}
      <div className="relationship-map">
        {rules.map((rule) => (
          <div className="flow-node" key={rule.id}>
            <div>
              <strong>{rule.subject || rule.action || rule.id}</strong>
              <span>{rule.type}</span>
            </div>
            <p>
              Section <ChevronRight size={14} /> {sectionTitleById.get(rule.section_id || "") || rule.section_id || "unknown"}
            </p>
            {rule.options.map((option) => (
              <p key={`${rule.id}-${option.label}`}>
                option {option.label || "path"} <ChevronRight size={14} /> {option.action || option.condition || "related path"}
              </p>
            ))}
            {rule.dependencies.map((dependency) => (
              <p key={`${rule.id}-${dependency.type}-${dependency.rule_id}-${dependency.reason}`}>
                {dependency.type} <ChevronRight size={14} /> {dependency.rule_id ? nodeById.get(dependency.rule_id)?.label ?? dependency.rule_id : dependency.reason}
              </p>
            ))}
            {graph.edges
              .filter((edge) => edge.source === rule.id)
              .map((edge) => (
                <p key={`${edge.source}-${edge.target}-${edge.label}`}>
                  {edge.label} <ChevronRight size={14} /> {nodeById.get(edge.target)?.label ?? edge.target}
                </p>
              ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{labelStatus(status)}</span>;
}

function StatsGrid({ stats }: { stats: DocumentStats | null }) {
  const items = [
    ["Sections", stats?.total_sections ?? 0],
    ["Classified", stats?.classified_sections ?? 0],
    ["Candidates", stats?.candidate_sections ?? 0],
    ["Windows", `${stats?.llm_windows_completed ?? 0}/${stats?.llm_windows_total ?? 0}`],
    ["Rules", stats?.rules_extracted ?? 0],
    ["Options", stats?.option_rules ?? 0],
    ["Links", stats?.dependency_links ?? 0],
    ["Low confidence", stats?.low_confidence_rules ?? 0],
    ["Reviewed", stats?.reviewed_rules ?? 0],
    ["Draft", stats?.draft_rules ?? 0],
    ["Rejected", stats?.rejected_rules ?? 0],
    ["Failures", stats?.partial_failures ?? 0]
  ];
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

function viewLabel(view: View) {
  const labels: Record<View, string> = {
    import: "Import PDF",
    processing: "Processing",
    review: "Document Review",
    rules: "Rules",
    map: "Rule Map"
  };
  return labels[view];
}

function exportLabel(kind: string) {
  return kind
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
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

function replaceSection(sections: Section[], next: Section): Section[] {
  return sections.map((section) => {
    if (section.id === next.id) return { ...next, children: section.children };
    return { ...section, children: replaceSection(section.children, next) };
  });
}
