import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProfessionalWorkbench } from "./ProfessionalWorkbench";

vi.mock("../api", () => ({
  approveProcedureSet: vi.fn(),
  bulkReviewSourceFields: vi.fn(),
  createFieldRuleMapping: vi.fn(),
  createMappingRun: vi.fn(),
  createProcedureSet: vi.fn(),
  deleteFieldRuleMapping: vi.fn(),
  getAuditEvents: vi.fn().mockResolvedValue([]),
  getCollections: vi.fn().mockResolvedValue([{ id: "col-1", name: "Demo Workspace", contract_family: "ECC", jurisdiction: "Hong Kong", version: "2026", status: "active" }]),
  getDashboardSummary: vi.fn().mockResolvedValue({ total_documents: 0, awaiting_text_review: 0, awaiting_record_review: 0, processing: 0, failed: 0, approved_procedure_sets: 0, recent_activity: [] }),
  getDocuments: vi.fn().mockResolvedValue([]),
  getFieldRuleMappings: vi.fn().mockResolvedValue([]),
  getLibrarySlots: vi.fn().mockResolvedValue([
    { id: "slot-1", collection_id: "col-1", name: "Contract Data Part One", short_name: "CDP1", description: "Required template", doc_type: "template", required: true, grouping_level: 3, sort_order: 1 }
  ]),
  getProcedureSets: vi.fn().mockResolvedValue([]),
  getRules: vi.fn().mockResolvedValue([]),
  getSourceDocuments: vi.fn().mockResolvedValue([]),
  getTemplateFields: vi.fn().mockResolvedValue([]),
  importSourceDocumentUrl: vi.fn(),
  updateFieldRuleMapping: vi.fn(),
  updateSourceDocument: vi.fn(),
  updateTemplateField: vi.fn(),
}));

describe("ProfessionalWorkbench", () => {
  it("renders configurable gray placeholders in the source library", async () => {
    const { container } = render(
      <ProfessionalWorkbench page="sources" onPageChange={vi.fn()} onOpenDocument={vi.fn()} />
    );

    expect(await screen.findByText("Contract Data Part One")).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(screen.getByText("Import URL")).toBeInTheDocument();
    await waitFor(() => expect(container.querySelector(".source-placeholder-card")).toBeTruthy());
  });

  it("keeps deferred tender workflows as polished coming-soon pages", () => {
    render(<ProfessionalWorkbench page="submissions" onPageChange={vi.fn()} onOpenDocument={vi.fn()} />);
    expect(screen.getByText("Tender Submissions")).toBeInTheDocument();
    expect(screen.getByText("Coming Soon")).toBeInTheDocument();
  });
});
