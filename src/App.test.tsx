import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the import workflow", () => {
    render(<App />);
    expect(screen.getByText("Rule Extraction Portal")).toBeInTheDocument();
    expect(screen.getByLabelText("Public PDF URL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start MinerU/i })).toBeInTheDocument();
  });
});
