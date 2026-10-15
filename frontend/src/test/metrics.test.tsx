import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { setLang } from "../i18n";
import { BriefPanel, countDecisions } from "../clinic/BriefPanel";
import { DecisionLine, InboxMetrics } from "../clinic/Metrics";
import type { Brief, BriefItem, ClinicMetrics, SharePackage } from "../types";

afterEach(() => { vi.restoreAllMocks(); act(() => setLang("en")); });

const item = (id: string, review: BriefItem["review"], origin: BriefItem["origin"] = "ai"): BriefItem =>
  ({ id, section: "symptoms", text: `line ${id}`, cites: [], origin, review });

describe("pilot metric", () => {
  it("counts AI lines by decision and ignores patient lines and pending ones", () => {
    const items = [item("a", "accepted"), item("b", "accepted"), item("c", "edited"), item("d", "rejected"), item("e", "pending"), item("f", "accepted", "patient")];
    expect(countDecisions(items)).toEqual({ accepted: 2, edited: 1, rejected: 1 });
  });

  it("renders the line in English and Italian with minutes and seconds", () => {
    render(<DecisionLine counts={{ accepted: 12, edited: 2, rejected: 1 }} seconds={220} />);
    expect(screen.getByTestId("decision-line")).toHaveTextContent("Lines accepted 12 · edited 2 · rejected 1 · 3 min 40 s to finalize");
    act(() => setLang("it"));
    expect(screen.getByTestId("decision-line")).toHaveTextContent("Righe accettate 12 · modificate 2 · scartate 1 · 3 min 40 s per rendere definitivo");
  });

  it("shows seconds only under a minute and omits the time when unknown", () => {
    const { rerender } = render(<DecisionLine counts={{ accepted: 1, edited: 0, rejected: 0 }} seconds={40} />);
    expect(screen.getByTestId("decision-line")).toHaveTextContent("40 s to finalize");
    rerender(<DecisionLine counts={{ accepted: 1, edited: 0, rejected: 0 }} />);
    expect(screen.getByTestId("decision-line")).not.toHaveTextContent("finalize");
  });

  it("inbox header shows totals and the average, and stays hidden with no finalized brief", async () => {
    const empty: ClinicMetrics = { briefs: [], totals: { accepted: 0, edited: 0, rejected: 0 }, finalized: 0, timed: 0, mean_review_seconds: null };
    const spy = vi.spyOn(api, "clinicMetrics").mockResolvedValue(empty);
    const { unmount } = render(<InboxMetrics />);
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.queryByTestId("inbox-metrics")).toBeNull();
    unmount();
    spy.mockResolvedValue({ ...empty, finalized: 2, timed: 2, mean_review_seconds: 95, totals: { accepted: 12, edited: 2, rejected: 1 } });
    render(<InboxMetrics />);
    expect(await screen.findByTestId("inbox-metrics")).toHaveTextContent("2 finalized briefs · Lines accepted 12 · edited 2 · rejected 1 · 1 min 35 s average to finalize");
  });

  it("sends the time since the package was opened when finalizing", async () => {
    vi.spyOn(api, "gpu").mockResolvedValue(null);
    const brief: Brief = { package_id: "pkg_1", items: [item("a", "accepted"), item("b", "rejected")], model: null, backend: null, finalized: false, stats: {} };
    const fin = vi.spyOn(api, "finalize").mockResolvedValue({ ...brief, finalized: true, review_seconds: 12 });
    const setBrief = vi.fn();
    const pkg = { package_id: "pkg_1", patient_alias: "Ash-001", entries: [], entities: [], labs: [], patterns: [], period: ["2026-09-01", "2026-10-02"] } as unknown as SharePackage;
    render(<MemoryRouter><BriefPanel pkg={pkg} brief={brief} setBrief={setBrief} /></MemoryRouter>);
    expect(screen.getByTestId("decision-line")).toHaveTextContent("Lines accepted 1 · edited 0 · rejected 1");
    fireEvent.click(screen.getByRole("button", { name: "Finalize brief" }));
    await vi.waitFor(() => expect(fin).toHaveBeenCalled());
    expect(fin.mock.calls[0][0]).toBe("pkg_1");
    expect(typeof fin.mock.calls[0][1]).toBe("number");
    expect(fin.mock.calls[0][1] as number).toBeGreaterThanOrEqual(0);
  });
});
