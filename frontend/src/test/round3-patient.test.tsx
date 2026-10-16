import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { prettyUnit } from "../lib";
import { setLang, patientTermLine } from "../i18n";
import { SignalPill } from "../components/ui";
import PatternsPage from "../patient/PatternsPage";
import { EntryCard } from "../patient/EntryCard";
import type { Entry } from "../types";

afterEach(() => { vi.restoreAllMocks(); setLang("en"); });

describe("units", () => {
  it("prints superscripts and micro signs", () => {
    expect(prettyUnit("10^3/uL")).toBe("10³/µL");
    expect(prettyUnit("ug/dL")).toBe("µg/dL");
    expect(prettyUnit("mg/dL")).toBe("mg/dL");
    expect(prettyUnit("U/L")).toBe("U/L");
  });
});

describe("patient term lines never show an HPO code or an English label in Italian", () => {
  it("en shows the label, it only a shipped Italian name", () => {
    expect(patientTermLine("HP:0002315", "Headache", "Pain in the head")).toBe("Headache");
    expect(patientTermLine("HP:0002315", "Headache", "Headache")).toBeNull();
    setLang("it");
    expect(patientTermLine("HP:0002315", "Headache", "Dolore")).toBe("Mal di testa");
    expect(patientTermLine("HP:9999999", "Generalized morning stiffness", "Rigidità")).toBeNull();
  });
});

describe("signal pill", () => {
  it("opens a plain explainer that is not a diagnosis", () => {
    render(<SignalPill signal="strong" />);
    fireEvent.click(screen.getByRole("button", { name: /strong signal/i }));
    expect(screen.getByRole("note").textContent).toMatch(/not a diagnosis/i);
    expect(screen.getByRole("note").textContent).not.toMatch(/%/);
  });
});

describe("patterns early state", () => {
  it("points at terms waiting for an OK", async () => {
    vi.spyOn(api, "patterns").mockResolvedValue({ patterns: [], confirmed_terms: 0, to_check: 7, note: "" });
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/7 terms in your notes wait for your OK/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /check them/i })).toHaveAttribute("href", "/review");
  });
});

describe("all correct", () => {
  it("confirms the auto terms of one note", async () => {
    const ent = (review: "auto" | "confirmed") => ({
      id: "x1", entry_id: "e1", type: "symptom", quote: "knees ache", canonical: "Arthralgia", hpo_id: "HP:0002829", hpo_label: "Arthralgia",
      negated: false, severity: null, onset_hint: null, family_history: false, confidence: 0.9, review, flags: [], model: "m",
    });
    const entry = { id: "e1", created_at: "2026-03-01T00:00:00Z", occurred_on: "2026-03-01", text: "Knees ache", mood: null, extraction: "done", entities: [ent("auto")] } as unknown as Entry;
    const done = { ...entry, entities: [ent("confirmed")] } as unknown as Entry;
    const spy = vi.spyOn(api, "confirmAllInEntry").mockResolvedValue({ confirmed: 1, entry: done });
    render(<MemoryRouter><EntryCard initial={entry} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "All correct" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("e1"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "All correct" })).toBeNull());
  });
});
