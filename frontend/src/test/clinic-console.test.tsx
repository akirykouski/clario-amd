import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { BriefPanel } from "../clinic/BriefPanel";
import PackagePage from "../clinic/PackagePage";
import type { Brief, BriefEditorItem, BriefItem, BriefWarning, SharedLab, SharePackage } from "../types";

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
  const items: BriefEditorItem[] = [
    { id: "s1", section: "summary", text: "Joint pain and rash over five weeks.", cites: ["e2"], origin: "ai" },
    { id: "t1", section: "timeline", text: "20 Sep: fatigue first noted.", cites: ["e2"], origin: "ai" },
    { id: "lab", section: "labs", text: "CRP: 12 mg/L, high", cites: [], origin: "document", rows: [
      { test: "CRP", value: "12 mg/L", flag: "high", abnormal: true, date: "2026-09-15", page: 2, range: "up to 5", corrected: false }] },
  ];
  const sections = (["summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"] as const).map((key) => ({ key, title: key.toUpperCase() }));
  const citation = { kind: "citation" as const, section: "timeline", line: "20 Sep: fatigue first noted. [20 Sept]", item: 1, message: 'Names "fatigue", which none of the cited entries records.' };
  const textOf = (warnings: BriefWarning[]) => ({ text: "x", items, sections, warnings, lang: "en" as const, signed: false });

  it("opens the draft as a PDF marked as an unreviewed AI draft", () => {
    renderPanel([ai("a")]);
    // the page is a PNG of the same PDF (Chrome's embedded viewer is dark); clicking it opens the PDF
    const page = screen.getByAltText("Brief PDF");
    expect(page.getAttribute("src")).toMatch(/^\/api\/inbox\/pkg_1\/brief\.png\?v=\d+$/);
    const pdf = page.getAttribute("src")!.replace("brief.png", "brief.pdf");
    expect(page.closest("a")).toHaveAttribute("href", pdf);
    expect(screen.getByTestId("draft-badge")).toHaveTextContent("AI draft, not reviewed");
    expect(screen.getByRole("link", { name: "Open PDF" })).toHaveAttribute("href", pdf);
    expect(screen.queryByRole("button", { name: /^Accept$/ })).toBeNull();  // no per-line review any more
  });

  it("Edit and sign shows one card per section, the warning on its line, labs as a table; flagged lines and unchecked labs block signing", async () => {
    const text = vi.spyOn(api, "briefText").mockResolvedValue(textOf([citation, { kind: "labs_pending", message: "3 lab readings" }]));
    renderPanel([ai("a")]);
    fireEvent.click(screen.getByRole("button", { name: "Edit and sign" }));
    await screen.findByTestId("brief-editor");
    expect(text).toHaveBeenCalledWith("pkg_1", undefined);
    expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(sections.map((s) => s.title));
    const flagged = within(screen.getByTestId("brief-section-timeline")).getByTestId("brief-line");
    expect(flagged).toHaveAttribute("data-flagged", "true");
    expect(within(flagged).getByTestId("brief-warning")).toHaveTextContent('Names "fatigue"');
    expect(within(flagged).getByText("AI")).toBeInTheDocument();
    expect(within(screen.getByTestId("brief-labs")).getByRole("table")).toHaveTextContent("CRP12 mg/LHigh");
    fireEvent.mouseOver(within(flagged).getByRole("button", { name: /Diary note/ }));
    expect(within(flagged).getByRole("tooltip")).toHaveTextContent("Knees");
    expect(screen.getByTestId("attention")).toHaveTextContent("1 line needs attention");
    fireEvent.change(screen.getByLabelText("Reviewed and signed by"), { target: { value: "Dr Rossi" } });
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();
    expect(screen.getByTestId("labs-pending")).toHaveTextContent("3");
  });

  it("edits inline, removes with undo, adds a line, keeps a flagged line anyway, and signs the cards with name and time", async () => {
    const clean = { ...pkg, labs: [] };
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    vi.spyOn(api, "briefText").mockResolvedValue(textOf([citation]));
    const check = vi.spyOn(api, "checkBrief").mockImplementation(async (_id, lines) =>
      ({ warnings: lines.some((l) => l.id === "t1") ? [{ ...citation, item: lines.findIndex((l) => l.id === "t1") }] : [] }));
    const signed: Brief = { ...briefOf([ai("a", { review: "accepted" })]), finalized: true, signed_by: "Dr Rossi", finalized_at: "2026-10-17T10:00:00Z", text: "x" };
    const sign = vi.spyOn(api, "signBrief").mockResolvedValue(signed);
    const setBrief = vi.fn();
    render(<MemoryRouter><BriefPanel pkg={clean} brief={briefOf([ai("a")])} setBrief={setBrief} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Edit and sign" }));
    await screen.findByTestId("brief-editor");
    fireEvent.change(screen.getByLabelText("Reviewed and signed by"), { target: { value: "  Dr Rossi " } });
    // edit the summary line in place
    const summary = screen.getByTestId("brief-section-summary");
    fireEvent.click(within(summary).getByRole("button", { name: "Edit line" }));
    const box = within(summary).getByLabelText("Edit line");
    fireEvent.change(box, { target: { value: "Joint pain and rash over five weeks, worse in the sun." } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(within(summary).getByText("edited")).toBeInTheDocument();
    // remove the flagged line, then undo: it needs attention again; keep it anyway
    const timeline = screen.getByTestId("brief-section-timeline");
    fireEvent.click(within(timeline).getAllByRole("button", { name: "Remove" })[0]);
    expect(within(timeline).getByTestId("line-removed")).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.getByTestId("attention")).toHaveTextContent("Code checks pass."), { timeout: 2000 });
    fireEvent.click(within(timeline).getByRole("button", { name: "Undo" }));
    await vi.waitFor(() => expect(screen.getByTestId("attention")).toHaveTextContent("1 line needs attention"), { timeout: 2000 });
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();
    fireEvent.click(within(timeline).getByRole("button", { name: "Keep anyway" }));
    // add a line of one's own
    const patterns = screen.getByTestId("brief-section-patterns");
    fireEvent.click(within(patterns).getByRole("button", { name: "Add line" }));
    const own = within(patterns).getByLabelText("Edit line");
    fireEvent.change(own, { target: { value: "Rash after sun may be worth discussing." } });
    fireEvent.keyDown(own, { key: "Enter" });
    await vi.waitFor(() => expect(check).toHaveBeenLastCalledWith("pkg_1", expect.arrayContaining([{ section: "patterns", text: "Rash after sun may be worth discussing.", cites: [] }]), undefined), { timeout: 2000 });
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "Sign" })).toBeEnabled(), { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: "Sign" }));
    await vi.waitFor(() => expect(sign).toHaveBeenCalled());
    const [pid, body] = sign.mock.calls[0];
    expect(pid).toBe("pkg_1");
    expect(body).toMatchObject({ clinician: "Dr Rossi", specialty: undefined, items: [
      { id: "s1", section: "summary", text: "Joint pain and rash over five weeks, worse in the sun.", cites: ["e2"] },
      { id: "t1", section: "timeline", text: "20 Sep: fatigue first noted.", cites: ["e2"] },
      { id: "lab", section: "labs", text: "CRP: 12 mg/L, high", cites: [] },
      { section: "patterns", text: "Rash after sun may be worth discussing.", cites: [] },
    ] });
    expect(body.seconds).toBeGreaterThanOrEqual(0);
    await vi.waitFor(() => expect(setBrief).toHaveBeenCalledWith(signed));
  });

  it("speaks Italian in the editor", async () => {
    act(() => setLang("it"));
    vi.spyOn(api, "briefText").mockResolvedValue(textOf([citation]));
    renderPanel([ai("a")]);
    fireEvent.click(screen.getByRole("button", { name: "Modifica e firma" }));
    await screen.findByTestId("brief-editor");
    expect(screen.getByTestId("attention")).toHaveTextContent("1 riga da controllare");
    expect(screen.getAllByText("IA").length).toBe(2);
    expect(screen.getByRole("button", { name: "Tieni comunque" })).toBeInTheDocument();
    expect(screen.getByLabelText("Rivisto e firmato da")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anteprima PDF" })).toBeInTheDocument();
  });

  it("a precomputed demo draft says so in the chips, with the original speed, and Regenerate live calls the model", async () => {
    const pre: Brief = { ...briefOf([ai("a")]), model: "Gemma-4-31B-IT", backend: "amd-token-factory", precomputed: "2026-10-17",
      stats: { tokens_per_s: 17.6, latency_ms: 52462.8, tokens: 925 }, pseudonymized: true };
    const startBrief = vi.spyOn(api, "startBrief").mockResolvedValue({ run_id: "r1", precomputed: false });
    vi.spyOn(api, "runEventsUrl").mockReturnValue("/api/runs/r1/events");
    vi.stubGlobal("EventSource", class { onmessage = null; onerror = null; addEventListener() {} close() {} });
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={pre} setBrief={vi.fn()} /></MemoryRouter>);
    expect(screen.getByTestId("run-chip-model")).toHaveTextContent("precomputed · Gemma 4 31B · AMD Token Factory · 17 Oct 2026");
    expect(screen.getByTestId("run-chips")).toHaveTextContent("17.6 tokens/s");
    expect(screen.getByTestId("run-chips")).toHaveTextContent("52.5 s");
    expect(screen.queryByRole("button", { name: "Generate again" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Regenerate live" }));
    await vi.waitFor(() => expect(startBrief).toHaveBeenCalledWith("pkg_1", "en", true));
    act(() => setLang("it"));
    expect(screen.getByTestId("run-chip-model")).toHaveTextContent("precalcolato · Gemma 4 31B · AMD Token Factory");
    vi.unstubAllGlobals();
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
