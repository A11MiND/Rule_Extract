import { useCallback, useEffect, useState } from "react";
import { BookOpen, Database, FileText, RefreshCw, Search, Shield } from "lucide-react";
import { getKnowledgeItems, getKnowledgeStats, triggerIngestion } from "../api";
import type { KBStats, KnowledgeItem } from "../types";

const SOURCE_LABELS: Record<string, string> = {
  clause: "Clauses",
  template_spec: "Template Specs",
  policy: "Policies",
  department_rule: "Dept Rules",
};

const SOURCE_ICONS: Record<string, React.ReactNode> = {
  clause: <BookOpen size={14} />,
  template_spec: <FileText size={14} />,
  policy: <Shield size={14} />,
  department_rule: <Database size={14} />,
};

const SOURCE_COLORS: Record<string, string> = {
  clause: "#7c3aed",
  template_spec: "#0891b2",
  policy: "#d97706",
  department_rule: "#059669",
};

export function KBWorkspace() {
  const [stats, setStats] = useState<KBStats | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [selected, setSelected] = useState<KnowledgeItem | null>(null);
  const [filterType, setFilterType] = useState<string>("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [ingestStatus, setIngestStatus] = useState("");

  const loadStats = useCallback(async () => {
    try {
      setStats(await getKnowledgeStats());
    } catch {
      // stats not available yet
    }
  }, []);

  const loadItems = useCallback(async () => {
    setBusy(true);
    try {
      const result = await getKnowledgeItems({
        source_type: filterType || undefined,
        search: search || undefined,
        limit: 200,
      });
      setItems(result);
    } catch {
      setItems([]);
    } finally {
      setBusy(false);
    }
  }, [filterType, search]);

  useEffect(() => {
    loadStats();
    loadItems();
  }, [loadStats, loadItems]);

  const handleIngest = async () => {
    setIngestStatus("Starting...");
    try {
      const res = await triggerIngestion();
      setIngestStatus(`Queued: ${res.task_id || "unknown"}`);
      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const r = await fetch("/api/knowledge/ingest/status");
          const data = await r.json();
          setIngestStatus(`${data.status}: ${data.progress}`);
          if (data.status === "completed" || data.status === "failed" || data.status === "idle") {
            clearInterval(poll);
            loadStats();
            loadItems();
          }
        } catch {
          clearInterval(poll);
        }
      }, 2000);
    } catch (e: any) {
      setIngestStatus(`Error: ${e.message}`);
    }
  };

  const handleEmbed = async () => {
    try {
      const r = await fetch("/api/knowledge/embed-all", { method: "POST" });
      const data = await r.json();
      setIngestStatus(`Embedded ${data.embedded} items`);
    } catch (e: any) {
      setIngestStatus(`Embed error: ${e.message}`);
    }
  };

  const typeFilters = ["", ...Object.keys(SOURCE_LABELS)];

  return (
    <div className="kb-workspace">
      {/* Stats Bar */}
      <div className="kb-stats-bar">
        {stats ? (
          <>
            {Object.entries(SOURCE_LABELS).map(([key, label]) => (
              <span
                key={key}
                className={`kb-stat-chip ${filterType === key ? "active" : ""}`}
                style={{ borderLeftColor: SOURCE_COLORS[key] }}
                onClick={() => setFilterType(filterType === key ? "" : key)}
              >
                <span className="kb-stat-dot" style={{ background: SOURCE_COLORS[key] }} />
                {label}: <strong>{stats.by_type[key] || 0}</strong>
              </span>
            ))}
            <span className="kb-stat-total">
              Total: <strong>{stats.total}</strong> ({stats.active} active)
            </span>
          </>
        ) : (
          <span className="kb-stat-total">Loading stats...</span>
        )}
        <div className="kb-actions">
          <button className="btn btn-sm btn-outline" onClick={handleIngest} disabled={!!ingestStatus.match(/Starting|running|Queued/)}>
            <RefreshCw size={14} /> Ingest
          </button>
          <button className="btn btn-sm btn-outline" onClick={handleEmbed}>
            Embed All
          </button>
          {ingestStatus && <span className="kb-ingest-msg">{ingestStatus}</span>}
        </div>
      </div>

      <div className="kb-main">
        {/* Filter Sidebar */}
        <aside className="kb-sidebar">
          <div className="kb-search">
            <Search size={14} />
            <input
              type="text"
              placeholder="Search..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="kb-type-filters">
            {typeFilters.map((tf) => (
              <button
                key={tf || "all"}
                className={`kb-filter-btn ${filterType === tf ? "active" : ""}`}
                style={tf ? { borderLeftColor: SOURCE_COLORS[tf] } : undefined}
                onClick={() => setFilterType(tf)}
              >
                {tf ? (
                  <>
                    {SOURCE_ICONS[tf]}
                    {SOURCE_LABELS[tf]}
                  </>
                ) : (
                  "All Types"
                )}
              </button>
            ))}
          </div>
        </aside>

        {/* Items Table */}
        <div className="kb-table-wrap">
          {busy ? (
            <div className="kb-empty">Loading...</div>
          ) : items.length === 0 ? (
            <div className="kb-empty">
              <Database size={32} />
              <p>No knowledge items yet</p>
              <p className="kb-muted">Click "Ingest" to populate from source documents</p>
            </div>
          ) : (
            <table className="kb-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Type</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={`kb-row ${selected?.id === item.id ? "selected" : ""}`}
                    onClick={() => setSelected(item)}
                  >
                    <td className="kb-id">{item.id}</td>
                    <td className="kb-title">{item.title}</td>
                    <td>
                      <span
                        className="kb-type-badge"
                        style={{ background: SOURCE_COLORS[item.source_type] || "#6b7280" }}
                      >
                        {SOURCE_LABELS[item.source_type] || item.source_type}
                      </span>
                    </td>
                    <td className="kb-source">{item.source_document}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Detail Panel */}
        <div className="kb-detail">
          {selected ? (
            <div className="kb-detail-inner">
              <h3 className="kb-detail-title">{selected.title}</h3>
              <div className="kb-detail-meta">
                <span
                  className="kb-type-badge"
                  style={{ background: SOURCE_COLORS[selected.source_type] || "#6b7280" }}
                >
                  {SOURCE_LABELS[selected.source_type] || selected.source_type}
                </span>
                <span className="kb-detail-id">{selected.id}</span>
                {selected.clause_number && <span>Clause: {selected.clause_number}</span>}
                {selected.template_name && <span>Template: {selected.template_name}</span>}
                {selected.section_number && <span>Section: {selected.section_number}</span>}
                {selected.embedding_id && (
                  <span className="kb-embedded" title="Vector indexed">EMB</span>
                )}
              </div>
              <div className="kb-detail-content">
                {selected.summary && (
                  <div className="kb-detail-summary">
                    <strong>Summary:</strong> {selected.summary}
                  </div>
                )}
                <div className="kb-detail-body">{selected.content}</div>
              </div>
              {selected.clause_remarks && (
                <div className="kb-detail-remarks">
                  <strong>Remarks:</strong> {selected.clause_remarks}
                </div>
              )}
              {selected.field_definitions && (
                <details className="kb-detail-fields">
                  <summary>Field Definitions</summary>
                  <pre>{selected.field_definitions}</pre>
                </details>
              )}
            </div>
          ) : (
            <div className="kb-empty">
              <BookOpen size={32} />
              <p>Select a knowledge item</p>
              <p className="kb-muted">to view its details here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
