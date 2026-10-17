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

describe("brief: generate, PDF, edit and sign", () => {
  const draft = "## Summary\n- line a [20 Sept]\n\n## Timeline\n- 20 Sep: fatigue first noted. [20 Sept]\n";
  const citation = { kind: "citation" as const, section: "timeline", line: "20 Sep: fatigue first noted. [20 Sept]", message: 'Names "fatigue", which none of the cited entries records.' };

  it("opens the draft as a PDF marked as an unreviewed AI draft", () => {
    renderPanel([ai("a")]);
    const frame = screen.getByTitle("Brief PDF");
    expect(frame.getAttribute("src")).toMatch(/^\/api\/inbox\/pkg_1\/brief\.pdf\?v=\d+$/);
    expect(screen.getByTestId("draft-badge")).toHaveTextContent("AI draft, not reviewed");
    expect(screen.getByRole("link", { name: "Open PDF" })).toHaveAttribute("href", frame.getAttribute("src"));
    expect(screen.queryByRole("button", { name: /^Accept$/ })).toBeNull();  // no per-line review any more
  });

  it("Edit and sign shows the text with the code checks as warnings; unchecked labs block signing", async () => {
    const text = vi.spyOn(api, "briefText").mockResolvedValue({ text: draft, warnings: [citation, { kind: "labs_pending", message: "3 lab readings" }], lang: "en", signed: false });
    renderPanel([ai("a")]);
    fireEvent.click(screen.getByRole("button", { name: "Edit and sign" }));
    const box = await screen.findByLabelText("Brief text") as HTMLTextAreaElement;
    expect(text).toHaveBeenCalledWith("pkg_1", undefined);
    expect(box.value).toBe(draft);
    expect(screen.getByTestId("brief-warning")).toHaveTextContent('Names "fatigue"');
    fireEvent.change(screen.getByLabelText(/Your name/), { target: { value: "Dr Rossi" } });
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();
    expect(screen.getByTestId("labs-pending")).toHaveTextContent("3");
  });

  it("checks the text again as the clinician types, and signs with name and time", async () => {
    const clean = { ...pkg, labs: [] };
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    vi.spyOn(api, "briefText").mockResolvedValue({ text: draft, warnings: [citation], lang: "en", signed: false });
    const check = vi.spyOn(api, "checkBrief").mockResolvedValue({ warnings: [] });
    const signed: Brief = { ...briefOf([ai("a", { review: "accepted" })]), finalized: true, signed_by: "Dr Rossi", finalized_at: "2026-10-17T10:00:00Z", text: "x" };
    const sign = vi.spyOn(api, "signBrief").mockResolvedValue(signed);
    const setBrief = vi.fn();
    render(<MemoryRouter><BriefPanel pkg={clean} brief={briefOf([ai("a")])} setBrief={setBrief} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Edit and sign" }));
    const box = await screen.findByLabelText("Brief text");
    const edited = draft.replace("- 20 Sep: fatigue first noted. [20 Sept]\n", "");
    fireEvent.change(box, { target: { value: edited } });
    await vi.waitFor(() => expect(check).toHaveBeenCalledWith("pkg_1", edited, undefined), { timeout: 2000 });
    await vi.waitFor(() => expect(screen.getByText("No warnings from the code checks.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();  // no name yet
    fireEvent.change(screen.getByLabelText(/Your name/), { target: { value: "  Dr Rossi " } });
    fireEvent.click(screen.getByRole("button", { name: "Sign" }));
    await vi.waitFor(() => expect(sign).toHaveBeenCalled());
    const [pid, body] = sign.mock.calls[0];
    expect(pid).toBe("pkg_1");
    expect(body).toMatchObject({ text: edited, clinician: "Dr Rossi", specialty: undefined });
    expect(body.seconds).toBeGreaterThanOrEqual(0);
    await vi.waitFor(() => expect(setBrief).toHaveBeenCalledWith(signed));
  });

  it("a signed brief shows who signed it and the signed PDF, in English and Italian", () => {
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    const signed: Brief = { ...briefOf([ai("a", { review: "accepted" }), ai("b", { review: "rejected" })]), finalized: true,
      signed_by: "Dr Rossi", finalized_at: "2026-10-17T10:00:00Z", review_seconds: 75, pseudonymized: true };
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={signed} setBrief={vi.fn()} /></MemoryRouter>);
    expect(screen.getByTestId("signed-by")).toHaveTextContent("Reviewed and signed by Dr Rossi, 17 Oct 2026");
    expect(screen.getByRole("link", { name: "Open signed PDF" })).toHaveAttribute("href", expect.stringMatching(/brief\.pdf\?v=/));
    expect(screen.getByTestId("decision-line")).toHaveTextContent("accepted 1 · edited 0 · rejected 1 · 1 min 15 s to sign");
    expect(screen.getByTestId("sent-pseudonymised")).toHaveTextContent("pseudonymised");
    expect(screen.queryByRole("button", { name: "Edit and sign" })).toBeNull();
    act(() => setLang("it"));
    expect(screen.getByTestId("signed-by")).toHaveTextContent("Rivisto e firmato da Dr Rossi");
    expect(screen.getByRole("link", { name: "Apri il PDF firmato" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Riepilogo per la visita" })).toBeInTheDocument();
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
