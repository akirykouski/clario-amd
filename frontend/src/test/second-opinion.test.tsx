import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { en } from "../i18n/en";
import { it as itDict } from "../i18n/it";
import { resetHealthCache } from "../components/useHealth";
import PackagePage from "../clinic/PackagePage";
import Inbox from "../clinic/Inbox";
import SharePage from "../patient/SharePage";
import type { Brief, Care, Comparison, SharePackage } from "../types";

afterEach(() => { vi.restoreAllMocks(); resetHealthCache(); act(() => setLang("en")); });

const pkg: SharePackage = {
  package_id: "pkg_1", patient_alias: "Ash-001", created_at: "x", expires_at: "2026-12-01", period: ["2026-08-01", "2026-10-17"], note: null,
  entries: [{ id: "e1", created_at: "x", occurred_on: "2026-08-22", text: "Knees ache", mood: null, entities: [], extraction: "done" }] as unknown as SharePackage["entries"],
  entities: [{ entry_id: "e1", occurred_on: "2026-08-22", type: "symptom", quote: "Knees ache", canonical: "Arthralgia", hpo_id: "HP:0002829", negated: false, family_history: false, severity: null, reviewed: true }],
  labs: [], patterns: [], second_opinion: true, previous: null,
  tried: [{ treatment: "Ibuprofen (an NSAID), as needed", started: "2026-08-31", duration: "2 weeks", effect: "none", note: "Joint pain the same." }],
  tested: [{ test: "Urine test", date: "2026-09-17", result: "Protein present", abnormal: true }, { test: "Hand X-ray", date: "2026-09-03", result: "No erosions", abnormal: false }],
};
const brief = (finalized: boolean): Brief => ({ package_id: "pkg_1", items: [], model: null, backend: null, finalized, stats: {} });
const comparison: Comparison = {
  previous: { clinician: "GP", date: "2026-08-31", diagnosis: [{ name: "Fibromyalgia" }], conditions: [{ name: "Rheumatoid arthritis", disease_id: "OMIM:180300" }],
    accepted: ["Widespread aches during a stressful period."], rejected: ["Red cheeks after sun may be worth checking."], notes: "Most likely stress." },
  current: { conditions: [{ disease_id: "ORPHA:536", name: "Systemic lupus erythematosus", rank: 1, signal: "moderate" }], accepted: ["Malar rash after sun."], rejected: [], finalized_at: "x" },
  rows: [
    { name: "Fibromyalgia", disease_id: null, previous: "diagnosis", current_rank: null, agree: false },
    { name: "Rheumatoid arthritis", disease_id: "OMIM:180300", previous: "considered", current_rank: null, agree: false },
    { name: "Systemic lupus erythematosus", disease_id: "ORPHA:536", previous: null, current_rank: 1, agree: false },
  ],
  disagreements: 3, since_previous: ["Fever", "Urine test: Protein present"],
};

function renderPackage(finalized: boolean) {
  vi.spyOn(api, "gpu").mockResolvedValue(null);
  vi.spyOn(api, "package").mockResolvedValue(pkg);
  vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_1", patient_alias: "Ash-001", period: pkg.period, received_at: "x", expires_at: "x", entities: 1, brief_state: finalized ? "final" : "none", second_opinion: true }]);
  vi.spyOn(api, "brief").mockResolvedValue(brief(finalized));
  vi.spyOn(api, "decisions").mockResolvedValue({ terms: {}, answers: [] });
  vi.spyOn(api, "termSystems").mockResolvedValue({});
  vi.spyOn(api, "ddx").mockResolvedValue({ conditions: [], question: null, answers: [], n_terms: 0, note: "" });
  vi.spyOn(api, "overview").mockRejectedValue(new Error("none"));
  return render(<MemoryRouter initialEntries={["/p/pkg_1"]}><Routes><Route path="/p/:id" element={<PackagePage />} /></Routes></MemoryRouter>);
}

describe("clinic: second opinion", () => {
  it("says the previous conclusions are hidden and shows what was already tried and tested", async () => {
    const cmp = vi.spyOn(api, "compare").mockResolvedValue(comparison);
    renderPackage(false);
    expect(await screen.findByTestId("so-banner")).toHaveTextContent("Second opinion: the previous doctor's conclusions are hidden so they don't influence you.");
    const tried = screen.getByTestId("so-tried-row");
    expect(tried).toHaveTextContent("Ibuprofen (an NSAID), as needed");
    expect(tried).toHaveTextContent("2 weeks");
    expect(tried).toHaveTextContent("No effect");
    expect(screen.getAllByTestId("so-tested-row")[0]).toHaveTextContent("Urine testProtein present");
    const button = within(screen.getByTestId("so-compare")).getByRole("button", { name: "Compare with the previous opinion" });
    expect(button).toBeDisabled();
    expect(screen.getByTestId("so-compare")).toHaveTextContent("Opens after you finalize your brief");
    expect(document.body.textContent).not.toMatch(/fibromyalg/i);
    expect(cmp).not.toHaveBeenCalled();
  });

  it("after the brief is final, reveals both opinions side by side with the disagreements marked", async () => {
    const cmp = vi.spyOn(api, "compare").mockResolvedValue(comparison);
    renderPackage(true);
    const box = await screen.findByTestId("so-compare");
    const button = within(box).getByRole("button", { name: "Compare with the previous opinion" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(cmp).toHaveBeenCalledWith("pkg_1", "en"));
    expect(await screen.findByTestId("so-disagree")).toHaveTextContent("3 points where the two opinions differ");
    const rows = screen.getAllByTestId("so-row");
    expect(rows[0]).toHaveTextContent("Fibromyalgia");
    expect(rows[0]).toHaveTextContent("Diagnosis");
    expect(rows[0]).toHaveAttribute("data-agree", "no");
    expect(rows[2]).toHaveTextContent("#1 to consider");
    expect(rows[2]).toHaveTextContent("Differs");
    expect(screen.getByTestId("so-previous")).toHaveTextContent("Most likely stress.");
    expect(screen.getByTestId("so-previous")).toHaveTextContent("Red cheeks after sun may be worth checking.");
    expect(screen.getByTestId("so-yours")).toHaveTextContent("Malar rash after sun.");
    expect(screen.getByTestId("so-after")).toHaveTextContent("Fever, Urine test: Protein present");
  });

  it("marks a second opinion in the inbox", async () => {
    vi.spyOn(api, "clinicMetrics").mockResolvedValue({ briefs: [], totals: { accepted: 0, edited: 0, rejected: 0 }, finalized: 0, timed: 0, mean_review_seconds: null });
    vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_1", patient_alias: "Ash-001", period: pkg.period, received_at: "x", expires_at: "x", entities: 1, brief_state: "none", second_opinion: true }]);
    render(<MemoryRouter><Inbox /></MemoryRouter>);
    expect(await screen.findByTestId("inbox-second")).toHaveTextContent("Second opinion");
  });

  it("has the clinic strings in Italian", () => {
    expect(itDict["so.banner"]).toMatch(/Secondo parere/);
    expect(itDict["so.compare"]).toBe("Confronta con il parere precedente");
    expect(en["so.compare"]).toBe("Compare with the previous opinion");
  });
});

const care: Care = {
  tried: [{ treatment: "Ibuprofen (an NSAID), as needed", started: "2026-08-31", duration: "2 weeks", effect: "none" }],
  tested: [{ test: "Urine test", date: "2026-09-17", result: "Protein present", abnormal: true }],
  previous: { clinician: "GP", date: "2026-08-31" },
};

describe("patient: get a second opinion", () => {
  it("lists what was already tried, and sends a second-opinion package", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, mode: "patient", llm: {}, clinic_url: null });
    vi.spyOn(api, "profile").mockResolvedValue({});
    vi.spyOn(api, "saveProfile").mockResolvedValue({});
    vi.spyOn(api, "care").mockResolvedValue(care);
    vi.spyOn(api, "clinicKey").mockResolvedValue({ public_key: "k", fingerprint: "AAAA BBBB", clinic_name: "Second clinic" });
    const share = vi.spyOn(api, "share").mockResolvedValue({ package_id: "pkg_2", clinic_url: "u", expires_at: "2026-10-20", qr_payload: "x", entities: 3, entries: 2, second_opinion: true });
    render(<MemoryRouter><SharePage /></MemoryRouter>);
    const list = await screen.findByTestId("share-care");
    expect(list).toHaveTextContent("Ibuprofen (an NSAID), as needed, 2 weeks: No effect");
    expect(list).toHaveTextContent("Urine test: Protein present");
    fireEvent.click(screen.getByRole("checkbox", { name: "Get a second opinion" }));
    expect(screen.getByTestId("share-second-previous")).toHaveTextContent("On file: an earlier opinion (GP,");
    // the patient screens never name a condition: the previous doctor's conclusions are not even fetched
    expect(document.body.textContent).not.toMatch(/fibromyalg|diagnos/i);
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    const send = await screen.findByRole("button", { name: "Send for a second opinion" });
    fireEvent.click(send);
    await waitFor(() => expect(share).toHaveBeenCalled());
    expect(share.mock.calls[0][0]).toMatchObject({ second_opinion: true });
    expect(await screen.findByTestId("share-sent-second")).toHaveTextContent("Sent for a second opinion.");
  });

  it("sends an ordinary share unless the box is ticked", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, mode: "patient", llm: {}, clinic_url: null });
    vi.spyOn(api, "profile").mockResolvedValue({});
    vi.spyOn(api, "saveProfile").mockResolvedValue({});
    vi.spyOn(api, "care").mockResolvedValue({ tried: [], tested: [], previous: null });
    vi.spyOn(api, "clinicKey").mockResolvedValue({ public_key: "k", fingerprint: "AAAA", clinic_name: "Clinic" });
    const share = vi.spyOn(api, "share").mockResolvedValue({ package_id: "pkg_3", clinic_url: "u", expires_at: "2026-10-20", qr_payload: "x", entities: 3, entries: 2 });
    render(<MemoryRouter><SharePage /></MemoryRouter>);
    expect(screen.queryByTestId("share-care")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    fireEvent.click(await screen.findByRole("button", { name: "Send to clinic" }));
    await waitFor(() => expect(share).toHaveBeenCalled());
    expect(share.mock.calls[0][0]).toMatchObject({ second_opinion: false });
    expect(screen.queryByTestId("share-sent-second")).toBeNull();
  });
});
