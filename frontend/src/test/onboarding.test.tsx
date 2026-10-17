import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { en } from "../i18n/en";
import { it as itDict } from "../i18n/it";
import PatientApp from "../patient/PatientApp";
import ClinicApp from "../clinic/ClinicApp";
import { CLINIC_TOUR, PATIENT_TOUR, TourButton, clinicTour, type TourStep } from "../components/Tour";
import type { Health } from "../types";

// jsdom has no layout: give every element a box so tour targets count as visible.
const box = { top: 120, left: 40, width: 320, height: 80, bottom: 200, right: 360, x: 40, y: 120, toJSON: () => ({}) } as DOMRect;

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(box);
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
});
afterEach(() => {
  vi.restoreAllMocks();
  act(() => setLang("en"));
  document.querySelectorAll(".driver-popover, .driver-overlay, .clario-tour-blur, .clario-tour-ring").forEach((n) => n.remove());
});

const WAIT = { timeout: 4000 };
const dialog = () => screen.findByRole("dialog", undefined, WAIT);
const count = async (text: string) => waitFor(() => expect(screen.getByTestId("tour-count")).toHaveTextContent(text), WAIT);
const next = () => fireEvent.click(screen.getByRole("button", { name: /^(Next|Avanti|Done|Fine)$/ }));
const back = () => fireEvent.click(screen.getByRole("button", { name: /^(Back|Indietro)$/ }));
const esc = () => fireEvent.keyUp(window, { key: "Escape" });

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

/** A small app with three screens, each with one tour target, to test how the tour drives navigation. */
const STEPS: TourStep[] = [
  { title: "tour.p1.title", body: "tour.p1.body", route: "/", target: "a" },
  { title: "tour.p2.title", body: "tour.p2.body", route: "/two", target: "b" },
  { title: "tour.p3.title", body: "tour.p3.body", route: "/three?x=1", target: "c" },
];
function renderFake(start = "/elsewhere", steps: TourStep[] = STEPS) {
  render(
    <MemoryRouter initialEntries={[start]}>
      <TourButton steps={steps} />
      <Where />
      <Routes>
        <Route path="/" element={<div data-tour="a">Screen one</div>} />
        <Route path="/two" element={<div data-tour="b">Screen two</div>} />
        <Route path="/three" element={<div data-tour="c">Screen three</div>} />
        <Route path="*" element={<div>Somewhere else</div>} />
      </Routes>
    </MemoryRouter>,
  );
  return screen.getByRole("button", { name: "How it works" });
}
const where = () => screen.getByTestId("where").textContent;

describe("tour engine", () => {
  it("is not shown until ? is pressed", () => {
    renderFake();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens from ?, navigates to each step's screen and spotlights its element", async () => {
    fireEvent.click(renderFake());
    expect(await dialog()).toHaveTextContent(en["tour.p1.title"]);
    await count("1 of 3");
    expect(where()).toBe("/");
    await waitFor(() => expect(document.querySelector('[data-tour="a"]')).toHaveClass("driver-active-element"), WAIT);
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull(); // no Back on the first step
    expect(document.querySelector(".clario-tour-blur")).not.toBeNull();

    next();
    await count("2 of 3");
    expect(where()).toBe("/two");
    await waitFor(() => expect(document.querySelector('[data-tour="b"]')).toHaveClass("driver-active-element"), WAIT);

    next();
    await count("3 of 3");
    expect(where()).toBe("/three?x=1");
    expect(screen.getByRole("dialog")).toHaveTextContent(en["tour.p3.title"]);
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("Back returns to the previous screen", async () => {
    fireEvent.click(renderFake());
    await count("1 of 3");
    next();
    await count("2 of 3");
    next();
    await count("3 of 3");
    back();
    await count("2 of 3");
    expect(where()).toBe("/two");
    expect(screen.getByRole("dialog")).toHaveTextContent(en["tour.p2.title"]);
  });

  it("Esc closes, brings back the starting screen and focuses ?", async () => {
    const open = renderFake("/elsewhere");
    fireEvent.click(open);
    await count("1 of 3");
    next();
    await count("2 of 3");
    expect(where()).toBe("/two");
    esc();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), WAIT);
    expect(where()).toBe("/elsewhere");
    expect(document.querySelector(".clario-tour-blur")).toBeNull();
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("Done on the last step and the close button also restore the start", async () => {
    fireEvent.click(renderFake("/elsewhere"));
    await count("1 of 3");
    next(); await count("2 of 3");
    next(); await count("3 of 3");
    next(); // Done
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), WAIT);
    expect(where()).toBe("/elsewhere");

    fireEvent.click(screen.getByRole("button", { name: "How it works" }));
    await count("1 of 3");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), WAIT);
  });

  it("arrow keys move between steps", async () => {
    fireEvent.click(renderFake());
    await count("1 of 3");
    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toHaveFocus(), WAIT);
    fireEvent.keyUp(window, { key: "ArrowRight" });
    await count("2 of 3");
    // keys are ignored while the window glides; the end of the move puts focus on Next
    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toHaveFocus(), WAIT);
    fireEvent.keyUp(window, { key: "ArrowLeft" });
    await count("1 of 3");
  });

  it("a target missing on its screen falls back to a centred card, still blurred", async () => {
    const steps: TourStep[] = [{ title: "tour.p1.title", body: "tour.p1.body", route: "/", target: "not-here" }];
    fireEvent.click(renderFake("/", steps));
    expect(await dialog()).toHaveTextContent(en["tour.p1.title"]);
    expect(document.getElementById("driver-dummy-element")).not.toBeNull();
    expect(document.querySelector(".clario-tour-blur")).not.toBeNull();
    expect(screen.getByTestId("tour-spotlight")).not.toHaveClass("is-on");
  });
});

describe("tour content", () => {
  it("patient steps open Today, Timeline, Share and What left this device", () => {
    expect(PATIENT_TOUR.map((s) => s.route)).toEqual(["/", "/", "/timeline", "/share", "/privacy"]);
    expect(PATIENT_TOUR.map((s) => s.target)).toEqual(["today-write", "today-recent", "timeline-heat", "share-period", "privacy-log"]);
  });

  it("clinic steps open the first package, and the brief pane last", () => {
    const steps = clinicTour("pkg_1");
    expect(steps.map((s) => s.route)).toEqual(["/", "/p/pkg_1", "/p/pkg_1", "/p/pkg_1", "/p/pkg_1?pane=brief"]);
    expect(steps.map((s) => s.target)).toEqual(["inbox", "pkg-glance", "needs-check", "ddx", "brief"]);
    expect(clinicTour(null).map((s) => s.title)).toEqual(["tour.c0.title"]);
  });

  it("has at most five steps and no condition names on patient steps", () => {
    expect(PATIENT_TOUR.length).toBeLessThanOrEqual(5);
    expect(clinicTour("x").length).toBeLessThanOrEqual(5);
    for (const s of PATIENT_TOUR) for (const d of [en, itDict]) {
      expect(d[s.title]).not.toMatch(/diagnos|condition|condizion|lupus|disease|malattia/i);
      expect(d[s.body]).not.toMatch(/diagnos|condition|condizion|lupus|disease|malattia/i);
    }
  });

  it("says decision support, not a diagnosis, in both languages", () => {
    expect(en["tour.c4.body"]).toMatch(/not a diagnosis/);
    expect(itDict["tour.c4.body"]).toMatch(/non una diagnosi/);
  });
});

describe("tour in the apps", () => {
  function mockPatient() {
    vi.spyOn(api, "vault").mockResolvedValue({ initialized: true, locked: false });
    vi.spyOn(api, "entries").mockResolvedValue([]);
    vi.spyOn(api, "privacyCounts").mockResolvedValue({} as never);
  }

  it("patient app: ? opens step 1 on Today", async () => {
    mockPatient();
    render(<MemoryRouter><PatientApp /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "How it works" }));
    expect(await dialog()).toHaveTextContent(en["tour.p1.title"]);
    await count("1 of 5");
    await waitFor(() => expect(document.querySelector('[data-tour="today-write"]')).toHaveClass("driver-active-element"), WAIT);
  });

  it("speaks Italian", async () => {
    act(() => setLang("it"));
    mockPatient();
    render(<MemoryRouter><PatientApp /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Come funziona" }));
    expect(await dialog()).toHaveTextContent(itDict["tour.p1.title"]);
    await count("1 di 5");
    expect(screen.getByRole("button", { name: "Avanti" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chiudi" })).toBeInTheDocument();
  });

  it("clinic with an empty inbox explains how to get a package, in one step", async () => {
    vi.spyOn(api, "clinicKey").mockResolvedValue({ public_key: "k", fingerprint: "ab:cd", clinic_name: "C" } as never);
    vi.spyOn(api, "inbox").mockResolvedValue([]);
    vi.spyOn(api, "clinicMetrics").mockResolvedValue({} as never);
    const health = { ok: true, mode: "clinic", llm: { backend: "offline-fixtures" } } as unknown as Health;
    render(<MemoryRouter><ClinicApp health={health} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "How it works" }));
    expect(await dialog()).toHaveTextContent(en["tour.c0.title"]);
    await count("1 of 1");
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("clinic tour is built from the inbox", async () => {
    vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_9" }] as never);
    const steps = await (CLINIC_TOUR as () => Promise<TourStep[]>)();
    expect(steps[1].route).toBe("/p/pkg_9");
  });
});
