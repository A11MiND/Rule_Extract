import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Check,
  Edit3,
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
  getDocuments,
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
    getDocuments()
      .then((documents) => {
        if (documents.length) {
          setDocumentJob(documents[0]);
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
    <section className="panel tall-panel document-panel">
      <div className="panel-title">
        <FileText size={20} />
        <h2>Document Preview</h2>
      </div>
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

function isClauseParagraph(section: Section) {
  const title = section.title.trim();
  const hasLongNumberedLead = /^([A-Z]\d+(?:\.\d+){2,}|\d+(?:\.\d+){2,})\s+.{24,}/.test(title);
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

function replaceSection(sections: Section[], next: Section): Section[] {
  return sections.map((section) => {
    if (section.id === next.id) return { ...next, children: section.children };
    return { ...section, children: replaceSection(section.children, next) };
  });
}
