import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { resetHealthCache } from "../components/useHealth";
import { setLang } from "../i18n";
import { ComputeBadge } from "../clinic/ClinicApp";
import { labName } from "../patient/LabsPage";
import ReviewPage, { ConfidenceBar } from "../patient/ReviewPage";
import type { ReviewItem } from "../types";

const offlineHealth = { ok: true, mode: "patient" as const, llm: { backend: "offline-fixtures", model: "offline-fixture-v1" } };

beforeEach(() => { setLang("en"); resetHealthCache(); });
afterEach(() => { vi.restoreAllMocks(); resetHealthCache(); });

const labItem = (n: number, conf = 0.55): ReviewItem => ({
  kind: "lab", id: `l${n}`, entry_id: null, canonical: "Sodio", display: `Sodio: ${130 + n}`, value: `${130 + n}`, confidence: conf,
  source_excerpt: `Sodio   ${130 + n}`, quote: null, flag: "low", page: 1,
} as ReviewItem);

describe("offline demo model", () => {
  it("shows a word instead of a percent for reading quality", async () => {
    vi.spyOn(api, "health").mockResolvedValue(offlineHealth);
    const { container } = render(<ConfidenceBar value={0.55} />);
    expect(await screen.findByText("To review")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/%/);
  });

  it("clinic header names the demo model, not fixture ids", () => {
    render(<ComputeBadge llm={offlineHealth.llm} />);
    expect(screen.getByText("Demo model (offline)")).toBeInTheDocument();
    expect(screen.queryByText(/offline-fixture/)).toBeNull();
  });
});

describe("review queue", () => {
  it("collapses many identical-confidence lab items under one line and shows each value once", async () => {
    vi.spyOn(api, "review").mockResolvedValue({ items: [labItem(1), labItem(2), labItem(3), labItem(4)], count: 4 });
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);
    expect(await screen.findByText("4 lab values read with the same level of confidence")).toBeInTheDocument();
    expect(screen.getAllByTestId("review-group")).toHaveLength(1);
    await waitFor(() => expect(screen.getAllByText(/Sodium: 131/)).toHaveLength(1));
    expect(document.body.textContent).not.toMatch(/%/);
  });

  it("confirms the whole lab group with one button", async () => {
    vi.spyOn(api, "review").mockResolvedValue({ items: [labItem(1), labItem(2), labItem(3), labItem(4)], count: 4 });
    const act = vi.spyOn(api, "reviewAct").mockResolvedValue({ ok: true, count: 0 } as never);
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);
    fireEvent.click(await screen.findByTestId("group-confirm-all"));
    await waitFor(() => expect(act).toHaveBeenCalledTimes(4));
    expect(act.mock.calls.every((c) => c[2] === "confirm")).toBe(true);
  });

  it("keeps a few lab items as separate cards", async () => {
    vi.spyOn(api, "review").mockResolvedValue({ items: [labItem(1), labItem(2)], count: 2 });
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);
    await screen.findAllByRole("button", { name: /confirm/i });
    expect(screen.queryByTestId("review-group")).toBeNull();
  });
});

describe("lab names", () => {
  it("English shows the English name and keeps the printed Italian one", () => {
    expect(labName("Sodio", "en")).toEqual({ main: "Sodium", printed: "Sodio" });
    expect(labName("Piastrine", "en").main).toBe("Platelets");
    expect(labName("TSH", "en")).toEqual({ main: "TSH", printed: null });
    expect(labName("Sodio", "it")).toEqual({ main: "Sodio", printed: null });
  });
});
