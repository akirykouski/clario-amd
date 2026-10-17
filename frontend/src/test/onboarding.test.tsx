import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { en } from "../i18n/en";
import { it as itDict } from "../i18n/it";
import PatientApp from "../patient/PatientApp";
import ClinicApp from "../clinic/ClinicApp";
import { Tour, PATIENT_TOUR, CLINIC_TOUR } from "../components/Tour";
import type { Health } from "../types";

afterEach(() => { vi.restoreAllMocks(); act(() => setLang("en")); });

async function renderPatient() {
  vi.spyOn(api, "vault").mockResolvedValue({ initialized: true, locked: false });
  vi.spyOn(api, "entries").mockResolvedValue([]);
  vi.spyOn(api, "privacyCounts").mockResolvedValue({} as never);
  render(<MemoryRouter><PatientApp /></MemoryRouter>);
  return screen.findByRole("button", { name: "How it works" });
}

async function renderClinic() {
  vi.spyOn(api, "clinicKey").mockResolvedValue({ public_key: "k", fingerprint: "ab:cd", clinic_name: "C" } as never);
  vi.spyOn(api, "inbox").mockResolvedValue([]);
  vi.spyOn(api, "clinicMetrics").mockResolvedValue({} as never);
  const health = { ok: true, mode: "clinic", llm: { backend: "offline-fixtures" } } as unknown as Health;
  render(<MemoryRouter><ClinicApp health={health} /></MemoryRouter>);
  return screen.findByRole("button", { name: "How it works" });
}

describe("onboarding tour, patient app", () => {
  it("is not shown on load", async () => {
    await renderPatient();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens from ?, goes next and back, and closes with Done", async () => {
    fireEvent.click(await renderPatient());
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Step 1 of 5");
    expect(dialog).toHaveTextContent(en["tour.p1.title"]);
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent("Step 2 of 5");
    expect(dialog).toHaveTextContent(en["tour.p2.title"]);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(dialog).toHaveTextContent("Step 1 of 5");
    for (let n = 0; n < 4; n++) fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent("Step 5 of 5");
    expect(dialog).toHaveTextContent(en["tour.p5.title"]);
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape and gives focus back to ?", async () => {
    const open = await renderPatient();
    fireEvent.click(open);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(open).toHaveFocus();
  });

  it("keeps Tab inside the card", async () => {
    fireEvent.click(await renderPatient());
    const close = screen.getByRole("button", { name: "Close" });
    const next = screen.getByRole("button", { name: "Next" });
    next.focus();
    fireEvent.keyDown(next, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(next).toHaveFocus();
  });

  it("speaks Italian", async () => {
    act(() => setLang("it"));
    vi.spyOn(api, "vault").mockResolvedValue({ initialized: true, locked: false });
    vi.spyOn(api, "entries").mockResolvedValue([]);
    vi.spyOn(api, "privacyCounts").mockResolvedValue({} as never);
    render(<MemoryRouter><PatientApp /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Come funziona" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Passo 1 di 5");
    expect(screen.getByRole("dialog")).toHaveTextContent(itDict["tour.p1.title"]);
    fireEvent.click(screen.getByRole("button", { name: "Avanti" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(itDict["tour.p2.title"]);
  });
});

describe("onboarding tour, clinic console", () => {
  it("opens from ?, goes next and back, and closes", async () => {
    const open = await renderClinic();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(open);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Step 1 of 5");
    expect(dialog).toHaveTextContent(en["tour.c1.title"]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent(en["tour.c3.title"]);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(dialog).toHaveTextContent(en["tour.c2.title"]);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("says decision support, not a diagnosis, in both languages", () => {
    expect(en["tour.c4.body"]).toMatch(/not a diagnosis/);
    expect(itDict["tour.c4.body"]).toMatch(/non una diagnosi/);
  });
});

describe("tour spotlight", () => {
  it("rings the visible element for the step and falls back to a centred card", () => {
    const rect = { top: 100, left: 20, width: 200, height: 40, bottom: 140, right: 220, x: 20, y: 100, toJSON: () => ({}) } as DOMRect;
    render(<><div data-tour="hidden-one" /><div data-tour="shown" data-testid="t" /></>);
    vi.spyOn(screen.getByTestId("t"), "getBoundingClientRect").mockReturnValue(rect);
    render(<Tour steps={[{ title: "tour.p1.title", body: "tour.p1.body", target: "shown" }, { title: "tour.p2.title", body: "tour.p2.body", target: "hidden-one" }]} onClose={() => {}} />);
    const ring = screen.getByTestId("tour-spotlight");
    expect(ring.style.top).toBe("94px");
    expect(ring.style.width).toBe("212px");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.queryByTestId("tour-spotlight")).toBeNull();
  });

  it("has at most five steps and no condition names on patient steps", () => {
    expect(PATIENT_TOUR.length).toBeLessThanOrEqual(5);
    expect(CLINIC_TOUR.length).toBeLessThanOrEqual(5);
    for (const s of PATIENT_TOUR) for (const d of [en, itDict]) expect(d[s.body]).not.toMatch(/diagnos|condition|condizion/i);
  });
});
