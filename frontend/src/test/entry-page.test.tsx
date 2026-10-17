import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { clinicFlagNote, flagNote } from "../lib";
import EntryPage from "../patient/EntryPage";
import type { Entity, Entry } from "../types";

afterEach(() => { vi.restoreAllMocks(); setLang("en"); });

const ent = (o: Partial<Entity>): Entity => ({
  id: "x", entry_id: "e1", type: "symptom", quote: "q", canonical: "Fatigue", hpo_id: null, hpo_label: null, negated: false,
  severity: null, family_history: false, onset_hint: null, confidence: null, review: "auto", flags: [], model: null, ...o,
});
const entry = (entities: Entity[]): Entry => ({
  id: "e1", created_at: "x", occurred_on: "2026-10-17", mood: null, extraction: "done", entities,
  text: "My knees ache in the morning and my cheeks went red after the sun, no fever",
});

function mount(e: Entry) {
  vi.spyOn(api, "entry").mockResolvedValue(e);
  return render(<MemoryRouter initialEntries={["/entry/e1"]}><Routes><Route path="/entry/:id" element={<EntryPage />} /></Routes></MemoryRouter>);
}

describe("patient entry page", () => {
  it("shows an unsure term with only the plain line and the actions, never the technical reason", async () => {
    mount(entry([ent({ id: "u1", quote: "cheeks went red", canonical: "Facial erythema", review: "needs_review", flags: ["hpo_dropped"] })]));
    const card = (await screen.findByText("cheeks went red", { selector: "li mark" })).closest("li") as HTMLElement;
    expect(card).toHaveTextContent("We are not sure we read this right.");
    expect(card).not.toHaveTextContent(/medical term list/i);
    expect(card).not.toHaveTextContent(/removed the medical term/i);
    expect(card).not.toHaveTextContent(/hpo/i);
    for (const name of [/yes/i, /not right/i, /fix term/i]) expect(within(card).getByRole("button", { name })).toBeInTheDocument();
  });

  it("does not show raw flag names or a missing-code line on a settled term", async () => {
    mount(entry([ent({ id: "a1", quote: "knees ache", canonical: "Knee pain", flags: ["no_hpo", "onset_dropped", "fixed_by_patient"] })]));
    const card = (await screen.findByText("knees ache", { selector: "li mark" })).closest("li") as HTMLElement;
    expect(card).not.toHaveTextContent(/no hpo|onset dropped|fixed by patient|medical term list/i);
    expect(card).not.toHaveTextContent("Since:");
  });

  it("keeps the plain notes and a real onset", async () => {
    mount(entry([ent({ id: "n1", quote: "fever", canonical: "Fever", negated: true, flags: ["negation_from_text"], onset_hint: "since Tuesday" })]));
    const card = (await screen.findByText("fever", { selector: "li mark" })).closest("li") as HTMLElement;
    expect(card).toHaveTextContent("Marked as absent because your words say you do not have it.");
    expect(card).toHaveTextContent("Since: since Tuesday");
  });

  it("flag notes: plain words for the patient, the technical reason for the clinic, in both languages", () => {
    expect(flagNote("hpo_dropped")).toBeNull();
    expect(flagNote("no_hpo")).toBeNull();
    expect(flagNote("onset_dropped")).toBeNull();
    expect(clinicFlagNote(["hpo_dropped"])).toMatch(/did not match the patient's words/);
    expect(clinicFlagNote(["no_hpo"])).toBe("No matching HPO term");
    expect(clinicFlagNote(["negation_from_text"])).toBeNull();
    setLang("it");
    expect(flagNote("negation_from_text")).toMatch(/assente/);
    expect(clinicFlagNote(["hpo_dropped"])).toMatch(/non corrispondeva alle parole del paziente/);
  });
});
