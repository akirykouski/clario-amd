import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { REVIEW_EVENT, confidencePct, splitQuotes } from "../lib";
import ReviewPage, { ConfidenceBar } from "../patient/ReviewPage";
import { EntryCard } from "../patient/EntryCard";
import type { Entity, Entry, ReviewItem } from "../types";

afterEach(() => vi.restoreAllMocks());

const item: ReviewItem = {
  kind: "entity", id: "ent_1", entry_id: "e1", display: "Arthralgia", value: "HP:0002829", confidence: 0.6,
  source_excerpt: "Maybe my knees ache a bit. So tired.", quote: "knees ache", hpo_label: "Arthralgia",
};

const ent = (o: Partial<Entity>): Entity => ({
  id: "x", entry_id: "e1", type: "symptom", quote: "q", canonical: "Fatigue", hpo_id: null, hpo_label: null, negated: false,
  severity: null, family_history: false, onset_hint: null, confidence: null, review: "auto", flags: [], model: null, ...o,
});

describe("review", () => {
  it("rounds confidence to a percent and handles null", () => {
    expect(confidencePct(0.6)).toBe(60);
    expect(confidencePct(0.666)).toBe(67);
    expect(confidencePct(null)).toBeNull();
    expect(confidencePct(3)).toBe(100);
  });

  it("highlights the quote inside the excerpt", () => {
    const segs = splitQuotes(item.source_excerpt, [item.quote!]);
    expect(segs.find((s) => s.quoted)?.text).toBe("knees ache");
  });

  it("shows a meter for the confidence, and a note when it was not measured", () => {
    const { rerender } = render(<ConfidenceBar value={0.6} />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "60");
    rerender(<ConfidenceBar value={null} />);
    expect(screen.getByText("Confidence not measured")).toBeInTheDocument();
  });

  it("lists items, sends the action and removes the card", async () => {
    vi.spyOn(api, "review").mockResolvedValue({ items: [item], count: 1 });
    const act = vi.spyOn(api, "reviewAct").mockResolvedValue({ ok: true, count: 0 });
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);
    expect(await screen.findByText("We are 60% sure")).toBeInTheDocument();
    expect(document.querySelector("mark")?.textContent).toBe("knees ache");
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(act).toHaveBeenCalledWith("entity", "ent_1", "confirm", undefined);
    await waitFor(() => expect(screen.getByText("Nothing to review")).toBeInTheDocument());
  });

  it("reject posts reject", async () => {
    vi.spyOn(api, "review").mockResolvedValue({ items: [item], count: 1 });
    const act = vi.spyOn(api, "reviewAct").mockResolvedValue({ ok: true, count: 0 });
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: /reject/i }));
    expect(act).toHaveBeenCalledWith("entity", "ent_1", "reject", undefined);
  });

  it("entry cards mark needs_review terms amber and link to the queue", () => {
    const entry: Entry = {
      id: "e1", created_at: "x", occurred_on: "2026-09-01", text: "Maybe my knees ache", mood: null, extraction: "done",
      entities: [ent({ id: "a", canonical: "Arthralgia", review: "needs_review" }), ent({ id: "b", canonical: "Fatigue", review: "confirmed" })],
    };
    render(<MemoryRouter><EntryCard initial={entry} /></MemoryRouter>);
    const link = screen.getByRole("link", { name: /Arthralgia/ });
    expect(link).toHaveAttribute("href", "/review");
    expect(link.className).toContain("chip-review");
    expect(screen.getByText("Fatigue").closest("a")).toBeNull();
  });

  it("pending entry cards share one poll and tell the nav badge when extraction finishes", async () => {
    vi.useFakeTimers();
    try {
      const pending = (id: string): Entry => ({ id, created_at: "x", occurred_on: "2026-09-01", text: `note ${id}`, mood: null, extraction: "pending", entities: [] });
      const done = { ...pending("e2"), extraction: "done" as const };
      const list = vi.spyOn(api, "entries").mockResolvedValue([pending("e1"), done]);
      const single = vi.spyOn(api, "entry");
      const changed = vi.fn();
      window.addEventListener(REVIEW_EVENT, changed);
      render(<MemoryRouter><EntryCard initial={pending("e1")} /><EntryCard initial={pending("e2")} /></MemoryRouter>);
      await vi.advanceTimersByTimeAsync(2100);
      expect(list).toHaveBeenCalledTimes(1);  // two pending cards, one request
      expect(single).not.toHaveBeenCalled();
      expect(changed).toHaveBeenCalledTimes(1);  // e2 finished
      window.removeEventListener(REVIEW_EVENT, changed);
    } finally {
      vi.useRealTimers();
    }
  });
});
