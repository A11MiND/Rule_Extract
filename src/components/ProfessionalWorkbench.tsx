import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Select,
  Space,
  Statistic,
  Steps,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import {
  Activity,
  BookOpen,
  CheckCircle2,
  Clock3,
  FileSearch,
  FileText,
  GitBranch,
  Grid2X2,
  List as ListIcon,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  Sparkles,
  Upload,
  XCircle
} from "lucide-react";
import {
  approveProcedureSet,
  bulkReviewSourceFields,
  createFieldRuleMapping,
  createMappingRun,
  createProcedureSet,
  deleteFieldRuleMapping,
  getAuditEvents,
  getCollections,
  getDashboardSummary,
  getDocuments,
  getFieldRuleMappings,
  getLibrarySlots,
  getProcedureSets,
  getRules,
  getSourceDocuments,
  getTemplateFields,
  importSourceDocumentUrl,
  updateFieldRuleMapping,
  updateSourceDocument,
  updateTemplateField
} from "../api";
import type { FieldRuleMappingUpdate, TemplateFieldUpdate } from "../api";
import type { NavPage } from "./Sidebar";
import type {
  AuditEvent,
  DashboardSummary,
  DocumentCollection,
  DocumentJob,
  FieldRuleMapping,
  LibrarySlot,
  ProcedureSet,
  Rule,
  SourceDocument,
  TemplateField
} from "../types";
import { ReviewConfidence, ReviewStatusBadge, ReviewTypeChip } from "./ReviewPrimitives";
import { labelStatus } from "../utils/status";

type Page = "dashboard" | "sources" | "queue" | "field-review" | "mapping-review" | "submissions" | "results" | "activity";

type Props = {
  page: Page;
  onPageChange: (page: NavPage) => void;
  onOpenDocument: (documentId: number, view: "document-review" | "rule-review" | "queue") => void;
};

const RUNNING = new Set(["created", "mineru_queued", "mineru_submitting", "mineru_processing", "rule_extraction_queued", "extracting_rules"]);
const FAILED = new Set(["mineru_failed", "rule_extraction_failed"]);

export function ProfessionalWorkbench({ page, onPageChange, onOpenDocument }: Props) {
  const [messageApi, contextHolder] = message.useMessage();
  const [collections, setCollections] = useState<DocumentCollection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [slots, setSlots] = useState<LibrarySlot[]>([]);
  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [documents, setDocuments] = useState<DocumentJob[]>([]);
  const [fields, setFields] = useState<TemplateField[]>([]);
  const [mappings, setMappings] = useState<FieldRuleMapping[]>([]);
  const [procedures, setProcedures] = useState<ProcedureSet[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [audits, setAudits] = useState<AuditEvent[]>([]);
  const [selectedSource, setSelectedSource] = useState<SourceDocument | null>(null);
  const [selectedField, setSelectedField] = useState<TemplateField | null>(null);
  const [busy, setBusy] = useState(false);

  const linkedDocuments = useMemo(() => new Map(documents.map((document) => [document.id, document])), [documents]);
  const activeCollection = collections.find((collection) => collection.id === collectionId) ?? null;

  const refresh = useCallback(async (requestedCollection = collectionId) => {
    const [nextCollections, allSources, allDocuments] = await Promise.all([
      getCollections(),
      getSourceDocuments().catch(() => []),
      getDocuments().catch(() => [])
    ]);
    const nextCollection = requestedCollection || allSources[0]?.collection_id || nextCollections[0]?.id || "";
    setCollections(nextCollections);
    setDocuments(allDocuments);
    if (nextCollection !== collectionId) setCollectionId(nextCollection);
    if (!nextCollection) return;
    const [nextSlots, nextSources, nextFields, nextMappings, nextProcedures, nextSummary, nextAudits] = await Promise.all([
      getLibrarySlots(nextCollection),
      getSourceDocuments({ collection_id: nextCollection }),
      getTemplateFields({ collection_id: nextCollection }),
      getFieldRuleMappings({ collection_id: nextCollection }),
      getProcedureSets(nextCollection),
      getDashboardSummary(nextCollection),
      getAuditEvents(120)
    ]);
    setSlots(nextSlots);
    setSources(nextSources);
    setFields(nextFields);
    setMappings(nextMappings);
    setProcedures(nextProcedures);
    setSummary(nextSummary);
    setAudits(nextAudits);
  }, [collectionId]);

  useEffect(() => {
    refresh().catch((error) => messageApi.error(error.message));
  }, [refresh]);

  async function runAction<T>(action: () => Promise<T>, success: string) {
    setBusy(true);
    try {
      const result = await action();
      messageApi.success(success);
      await refresh();
      return result;
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "Action failed");
      return null;
    } finally {
      setBusy(false);
    }
  }

  let body;
  if (page === "dashboard") {
    body = <Dashboard summary={summary} collection={activeCollection} onPageChange={onPageChange} />;
  } else if (page === "sources") {
    body = (
      <SourceLibrary
        collectionId={collectionId}
        slots={slots}
        sources={sources}
        linkedDocuments={linkedDocuments}
        busy={busy}
        onImport={(payload) => runAction(() => importSourceDocumentUrl(payload), "Document import queued")}
        onSelect={setSelectedSource}
        onOpenDocument={onOpenDocument}
      />
    );
  } else if (page === "queue") {
    body = <Queue sources={sources} linkedDocuments={linkedDocuments} onSelect={setSelectedSource} onOpenDocument={onOpenDocument} />;
  } else if (page === "field-review") {
    body = (
      <FieldsReview
        sources={sources.filter((source) => source.doc_type === "template")}
        fields={fields}
        busy={busy}
        onSelect={setSelectedField}
        onSave={(field, data) => runAction(() => updateTemplateField(field.id, data), "Field updated")}
        onApproveAll={(source) => runAction(() => bulkReviewSourceFields(source.id, "approved"), "Outstanding fields approved")}
      />
    );
  } else if (page === "mapping-review") {
    body = (
      <MappingWorkspace
        collectionId={collectionId}
        sources={sources}
        fields={fields}
        mappings={mappings}
        procedures={procedures}
        busy={busy}
        onSuggest={(templateIds, ruleIds) => runAction(() => createMappingRun(collectionId, templateIds, ruleIds), "Mapping suggestions generated")}
        onSave={(mapping, data) => runAction(() => updateFieldRuleMapping(mapping.id, data), "Mapping updated")}
        onDelete={(mapping) => runAction(() => deleteFieldRuleMapping(mapping.id), "Mapping deleted")}
        onCreate={(payload) => runAction(() => createFieldRuleMapping(payload), "Mapping added")}
        onCreateProcedure={(payload) => runAction(() => createProcedureSet(payload), "Draft procedure set saved")}
        onApproveProcedure={(procedure) => runAction(() => approveProcedureSet(procedure.id), "Procedure set approved")}
      />
    );
  } else if (page === "activity") {
    body = <ActivityLog events={audits} />;
  } else {
    body = <ComingSoon title={page === "submissions" ? "Tender Submissions" : "Results"} />;
  }

  return (
    <div className="workbench-page professional-workbench">
      {contextHolder}
      {body}
      <SourceDetailsDrawer
        source={selectedSource}
        linked={selectedSource?.linked_document_id ? linkedDocuments.get(selectedSource.linked_document_id) : undefined}
        busy={busy}
        onClose={() => setSelectedSource(null)}
        onSave={(data) => selectedSource && runAction(() => updateSourceDocument(selectedSource.id, data), "Document details updated")}
        onOpenDocument={onOpenDocument}
      />
      <FieldEvidenceDrawer field={selectedField} sources={sources} onClose={() => setSelectedField(null)} />
    </div>
  );
}

function Dashboard({ summary, collection, onPageChange }: { summary: DashboardSummary | null; collection: DocumentCollection | null; onPageChange: Props["onPageChange"] }) {
  const metrics = [
    ["Documents", summary?.total_documents ?? 0, <BookOpen size={18} />],
    ["Text review", summary?.awaiting_text_review ?? 0, <FileSearch size={18} />],
    ["Record review", summary?.awaiting_record_review ?? 0, <CheckCircle2 size={18} />],
    ["Processing", summary?.processing ?? 0, <Loader2 size={18} />],
    ["Failed", summary?.failed ?? 0, <XCircle size={18} />],
    ["Approved procedures", summary?.approved_procedure_sets ?? 0, <GitBranch size={18} />],
  ] as const;
  return (
    <>
      <PageHeader
        eyebrow="Tender Vetting"
        title="Operational overview"
        description={collection?.name ?? "Import a document to create the first workspace."}
        actions={[
          <Button key="source" type="primary" icon={<Upload size={16} />} onClick={() => onPageChange("sources")}>Add Document</Button>,
          <Button key="mapping" icon={<GitBranch size={16} />} onClick={() => onPageChange("mapping-review")}>Open Mapping</Button>
        ]}
      />
      <div className="professional-metrics">
        {metrics.map(([label, value, icon]) => (
          <Card key={label} className="professional-metric-card">
            <span className="metric-icon">{icon}</span>
            <CountUp value={value} />
            <span>{label}</span>
          </Card>
        ))}
      </div>
      <div className="dashboard-professional-grid">
        <Card title="Workflow readiness" className="workflow-readiness-card">
          <Steps
            direction="vertical"
            current={(summary?.approved_procedure_sets ?? 0) > 0 ? 4 : (summary?.awaiting_record_review ?? 0) > 0 ? 2 : (summary?.awaiting_text_review ?? 0) > 0 ? 1 : 0}
            items={[
              { title: "Source library", content: `${summary?.total_documents ?? 0} documents registered` },
              { title: "Text review", content: `${summary?.awaiting_text_review ?? 0} awaiting confirmation` },
              { title: "Rule and field review", content: `${summary?.awaiting_record_review ?? 0} records awaiting decisions` },
              { title: "Mapping", content: "Human-reviewed field-to-rule links" },
              { title: "Approved procedure", content: `${summary?.approved_procedure_sets ?? 0} active versions` },
            ]}
          />
        </Card>
        <Card title="Recent activity">
          <List
            dataSource={summary?.recent_activity ?? []}
            locale={{ emptyText: <Empty description="No activity yet" /> }}
            renderItem={(event) => (
              <List.Item>
                <List.Item.Meta title={event.summary} description={`${event.actor} · ${createdLabel(event.created_at)}`} />
                <Tag>{event.action.replaceAll("_", " ")}</Tag>
              </List.Item>
            )}
          />
        </Card>
      </div>
    </>
  );
}

function SourceLibrary({
  collectionId, slots, sources, linkedDocuments, busy, onImport, onSelect, onOpenDocument
}: {
  collectionId: string;
  slots: LibrarySlot[];
  sources: SourceDocument[];
  linkedDocuments: Map<number, DocumentJob>;
  busy: boolean;
  onImport: (payload: { collection_id: string; name: string; doc_type: SourceDocument["doc_type"]; pdf_url: string; description?: string; slot_id?: string | null; grouping_level?: number }) => void;
  onSelect: (source: SourceDocument) => void;
  onOpenDocument: Props["onOpenDocument"];
}) {
  const [display, setDisplay] = useState<"cards" | "list">("cards");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("all");
  const [importTarget, setImportTarget] = useState<LibrarySlot | null | "custom">(null);
  const [form] = Form.useForm();
  const sourceBySlot = useMemo(() => new Map(sources.filter((source) => source.slot_id).map((source) => [source.slot_id as string, source])), [sources]);
  const items = useMemo(() => {
    const slotItems = slots.map((slot) => ({ id: slot.id, slot, source: sourceBySlot.get(slot.id) ?? null }));
    const custom = sources.filter((source) => !source.slot_id).map((source) => ({ id: source.id, slot: null, source }));
    return [...slotItems, ...custom].filter(({ slot, source }) => {
      const name = (source?.name ?? slot?.name ?? "").toLowerCase();
      const docType = source?.doc_type ?? slot?.doc_type;
      return (!query || name.includes(query.toLowerCase())) && (role === "all" || docType === role);
    });
  }, [query, role, slots, sourceBySlot, sources]);

  function openImport(target: LibrarySlot | "custom") {
    setImportTarget(target);
    form.setFieldsValue(target === "custom" ? { doc_type: "rulebook", grouping_level: 2 } : {
      name: target.name, description: target.description, doc_type: target.doc_type, grouping_level: target.grouping_level
    });
  }

  return (
    <>
      <PageHeader
        eyebrow="Source Library"
        title="Controlled documents"
        description="Required placeholders and unlimited custom sources share one searchable document library."
        actions={[<Button key="add" type="primary" icon={<Plus size={16} />} onClick={() => openImport("custom")}>Add Document</Button>]}
      />
      <div className="library-toolbar">
        <Input prefix={<Search size={15} />} allowClear placeholder="Search documents" value={query} onChange={(event) => setQuery(event.target.value)} />
        <Select value={role} onChange={setRole} options={[
          { label: "All roles", value: "all" }, { label: "Rulebooks", value: "rulebook" }, { label: "Reference clauses", value: "reference_clause" }, { label: "Templates", value: "template" }
        ]} />
        <Segmented value={display} onChange={(value) => setDisplay(value as "cards" | "list")} options={[
          { value: "cards", icon: <Grid2X2 size={15} /> }, { value: "list", icon: <ListIcon size={15} /> }
        ]} />
      </div>
      {display === "cards" ? (
        <div className="source-card-grid">
          {items.map(({ id, slot, source }) => {
            const linked = source?.linked_document_id ? linkedDocuments.get(source.linked_document_id) : undefined;
            return (
              <Card
                key={id}
                className={`source-library-card ${source ? "" : "source-placeholder-card"}`}
                cover={source?.linked_document_id ? (
                  <div className="source-cover"><img src={`/api/documents/${source.linked_document_id}/pages/1/preview`} alt="" onError={(event) => { event.currentTarget.style.display = "none"; }} /></div>
                ) : <div className="source-cover source-cover-placeholder"><FileText size={42} /></div>}
                actions={source ? [
                  <Button key="open" type="link" onClick={() => source.linked_document_id && onOpenDocument(source.linked_document_id, "document-review")}>Open Review</Button>,
                  <Button key="details" type="text" icon={<MoreHorizontal size={16} />} onClick={() => onSelect(source)} aria-label={`Open details for ${source.name}`} />
                ] : [
                  <Button key="import" type="link" icon={<Upload size={15} />} onClick={() => slot && openImport(slot)}>Import URL</Button>
                ]}
              >
                <Space orientation="vertical" size={5}>
                  <Space wrap><RoleTag value={source?.doc_type ?? slot?.doc_type ?? "rulebook"} />{slot?.required ? <Tag color="gold">Required</Tag> : null}</Space>
                  <Typography.Title level={4}>{source?.name ?? slot?.name}</Typography.Title>
                  <Typography.Text type="secondary" ellipsis>{source?.description || slot?.description || "Custom document"}</Typography.Text>
                  <StatusTag status={linked?.status ?? source?.status ?? "not_uploaded"} />
                </Space>
              </Card>
            );
          })}
        </div>
      ) : (
        <Table
          className="ant-workbench-table"
          rowKey="id"
          dataSource={items}
          columns={[
            { title: "Document", render: (_, item) => <Button type="link" disabled={!item.source} onClick={() => item.source && onSelect(item.source)}>{item.source?.name ?? item.slot?.name}</Button> },
            { title: "Role", render: (_, item) => <RoleTag value={item.source?.doc_type ?? item.slot?.doc_type ?? "rulebook"} /> },
            { title: "Required", render: (_, item) => item.slot?.required ? <Tag color="gold">Required</Tag> : "Optional" },
            { title: "Status", render: (_, item) => <StatusTag status={item.source?.status ?? "not_uploaded"} /> },
            { title: "Action", render: (_, item) => item.source ? <Button onClick={() => item.source?.linked_document_id && onOpenDocument(item.source.linked_document_id, "document-review")}>Open Review</Button> : <Button onClick={() => item.slot && openImport(item.slot)}>Import URL</Button> }
          ]}
        />
      )}
      <Modal title={importTarget === "custom" ? "Add document" : `Import ${importTarget?.name ?? ""}`} open={Boolean(importTarget)} onCancel={() => setImportTarget(null)} footer={null} destroyOnHidden>
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            onImport({ collection_id: collectionId, slot_id: importTarget === "custom" ? null : importTarget?.id, ...values });
            setImportTarget(null);
            form.resetFields();
          }}
        >
          <Form.Item name="name" label="Document name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="Description"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="doc_type" label="Document role" rules={[{ required: true }]}><Select options={roleOptions()} /></Form.Item>
          <Form.Item name="grouping_level" label="Extraction grouping"><Select options={[1, 2, 3].map((value) => ({ label: `Heading level ${value}`, value }))} /></Form.Item>
          <Form.Item name="pdf_url" label="Public PDF URL" rules={[{ required: true }, { type: "url" }]}><Input placeholder="https://example.com/document.pdf" /></Form.Item>
          <Button type="primary" htmlType="submit" loading={busy} icon={<Upload size={16} />}>Import URL</Button>
        </Form>
      </Modal>
    </>
  );
}

function Queue({ sources, linkedDocuments, onSelect, onOpenDocument }: { sources: SourceDocument[]; linkedDocuments: Map<number, DocumentJob>; onSelect: (source: SourceDocument) => void; onOpenDocument: Props["onOpenDocument"] }) {
  const [filter, setFilter] = useState("attention");
  const [active, setActive] = useState<SourceDocument | null>(sources.find((source) => RUNNING.has(source.status) || FAILED.has(source.status)) ?? sources[0] ?? null);
  useEffect(() => {
    setActive((current) => {
      const refreshed = sources.find((source) => source.id === current?.id);
      return refreshed ?? sources.find((source) => RUNNING.has(source.status) || FAILED.has(source.status) || source.text_review_status !== "verified") ?? sources[0] ?? null;
    });
  }, [sources]);
  const filtered = sources.filter((source) => filter === "all" || (filter === "attention" && (RUNNING.has(source.status) || FAILED.has(source.status) || source.text_review_status !== "verified")) || (filter === "failed" && FAILED.has(source.status)) || (filter === "ready" && !RUNNING.has(source.status) && !FAILED.has(source.status)));
  const linked = active?.linked_document_id ? linkedDocuments.get(active.linked_document_id) : undefined;
  return (
    <>
      <PageHeader
        eyebrow="Processing Queue"
        title="Document workflow"
        description="Conversion, review, extraction, and readiness are tracked by document role and status."
        actions={[<Segmented key="filter" value={filter} onChange={(value) => setFilter(String(value))} options={["attention", "all", "failed", "ready"]} />]}
      />
      <div className="queue-professional-layout">
        <Card className="queue-document-list">
          <List
            dataSource={filtered}
            renderItem={(source) => (
              <List.Item className={active?.id === source.id ? "queue-active-item" : ""} onClick={() => setActive(source)}>
                <List.Item.Meta title={source.name} description={<Space><RoleTag value={source.doc_type} /><StatusTag status={source.status} /></Space>} />
              </List.Item>
            )}
          />
        </Card>
        <Card className="queue-stage-card" title={active?.name ?? "Select a document"}>
          {active ? (
            <>
              <Steps current={sourceStage(active)} items={[
                { title: "Import URL" }, { title: "Convert" }, { title: "Review Text" }, { title: "Extract Records" }, { title: "Review Records" }, { title: "Ready for Mapping" }
              ]} />
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="Role">{active.doc_type.replaceAll("_", " ")}</Descriptions.Item>
                <Descriptions.Item label="Text review">{active.text_review_status}</Descriptions.Item>
                <Descriptions.Item label="Status"><StatusTag status={linked?.status ?? active.status} /></Descriptions.Item>
                <Descriptions.Item label="Updated">{createdLabel(active.updated_at)}</Descriptions.Item>
              </Descriptions>
              {linked?.error_message ? <Alert type="error" showIcon message={linked.error_message} /> : null}
              <Space wrap>
                {active.linked_document_id ? <Button type="primary" onClick={() => onOpenDocument(active.linked_document_id!, "document-review")}>Open Document Review</Button> : null}
                <Button onClick={() => onSelect(active)}>Document details</Button>
              </Space>
            </>
          ) : <Empty description="No documents need attention" />}
        </Card>
      </div>
    </>
  );
}

function FieldsReview({ sources, fields, busy, onSelect, onSave, onApproveAll }: { sources: SourceDocument[]; fields: TemplateField[]; busy: boolean; onSelect: (field: TemplateField) => void; onSave: (field: TemplateField, data: TemplateFieldUpdate) => void; onApproveAll: (source: SourceDocument) => void }) {
  const [sourceId, setSourceId] = useState(sources[0]?.id ?? "");
  useEffect(() => { if (!sourceId && sources[0]) setSourceId(sources[0].id); }, [sources, sourceId]);
  const source = sources.find((item) => item.id === sourceId) ?? null;
  const visible = fields.filter((field) => field.source_document_id === sourceId);
  return (
    <>
      <PageHeader
        eyebrow="Field Review"
        title="Canonical template fields"
        description="Review atomic values, tables, schedules, and bidder/project-office ownership before mapping."
        actions={[
          <Select key="source" className="document-context-select" placeholder="Select template" value={sourceId || undefined} options={sources.map((item) => ({ label: item.name, value: item.id }))} onChange={setSourceId} />,
          <Popconfirm key="approve" title="Approve every outstanding field except rejected fields?" onConfirm={() => source && onApproveAll(source)}><Button type="primary" disabled={!source || busy}>Approve All Outstanding</Button></Popconfirm>
        ]}
      />
      <Table
        className="ant-workbench-table"
        rowKey="id"
        dataSource={visible}
        pagination={{ pageSize: 14 }}
        scroll={{ x: 1100 }}
        columns={[
          { title: "Field", dataIndex: "label", render: (value, field) => <Button type="link" onClick={() => onSelect(field)}>{value}</Button> },
          { title: "Check intent", dataIndex: "check_intent", ellipsis: true },
          { title: "Part", dataIndex: "part_ref" },
          { title: "Type", dataIndex: "input_type", render: (value) => <ReviewTypeChip label={value} /> },
          { title: "Supplied by", dataIndex: "filled_by", render: (value) => <Tag>{String(value).replaceAll("_", " ")}</Tag> },
          { title: "Confidence", dataIndex: "confidence", render: (value) => <ReviewConfidence value={value} /> },
          { title: "Status", dataIndex: "review_status", render: (value) => <ReviewStatusBadge status={value} /> },
          { title: "Decision", render: (_, field) => <Space><Button size="small" onClick={() => onSave(field, { review_status: "approved" })}>Approve</Button><Button size="small" onClick={() => onSave(field, { review_status: "needs_edit" })}>Edit</Button><Button size="small" danger onClick={() => onSave(field, { review_status: "rejected" })}>Reject</Button></Space> }
        ]}
        locale={{ emptyText: <Empty description="Select a template with extracted fields" /> }}
      />
    </>
  );
}

function MappingWorkspace({
  collectionId, sources, fields, mappings, procedures, busy, onSuggest, onSave, onDelete, onCreate, onCreateProcedure, onApproveProcedure
}: {
  collectionId: string; sources: SourceDocument[]; fields: TemplateField[]; mappings: FieldRuleMapping[]; procedures: ProcedureSet[]; busy: boolean;
  onSuggest: (templateIds: string[], ruleIds: string[]) => void;
  onSave: (mapping: FieldRuleMapping, data: FieldRuleMappingUpdate) => void;
  onDelete: (mapping: FieldRuleMapping) => void;
  onCreate: (payload: Omit<FieldRuleMapping, "id" | "field_label" | "rule_subject" | "created_at" | "updated_at">) => void;
  onCreateProcedure: (payload: Pick<ProcedureSet, "collection_id" | "name" | "template_source_ids" | "rule_source_ids" | "mapping_ids">) => void;
  onApproveProcedure: (procedure: ProcedureSet) => void;
}) {
  const templates = sources.filter((source) => source.doc_type === "template");
  const rulebooks = sources.filter((source) => ["rulebook", "reference_clause"].includes(source.doc_type));
  const [templateIds, setTemplateIds] = useState<string[]>(templates.map((source) => source.id));
  const [ruleIds, setRuleIds] = useState<string[]>(rulebooks.map((source) => source.id));
  const approvedFields = fields.filter((field) => field.review_status === "approved" && templateIds.includes(field.source_document_id ?? ""));
  const [fieldId, setFieldId] = useState(approvedFields[0]?.id ?? "");
  const [rules, setRules] = useState<Rule[]>([]);
  const [newMappingOpen, setNewMappingOpen] = useState(false);
  const [procedureName, setProcedureName] = useState("Tender Vetting Procedure");
  const fieldMappings = mappings.filter((mapping) => mapping.template_field_id === fieldId);

  useEffect(() => {
    if (!templateIds.length && templates.length) setTemplateIds(templates.map((source) => source.id));
    if (!ruleIds.length && rulebooks.length) setRuleIds(rulebooks.map((source) => source.id));
  }, [rulebooks.length, templateIds.length, templates.length, ruleIds.length]);
  const selectedRuleDocumentIds = rulebooks
    .filter((source) => ruleIds.includes(source.id) && source.linked_document_id)
    .map((source) => source.linked_document_id!)
    .sort((a, b) => a - b);
  useEffect(() => {
    Promise.all(selectedRuleDocumentIds.map((documentId) => getRules(documentId))).then((rows) => setRules(rows.flat())).catch(() => setRules([]));
  }, [selectedRuleDocumentIds.join(",")]);
  useEffect(() => { if (!fieldId && approvedFields[0]) setFieldId(approvedFields[0].id); }, [approvedFields, fieldId]);

  return (
    <>
      <PageHeader
        eyebrow="Mapping & Procedures"
        title="Human-reviewed field-to-rule logic"
        description="Select template and rule books, generate ranked links, approve the mappings, then freeze an approved procedure version."
        actions={[<Button key="suggest" type="primary" icon={<Sparkles size={16} />} disabled={busy || !templateIds.length || !ruleIds.length} onClick={() => onSuggest(templateIds, ruleIds)}>Generate Suggestions</Button>]}
      />
      <Card className="mapping-source-selector">
        <div><Typography.Text strong>Template books</Typography.Text><Select mode="multiple" value={templateIds} onChange={setTemplateIds} options={templates.map((source) => ({ label: source.name, value: source.id }))} /></div>
        <div><Typography.Text strong>Rule books</Typography.Text><Select mode="multiple" value={ruleIds} onChange={setRuleIds} options={rulebooks.map((source) => ({ label: source.name, value: source.id }))} /></div>
      </Card>
      <div className="field-mapping-workspace">
        <Card title={`Approved fields (${approvedFields.length})`} className="mapping-fields">
          <List dataSource={approvedFields} renderItem={(field) => <List.Item className={field.id === fieldId ? "mapping-field-active" : ""} onClick={() => setFieldId(field.id)}><List.Item.Meta title={field.label} description={`${field.template_doc} · ${mappings.filter((mapping) => mapping.template_field_id === field.id).length} links`} /></List.Item>} />
        </Card>
        <Card title="Suggested and approved rule links" className="mapping-links" extra={<Button size="small" onClick={() => setNewMappingOpen(true)} disabled={!fieldId}>Add Link</Button>}>
          <List
            dataSource={fieldMappings}
            locale={{ emptyText: <Empty description="Generate or add rule links for this field" /> }}
            renderItem={(mapping) => (
              <List.Item actions={[
                <Button size="small" onClick={() => onSave(mapping, { review_status: "approved" })}>Approve</Button>,
                <Button size="small" onClick={() => onSave(mapping, { review_status: "needs_edit" })}>Edit</Button>,
                <Popconfirm title="Delete this mapping?" onConfirm={() => onDelete(mapping)}><Button size="small" danger>Delete</Button></Popconfirm>
              ]}>
                <List.Item.Meta title={mapping.rule_subject || mapping.rule_id || "Manual check"} description={<Space wrap><ReviewConfidence value={mapping.confidence} /><ReviewStatusBadge status={mapping.review_status} /><ReviewTypeChip label={mapping.check_type} /></Space>} />
                <Typography.Paragraph ellipsis={{ rows: 2 }}>{mapping.rationale}</Typography.Paragraph>
              </List.Item>
            )}
          />
          {fieldMappings.some((mapping) => mapping.confidence >= 0.75 && mapping.review_status !== "approved") ? <Button onClick={() => fieldMappings.filter((mapping) => mapping.confidence >= 0.75 && mapping.review_status !== "approved").forEach((mapping) => onSave(mapping, { review_status: "approved" }))}>Approve High Confidence</Button> : null}
        </Card>
      </div>
      <Card title="Tender Vetting Procedure Sets">
        <Space wrap className="procedure-create-row">
          <Input value={procedureName} onChange={(event) => setProcedureName(event.target.value)} />
          <Button type="primary" disabled={!mappings.filter((mapping) => mapping.review_status === "approved").length} onClick={() => onCreateProcedure({ collection_id: collectionId, name: procedureName, template_source_ids: templateIds, rule_source_ids: ruleIds, mapping_ids: mappings.filter((mapping) => mapping.review_status === "approved").map((mapping) => mapping.id) })}>Save Draft Version</Button>
        </Space>
        <List dataSource={procedures} renderItem={(procedure) => <List.Item actions={procedure.status === "draft" ? [<Popconfirm title="Freeze and approve this procedure version?" onConfirm={() => onApproveProcedure(procedure)}><Button type="primary">Approve Version</Button></Popconfirm>] : []}><List.Item.Meta title={`${procedure.name} v${procedure.version}`} description={`${procedure.mapping_ids.length} mappings · ${procedure.template_source_ids.length} templates · ${procedure.rule_source_ids.length} rulebooks`} /><Tag color={procedure.status === "approved" ? "green" : "blue"}>{procedure.status}</Tag></List.Item>} />
      </Card>
      <Modal title="Add field-to-rule link" open={newMappingOpen} onCancel={() => setNewMappingOpen(false)} footer={null}>
        <Form layout="vertical" onFinish={(values) => { onCreate({ collection_id: collectionId, template_field_id: fieldId, source_type: "rule", confidence: 1, rationale: "Manually linked by reviewer", review_status: "suggested", review_notes: "", applicability_condition: "", check_type: "hybrid", ...values }); setNewMappingOpen(false); }}>
          <Form.Item name="rule_id" label="Rule" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={rules.map((rule) => ({ label: rule.subject || rule.action, value: rule.id }))} /></Form.Item>
          <Form.Item name="check_type" label="Check type" initialValue="hybrid"><Select options={["deterministic", "llm", "hybrid", "manual"].map((value) => ({ label: value, value }))} /></Form.Item>
          <Button type="primary" htmlType="submit">Add Mapping</Button>
        </Form>
      </Modal>
    </>
  );
}

function ActivityLog({ events }: { events: AuditEvent[] }) {
  const [query, setQuery] = useState("");
  const filtered = events.filter((event) => !query || `${event.summary} ${event.actor} ${event.entity_type}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <>
      <PageHeader eyebrow="Activity Log" title="System modification history" description="Demo-user and background-system changes with redacted before/after details." actions={[<Input key="search" prefix={<Search size={15} />} placeholder="Search activity" value={query} onChange={(event) => setQuery(event.target.value)} />]} />
      <Table
        className="ant-workbench-table"
        rowKey="id"
        dataSource={filtered}
        pagination={{ pageSize: 15 }}
        columns={[
          { title: "Time", dataIndex: "created_at", render: createdLabel },
          { title: "Actor", dataIndex: "actor", render: (value) => <Tag color={value === "System" ? "blue" : "green"}>{value}</Tag> },
          { title: "Action", dataIndex: "action", render: (value) => value.replaceAll("_", " ") },
          { title: "Entity", render: (_, event) => `${event.entity_type} · ${event.entity_id}` },
          { title: "Summary", dataIndex: "summary" },
          { title: "Change", render: (_, event) => <details><summary>View diff</summary><pre className="audit-diff">{JSON.stringify({ before: event.before_json, after: event.after_json }, null, 2)}</pre></details> }
        ]}
      />
    </>
  );
}

function SourceDetailsDrawer({ source, linked, busy, onClose, onSave, onOpenDocument }: { source: SourceDocument | null; linked?: DocumentJob; busy: boolean; onClose: () => void; onSave: (data: Partial<SourceDocument>) => void; onOpenDocument: Props["onOpenDocument"] }) {
  const [form] = Form.useForm();
  useEffect(() => { if (source) form.setFieldsValue(source); }, [source, form]);
  return (
    <Drawer title={source?.name ?? "Document details"} open={Boolean(source)} onClose={onClose} size="large">
      {source ? <Form form={form} layout="vertical" onFinish={onSave}>
        <Form.Item name="name" label="Name"><Input /></Form.Item>
        <Form.Item name="description" label="Description"><Input.TextArea rows={3} /></Form.Item>
        <Form.Item name="doc_type" label="Document role"><Select options={roleOptions()} /></Form.Item>
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Workflow status"><StatusTag status={linked?.status ?? source.status} /></Descriptions.Item>
          <Descriptions.Item label="Text review">{source.text_review_status}</Descriptions.Item>
          <Descriptions.Item label="Content fingerprint">{source.content_fingerprint ? source.content_fingerprint.slice(0, 18) + "…" : "Not verified"}</Descriptions.Item>
          <Descriptions.Item label="Public URL">{source.pdf_url}</Descriptions.Item>
        </Descriptions>
        <Space wrap className="drawer-actions">
          <Button type="primary" onClick={() => source.linked_document_id && onOpenDocument(source.linked_document_id, "document-review")}>Open Document Review</Button>
          {source.doc_type === "rulebook" || source.doc_type === "reference_clause" ? <Button onClick={() => source.linked_document_id && onOpenDocument(source.linked_document_id, "rule-review")}>Open Rule Review</Button> : null}
          <Button htmlType="submit" loading={busy}>Save Details</Button>
        </Space>
      </Form> : null}
    </Drawer>
  );
}

function FieldEvidenceDrawer({ field, sources, onClose }: { field: TemplateField | null; sources: SourceDocument[]; onClose: () => void }) {
  const source = sources.find((item) => item.id === field?.source_document_id);
  const documentId = field?.evidence_locator?.document_id ?? source?.linked_document_id;
  const page = Number.parseInt(field?.evidence_locator?.page_range ?? "1", 10) || 1;
  return (
    <Drawer title={field?.label ?? "Field evidence"} open={Boolean(field)} onClose={onClose} size="large">
      {field ? <div className="evidence-drawer-layout">
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Check intent">{field.check_intent || field.extraction_hint}</Descriptions.Item>
          <Descriptions.Item label="Supplied by">{field.filled_by}</Descriptions.Item>
          <Descriptions.Item label="Source section">{field.section_ref || "Unknown"}</Descriptions.Item>
          <Descriptions.Item label="Anchor text">{field.anchor_text || "No anchor text"}</Descriptions.Item>
          <Descriptions.Item label="Structured schema"><pre>{JSON.stringify(field.structured_schema, null, 2)}</pre></Descriptions.Item>
        </Descriptions>
        {documentId ? <iframe title="PDF evidence" src={`/api/documents/${documentId}/source-pdf#page=${page}`} /> : <Empty description="No linked PDF evidence" />}
      </div> : null}
    </Drawer>
  );
}

function ComingSoon({ title }: { title: string }) {
  return <Card className="coming-soon-card"><Clock3 size={46} /><Typography.Title level={2}>{title}</Typography.Title><Typography.Paragraph>This workflow is intentionally deferred. The current phase focuses on verified documents, fields, rules, mappings, and approved procedure sets.</Typography.Paragraph><Tag color="blue">Coming Soon</Tag></Card>;
}

function PageHeader({ eyebrow, title, description, actions = [] }: { eyebrow: string; title: string; description: string; actions?: ReactNode[] }) {
  return <div className="tv-page-header"><div><Typography.Text className="tv-eyebrow">{eyebrow}</Typography.Text><Typography.Title level={2}>{title}</Typography.Title><Typography.Text type="secondary">{description}</Typography.Text></div>{actions.length ? <Space wrap className="tv-page-actions">{actions}</Space> : null}</div>;
}

function CountUp({ value }: { value: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setDisplay(value); return; }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 600);
      setDisplay(Math.round(value * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <strong>{display.toLocaleString()}</strong>;
}

function RoleTag({ value }: { value: string }) {
  return <Tag color={value === "template" ? "cyan" : value === "reference_clause" ? "purple" : "blue"}>{value.replaceAll("_", " ")}</Tag>;
}

function StatusTag({ status }: { status: string }) {
  const color = FAILED.has(status) ? "red" : status.includes("verified") || status.includes("ready") || status === "rules_extracted" || status === "fields_extracted" ? "green" : RUNNING.has(status) ? "blue" : "default";
  return <Tag color={color}>{status === "not_uploaded" ? "Not uploaded" : labelStatus(status as never)}</Tag>;
}

function sourceStage(source: SourceDocument) {
  if (source.status === "rules_verified" || source.status === "fields_verified") return 5;
  if (source.status === "rules_extracted" || source.status === "fields_extracted") return 4;
  if (source.text_review_status === "verified") return 3;
  if (source.status === "markdown_ready") return 2;
  if (source.status.includes("mineru")) return 1;
  return 0;
}

function roleOptions() {
  return [
    { label: "Rulebook", value: "rulebook" },
    { label: "Reference clause", value: "reference_clause" },
    { label: "Template", value: "template" },
    { label: "Tender submission", value: "tender_submission" },
  ];
}

function createdLabel(value?: string | null) {
  if (!value) return "No timestamp";
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? "No timestamp" : new Date(timestamp).toLocaleString();
}
