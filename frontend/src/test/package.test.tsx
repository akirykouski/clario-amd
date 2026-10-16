import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    { test_name: "Cholesterol", value_numeric: 264, value_text: null, unit: "mg/dL", ref_low: 0, ref_high: 200, flag: "high", date: "2026-09-15", page: 2, entry_id: "e1", reviewed: true },
    { test_name: "Glucose", value_numeric: 90, value_text: null, unit: "mg/dL", ref_low: 70, ref_high: 100, flag: "normal", date: "2026-09-15", page: 3, entry_id: "e1", reviewed: false },
  ],
  patterns: [
    { disease_id: "ORPHA:1", disease_name: "Strong one", signal: "moderate", score: 0.5, matched: [], missing: [], rationale: "", rationale_source: "template", neutral_label: "" },
    { disease_id: "ORPHA:2", disease_name: "Weak one", signal: "weak", score: 0.3, matched: [], missing: [], rationale: "", rationale_source: "template", neutral_label: "" },
  ],
};

const ddx = {
  conditions: [
    { disease_id: "ORPHA:536", name: "Systemic lupus erythematosus", full_name: "Systemic lupus erythematosus", signal: "moderate" as const, score: 0.5, rank: 1,
      url: "https://www.orpha.net/en/disease/detail/536", matched: [{ hpo_id: "HP:0002829", label: "Arthralgia", count: 2, freq: null }],
      missing: [{ hpo_id: "HP:0001903", label: "Anemia", count: 0, freq: 0.4 }] },
    { disease_id: "OMIM:1", name: "Weak one", full_name: "Weak one 2", signal: null, score: 0.2, rank: 2, url: null, matched: [], missing: [] },
  ],
  question: { feature_id: "HP:0003326", label: "Myalgia", question: "Does the patient have: Myalgia?", ig: 0.4,
              freq_by: [{ name: "Systemic lupus erythematosus", freq: null }, { name: "Weak one", freq: 0 }] },
  answers: [], n_terms: 3, note: "",
};

function mount() {
  vi.spyOn(api, "package").mockResolvedValue(pkg);
  vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_1", patient_alias: "Ash-001", period: pkg.period, received_at: "x", expires_at: "x", entities: 2, brief_state: "none" }]);
  vi.spyOn(api, "decisions").mockResolvedValue({ terms: {}, answers: [] });
  vi.spyOn(api, "termSystems").mockResolvedValue({ "HP:0002829": "joints" });
  vi.spyOn(api, "ddx").mockResolvedValue(ddx);
  render(<MemoryRouter initialEntries={["/p/pkg_1"]}><Routes><Route path="/p/:id" element={<PackagePage />} /></Routes></MemoryRouter>);
}

describe("clinic package page", () => {
  it("leads with the visit goal, named conditions and the next question; technical detail is collapsed", async () => {
    mount();
    expect(await screen.findByTestId("pkg-counts")).toHaveTextContent("2 mentions of 1 terms");
    expect(screen.getByTestId("pkg-glance")).toHaveTextContent("1 notes over 1 weeks · 1 symptoms · 1 out-of-range labs");
    const box = await screen.findByTestId("ddx");
    expect(within(box).getAllByTestId("ddx-condition")[0]).toHaveTextContent("1.Systemic lupus erythematosus");
    expect(within(box).getByText("weaker match")).toBeInTheDocument();
    expect(within(box).getByText("40%")).toBeInTheDocument();
    const q = screen.getByTestId("ddx-question");
    expect(q).toHaveTextContent("Does the patient have: Myalgia?");
    expect(q).toHaveTextContent("listed");
    expect(q).toHaveTextContent("not listed");
    const details = screen.getByTestId("pkg-details");
    expect(details.tagName).toBe("DETAILS");
    const terms = within(details).getByRole("heading", { name: "All recorded terms" }).parentElement as HTMLElement;
    expect(within(terms).queryByText("Systemic lupus erythematosus")).toBeNull();  // the relative's condition is family history
    expect(within(terms).getByText("Arthralgia")).toBeInTheDocument();
    const fam = within(details).getByRole("heading", { name: "Family history (reported by the patient)" }).parentElement as HTMLElement;
    expect(within(fam).getByText(/Systemic lupus erythematosus/)).toBeInTheDocument();
    const labs = screen.getByTestId("pkg-labs");
    expect(within(labs).getAllByText("Cholesterol").length).toBeGreaterThan(0);
    expect(within(labs).getAllByText(/not reviewed by a person/).length).toBeGreaterThan(0);
    expect(await screen.findByTestId("pkg-heat")).toBeInTheDocument();
  });

  it("answering the question re-ranks and records the finding", async () => {
    mount();
    const after = { ...ddx, conditions: [ddx.conditions[1], { ...ddx.conditions[0], rank: 2 }].map((c, i) => ({ ...c, rank: i + 1 })),
                    question: null, answers: [{ feature_id: "HP:0003326", label: "Myalgia", answer: "yes" as const, at: "x" }] };
    const ans = vi.spyOn(api, "ddxAnswer").mockResolvedValue({ before: ddx.conditions, differential: after });
    const q = await screen.findByTestId("ddx-question");
    await userEvent.click(within(q).getByRole("button", { name: "Present" }));
    expect(ans).toHaveBeenCalledWith("pkg_1", { feature_id: "HP:0003326", answer: "yes", lang: "en" });
    expect(await screen.findByTestId("ddx-findings")).toHaveTextContent("Myalgia: Present");
    expect(screen.getByText("up 1")).toBeInTheDocument();
    expect(screen.getByText("down 1")).toBeInTheDocument();
  });

  it("asks the clinician to check unsure terms and refreshes the conditions after a decision", async () => {
    const unsure = { ...pkg, entities: [...pkg.entities, ent("Oral ulcer", "HP:0000155", { id: "x9", needs_review: true, confidence: 0.6, reviewed: false })] };
    vi.spyOn(api, "package").mockResolvedValue(unsure);
    vi.spyOn(api, "inbox").mockResolvedValue([]);
    vi.spyOn(api, "decisions").mockResolvedValue({ terms: {}, answers: [] });
    vi.spyOn(api, "termSystems").mockResolvedValue({});
    const getDdx = vi.spyOn(api, "ddx").mockResolvedValue(ddx);
    const decide = vi.spyOn(api, "decideTerm").mockResolvedValue({ terms: { x9: "rejected" }, answers: [] });
    render(<MemoryRouter initialEntries={["/p/pkg_1"]}><Routes><Route path="/p/:id" element={<PackagePage />} /></Routes></MemoryRouter>);
    const box = await screen.findByTestId("needs-check");
    expect(box).toHaveTextContent("1 item needs your check");
    expect(box).toHaveTextContent("60%");
    await userEvent.click(within(box).getByRole("button", { name: /reject/i }));
    expect(decide).toHaveBeenCalledWith("pkg_1", "x9", "rejected");
    expect(await within(box).findByText("Rejected by you")).toBeInTheDocument();
    await waitFor(() => expect(getDdx).toHaveBeenCalledTimes(2));
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
