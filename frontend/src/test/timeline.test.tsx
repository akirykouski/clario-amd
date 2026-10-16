import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import TimelinePage from "../patient/TimelinePage";
import type { Timeline } from "../types";

afterEach(() => { vi.restoreAllMocks(); });

// Same shape as backend models.Timeline: days[].entries are full entries, never bare ids.
const payload: Timeline = {
  days: [{
    date: "2026-10-01",
    entries: [{ id: "e1", created_at: "2026-10-01T08:00:00Z", occurred_on: "2026-10-01", text: "Knees ache in the morning.", mood: null, extraction: "done", entities: [] }],
    terms: [{ hpo_id: "HP:0002829", label: "Arthralgia" }],
  }],
  terms: [{ hpo_id: "HP:0002829", label: "Arthralgia", entry_ids: ["e1"], first_seen: "2026-10-01", last_seen: "2026-10-01", count: 1 }],
};

describe("timeline page", () => {
  it("renders the text of each entry of a day", async () => {
    vi.spyOn(api, "timeline").mockResolvedValue(payload);
    render(<MemoryRouter><TimelinePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Knees ache in the morning.")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Knees ache in the morning." })).toHaveAttribute("href", "/entry/e1");
  });
});
