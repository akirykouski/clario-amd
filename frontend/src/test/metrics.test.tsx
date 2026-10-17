import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { api } from "../api";
import { setLang } from "../i18n";
import { countDecisions } from "../clinic/BriefPanel";
import { DecisionLine, InboxMetrics } from "../clinic/Metrics";
import type { BriefItem, ClinicMetrics } from "../types";

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
    expect(screen.getByTestId("decision-line")).toHaveTextContent("This package · AI lines: accepted 12 · edited 2 · rejected 1 · 3 min 40 s to sign");
    act(() => setLang("it"));
    expect(screen.getByTestId("decision-line")).toHaveTextContent("Questo pacchetto · Righe dell'IA: accettate 12 · modificate 2 · scartate 1 · 3 min 40 s per firmare il riepilogo");
  });

  it("shows seconds only under a minute and omits the time when unknown", () => {
    const { rerender } = render(<DecisionLine counts={{ accepted: 1, edited: 0, rejected: 0 }} seconds={40} />);
    expect(screen.getByTestId("decision-line")).toHaveTextContent("40 s to sign");
    rerender(<DecisionLine counts={{ accepted: 1, edited: 0, rejected: 0 }} />);
    expect(screen.getByTestId("decision-line")).not.toHaveTextContent("to sign");
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
    const strip = await screen.findByTestId("inbox-metrics");
    expect(strip).toHaveTextContent("AI lines in all briefs on this server");
    expect(strip).toHaveTextContent("2 signed briefs · 1 min 35 s average to sign");
    expect(screen.getByTestId("metric-accepted")).toHaveTextContent("12accepted");
    expect(screen.getByTestId("metric-edited")).toHaveTextContent("2edited");
    expect(screen.getByTestId("metric-rejected")).toHaveTextContent("1rejected");
  });

});
