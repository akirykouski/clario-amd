import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import PackagePage from "../clinic/PackagePage";
import { RunChips } from "../clinic/BriefPanel";
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
    { test_name: "Cholesterol", value_numeric: 264, value_text: null, unit: "mg/dL", ref_low: 0, ref_high: 200, flag: "high", date: "2026-09-15", page: 2, entry_id: "e1", reviewed: true, id: "l1", test_key: "colesterolototale", name_en: null, abnormal: true, decision: null },
    { test_name: "Glucose", value_numeric: 90, value_text: null, unit: "mg/dL", ref_low: 70, ref_high: 100, flag: "normal", date: "2026-09-15", page: 3, entry_id: "e1", reviewed: false, id: "l2", test_key: "glicemia", name_en: null, abnormal: false, decision: null },
    { test_name: "ANA", value_numeric: null, value_text: "Positivo 1:160", unit: "", ref_low: null, ref_high: null, flag: null, date: "2026-04-07", page: 1, entry_id: "e1", reviewed: true, id: "l3", test_key: "ana", name_en: "ANA", abnormal: true, decision: null },
    { test_name: "ANA", value_numeric: null, value_text: "Negativo", unit: "", ref_low: null, ref_high: null, flag: null, date: "2026-09-15", page: 1, entry_id: "e1", reviewed: true, id: "l4", test_key: "ana", name_en: "ANA", abnormal: false, decision: null },
    { test_name: "Glicemia", value_numeric: 80, value_text: null, unit: "mg/dL", ref_low: null, ref_high: null, flag: null, date: "2026-09-16", page: 3, entry_id: "e1", reviewed: true, id: "l5", test_key: "glicemia", name_en: "Glucose", abnormal: false, decision: null },
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
    expect(within(terms).getAllByText("Arthralgia").length).toBeGreaterThan(0);
    const fam = screen.getByRole("heading", { name: "Family history (reported by the patient)" }).parentElement as HTMLElement;
    expect(within(fam).getByText(/Systemic lupus erythematosus/)).toBeInTheDocument();
    const labs = screen.getByTestId("pkg-labs");
    expect(within(labs).getAllByText("Cholesterol").length).toBeGreaterThan(0);
    expect(within(labs).getAllByText(/From documents, pending check/).length).toBeGreaterThan(0);
    // one history per test, oldest to newest: the earlier positive stays visible next to the later negative
    const ana = within(labs).getAllByTestId("lab-test").find((x) => x.textContent?.includes("ANA")) as HTMLElement;
    const vals = within(ana).getAllByRole("listitem").map((x) => x.textContent ?? "");
    expect(vals[0]).toContain("Positive 1:160");  // one statement, not a value plus a second "Positive" chip
    expect(vals[0].match(/Positive/g)).toHaveLength(1);
    expect(vals[1]).toContain("Negative");
    // lab names follow the UI language: Glucose in English
    expect(within(labs).getAllByText("Glucose").length).toBeGreaterThan(0);
    expect(within(labs).queryByText("Glicemia")).toBeNull();
    // an unchecked row blocks finalizing until the clinician decides
    expect(within(labs).getAllByRole("button", { name: /Accept/ }).length).toBeGreaterThan(0);
    const weak = screen.getByText("Weaker signals (1)").closest("details") as HTMLElement;
    expect(within(weak).getByText("Weak one")).toBeInTheDocument();
    expect(within(weak).queryByText("Strong one")).toBeNull();
  });
});

describe("run chips", () => {
  it("shows model, speed, latency and GPU for a real backend", async () => {
    vi.spyOn(api, "gpu").mockResolvedValue({ gpu_name: "AMD Instinct MI300X", util_pct: 71 });
    render(<RunChips backend="vllm" model="gemma-4" tokensPerS={42.3} latencyMs={2500} />);
    const chips = await screen.findByTestId("run-chips");
    await screen.findByText(/MI300X/);
    expect(chips).toHaveTextContent("vllm · gemma-4");
    expect(chips).toHaveTextContent("42.3 tokens/s");
    expect(chips).toHaveTextContent("2.5 s");
    expect(chips).toHaveTextContent("71%");
  });
  it("says Demo model (offline) and hides the speed for the offline fixtures", async () => {
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    render(<RunChips backend="offline-fixtures" model="offline-fixture-v1" tokensPerS={60} latencyMs={5} />);
    const chips = await screen.findByTestId("run-chips");
    expect(chips).toHaveTextContent("Demo model (offline)");
    expect(chips).not.toHaveTextContent("offline-fixture-v1");
    expect(chips).not.toHaveTextContent("tokens/s");
  });
});
