import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  BookOpen,
  CheckCircle2,
  FileCheck2,
  FileText,
  GitBranch,
  Loader2,
  Play,
  Plus,
  RefreshCcw,
  SearchCheck,
  Trash2,
  Upload
} from "lucide-react";
import {
  createCollection,
  createDocument,
  createMappingRun,
  createSourceDocument,
  deleteSourceDocument,
  extractRules,
  extractTemplateFields,
  getCollections,
  getDocuments,
  getFieldRuleMappings,
  getRules,
  getSourceDocuments,
  getTemplateFields,
  updateFieldRuleMapping,
  updateTemplateField,
  verifySourceDocument
} from "../api";
import type {
  DocumentCollection,
  DocumentJob,
  FieldRuleMapping,
  SourceDocument,
  TemplateField
} from "../types";

type SourceKind = "rulebook" | "template";

type AssetSlot = {
  id: string;
  kind: SourceKind;
  docType: SourceDocument["doc_type"];
  name: string;
  shortName: string;
  description: string;
  groupingLevel: number;
  expectedOutput: string;
};

type WorkflowWorkspaceProps = {
  onOpenDocument: (documentId: number, view: "review" | "map" | "processing") => void;
};

const RULEBOOK_SLOTS: AssetSlot[] = [
  {
    id: "nec-ecc-practice-notes",
    kind: "rulebook",
    docType: "rulebook",
    name: "NEC ECC Practice Notes",
    shortName: "NEC ECC PN",
    description: "Practice Note rule source for NEC ECC public works projects.",
    groupingLevel: 2,
    expectedOutput: "reviewed rules"
  },
  {
    id: "gct",
    kind: "rulebook",
    docType: "rulebook",
    name: "GCT",
    shortName: "GCT",
    description: "General Conditions of Tender reference/rule source.",
    groupingLevel: 2,
    expectedOutput: "clauses or rules"
  },
  {
    id: "sct",
    kind: "rulebook",
    docType: "rulebook",
    name: "SCT",
    shortName: "SCT",
    description: "Special Conditions of Tender reference/rule source.",
    groupingLevel: 2,
    expectedOutput: "project-specific rule clauses"
  },
  {
    id: "ntt",
    kind: "rulebook",
    docType: "rulebook",
    name: "NTT",
    shortName: "NTT",
    description: "Notes to Tenderers reference/rule source.",
    groupingLevel: 2,
    expectedOutput: "tender instruction rules"
  },
  {
    id: "acc",
    kind: "rulebook",
    docType: "rulebook",
    name: "ACC",
    shortName: "ACC",
    description: "Articles / Conditions of Contract reference source.",
    groupingLevel: 2,
    expectedOutput: "contract clause rules"
  }
];

const TEMPLATE_SLOTS: AssetSlot[] = [
  {
    id: "cdp1",
    kind: "template",
    docType: "template",
    name: "CDP1 Tender Template",
    shortName: "CDP1",
    description: "Contract Data Part 1 fields filled by the project office.",
    groupingLevel: 3,
    expectedOutput: "reviewable fields"
  },
  {
    id: "cdp2",
    kind: "template",
    docType: "template",
    name: "CDP2 Tender Template",
    shortName: "CDP2",
    description: "Contract Data Part 2 fields filled by the tenderer/contractor.",
    groupingLevel: 3,
    expectedOutput: "bidder input fields"
  },
  {
    id: "fot",
    kind: "template",
    docType: "template",
    name: "FOT Tender Template",
    shortName: "FOT",
    description: "Form of Tender fields and tender price declarations.",
    groupingLevel: 3,
    expectedOutput: "tender form fields"
  },
  {
    id: "aoa",
    kind: "template",
    docType: "template",
    name: "AOA Tender Template",
    shortName: "AOA",
    description: "Activity schedule / activity-on-arrow information to cross-check.",
    groupingLevel: 3,
    expectedOutput: "schedule fields"
  }
];

const ALL_SLOTS = [...RULEBOOK_SLOTS, ...TEMPLATE_SLOTS];

export function WorkflowWorkspace({ onOpenDocument }: WorkflowWorkspaceProps) {
  const [collections, setCollections] = useState<DocumentCollection[]>([]);
  const [activeCollectionId, setActiveCollectionId] = useState("");
  const [sourceDocuments, setSourceDocuments] = useState<SourceDocument[]>([]);
  const [templateFields, setTemplateFields] = useState<TemplateField[]>([]);
  const [mappings, setMappings] = useState<FieldRuleMapping[]>([]);
  const [legacyDocuments, setLegacyDocuments] = useState<DocumentJob[]>([]);
  const [ruleCounts, setRuleCounts] = useState<Record<number, number>>({});
  const [selectedSlotId, setSelectedSlotId] = useState("nec-ecc-practice-notes");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const activeCollection = collections.find((item) => item.id === activeCollectionId) ?? null;
  const selectedSlot = ALL_SLOTS.find((slot) => slot.id === selectedSlotId) ?? ALL_SLOTS[0];
  const linkedDocuments = useMemo(() => {
    const map = new Map<number, DocumentJob>();
    legacyDocuments.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [legacyDocuments]);

  const sourcesBySlot = useMemo(() => {
    const map = new Map<string, SourceDocument[]>();
    ALL_SLOTS.forEach((slot) => map.set(slot.id, []));
    for (const source of sourceDocuments) {
      const slot = matchSlot(source);
      if (!slot) continue;
      map.get(slot.id)?.push(source);
    }
    map.forEach((items) => items.sort(compareCreatedDesc));
    return map;
  }, [sourceDocuments]);

  const currentSource = sourcesBySlot.get(selectedSlot.id)?.[0] ?? null;
  const queueDocuments = useMemo(() => [...sourceDocuments].sort(compareCreatedDesc), [sourceDocuments]);
  const rulebookSources = sourceDocuments.filter((doc) => doc.doc_type === "rulebook" || doc.doc_type === "reference_clause");
  const templateSources = sourceDocuments.filter((doc) => doc.doc_type === "template");
  const approvedFields = templateFields.filter((field) => field.review_status === "approved");
  const reviewedRuleSources = rulebookSources.filter((source) => source.status === "rules_verified");
  const approvedMappings = mappings.filter((item) => item.review_status === "approved");
  const suggestedMappings = mappings.filter((item) => item.review_status === "suggested" || item.review_status === "needs_edit");

  const refresh = useCallback(async (collectionId = activeCollectionId) => {
    const [nextCollections, nextLegacyDocuments, allSourceDocuments] = await Promise.all([
      getCollections(),
      getDocuments().catch(() => []),
      getSourceDocuments().catch(() => [])
    ]);
    setCollections(nextCollections);
    setLegacyDocuments(nextLegacyDocuments);

    const collectionWithDocuments = allSourceDocuments[0]?.collection_id || "";
    const selected = collectionId || collectionWithDocuments || nextCollections[0]?.id || "";
    if (selected && selected !== activeCollectionId) setActiveCollectionId(selected);
    if (!selected) {
      setSourceDocuments([]);
      setTemplateFields([]);
      setMappings([]);
      setRuleCounts({});
      return;
    }

    const [docs, fields, maps] = await Promise.all([
      getSourceDocuments({ collection_id: selected }),
      getTemplateFields({ collection_id: selected }),
      getFieldRuleMappings({ collection_id: selected })
    ]);
    setSourceDocuments(docs);
    setTemplateFields(fields);
    setMappings(maps);

    const rulebookDocIds = docs
      .filter((doc) => (doc.doc_type === "rulebook" || doc.doc_type === "reference_clause") && doc.linked_document_id)
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

  async function handleSlotImport(event: FormEvent<HTMLFormElement>, slot: AssetSlot) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const pdfUrl = String(form.get("pdf_url") || "");
    const existing = sourcesBySlot.get(slot.id)?.[0] ?? null;
    if (existing) {
      const replace = window.confirm(`Replace the current ${slot.shortName} version? The old conversion, extracted records, and links for that file will be removed.`);
      if (!replace) return;
    }
    await runAction(
      async () => {
        const collectionId = await ensureCollection();
        if (existing) {
          await deleteSourceDocument(existing.id);
        }
        const documentJob = await createDocument({ name: slot.name, pdf_url: pdfUrl, grouping_level: slot.groupingLevel });
        await createSourceDocument({
          collection_id: collectionId,
          doc_type: slot.docType,
          name: slot.name,
          pdf_url: pdfUrl,
          linked_document_id: documentJob.id
        });
      },
      existing ? `${slot.shortName} replacement queued.` : `${slot.shortName} conversion queued.`,
      () => refresh()
    );
    event.currentTarget.reset();
  }

  function actionForSource(source: SourceDocument) {
    if (source.doc_type === "template") return nextTemplateAction(source);
    return nextRulebookAction(source);
  }

  function nextRulebookAction(source: SourceDocument) {
    const linkedId = source.linked_document_id;
    const linked = linkedId ? linkedDocuments.get(linkedId) : null;
    if (!linkedId) return { label: "Waiting", disabled: true, run: async () => undefined, success: "" };
    if (!linked || !["markdown_ready", "rule_extraction_failed", "rules_extracted"].includes(linked.status)) {
      return {
        label: "View Progress",
        disabled: busy,
        run: () => onOpenDocument(linkedId, "processing"),
        success: "Opened document progress."
      };
    }
    if (source.status === "rules_verified") {
      return {
        label: "Open Rules",
        disabled: busy,
        run: () => onOpenDocument(linkedId, "map"),
        success: "Opened extracted rules."
      };
    }
    if (linked.status === "rules_extracted") {
      return {
        label: "Confirm All Rules",
        disabled: busy,
        run: () => verifySourceDocument(source.id),
        success: "Rule book confirmed."
      };
    }
    return {
      label: "Extract Rules",
      disabled: busy || linked.status === "rule_extraction_failed",
      run: () => extractRules(linkedId),
      success: "Rule extraction started."
    };
  }

  function nextTemplateAction(source: SourceDocument) {
    const linkedId = source.linked_document_id;
    const linked = linkedId ? linkedDocuments.get(linkedId) : null;
    const fields = templateFields.filter((field) => field.source_document_id === source.id);
    if (!linkedId) return { label: "Waiting", disabled: true, run: async () => undefined, success: "" };
    if (!linked || !["markdown_ready", "rule_extraction_failed", "rules_extracted"].includes(linked.status)) {
      return {
        label: "View Progress",
        disabled: busy,
        run: () => onOpenDocument(linkedId, "processing"),
        success: "Opened document progress."
      };
    }
    if (source.status === "fields_verified") {
      return {
        label: "Fields Confirmed",
        disabled: true,
        run: async () => undefined,
        success: ""
      };
    }
    if (fields.length) {
      return {
        label: "Confirm All Fields",
        disabled: busy,
        run: () => verifySourceDocument(source.id),
        success: "Template fields confirmed."
      };
    }
    return {
      label: "Extract Fields",
      disabled: busy,
      run: () => extractTemplateFields(source.id),
      success: "Template fields extracted."
    };
  }

  return (
    <section className="workflow-shell asset-workbench">
      <div className="workflow-header asset-header">
        <div>
          <p className="eyebrow">NEC ECC POC</p>
          <h2>Document Asset Manager</h2>
          <p>Rule books and tender templates are independent assets. Import any file, leave it running, and come back for review or mapping.</p>
        </div>
        <span className="workspace-chip">{activeCollection?.name ?? "Workspace will be created on first import"}</span>
      </div>

      {message ? <div className="workflow-message">{message}</div> : null}

      <div className="asset-summary-grid">
        <MetricCard label="rule sources" value={rulebookSources.length} detail={`${reviewedRuleSources.length} confirmed`} />
        <MetricCard label="templates" value={templateSources.length} detail={`${approvedFields.length} approved fields`} />
        <MetricCard label="rule links" value={mappings.length} detail={`${approvedMappings.length} approved`} />
        <MetricCard label="queue" value={queueDocuments.length} detail={`${queueDocuments.filter((doc) => isRunning(doc, linkedDocuments)).length} running`} />
      </div>

      <div className="asset-layout">
        <WorkflowCard title="Document Library" icon={<BookOpen size={18} />}>
          <AssetSlotGroup
            title="Rule books / reference sources"
            slots={RULEBOOK_SLOTS}
            selectedSlotId={selectedSlot.id}
            sourcesBySlot={sourcesBySlot}
            linkedDocuments={linkedDocuments}
            ruleCounts={ruleCounts}
            templateFields={templateFields}
            onSelect={setSelectedSlotId}
          />
          <AssetSlotGroup
            title="Tender templates"
            slots={TEMPLATE_SLOTS}
            selectedSlotId={selectedSlot.id}
            sourcesBySlot={sourcesBySlot}
            linkedDocuments={linkedDocuments}
            ruleCounts={ruleCounts}
            templateFields={templateFields}
            onSelect={setSelectedSlotId}
          />
        </WorkflowCard>

        <WorkflowCard title={`${selectedSlot.shortName} Workbench`} icon={selectedSlot.kind === "rulebook" ? <FileText size={18} /> : <FileCheck2 size={18} />}>
          <SelectedAssetPanel
            slot={selectedSlot}
            source={currentSource}
            linked={currentSource?.linked_document_id ? linkedDocuments.get(currentSource.linked_document_id) : null}
            fields={currentSource ? templateFields.filter((field) => field.source_document_id === currentSource.id) : []}
            ruleCount={currentSource?.linked_document_id ? ruleCounts[currentSource.linked_document_id] ?? 0 : 0}
            busy={busy}
            onImport={(event) => handleSlotImport(event, selectedSlot)}
            onOpenDocument={onOpenDocument}
            onRunAction={(source) => {
              const action = actionForSource(source);
              runAction(action.run, action.success, () => refresh());
            }}
            actionForSource={actionForSource}
            onDelete={(source) => runAction(() => deleteSourceDocument(source.id), `${selectedSlot.shortName} removed`, () => refresh())}
          />
        </WorkflowCard>
      </div>

      <WorkflowCard title="Processing Queue and History" icon={<RefreshCcw size={18} />}>
        <SourceQueue
          docs={queueDocuments}
          linkedDocuments={linkedDocuments}
          templateFields={templateFields}
          ruleCounts={ruleCounts}
          actionForSource={actionForSource}
          onRunAction={(source) => {
            const action = actionForSource(source);
            runAction(action.run, action.success, () => refresh());
          }}
          onSelect={(source) => {
            const slot = matchSlot(source);
            if (slot) setSelectedSlotId(slot.id);
          }}
          onDelete={(source) => runAction(() => deleteSourceDocument(source.id), "Document removed", () => refresh())}
        />
      </WorkflowCard>

      <WorkflowCard title="Rule-to-Template Mapping Review" icon={<GitBranch size={18} />}>
        <div className="mapping-intro">
          <p className="workflow-copy">After rule books and template fields are confirmed, run the mapping suggestion. AI proposes links; experts approve them before tender vetting uses them.</p>
          <button className="primary-button" type="button" disabled={!activeCollectionId || !approvedFields.length || !reviewedRuleSources.length || busy} onClick={() => runAction(() => createMappingRun(activeCollectionId), "Rule links suggested")}>
            {busy ? <Loader2 className="spin" size={16} /> : <SearchCheck size={16} />}
            Suggest Rule Links
          </button>
        </div>
        <RecordTable
          headers={["Template Field", "Suggested Rule", "Reason", "Decision"]}
          rows={mappings.map((mapping) => [
            <strong key={`${mapping.id}-field`}>{mapping.field_label}</strong>,
            mapping.rule_subject || mapping.rule_id || "-",
            `${mapping.rationale} · ${Math.round(mapping.confidence * 100)}%`,
            <select key={mapping.id} value={mapping.review_status} onChange={(event) => runAction(() => updateFieldRuleMapping(mapping.id, { review_status: event.target.value as FieldRuleMapping["review_status"] }), "Mapping decision saved")}>
              <option value="suggested">suggested</option>
              <option value="approved">approved</option>
              <option value="needs_edit">needs edit</option>
              <option value="rejected">rejected</option>
            </select>
          ])}
        />
        {suggestedMappings.length || approvedMappings.length ? null : <p className="workflow-empty">Confirm at least one rule source and approve template fields, then suggest rule links.</p>}
      </WorkflowCard>

      <WorkflowCard title="Template Field Review" icon={<CheckCircle2 size={18} />}>
        <RecordTable
          headers={["Field", "Template", "Source text", "Decision"]}
          rows={templateFields.map((field) => [
            <strong key={`${field.id}-label`}>{field.label}</strong>,
            field.template_doc,
            <span className="anchor-snippet" key={`${field.id}-anchor`}>{humanAnchor(field.anchor_text || field.extraction_hint)}</span>,
            <select key={field.id} value={field.review_status} onChange={(event) => runAction(() => updateTemplateField(field.id, { review_status: event.target.value as TemplateField["review_status"] }), "Field verification updated")}>
              <option value="suggested">needs review</option>
              <option value="approved">approved</option>
              <option value="needs_edit">needs edit</option>
              <option value="rejected">rejected</option>
            </select>
          ])}
        />
      </WorkflowCard>
    </section>
  );
}

function SelectedAssetPanel({
  slot,
  source,
  linked,
  fields,
  ruleCount,
  busy,
  onImport,
  onOpenDocument,
  onRunAction,
  actionForSource,
  onDelete
}: {
  slot: AssetSlot;
  source: SourceDocument | null;
  linked: DocumentJob | null | undefined;
  fields: TemplateField[];
  ruleCount: number;
  busy: boolean;
  onImport: (event: FormEvent<HTMLFormElement>) => void;
  onOpenDocument: WorkflowWorkspaceProps["onOpenDocument"];
  onRunAction: (source: SourceDocument) => void;
  actionForSource: (source: SourceDocument) => { label: string; disabled: boolean; run: () => Promise<unknown>; success: string };
  onDelete: (source: SourceDocument) => void;
}) {
  const action = source ? actionForSource(source) : null;
  return (
    <div className="asset-detail">
      <div className="asset-detail-heading">
        <div>
          <strong>{slot.name}</strong>
          <span>{slot.description}</span>
        </div>
        <StatusPill source={source} linked={linked} />
      </div>

      <form className="workflow-import-form asset-import-form" onSubmit={onImport}>
        <input name="pdf_url" placeholder="https://example.com/document.pdf" required type="url" />
        <button className="primary-button" disabled={busy} type="submit">
          {source ? <RefreshCcw size={16} /> : <Upload size={16} />}
          {source ? "Upload New Version" : "Import PDF URL"}
        </button>
      </form>

      {source ? (
        <>
          <div className="asset-state-grid">
            <MetricCard label="PDF text" value={linked ? labelStatus(linked.status) : "queued"} detail={linked?.mineru_task_id ? `MinerU ${linked.mineru_task_id}` : "MinerU task"} />
            <MetricCard label={slot.kind === "rulebook" ? "rules" : "fields"} value={slot.kind === "rulebook" ? ruleCount : fields.length} detail={slot.expectedOutput} />
            <MetricCard label="review" value={labelStatus(source.status)} detail="current source status" />
          </div>
          {linked?.error_message ? <p className="source-error">{linked.error_message}</p> : null}
          <div className="workflow-actions">
            {linked?.id ? (
              <>
                <button className="secondary-button compact" type="button" onClick={() => onOpenDocument(linked.id, "processing")}>Progress</button>
                <button className="secondary-button compact" type="button" disabled={!canOpenReview(linked)} onClick={() => onOpenDocument(linked.id, "review")}>Review Text</button>
              </>
            ) : null}
            {action ? (
              <button className="primary-button compact" type="button" disabled={action.disabled} onClick={() => onRunAction(source)}>
                {action.label === "Extract Rules" || action.label === "Extract Fields" ? <Play size={15} /> : null}
                {action.label}
              </button>
            ) : null}
            <button className="icon-button" type="button" onClick={() => onDelete(source)} title="Delete this file">
              <Trash2 size={15} />
            </button>
          </div>
        </>
      ) : (
        <p className="workflow-empty">No current version. Import this PDF URL and it will enter the processing queue. You can switch to another file while it runs.</p>
      )}
    </div>
  );
}

function AssetSlotGroup({
  title,
  slots,
  selectedSlotId,
  sourcesBySlot,
  linkedDocuments,
  ruleCounts,
  templateFields,
  onSelect
}: {
  title: string;
  slots: AssetSlot[];
  selectedSlotId: string;
  sourcesBySlot: Map<string, SourceDocument[]>;
  linkedDocuments: Map<number, DocumentJob>;
  ruleCounts: Record<number, number>;
  templateFields: TemplateField[];
  onSelect: (slotId: string) => void;
}) {
  return (
    <div className="asset-slot-group">
      <h4>{title}</h4>
      <div className="asset-slot-grid">
        {slots.map((slot) => {
          const source = sourcesBySlot.get(slot.id)?.[0] ?? null;
          const linked = source?.linked_document_id ? linkedDocuments.get(source.linked_document_id) : null;
          const fields = source ? templateFields.filter((field) => field.source_document_id === source.id) : [];
          const count = slot.kind === "template"
            ? fields.length
            : source?.linked_document_id ? ruleCounts[source.linked_document_id] ?? 0 : 0;
          return (
            <button
              className={`asset-slot ${slot.id === selectedSlotId ? "active" : ""}`}
              key={slot.id}
              onClick={() => onSelect(slot.id)}
              type="button"
            >
              <strong>{slot.shortName}</strong>
              <span>{source ? statusSummary(source, linked, count) : "empty"}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SourceQueue({
  docs,
  linkedDocuments,
  templateFields,
  ruleCounts,
  actionForSource,
  onRunAction,
  onSelect,
  onDelete
}: {
  docs: SourceDocument[];
  linkedDocuments: Map<number, DocumentJob>;
  templateFields: TemplateField[];
  ruleCounts: Record<number, number>;
  actionForSource: (source: SourceDocument) => { label: string; disabled: boolean; run: () => Promise<unknown>; success: string };
  onRunAction: (source: SourceDocument) => void;
  onSelect: (source: SourceDocument) => void;
  onDelete: (source: SourceDocument) => void;
}) {
  if (!docs.length) return <p className="workflow-empty">No files yet. Pick a Rule Book or Template slot above and import a PDF URL.</p>;
  return (
    <div className="source-list queue-list">
      {docs.map((source) => {
        const linked = source.linked_document_id ? linkedDocuments.get(source.linked_document_id) : null;
        const fields = templateFields.filter((field) => field.source_document_id === source.id);
        const ruleCount = source.linked_document_id ? ruleCounts[source.linked_document_id] ?? 0 : 0;
        const action = actionForSource(source);
        return (
          <article className="source-row queue-row" key={source.id}>
            <button className="queue-row-main" type="button" onClick={() => onSelect(source)}>
              <strong>{source.name}</strong>
              <span>{source.doc_type.replace("_", " ")} · {statusSummary(source, linked, ruleCount || fields.length)} · {createdLabel(source.created_at)}</span>
              {linked?.error_message ? <small>{linked.error_message}</small> : null}
            </button>
            <div className="inline-actions">
              <button className="primary-button compact" type="button" disabled={action.disabled} onClick={() => onRunAction(source)}>{action.label}</button>
              <button className="icon-button" type="button" onClick={() => onDelete(source)} title="Delete this file"><Trash2 size={15} /></button>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: ReactNode; detail: string }) {
  return (
    <span className="metric-card">
      <small>{label}</small>
      <strong>{value}</strong>
      <em>{detail}</em>
    </span>
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

function StatusPill({ source, linked }: { source: SourceDocument | null; linked: DocumentJob | null | undefined }) {
  if (!source) return <span className="asset-status empty">not imported</span>;
  if (linked?.status === "mineru_failed" || linked?.status === "rule_extraction_failed") return <span className="asset-status failed">failed</span>;
  if (isRunning(source, new Map(linked ? [[linked.id, linked]] : []))) return <span className="asset-status running">running</span>;
  if (source.status === "rules_verified" || source.status === "fields_verified") return <span className="asset-status ready">confirmed</span>;
  if (linked?.status === "markdown_ready" || linked?.status === "rules_extracted" || source.status === "fields_extracted") return <span className="asset-status ready">ready for review</span>;
  return <span className="asset-status running">queued</span>;
}

function matchSlot(source: SourceDocument) {
  return ALL_SLOTS.find((slot) => {
    if (slot.docType !== source.doc_type) return false;
    return normalize(source.name).includes(normalize(slot.shortName)) || normalize(source.name).includes(normalize(slot.name));
  }) ?? null;
}

function compareCreatedDesc(a: SourceDocument, b: SourceDocument) {
  return Date.parse(b.created_at || "") - Date.parse(a.created_at || "");
}

function normalize(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function isRunning(source: SourceDocument, linkedDocuments: Map<number, DocumentJob>) {
  const linked = source.linked_document_id ? linkedDocuments.get(source.linked_document_id) : null;
  if (!linked) return source.status === "created";
  return ["created", "mineru_queued", "mineru_processing", "rule_extraction_queued", "extracting_rules"].includes(linked.status);
}

function canOpenReview(linked: DocumentJob) {
  return ["markdown_ready", "rule_extraction_failed", "rules_extracted"].includes(linked.status);
}

function statusSummary(source: SourceDocument, linked: DocumentJob | null | undefined, count: number) {
  if (source.status === "rules_verified") return `${count} rules confirmed`;
  if (source.status === "fields_verified") return "fields confirmed";
  if (source.status === "fields_extracted") return `${count} fields extracted`;
  if (linked?.status === "rules_extracted") return `${count} rules extracted`;
  if (linked?.status === "markdown_ready") return "text ready";
  if (linked?.status === "mineru_processing" || linked?.status === "mineru_queued") return labelStatus(linked.status);
  if (linked?.status === "extracting_rules" || linked?.status === "rule_extraction_queued") return "extracting rules";
  if (linked?.status === "mineru_failed" || linked?.status === "rule_extraction_failed") return "failed";
  return labelStatus(source.status);
}

function labelStatus(status: string) {
  const labels: Record<string, string> = {
    created: "created",
    mineru_queued: "PDF queued",
    mineru_processing: "converting PDF",
    markdown_ready: "text ready",
    rules_extracted: "rules extracted",
    rules_verified: "rules confirmed",
    fields_extracted: "fields extracted",
    fields_verified: "fields confirmed",
    rule_extraction_queued: "extracting rules",
    extracting_rules: "extracting rules",
    rule_extraction_failed: "rule extraction failed",
    mineru_failed: "PDF conversion failed"
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function createdLabel(value?: string | null) {
  if (!value) return "no timestamp";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "no timestamp";
  return new Date(timestamp).toLocaleString();
}

function humanAnchor(value: string) {
  return value
    .replace(/\[\[MINERU_TABLE_HTML\]\][\s\S]*?\[\[\/MINERU_TABLE_HTML\]\]/g, "[table]")
    .replace(/\[\[MINERU_MEDIA[^\]]+\]\]/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 220);
}
