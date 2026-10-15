import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import PackagePage from "../clinic/PackagePage";
import type { SharePackage } from "../types";

afterEach(() => vi.restoreAllMocks());

const ent = (canonical: string, hpo: string | null, extra: object = {}) => ({
  entry_id: "e1", occurred_on: "2026-10-01", type: "symptom" as const, quote: canonical, canonical, hpo_id: hpo,
  negated: false, family_history: false, severity: null, reviewed: true, ...extra,
});
const pkg: SharePackage = {
  package_id: "pkg_1", patient_alias: "Ash-001", created_at: "2026-10-02T00:00:00Z", expires_at: "2026-10-05T00:00:00Z",
  period: ["2026-09-01", "2026-10-02"], note: null,
  entries: [{ id: "e1", created_at: "x", occurred_on: "2026-10-01", text: "Mia madre ha il lupus. Ginocchia che fanno male.", mood: null, extraction: "done", entities: [] }],
  entities: [
    ent("Arthralgia", "HP:0002829"), ent("Arthralgia", "HP:0002829"), ent("Fever", "HP:0001945", { negated: true }),
    ent("Systemic lupus erythematosus", null, { family_history: true, type: "finding" }),
  ],
  labs: [
    { test_name: "Cholesterol", value_numeric: 264, value_text: null, unit: "mg/dL", ref_low: 0, ref_high: 200, flag: "high", date: "2026-09-15", page: 2, entry_id: "e1", reviewed: true },
    { test_name: "Glucose", value_numeric: 90, value_text: null, unit: "mg/dL", ref_low: 70, ref_high: 100, flag: "normal", date: "2026-09-15", page: 3, entry_id: "e1", reviewed: false },
  ],
  patterns: [
    { disease_id: "ORPHA:1", disease_name: "Strong one", signal: "moderate", score: 0.5, matched: [], missing: [], rationale: "", rationale_source: "template", neutral_label: "" },
    { disease_id: "ORPHA:2", disease_name: "Weak one", signal: "weak", score: 0.3, matched: [], missing: [], rationale: "", rationale_source: "template", neutral_label: "" },
  ],
};

describe("clinic package page", () => {
  it("counts only the patient's own terms, lists family history apart, shows labs and collapses weak signals", async () => {
    vi.spyOn(api, "package").mockResolvedValue(pkg);
    vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_1", patient_alias: "Ash-001", period: pkg.period, received_at: "x", expires_at: "x", entities: 2, brief_state: "none" }]);
    render(<MemoryRouter initialEntries={["/p/pkg_1"]}><Routes><Route path="/p/:id" element={<PackagePage />} /></Routes></MemoryRouter>);
    expect(await screen.findByTestId("pkg-counts")).toHaveTextContent("2 mentions of 1 terms");
    const terms = screen.getByRole("heading", { name: "Confirmed terms" }).parentElement as HTMLElement;
    expect(within(terms).queryByText("Systemic lupus erythematosus")).toBeNull();
    expect(within(terms).getByText("Arthralgia")).toBeInTheDocument();
    const fam = screen.getByRole("heading", { name: "Family history (reported by the patient)" }).parentElement as HTMLElement;
    expect(within(fam).getByText(/Systemic lupus erythematosus/)).toBeInTheDocument();
    const labs = screen.getByTestId("pkg-labs");
    expect(within(labs).getAllByText("Cholesterol").length).toBeGreaterThan(0);
    expect(within(labs).getAllByText(/not reviewed by a person/).length).toBeGreaterThan(0);
    const weak = screen.getByText("Weaker signals (1)").closest("details") as HTMLElement;
    expect(within(weak).getByText("Weak one")).toBeInTheDocument();
    expect(within(weak).queryByText("Strong one")).toBeNull();
  });
});
