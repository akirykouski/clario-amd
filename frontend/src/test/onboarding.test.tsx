import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { en } from "../i18n/en";
import { it as itDict } from "../i18n/it";
import PatientApp from "../patient/PatientApp";
import ClinicApp from "../clinic/ClinicApp";
import { CLINIC_TOUR, PATIENT_TOUR, TOUR_DATA_EVENT, TourButton, clinicTour, patientTour, type TourStep } from "../components/Tour";
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
  return screen.getByTestId("tour-open");
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
    // no padded hole around the zero-size stand-in (it showed as a dot mid-screen)
    await waitFor(() => expect(document.querySelector(".driver-overlay path")?.getAttribute("d")).toMatch(/^M0 0H\d+V\d+H0Z$/), WAIT);
  });

  it("?tour=1 opens the tour on arrival in the linked language and drops the flags from the address", async () => {
    renderFake("/?tour=1&lang=it&pkg=pkg_1");
    expect(await dialog()).toHaveTextContent(itDict["tour.p1.title"]);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/), WAIT);
  });
});

describe("tour content", () => {
  it("patient steps walk every screen: Today, Timeline, To discuss, Labs, Share, What left this device", () => {
    const steps = patientTour({ empty: false });
    expect(steps.map((s) => s.route)).toEqual(["/", "/", "/timeline", "/patterns", "/labs", "/share", "/privacy"]);
    expect(steps.map((s) => s.target)).toEqual(["today-write", "today-recent", "timeline-heat", "patterns", "labs", "share-period", "privacy-log"]);
  });

  it("an empty diary points steps 2 and 3 at where terms and weeks will appear", () => {
    const steps = patientTour({ empty: true });
    expect(steps[1]).toMatchObject({ target: "today-understood", body: "tour.p2.bodyEmpty" });
    expect(steps[2]).toMatchObject({ target: "timeline-heat", body: "tour.p3.bodyEmpty", ready: undefined });
  });

  it("hands over to the clinic as the last step when the server knows its clinic", () => {
    expect(patientTour({ empty: false }).some((s) => s.action)).toBe(false);
    const steps = patientTour({ empty: false, clinic: "https://clinic.example/", demo: true });
    expect(steps[steps.length - 1]).toMatchObject({ title: "tour.p6.title", body: "tour.p6.bodyDemo", action: { label: "tour.toClinic" } });
    expect(patientTour({ empty: false, clinic: "https://c.example" }).slice(-1)[0]?.body).toBe("tour.p6.body");
  });

  it("clinic steps open the first package, and the brief pane last", () => {
    const steps = clinicTour("pkg_1");
    expect(steps.map((s) => s.route)).toEqual(["/", "/p/pkg_1", "/p/pkg_1", "/p/pkg_1", "/p/pkg_1?pane=brief"]);
    expect(steps.map((s) => s.target)).toEqual(["inbox", "pkg-glance", "needs-check", "ddx", "brief"]);
    expect(clinicTour(null).map((s) => s.title)).toEqual(["tour.c0.title"]);
  });

  it("has at most eight steps and no condition names on patient steps", () => {
    const all = [...patientTour({ empty: false, clinic: "c", demo: true }), ...patientTour({ empty: true, clinic: "c" })];
    expect(all.length).toBeLessThanOrEqual(16);
    expect(clinicTour("x").length).toBeLessThanOrEqual(5);
    for (const s of all) for (const d of [en, itDict]) {
      expect(d[s.title]).not.toMatch(/diagnos|condition|condizion|lupus|disease|malattia/i);
      expect(d[s.body]).not.toMatch(/diagnos|condition|condizion|lupus|disease|malattia/i);
    }
  });

  it("says the diagnosis stays with the clinician, in both languages", () => {
    expect(en["tour.c4.body"]).toMatch(/the diagnosis stays yours/);
    expect(itDict["tour.c4.body"]).toMatch(/la diagnosi resta tua/);
  });
});

describe("hand-over to the clinic", () => {
  const health = (demo: boolean) => ({ ok: true, mode: "patient", llm: {}, demo_instance: demo, clinic_url: "https://clinic.example/" }) as unknown as Health;
  const plan = (p: typeof PATIENT_TOUR) => (typeof p === "function" ? p({}) : Promise.resolve(p));

  it("an empty diary on the demo server loads the demo patient, refreshes Today and shares only that diary", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health(true));
    vi.spyOn(api, "entries").mockResolvedValue([]);
    const demo = vi.spyOn(api, "demo").mockResolvedValue({ ok: true, entries: 19, persona: "giulia", lang: "en" });
    const fired = vi.fn();
    window.addEventListener(TOUR_DATA_EVENT, fired);
    const steps = await plan(PATIENT_TOUR);
    window.removeEventListener(TOUR_DATA_EVENT, fired);
    expect(demo).toHaveBeenCalledWith("giulia");
    expect(fired).toHaveBeenCalledTimes(1);
    expect(steps[1].target).toBe("today-recent");
    expect(steps[steps.length - 1].body).toBe("tour.p6.bodyDemo");
  });

  it("a diary with a note someone typed is never sent from the tour", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health(true));
    vi.spyOn(api, "entries").mockResolvedValue([{ id: "e_abc" }, { id: "e_demo_1" }] as never);
    const demo = vi.spyOn(api, "demo");
    const steps = await plan(PATIENT_TOUR);
    expect(demo).not.toHaveBeenCalled();
    expect(steps[steps.length - 1].body).toBe("tour.p6.body");
    const share = vi.spyOn(api, "share");
    const tab = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    expect(await steps[steps.length - 1].action!.run()).toBeNull();
    expect(share).not.toHaveBeenCalled();
    expect(tab.location.href).toBe("https://clinic.example/?tour=1&lang=en");
  });

  it("sends the demo diary and opens the clinic on that package", async () => {
    const share = vi.spyOn(api, "share").mockResolvedValue({ package_id: "pkg_42" } as never);
    const tab = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const last = patientTour({ empty: false, clinic: "https://clinic.example/", demo: true }).slice(-1)[0];
    expect(await last.action!.run()).toBeNull();
    expect(share).toHaveBeenCalledWith(expect.objectContaining({ clinic_url: "https://clinic.example", expires_hours: 72 }));
    expect(tab.location.href).toBe("https://clinic.example/?tour=1&lang=en&pkg=pkg_42");
  });

  it("a failed share closes the new tab and says why", async () => {
    vi.spyOn(api, "share").mockRejectedValue(new Error("timeout"));
    const tab = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const last = patientTour({ empty: false, clinic: "https://clinic.example", demo: true }).slice(-1)[0];
    expect(await last.action!.run()).toBe(en["tour.shareFailed"]);
    expect(tab.close).toHaveBeenCalled();
    expect(tab.location.href).toBe("");
  });

  it("the clinic tour opens the linked package when it is in the inbox, else the newest", async () => {
    vi.spyOn(api, "inbox").mockResolvedValue([{ package_id: "pkg_new" }, { package_id: "pkg_mine" }] as never);
    const build = CLINIC_TOUR as (o: { pkg?: string }) => Promise<TourStep[]>;
    expect((await build({ pkg: "pkg_mine" }))[1].route).toBe("/p/pkg_mine");
    expect((await build({ pkg: "pkg_gone" }))[1].route).toBe("/p/pkg_new");
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
    await count("1 of 7");
    await waitFor(() => expect(document.querySelector('[data-tour="today-write"]')).toHaveClass("driver-active-element"), WAIT);
  });

  it("speaks Italian", async () => {
    act(() => setLang("it"));
    mockPatient();
    render(<MemoryRouter><PatientApp /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Come funziona" }));
    expect(await dialog()).toHaveTextContent(itDict["tour.p1.title"]);
    await count("1 di 7");
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
