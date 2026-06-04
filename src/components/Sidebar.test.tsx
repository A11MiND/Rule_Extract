import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";
import type { NavPage } from "./Sidebar";

const pages: Array<{ key: NavPage; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "sources", label: "Sources" },
  { key: "queue", label: "Queue" },
  { key: "document-review", label: "Document Review" },
  { key: "rule-review", label: "Rules" },
  { key: "field-review", label: "Fields" },
  { key: "mapping-review", label: "Mappings" },
  { key: "submissions", label: "Submissions" },
  { key: "results", label: "Results" },
  { key: "activity", label: "Activity" },
  { key: "settings", label: "Settings" },
];

describe("Sidebar", () => {
  it("routes every primary navigation item to its own page key", () => {
    const onNavigate = vi.fn();
    render(<Sidebar activePage="dashboard" onNavigate={onNavigate} />);

    for (const page of pages) {
      fireEvent.click(screen.getByText(page.label));
      expect(onNavigate).toHaveBeenLastCalledWith(page.key);
    }

    expect(onNavigate).toHaveBeenCalledTimes(pages.length);
  });
});
