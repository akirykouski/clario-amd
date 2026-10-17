import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { BriefPanel, focusBrief } from "../clinic/BriefPanel";
import type { Brief, BriefItem, SharePackage } from "../types";

afterEach(() => { vi.restoreAllMocks(); act(() => setLang("en")); });

const pkg = {
  package_id: "pkg_1", patient_alias: "Giulia-001", created_at: "x", expires_at: "2026-12-01", period: ["2026-09-01", "2026-10-02"],
  note: null, entries: [], entities: [], labs: [], patterns: [],
} as unknown as SharePackage;
const item = (id: string, section: BriefItem["section"], specialties: BriefItem["specialties"], over: Partial<BriefItem> = {}): BriefItem =>
  ({ id, section, text: `line ${id}`, cites: [], origin: "patient", review: "accepted", specialties, ...over });
const items: BriefItem[] = [
  item("note", "summary", [], { kind: "patient_note", text: "Is the joint pain and rash connected?" }),
  item("headache", "symptoms", []),
  item("arthralgia", "symptoms", ["rheumatology"]),
  item("fatigue", "symptoms", ["rheumatology", "nephrology"]),
  item("sodium", "labs", ["nephrology"], { origin: "document" }),
  item("dsdna", "labs", ["rheumatology"], { origin: "document" }),
  item("tsh", "labs", [], { origin: "document" }),
  item("draft", "timeline", [], { origin: "ai", review: "pending" }),
  item("q", "questions", [], { origin: "ai", review: "accepted" }),
];
const ids = (f: ReturnType<typeof focusBrief>) => f.sections.flatMap((s) => s.items.map((i) => i.id));

describe("specialty focus", () => {
  it("general practice shows everything in the default order", () => {
    const f = focusBrief(items, "general");
    expect(f.hidden).toBe(0);
    expect(ids(f)).toEqual(["note", "draft", "headache", "arthralgia", "fatigue", "sodium", "dsdna", "tsh", "q"]);
  });

  it("rheumatology puts symptoms and labs first, its own lines first, and hides the rest", () => {
    const f = focusBrief(items, "rheumatology");
    expect(f.sections.map((s) => s.s).slice(0, 3)).toEqual(["summary", "symptoms", "labs"]);
    expect(ids(f)).toEqual(["note", "arthralgia", "fatigue", "dsdna", "draft", "q"]);
    expect(f.hidden).toBe(3);  // headache, sodium, tsh
  });

  it("nephrology reads labs first and never hides a line that still needs a decision", () => {
    const f = focusBrief(items, "nephrology");
    expect(f.sections.map((s) => s.s).slice(0, 2)).toEqual(["summary", "labs"]);
    expect(ids(f)).toEqual(["note", "sodium", "fatigue", "draft", "q"]);
    expect(ids(focusBrief([item("unchecked", "labs", [], { origin: "document", review: "pending" })], "nephrology"))).toEqual(["unchecked"]);
  });

  it("the selector filters the panel and Show everything goes back to general practice", () => {
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    const brief: Brief = { package_id: "pkg_1", items, model: null, backend: null, finalized: false, stats: {} };
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={brief} setBrief={vi.fn()} /></MemoryRouter>);
    const select = screen.getByLabelText("Specialty") as HTMLSelectElement;
    expect(select.value).toBe("general");
    const symptoms = () => within(screen.getByRole("region", { name: "Symptoms" }));
    expect(symptoms().getByText("line headache")).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "rheumatology" } });
    expect(symptoms().queryByText("line headache")).not.toBeInTheDocument();
    expect(symptoms().getByText("line arthralgia")).toBeInTheDocument();
    expect(screen.getByTestId("specialty-hidden")).toHaveTextContent("Rheumatology view: 3 lines hidden.");
    fireEvent.click(screen.getByRole("button", { name: "Show everything" }));
    expect(select.value).toBe("general");
    expect(symptoms().getByText("line headache")).toBeInTheDocument();
  });

  it("speaks Italian", () => {
    act(() => setLang("it"));
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    const brief: Brief = { package_id: "pkg_1", items, model: null, backend: null, finalized: false, stats: {} };
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={brief} setBrief={vi.fn()} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Specialità"), { target: { value: "nephrology" } });
    expect(screen.getByTestId("specialty-hidden")).toHaveTextContent("Vista Nefrologia: 4 righe nascoste.");
  });
});
