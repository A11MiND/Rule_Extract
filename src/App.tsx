import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  FileText,
  GitBranch,
  Loader2,
  Play,
  Save,
  SearchCheck
} from "lucide-react";
import {
  createDocument,
  extractRules,
  getDocument,
  getOutline,
  getRuleGraph,
  getRules,
  saveRule,
  saveSection
} from "./api";
import type { ContractFamily, DocumentJob, Rule, RuleGraph, Section } from "./types";

const READY_STATUSES = new Set(["markdown_ready", "classifying_sections", "extracting_rules", "rules_extracted"]);
const TERMINAL_STATUSES = new Set(["mineru_failed", "rule_extraction_failed", "rules_extracted"]);

export function App() {
  const [documentJob, setDocumentJob] = useState<DocumentJob | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [graph, setGraph] = useState<RuleGraph>({ nodes: [], edges: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
    getOutline(documentJob.id).then(setSections).catch((err) => setError(err.message));
    getRules(documentJob.id).then(setRules).catch(() => setRules([]));
    getRuleGraph(documentJob.id).then(setGraph).catch(() => setGraph({ nodes: [], edges: [] }));
  }, [documentJob?.id, documentJob?.status]);

  async function handleCreate(payload: { name: string; pdf_url: string; contract_family: ContractFamily }) {
    setBusy(true);
    setError("");
    try {
      const created = await createDocument(payload);
      setDocumentJob(created);
      setSections([]);
      setRules([]);
      setGraph({ nodes: [], edges: [] });
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
        <StatusBadge status={documentJob?.status ?? "idle"} />
      </header>

      {error ? (
        <div className="alert" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      <section className="workflow-grid">
        <ImportPanel onCreate={handleCreate} busy={busy} />
        <ProgressPanel documentJob={documentJob} />
      </section>

      {documentJob && READY_STATUSES.has(documentJob.status) ? (
        <section className="workspace-grid">
          <MarkdownReview documentId={documentJob.id} sections={sections} onSectionsChange={setSections} />
          <RulesPanel rules={rules} onRulesChange={setRules} />
          <RuleFlow graph={graph} />
        </section>
      ) : null}

      {documentJob?.status === "markdown_ready" ? (
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
  busy
}: {
  onCreate: (payload: { name: string; pdf_url: string; contract_family: ContractFamily }) => void;
  busy: boolean;
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
      </form>
    </section>
  );
}

function ProgressPanel({ documentJob }: { documentJob: DocumentJob | null }) {
  const steps = ["mineru_queued", "mineru_processing", "markdown_ready", "rules_extracted"];
  const currentIndex = documentJob ? steps.indexOf(documentJob.status) : -1;

  return (
    <section className="panel">
      <div className="panel-title">
        <SearchCheck size={20} />
        <h2>Processing</h2>
      </div>
      <ol className="timeline">
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
    </section>
  );
}

function MarkdownReview({
  documentId,
  sections,
  onSectionsChange
}: {
  documentId: number;
  sections: Section[];
  onSectionsChange: (sections: Section[]) => void;
}) {
  return (
    <section className="panel tall-panel">
      <div className="panel-title">
        <FileText size={20} />
        <h2>Markdown Review</h2>
      </div>
      <div className="section-list">
        {sections.map((section) => (
          <SectionEditor
            key={section.id}
            documentId={documentId}
            section={section}
            onSaved={(next) => onSectionsChange(replaceSection(sections, next))}
          />
        ))}
      </div>
    </section>
  );
}

function SectionEditor({
  documentId,
  section,
  onSaved
}: {
  documentId: number;
  section: Section;
  onSaved: (section: Section) => void;
}) {
  const [content, setContent] = useState(section.content);
  const [saving, setSaving] = useState(false);

  useEffect(() => setContent(section.content), [section.content]);

  async function handleSave() {
    setSaving(true);
    try {
      const saved = await saveSection(documentId, section.id, content);
      onSaved(saved);
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="section-editor" open={section.level <= 2}>
      <summary>
        <span className="heading-level">H{section.level}</span>
        <span>{section.heading_path.join(" / ")}</span>
      </summary>
      <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={8} />
      <div className="row-actions">
        <button onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
          Save section
        </button>
      </div>
      {section.children.map((child) => (
        <SectionEditor key={child.id} documentId={documentId} section={child} onSaved={onSaved} />
      ))}
    </details>
  );
}

function RulesPanel({ rules, onRulesChange }: { rules: Rule[]; onRulesChange: (rules: Rule[]) => void }) {
  return (
    <section className="panel tall-panel">
      <div className="panel-title">
        <CheckCircle2 size={20} />
        <h2>Rule Cards</h2>
      </div>
      <div className="rule-list">
        {rules.length === 0 ? <p className="muted">Extracted rules will appear here.</p> : null}
        {rules.map((rule) => (
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

function RuleFlow({ graph }: { graph: RuleGraph }) {
  const nodeById = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);

  return (
    <section className="panel tall-panel">
      <div className="panel-title">
        <GitBranch size={20} />
        <h2>Rule Flow</h2>
      </div>
      {graph.nodes.length === 0 ? <p className="muted">Dependencies and option paths will appear here.</p> : null}
      <div className="flow-list">
        {graph.nodes.map((node) => (
          <div className="flow-node" key={node.id}>
            <div>
              <strong>{node.label}</strong>
              <span>{node.type}</span>
            </div>
            {graph.edges
              .filter((edge) => edge.source === node.id)
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

function labelStatus(status: string) {
  return status.replaceAll("_", " ");
}

function replaceSection(sections: Section[], next: Section): Section[] {
  return sections.map((section) => {
    if (section.id === next.id) return { ...next, children: section.children };
    return { ...section, children: replaceSection(section.children, next) };
  });
}
