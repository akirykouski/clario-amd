import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { pastWhen } from "../lib";
import { EntryCard } from "../patient/EntryCard";
import EntryPage from "../patient/EntryPage";
import PackagePage from "../clinic/PackagePage";
import TimelinePage from "../patient/TimelinePage";
import type { Entity, Entry, PastRef, SharePackage } from "../types";

afterEach(() => { vi.restoreAllMocks(); setLang("en"); });

const FIVE: PastRef = { kind: "ago", n: 5, unit: "year", approx_date: "2021-01-01", cue: "5 years ago" };
const CHILD: PastRef = { kind: "childhood", n: null, unit: null, approx_date: null, cue: "As a child" };

const ent = (o: Partial<Entity>): Entity => ({
  id: "x", entry_id: "e1", type: "symptom", quote: "q", canonical: "Fatigue", hpo_id: null, hpo_label: null, negated: false,
  severity: null, family_history: false, onset_hint: null, confidence: null, review: "auto", flags: [], model: null, ...o,
});
const entry = (entities: Entity[]): Entry => ({
  id: "e1", created_at: "x", occurred_on: "2026-10-12", mood: null, extraction: "done", entities,
  text: "I remembered I had knee surgery 5 years ago. My knees ache today.",
});

describe("past history", () => {
  it("patient entry card: the past term reads 'Past: knee surgery (about 5 years ago)'; the current one has no mark", () => {
    render(<MemoryRouter><EntryCard initial={entry([
      ent({ id: "p1", quote: "knee surgery", canonical: "Knee surgery", type: "finding", past: FIVE, flags: ["past_from_text"] }),
      ent({ id: "c1", quote: "knees ache", canonical: "Arthralgia", hpo_id: "HP:0002829" }),
    ])} /></MemoryRouter>);
    const chips = screen.getAllByTestId("past-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent("Past: Knee surgery (about 5 years ago)");
    expect(screen.getByText("Arthralgia")).not.toHaveTextContent("Past");
  });

  it("patient entry card in Italian", () => {
    setLang("it");
    render(<MemoryRouter><EntryCard initial={{ ...entry([ent({ id: "p1", quote: "l'asma", canonical: "Asthma", hpo_id: "HP:0002099", past: CHILD })]),
      text: "Da bambina avevo l'asma." }} /></MemoryRouter>);
    expect(screen.getByTestId("past-chip")).toHaveTextContent(/^In passato: .+ \(nell'infanzia\)$/);
  });

  it("patient entry page says it is from the past and shows no 'Since:'", async () => {
    vi.spyOn(api, "entry").mockResolvedValue(entry([ent({ id: "p1", quote: "knee surgery", canonical: "Knee surgery", past: FIVE })]));
    render(<MemoryRouter initialEntries={["/entry/e1"]}><Routes><Route path="/entry/:id" element={<EntryPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByTestId("past-line")).toHaveTextContent("From the past, about 5 years ago. Not counted as something happening now.");
    expect(screen.queryByText(/Since:/)).toBeNull();
  });

  it("wording: years, months, a year, an explicit year, childhood, and the clinician's approximate date", () => {
    expect(pastWhen(FIVE)).toBe("about 5 years ago");
    expect(pastWhen(FIVE, true)).toBe("about 5 years ago (around 2021)");
    expect(pastWhen({ ...FIVE, n: 1 })).toBe("about a year ago");
    expect(pastWhen({ ...FIVE, n: 3, unit: "month", approx_date: "2026-07-01" })).toBe("about 3 months ago");
    expect(pastWhen({ ...FIVE, n: null, approx_date: null })).toBe("some years ago");
    expect(pastWhen({ kind: "year", n: 2019, unit: null, approx_date: "2019-01-01", cue: "in 2019" })).toBe("in 2019");
    expect(pastWhen(CHILD)).toBe("in childhood");
    setLang("it");
    expect(pastWhen(FIVE, true)).toBe("circa 5 anni fa (intorno al 2021)");
    expect(pastWhen(CHILD)).toBe("nell'infanzia");
  });

  it("clinic: past history line in the glance and the details, out of the term counts and the heat map", async () => {
    const shared = (canonical: string, hpo: string | null, extra: object = {}) => ({
      id: canonical, entry_id: "e1", occurred_on: "2026-10-12", type: "symptom" as const, quote: canonical.toLowerCase(), canonical,
      hpo_id: hpo, negated: false, family_history: false, severity: null, reviewed: true, ...extra,
    });
    const pkg: SharePackage = {
      package_id: "pkg_p", patient_alias: "Ash-002", created_at: "2026-10-13T00:00:00Z", expires_at: "2026-10-16T00:00:00Z",
      period: ["2026-10-01", "2026-10-13"], note: null, labs: [], patterns: [],
      entries: [{ id: "e1", created_at: "x", occurred_on: "2026-10-12", text: "I remembered I had knee surgery 5 years ago. As a child I had asthma. My knees ache today.", mood: null, extraction: "done", entities: [] }],
      entities: [shared("Knee surgery", null, { type: "finding", past: FIVE }), shared("Asthma", "HP:0002099", { past: CHILD }),
                 shared("Arthralgia", "HP:0002829")],
    };
    vi.spyOn(api, "package").mockResolvedValue(pkg);
    vi.spyOn(api, "inbox").mockResolvedValue([]);
    vi.spyOn(api, "decisions").mockResolvedValue({ terms: {}, answers: [] });
    const systems = vi.spyOn(api, "termSystems").mockResolvedValue({ "HP:0002829": "joints" });
    vi.spyOn(api, "ddx").mockResolvedValue({ conditions: [], question: null, answers: [], n_terms: 1, note: "" });
    vi.spyOn(api, "overview").mockResolvedValue({
      profile: null, notes: 1, weeks: 1, severe: [], labs_off: [], family: [], denied: [], mood: null, asks: [], new: ["joint pain"],
      frequent: [{ label: "joint pain", count: 1, recent_count: 1, first: "2026-10-12", last: "2026-10-12", max_severity: null }],
      recent: [{ label: "joint pain", count: 1, recent_count: 1, first: "2026-10-12", last: "2026-10-12", max_severity: null }],
      first: { label: "joint pain", count: 1, recent_count: 1, first: "2026-10-12", last: "2026-10-12", max_severity: null },
      past: [{ label: "asthma", past: CHILD, when: "in childhood", entry_id: "e1", date: "2026-10-12", quote: "asthma" },
             { label: "knee surgery", past: FIVE, when: "about 5 years ago (around 2021)", entry_id: "e1", date: "2026-10-12", quote: "knee surgery" }],
    });
    render(<MemoryRouter initialEntries={["/p/pkg_p"]}><Routes><Route path="/p/:id" element={<PackagePage />} /></Routes></MemoryRouter>);
    expect(await screen.findByTestId("ov-past")).toHaveTextContent("asthma, in childhood; knee surgery, about 5 years ago (around 2021)");
    expect(screen.getByTestId("pkg-counts")).toHaveTextContent("1 mentions of 1 terms");  // past terms are not current terms
    const past = screen.getByTestId("pkg-past");
    expect(past).toHaveTextContent("Past history (mentioned by the patient)");
    expect(past).toHaveTextContent("Knee surgery about 5 years ago (around 2021)");
    expect(past).toHaveTextContent("Asthma HP:0002099 in childhood");
    const terms = within(screen.getByTestId("pkg-details")).getByRole("heading", { name: "All recorded terms" }).parentElement as HTMLElement;
    expect(within(terms).queryByText("Asthma")).toBeNull();
    expect(within(terms).getByText("Arthralgia")).toBeInTheDocument();
    // the heat map asks for systems of the current terms only: asthma never lights up this week
    await screen.findByTestId("pkg-heat");
    expect(systems).toHaveBeenCalledWith(["HP:0002829"]);
    expect(screen.getByTestId("pkg-heat")).not.toHaveTextContent(/asthma|knee surgery/i);
  });

  it("patient timeline: a 'From your past' list, oldest first, rejected and negated left out; never in the heat map", async () => {
    const e = { ...entry([
      ent({ id: "p1", quote: "knee surgery", canonical: "Knee surgery", type: "finding", past: FIVE }),
      ent({ id: "p2", quote: "asthma", canonical: "Asthma", hpo_id: "HP:0002099", past: CHILD }),
      ent({ id: "p3", quote: "fracture", canonical: "Fracture", past: FIVE, review: "rejected" }),
      ent({ id: "c1", quote: "knees ache", canonical: "Arthralgia", hpo_id: "HP:0002829" }),
    ]) };
    vi.spyOn(api, "timeline").mockResolvedValue({
      days: [{ date: "2026-10-12", entries: [e], terms: [{ hpo_id: "HP:0002829", label: "Arthralgia" }] }],
      terms: [{ hpo_id: "HP:0002829", label: "Joint pain", clinical: "Arthralgia", count: 1, entry_ids: ["e1"], first_seen: "2026-10-12", last_seen: "2026-10-12" }],
      systems: { "HP:0002829": "joints" },
    } as never);
    render(<MemoryRouter><TimelinePage /></MemoryRouter>);
    const past = await screen.findByTestId("timeline-past");
    const rows = within(past).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows).toEqual(["Asthma in childhood", "Knee surgery about 5 years ago"]);
    expect(within(past).getByRole("link", { name: "Knee surgery" })).toHaveAttribute("href", "/entry/e1");
  });
});
