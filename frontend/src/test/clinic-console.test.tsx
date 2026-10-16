import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { BriefPanel } from "../clinic/BriefPanel";
import PackagePage from "../clinic/PackagePage";
import type { Brief, BriefItem, SharedLab, SharePackage } from "../types";

afterEach(() => { vi.restoreAllMocks(); act(() => setLang("en")); });

const lab = (id: string, test_key: string, page: number, over: Partial<SharedLab> = {}): SharedLab => ({
  test_name: test_key, value_numeric: 5, value_text: null, unit: "mg/dL", ref_low: null, ref_high: 200, flag: "normal", date: "2026-09-15", page,
  entry_id: "e9", reviewed: false, needs_review: true, id, test_key, name_en: null, abnormal: false, decision: null, ...over,
});
const pkg: SharePackage = {
  package_id: "pkg_1", patient_alias: "Ash-001", created_at: "x", expires_at: "2026-12-01", period: ["2026-09-01", "2026-10-02"], note: null,
  entries: [
    { id: "e1", created_at: "x", occurred_on: "2026-08-22", text: "Tired", mood: null, entities: [], extraction: "done" },
    { id: "e2", created_at: "x", occurred_on: "2026-09-20", text: "Knees", mood: null, entities: [], extraction: "done" },
  ] as unknown as SharePackage["entries"],
  entities: [{ entry_id: "e1", occurred_on: "2026-08-22", type: "symptom", quote: "Tired", canonical: "Fatigue", hpo_id: "HP:0012378", negated: false, family_history: false, severity: null, reviewed: true }],
  labs: [lab("l1", "sodio", 1), lab("l2", "sodio", 2), lab("l3", "pcr", 2, { flag: "high", abnormal: true })], patterns: [],
};
const ai = (id: string, over: Partial<BriefItem> = {}): BriefItem => ({ id, section: "timeline", text: `line ${id}`, cites: ["e2"], origin: "ai", review: "pending", ...over });
const briefOf = (items: BriefItem[]): Brief => ({ package_id: "pkg_1", items, model: null, backend: null, finalized: false, stats: {} });

function renderPanel(items: BriefItem[], setBrief = vi.fn()) {
  vi.spyOn(api, "gpu").mockResolvedValue(null);
  render(<MemoryRouter><BriefPanel pkg={pkg} brief={briefOf(items)} setBrief={setBrief} /></MemoryRouter>);
  return setBrief;
}

describe("brief citation check", () => {
  const flagged = ai("f", { flag: "citation_mismatch", flag_term: "fatigue", flag_entries: ["e1"], text: "20 Sep: fatigue first noted." });

  it("says why a line is flagged and asks for a confirm before accepting it", () => {
    const review = vi.spyOn(api, "reviewItem").mockResolvedValue({ ...flagged, review: "accepted" });
    renderPanel([flagged]);
    const why = screen.getByTestId("flag-reason");
    expect(why).toHaveTextContent('"fatigue", but the entry it cites (entry 1, 20 Sept) does not record it');
    expect(why).toHaveTextContent('"fatigue" is recorded on 22 Aug');
    fireEvent.click(screen.getByRole("button", { name: /^Accept$/ }));
    expect(review).not.toHaveBeenCalled();  // first click only opens the confirm step
    expect(screen.getByTestId("flag-confirm")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept as it is" }));
    expect(review).toHaveBeenCalledWith("pkg_1", "f", { review: "accepted" });
  });

  it("accepts an unflagged line in one click and collapses it to a status with Undo", () => {
    const plain = ai("p");
    const review = vi.spyOn(api, "reviewItem").mockResolvedValue({ ...plain, review: "pending" });
    renderPanel([{ ...plain, review: "accepted" }]);
    const row = screen.getByTestId("item-decided");
    expect(row).toHaveTextContent("accepted");
    fireEvent.click(within(row).getByRole("button", { name: "Undo" }));
    expect(review).toHaveBeenCalledWith("pkg_1", "p", { review: "pending" });
  });
});

describe("finalize gate", () => {
  it("stays off while a reading that needs a check has no decision, and says how many", () => {
    renderPanel([ai("p", { review: "accepted" })]);
    expect(screen.getByRole("button", { name: "Finalize brief" })).toBeDisabled();
    expect(screen.getByTestId("labs-pending")).toHaveTextContent("3");
  });
});

describe("brief item origin chips", () => {
  it("names documents, answers to app questions and the patient's note", () => {
    renderPanel([
      { id: "d", section: "labs", text: "Sodium: 5 mg/dL", cites: [], origin: "document", review: "accepted", pages: [2] },
      { id: "q", section: "symptoms", text: "Fatigue: you answered yes", cites: ["e1"], origin: "patient", review: "accepted", from_question: true },
      { id: "n", section: "summary", text: "Is it linked?", cites: [], origin: "patient", review: "accepted", kind: "patient_note" },
    ]);
    expect(screen.getByText("From documents")).toBeInTheDocument();
    expect(screen.getByText("report p.2")).toBeInTheDocument();
    expect(screen.getByText("Asked by the app")).toBeInTheDocument();
    expect(screen.getByText("Patient's question for this visit")).toBeInTheDocument();
    act(() => setLang("it"));
    expect(screen.getByText("Dai referti")).toBeInTheDocument();
    expect(screen.getByText("referto p.2")).toBeInTheDocument();
    expect(screen.getByText("Chiesto dall'app")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Riepilogo per la visita" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vai alla nota citata 1" })).toBeInTheDocument();
  });
});

describe("lab bulk decisions", () => {
  function open() {
    vi.spyOn(api, "package").mockResolvedValue(pkg);
    vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_1", patient_alias: "Ash-001", period: pkg.period, received_at: "x", expires_at: "x", entities: 1, brief_state: "none" }]);
    vi.spyOn(api, "decisions").mockResolvedValue({ terms: {}, answers: [] });
    vi.spyOn(api, "termSystems").mockResolvedValue({});
    vi.spyOn(api, "ddx").mockResolvedValue({ conditions: [], question: null, answers: [], n_terms: 0, note: "" });
    vi.spyOn(api, "overview").mockRejectedValue(new Error("none"));
    return render(<MemoryRouter initialEntries={["/p/pkg_1"]}><Routes><Route path="/p/:id" element={<PackagePage />} /></Routes></MemoryRouter>);
  }

  it("confirms a whole report page, or everything, in one call each", async () => {
    const all = { ...pkg, labs: pkg.labs.map((l) => ({ ...l, decision: "confirmed" as const })) };
    const decide = vi.spyOn(api, "decideLabs").mockResolvedValueOnce(pkg).mockResolvedValue(all);
    open();
    const bulk = await screen.findByTestId("lab-bulk");
    fireEvent.click(within(bulk).getByRole("button", { name: "Confirm the 2 readings from page 2" }));
    expect(decide).toHaveBeenLastCalledWith("pkg_1", { decision: "confirmed", page: 2, entry_id: "e9" });
    await act(async () => {});
    fireEvent.click(within(bulk).getByRole("button", { name: "Confirm all 3 readings" }));
    expect(decide).toHaveBeenLastCalledWith("pkg_1", { decision: "confirmed" });
    expect(decide).toHaveBeenCalledTimes(2);
    // everything decided: no bulk buttons are left
    await vi.waitFor(() => expect(screen.queryByTestId("lab-bulk")).toBeNull());
  });

  it("writes a one-sided printed range in words, in both languages", async () => {
    open();
    await screen.findByTestId("lab-bulk");
    expect(screen.getAllByText(/up to 200/).length).toBeGreaterThan(0);
    act(() => setLang("it"));
    expect(screen.getAllByText(/fino a 200/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/ - 200/)).toBeNull();
  });

  it("offers a Package | Brief switch for narrow screens", async () => {
    open();
    const sw = await screen.findByTestId("pane-switch");
    const tabs = within(sw).getAllByRole("tab");
    expect(tabs.map((x) => x.textContent)).toEqual(["Package", "Brief"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });
});
