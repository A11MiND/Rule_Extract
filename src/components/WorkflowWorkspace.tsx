import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Check, ClipboardList, FileText, GitBranch, Loader2, Play, Plus, Trash2 } from "lucide-react";
import {
  createCollection,
  createDocument,
  createMappingRun,
  createSourceDocument,
  createTenderSubmission,
  deleteSourceDocument,
  deleteTenderSubmission,
  extractRules,
  extractTenderEvidence,
  extractTemplateFields,
  getCollections,
  getDocuments,
  getFieldRuleMappings,
  getRules,
  getSourceDocuments,
  getTemplateFields,
  getTenderResults,
  getTenderSubmissions,
  runTenderChecks,
  updateFieldRuleMapping,
  updateTemplateField,
  verifySourceDocument
} from "../api";
import type {
  CheckResult,
  DocumentCollection,
  DocumentJob,
  FieldRuleMapping,
  Rule,
  SourceDocument,
  TemplateField,
  TenderSubmission
} from "../types";

type SourceKind = "rulebook" | "template";

type WorkflowWorkspaceProps = {
  onOpenDocument: (documentId: number, view: "review" | "map" | "processing") => void;
};

export function WorkflowWorkspace({ onOpenDocument }: WorkflowWorkspaceProps) {
  const [collections, setCollections] = useState<DocumentCollection[]>([]);
  const [activeCollectionId, setActiveCollectionId] = useState("");
  const [sourceDocuments, setSourceDocuments] = useState<SourceDocument[]>([]);
  const [templateFields, setTemplateFields] = useState<TemplateField[]>([]);
  const [mappings, setMappings] = useState<FieldRuleMapping[]>([]);
  const [tenderSubmissions, setTenderSubmissions] = useState<TenderSubmission[]>([]);
  const [tenderResultsBySubmission, setTenderResultsBySubmission] = useState<Record<string, CheckResult[]>>({});
  const [expandedSubmissionId, setExpandedSubmissionId] = useState<string | null>(null);
  const [legacyDocuments, setLegacyDocuments] = useState<DocumentJob[]>([]);
  const [ruleCounts, setRuleCounts] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const activeCollection = collections.find((item) => item.id === activeCollectionId) ?? null;
  const rulebooks = sourceDocuments.filter((doc) => doc.doc_type === "rulebook");
  const templates = sourceDocuments.filter((doc) => doc.doc_type === "template");
  const tenderSources = sourceDocuments.filter((doc) => doc.doc_type === "tender_submission");
  const approvedFields = templateFields.filter((field) => field.review_status === "approved");
  const suggestedMappings = mappings.filter((item) => item.review_status === "suggested" || item.review_status === "needs_edit");
  const approvedMappings = mappings.filter((item) => item.review_status === "approved");

  const linkedDocuments = useMemo(() => {
    const map = new Map<number, DocumentJob>();
    legacyDocuments.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [legacyDocuments]);

  const refresh = useCallback(async (collectionId = activeCollectionId) => {
    const [nextCollections, nextLegacyDocuments] = await Promise.all([
      getCollections(),
      getDocuments().catch(() => [])
    ]);
    setCollections(nextCollections);
    setLegacyDocuments(nextLegacyDocuments);

    const selected = collectionId || nextCollections[0]?.id || "";
    if (selected && selected !== activeCollectionId) setActiveCollectionId(selected);
    if (!selected) {
      setSourceDocuments([]);
      setTemplateFields([]);
      setMappings([]);
      setTenderSubmissions([]);
      setTenderResultsBySubmission({});
      setRuleCounts({});
      return;
    }

    const [docs, fields, maps, submissions] = await Promise.all([
      getSourceDocuments({ collection_id: selected }),
      getTemplateFields({ collection_id: selected }),
      getFieldRuleMappings({ collection_id: selected }),
      getTenderSubmissions({ collection_id: selected })
    ]);
    setSourceDocuments(docs);
    setTemplateFields(fields);
    setMappings(maps);
    setTenderSubmissions(submissions);

    const resultsEntries = await Promise.all(
      submissions.map(async (submission) => {
        try {
          const rows = await getTenderResults(submission.id);
          return [submission.id, rows] as const;
        } catch {
          return [submission.id, []] as const;
        }
      })
    );
    setTenderResultsBySubmission(Object.fromEntries(resultsEntries));

    const rulebookDocIds = docs
      .filter((doc) => doc.doc_type === "rulebook" && doc.linked_document_id)
      .map((doc) => doc.linked_document_id as number);
    const counts: Record<number, number> = {};
    await Promise.all(
      rulebookDocIds.map(async (id) => {
        counts[id] = await getRules(id).then((rules) => rules.length).catch(() => 0);
      })
    );
    setRuleCounts(counts);
  }, [activeCollectionId]);

  useEffect(() => {
    refresh().catch((error) => setMessage(error.message));
  }, []);

  async function runAction<T>(action: () => Promise<T>, success: string, after?: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await action();
      setMessage(success);
      await (after ?? refresh)();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function ensureCollection() {
    if (activeCollectionId) return activeCollectionId;
    const created = await createCollection({
      name: "NEC ECC Rule Mapping Demo",
      contract_family: "ECC",
      jurisdiction: "Hong Kong",
      version: "2024"
    });
    setCollections((current) => [created, ...current]);
    setActiveCollectionId(created.id);
    return created.id;
  }

  async function handleImport(event: FormEvent<HTMLFormElement>, kind: SourceKind) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") || (kind === "rulebook" ? "NEC ECC Practice Notes" : "Tender Template"));
    const pdfUrl = String(form.get("pdf_url") || "");
    await runAction(
      async () => {
        const collectionId = await ensureCollection();
        const documentJob = await createDocument({ name, pdf_url: pdfUrl, grouping_level: kind === "rulebook" ? 2 : 3 });
        await createSourceDocument({
          collection_id: collectionId,
          doc_type: kind,
          name,
          pdf_url: pdfUrl,
          linked_document_id: documentJob.id
        });
      },
      kind === "rulebook"
        ? "Rule book sent to MinerU. Verify Markdown when it is ready."
        : "Tender template sent to MinerU. Extract template fields after Markdown is ready.",
      () => refresh()
    );
    event.currentTarget.reset();
  }

  async function handleCreateSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") || "").trim();
    const ids = form.getAll("source_document_id").map(String).filter(Boolean);
    if (!name) {
      setMessage("Submission name is required.");
      return;
    }
    if (!ids.length) {
      setMessage("Pick at least one tender source document.");
      return;
    }
    await runAction(
      async () => {
        const collectionId = await ensureCollection();
        await createTenderSubmission({ collection_id: collectionId, name, source_document_ids: ids });
      },
      "Tender submission created. Run Extract Evidence next.",
      () => refresh()
    );
    event.currentTarget.reset();
  }

  async function loadTenderResults(submissionId: string) {
    try {
      const rows = await getTenderResults(submissionId);
      setTenderResultsBySubmission((current) => ({ ...current, [submissionId]: rows }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load results");
    }
  }

  async function runTenderAction<T>(
    submissionId: string,
    action: () => Promise<T>,
    success: string,
    expandAfter: boolean
  ) {
    await runAction(async () => {
      await action();
      if (expandAfter) {
        const rows = await getTenderResults(submissionId);
        setTenderResultsBySubmission((current) => ({ ...current, [submissionId]: rows }));
        setExpandedSubmissionId(submissionId);
      }
    }, success);
  }

  return (
    <section className="workflow-shell focused-workflow">
      <div className="workflow-hero">
        <div>
          <p className="eyebrow">NEC ECC POC Main Flow</p>
          <h2>Rule Books to Tender Templates to Verified Mapping</h2>
          <p>
            Start with a rule book such as NEC ECC Practice Notes, then add tender templates such as CDP1/CDP2/FOT/AOA.
            MinerU converts each PDF to Markdown, extraction runs by document type, then you verify and approve the mapping.
          </p>
        </div>
        <div className="workflow-scope">
          <strong>{activeCollection?.name ?? "Demo workspace will be created automatically"}</strong>
          <span>{rulebooks.length} rule book(s)</span>
          <span>{templates.length} template(s)</span>
          <span>{approvedMappings.length} approved mapping(s)</span>
        </div>
      </div>

      {message ? <div className="workflow-message">{message}</div> : null}

      <div className="flow-rail" aria-label="Main workflow">
        <FlowStep index={1} title="Import Rule Books" detail="MinerU -> Markdown -> rule extraction -> rule verification" done={rulebooks.length > 0} />
        <FlowStep index={2} title="Import Tender Templates" detail="MinerU -> Markdown -> template field extraction -> field verification" done={templateFields.length > 0} />
        <FlowStep index={3} title="AI Assist Mapping" detail="Template field -> candidate rules -> approve/reject mapping" done={approvedMappings.length > 0} />
        <FlowStep index={4} title="Tender Vetting" detail="Create a submission, extract evidence, run approved checks" done={tenderSubmissions.some((submission) => submission.status === "checked")} />
      </div>

      <div className="workflow-two-column">
        <WorkflowCard title="1. Rule Books" icon={<FileText size={18} />}>
          <div className="start-here">Start here: paste the NEC ECC Practice Notes PDF URL.</div>
          <p className="workflow-copy">Upload or paste a public PDF URL for NEC ECC Practice Notes or another rule book. This starts MinerU first; rule extraction is a second process after Markdown verification.</p>
          <ImportForm
            kind="rulebook"
            busy={busy}
            defaultName="NEC ECC Practice Notes"
            onSubmit={(event) => handleImport(event, "rulebook")}
          />
          <SourceList
            docs={rulebooks}
            linkedDocuments={linkedDocuments}
            renderMeta={(source) => {
              const linked = source.linked_document_id ? linkedDocuments.get(source.linked_document_id) : null;
              const count = source.linked_document_id ? ruleCounts[source.linked_document_id] ?? 0 : 0;
              return `${linked ? labelStatus(linked.status) : source.status} · ${count} rule(s)`;
            }}
            actions={(source) => {
              const linkedId = source.linked_document_id;
              const linked = linkedId ? linkedDocuments.get(linkedId) : null;
              return (
                <div className="inline-actions">
                  {linkedId ? <button className="secondary-button compact" type="button" onClick={() => onOpenDocument(linkedId, viewForLinkedDocument(linked, "rulebook"))}>Verify</button> : null}
                  {linkedId ? <button className="secondary-button compact" type="button" disabled={busy || linked?.status === "extracting_rules"} onClick={() => runAction(() => extractRules(linkedId), "Rule extraction started", () => refresh())}>Extract Rules</button> : null}
                  <button className="secondary-button compact" type="button" disabled={busy || !linkedId || (source.status === "rules_verified")} onClick={() => runAction(() => verifySourceDocument(source.id), "Rule book confirmed. All extracted rules marked reviewed.")}>Confirm Rule Book</button>
                  <button className="icon-button" type="button" onClick={() => runAction(() => deleteSourceDocument(source.id), "Rule book removed")}><Trash2 size={15} /></button>
                </div>
              );
            }}
          />
        </WorkflowCard>

        <WorkflowCard title="2. Tender Templates" icon={<Check size={18} />}>
          <div className="start-here secondary">Then add CDP1, CDP2, FOT, or AOA template PDFs.</div>
          <p className="workflow-copy">Upload or paste template PDFs such as CDP1, CDP2, FOT, and AOA. The template extraction process finds reviewable fields, not rules.</p>
          <ImportForm
            kind="template"
            busy={busy}
            defaultName="CDP1 Tender Template"
            onSubmit={(event) => handleImport(event, "template")}
          />
          <SourceList
            docs={templates}
            linkedDocuments={linkedDocuments}
            renderMeta={(source) => {
              const linked = source.linked_document_id ? linkedDocuments.get(source.linked_document_id) : null;
              const fields = templateFields.filter((field) => field.source_document_id === source.id);
              return `${linked ? labelStatus(linked.status) : source.status} · ${fields.length} field(s)`;
            }}
            actions={(source) => {
              const linkedId = source.linked_document_id;
              const linked = linkedId ? linkedDocuments.get(linkedId) : null;
              return (
                <div className="inline-actions">
                  {linkedId ? <button className="secondary-button compact" type="button" onClick={() => onOpenDocument(linkedId, viewForLinkedDocument(linked, "template"))}>Verify MD</button> : null}
                  <button className="secondary-button compact" type="button" disabled={busy} onClick={() => runAction(() => extractTemplateFields(source.id), "Template fields extracted")}>Extract Fields</button>
                  <button className="secondary-button compact" type="button" disabled={busy || source.status === "fields_verified"} onClick={() => runAction(() => verifySourceDocument(source.id), "Template confirmed. All extracted fields approved.")}>Confirm Template</button>
                  <button className="icon-button" type="button" onClick={() => runAction(() => deleteSourceDocument(source.id), "Template removed")}><Trash2 size={15} /></button>
                </div>
              );
            }}
          />
        </WorkflowCard>
      </div>

      <WorkflowCard title="3. Verify Template Fields" icon={<Check size={18} />}>
        <div className="workflow-card-toolbar">
          <MetricStrip items={[
            ["Extracted fields", templateFields.length],
            ["Approved fields", approvedFields.length],
            ["Need review", templateFields.filter((field) => field.review_status !== "approved").length]
          ]} />
        </div>
        <RecordTable
          headers={["Template Field", "Template", "Evidence Anchor", "Verify"]}
          rows={templateFields.map((field) => [
            <strong key={`${field.id}-label`}>{field.label}</strong>,
            field.template_doc,
            field.anchor_text || field.extraction_hint,
            <select key={field.id} value={field.review_status} onChange={(event) => runAction(() => updateTemplateField(field.id, { review_status: event.target.value as TemplateField["review_status"] }), "Field verification updated")}>
              <option value="suggested">needs review</option>
              <option value="approved">approved</option>
              <option value="needs_edit">needs edit</option>
              <option value="rejected">rejected</option>
            </select>
          ])}
        />
      </WorkflowCard>

      <WorkflowCard title="4. AI Assist Mapping" icon={<GitBranch size={18} />}>
        <div className="mapping-intro">
          <p className="workflow-copy">This maps each approved template field to extracted rule-book rules. AI suggestions remain draft until you approve them.</p>
          <button className="primary-button" type="button" disabled={!activeCollectionId || !templateFields.length || busy} onClick={() => runAction(() => createMappingRun(activeCollectionId), "Mapping suggestions generated")}>
            {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            AI Assist Mapping
          </button>
        </div>
        <MetricStrip items={[
          ["Suggested mappings", suggestedMappings.length],
          ["Approved mappings", approvedMappings.length],
          ["Rejected mappings", mappings.filter((m) => m.review_status === "rejected").length]
        ]} />
        <RecordTable
          headers={["Tender Template Field", "Matched Rule", "Why", "Confidence", "Decision"]}
          rows={mappings.map((mapping) => [
            <strong key={`${mapping.id}-field`}>{mapping.field_label}</strong>,
            mapping.rule_subject || mapping.rule_id || "-",
            mapping.rationale,
            `${Math.round(mapping.confidence * 100)}%`,
            <select key={mapping.id} value={mapping.review_status} onChange={(event) => runAction(() => updateFieldRuleMapping(mapping.id, { review_status: event.target.value as FieldRuleMapping["review_status"] }), "Mapping decision saved")}>
              <option value="suggested">suggested</option>
              <option value="approved">approved</option>
              <option value="needs_edit">needs edit</option>
              <option value="rejected">rejected</option>
            </select>
          ])}
        />
      </WorkflowCard>

      <WorkflowCard title="5. Tender Vetting" icon={<ClipboardList size={18} />}>
        <p className="workflow-copy">Create a tender submission from one or more source documents, then extract evidence and run checks against approved mappings.</p>
        <TenderSubmissionForm
          busy={busy}
          tenderSources={tenderSources}
          hasApprovedMappings={approvedMappings.length > 0}
          onSubmit={handleCreateSubmission}
        />
        {!tenderSubmissions.length ? (
          <p className="workflow-empty">No tender submissions yet. Register a tender_submission source document first, then create a submission above.</p>
        ) : (
          <TenderSubmissionList
            submissions={tenderSubmissions}
            resultsBySubmission={tenderResultsBySubmission}
            expandedId={expandedSubmissionId}
            onToggleExpand={(id) => {
              const next = expandedSubmissionId === id ? null : id;
              setExpandedSubmissionId(next);
              if (next) loadTenderResults(id);
            }}
            onExtractEvidence={(id) => runTenderAction(id, () => extractTenderEvidence(id), "Tender evidence extracted (LLM).", true)}
            onRunChecks={(id) => runTenderAction(id, () => runTenderChecks(id), "Checks executed (LLM). Results below.", true)}
            onDelete={(id) => runAction(() => deleteTenderSubmission(id), "Submission removed", () => refresh())}
            busy={busy}
            hasApprovedMappings={approvedMappings.length > 0}
          />
        )}
      </WorkflowCard>
    </section>
  );
}

function ImportForm({
  kind,
  defaultName,
  busy,
  onSubmit
}: {
  kind: SourceKind;
  defaultName: string;
  busy: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form className="workflow-import-form" onSubmit={onSubmit}>
      <input name="name" placeholder={defaultName} defaultValue={defaultName} required />
      <input name="pdf_url" placeholder="https://example.com/document.pdf" required type="url" />
      <button className="primary-button" disabled={busy} type="submit">
        <Plus size={16} /> Start {kind === "rulebook" ? "Rule Book" : "Template"} MinerU
      </button>
    </form>
  );
}

function SourceList({
  docs,
  linkedDocuments,
  renderMeta,
  actions
}: {
  docs: SourceDocument[];
  linkedDocuments: Map<number, DocumentJob>;
  renderMeta: (source: SourceDocument) => string;
  actions: (source: SourceDocument) => ReactNode;
}) {
  if (!docs.length) return <p className="workflow-empty">No document yet. Start with the PDF URL form above.</p>;
  return (
    <div className="source-list">
      {docs.map((source) => {
        const linked = source.linked_document_id ? linkedDocuments.get(source.linked_document_id) : null;
        return (
          <article className="source-row" key={source.id}>
            <div>
              <strong>{source.name}</strong>
              <span>{renderMeta(source)}</span>
              {linked?.error_message ? <small>{linked.error_message}</small> : null}
            </div>
            {actions(source)}
          </article>
        );
      })}
    </div>
  );
}

function FlowStep({ index, title, detail, done, muted = false }: { index: number; title: string; detail: string; done: boolean; muted?: boolean }) {
  return (
    <div className={`flow-step ${done ? "done" : ""} ${muted ? "muted" : ""}`}>
      <span>{done ? <Check size={15} /> : index}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function WorkflowCard({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="workflow-card">
      <div className="workflow-card-title">{icon}<h3>{title}</h3></div>
      {children}
    </section>
  );
}

function MetricStrip({ items }: { items: [string, string | number][] }) {
  return (
    <div className="workflow-metrics">
      {items.map(([label, value]) => <span key={label}><strong>{value}</strong>{label}</span>)}
    </div>
  );
}

function RecordTable({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  if (!rows.length) return <p className="workflow-empty">No extracted records yet.</p>;
  return (
    <div className="workflow-table-wrap">
      <table className="workflow-table">
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function labelStatus(status: string) {
  return status.replaceAll("_", " ");
}

function viewForLinkedDocument(linked: DocumentJob | null | undefined, kind: SourceKind): "review" | "map" | "processing" {
  if (!linked) return "processing";
  if (kind === "rulebook" && linked.status === "rules_extracted") return "map";
  if (["markdown_ready", "rule_extraction_failed", "rules_extracted"].includes(linked.status)) return "review";
  return "processing";
}

function TenderSubmissionForm({
  busy,
  tenderSources,
  hasApprovedMappings,
  onSubmit
}: {
  busy: boolean;
  tenderSources: SourceDocument[];
  hasApprovedMappings: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const disabled = busy || !tenderSources.length;
  return (
    <form className="workflow-import-form" onSubmit={onSubmit}>
      <input name="name" placeholder="Tender submission name" required />
      <select name="source_document_id" multiple size={Math.min(4, Math.max(2, tenderSources.length))} required>
        {tenderSources.length === 0 ? (
          <option value="" disabled>No tender source documents in this collection yet</option>
        ) : (
          tenderSources.map((source) => (
            <option key={source.id} value={source.id}>{source.name}</option>
          ))
        )}
      </select>
      <button className="primary-button" type="submit" disabled={disabled}>
        <Plus size={16} /> Create Submission
      </button>
      {!hasApprovedMappings ? (
        <small className="workflow-hint">Run-checks will be disabled until at least one mapping is approved in step 4.</small>
      ) : null}
    </form>
  );
}

function TenderSubmissionList({
  submissions,
  resultsBySubmission,
  expandedId,
  onToggleExpand,
  onExtractEvidence,
  onRunChecks,
  onDelete,
  busy,
  hasApprovedMappings
}: {
  submissions: TenderSubmission[];
  resultsBySubmission: Record<string, CheckResult[]>;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  onExtractEvidence: (id: string) => void;
  onRunChecks: (id: string) => void;
  onDelete: (id: string) => void;
  busy: boolean;
  hasApprovedMappings: boolean;
}) {
  return (
    <div className="source-list">
      {submissions.map((submission) => {
        const isExpanded = expandedId === submission.id;
        const results = resultsBySubmission[submission.id] || [];
        return (
          <article className="source-row tender-submission" key={submission.id}>
            <div>
              <strong>{submission.name}</strong>
              <span>{labelStatus(submission.status)} · {submission.source_document_ids.length} source document(s)</span>
            </div>
            <div className="inline-actions">
              <button
                className="secondary-button compact"
                type="button"
                disabled={busy || submission.status === "evidence_extracted" && submission.source_document_ids.length === 0}
                onClick={() => onExtractEvidence(submission.id)}
              >
                Extract Evidence
              </button>
              <button
                className="secondary-button compact"
                type="button"
                disabled={busy || !hasApprovedMappings}
                onClick={() => onRunChecks(submission.id)}
              >
                Run Checks
              </button>
              <button
                className="secondary-button compact"
                type="button"
                onClick={() => onToggleExpand(submission.id)}
              >
                {isExpanded ? "Hide Results" : `View Results (${results.length})`}
              </button>
              <button className="icon-button" type="button" onClick={() => onDelete(submission.id)}>
                <Trash2 size={15} />
              </button>
            </div>
            {isExpanded ? <TenderResultPanel results={results} /> : null}
          </article>
        );
      })}
    </div>
  );
}

function TenderResultPanel({ results }: { results: CheckResult[] }) {
  if (!results.length) {
    return <p className="workflow-empty">No check results yet. Run Checks above to populate.</p>;
  }
  return (
    <div className="tender-result-panel">
      <RecordTable
        headers={["Template Field", "Result", "Severity", "Reason", "Rule Evidence", "Tender Evidence"]}
        rows={results.map((result) => [
          <strong key={`${result.id}-field`}>{result.template_field_id}</strong>,
          <span key={`${result.id}-result`} className={`result-pill result-${result.result}`}>{result.result.replaceAll("_", " ")}</span>,
          result.severity,
          result.reason,
          result.rule_evidence || "-",
          result.tender_evidence || "-"
        ])}
      />
    </div>
  );
}
