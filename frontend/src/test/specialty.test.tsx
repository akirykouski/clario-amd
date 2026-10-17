import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { BriefPanel } from "../clinic/BriefPanel";
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
describe("specialty focus", () => {
  it("the selector picks what the server puts into the draft PDF and the editor text", async () => {
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    const text = vi.spyOn(api, "briefText").mockResolvedValue({ text: "## Summary\n- x\n", warnings: [], lang: "en", signed: false });
    const brief: Brief = { package_id: "pkg_1", items, model: null, backend: null, finalized: false, stats: {} };
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={brief} setBrief={vi.fn()} /></MemoryRouter>);
    const select = screen.getByLabelText("Specialty") as HTMLSelectElement;
    expect(select.value).toBe("general");
    expect(screen.getByTitle("Brief PDF").getAttribute("src")).not.toContain("specialty");
    fireEvent.change(select, { target: { value: "rheumatology" } });
    expect(screen.getByTitle("Brief PDF").getAttribute("src")).toContain("specialty=rheumatology");
    fireEvent.click(screen.getByRole("button", { name: "Edit and sign" }));
    await screen.findByLabelText("Brief text");
    expect(text).toHaveBeenCalledWith("pkg_1", "rheumatology");
    expect(screen.getByText("Prepared for Rheumatology")).toBeInTheDocument();
    expect(screen.queryByLabelText("Specialty")).toBeNull();  // fixed while editing: the text was made for it
  });

  it("speaks Italian", () => {
    act(() => setLang("it"));
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    const brief: Brief = { package_id: "pkg_1", items, model: null, backend: null, finalized: false, stats: {} };
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={brief} setBrief={vi.fn()} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Specialità"), { target: { value: "nephrology" } });
    expect(screen.getByRole("option", { name: "Nefrologia" })).toBeInTheDocument();
    expect(screen.getByTitle("PDF del riepilogo").getAttribute("src")).toContain("specialty=nephrology");
    expect(screen.getByRole("button", { name: "Modifica e firma" })).toBeInTheDocument();
  });
});
