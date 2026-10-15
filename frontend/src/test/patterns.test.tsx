import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { reorderDelta } from "../lib";
import PatternsPage from "../patient/PatternsPage";
import type { Pattern } from "../types";

afterEach(() => vi.restoreAllMocks());

const pat = (id: string, name: string, label: string): Pattern => ({
  disease_id: id, disease_name: name, signal: "moderate", score: 0.6, neutral_label: label,
  matched: [{ hpo_id: "HP:1", label: "Fatigue", entry_ids: ["e1"], first_seen: "2026-03-01", last_seen: "2026-03-05", count: 2 }],
  missing: [], rationale: `Overlaps with ${name}. It may be worth discussing.`, rationale_source: "template",
});
const A = pat("ORPHA:1", "Zeta syndrome", "Fatigue, rash"), B = pat("ORPHA:2", "Eta disease", "Joint pain, stiffness");

describe("reorderDelta", () => {
  it("is negative for items that moved up and skips new ids", () => {
    expect(reorderDelta(["a", "b", "c"], ["c", "a", "x"])).toEqual({ c: -2, a: 1 });
  });
});

describe("patterns page", () => {
  it("leads with evidence, hides the condition name until asked, and reorders after an answer", async () => {
    const get = vi.spyOn(api, "patterns");
    get.mockResolvedValueOnce({ patterns: [A, B], confirmed_terms: 5, note: "" });
    get.mockResolvedValue({ patterns: [B, A], confirmed_terms: 6, note: "" });
    vi.spyOn(api, "nextQuestion").mockResolvedValue({
      feature_id: "HP:9", question: "Do you sometimes have: dry mouth?", why: "Your answer may help tell apart two of the patterns shown here.",
      ig: 0.5, splits: ["ORPHA:1", "ORPHA:2"], question_source: "template",
    });
    const answer = vi.spyOn(api, "answerQuestion").mockResolvedValue({ before: [], after: [], entry_id: "e9" });
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Patterns to discuss with your clinician" })).toBeInTheDocument();
    const titles = () => screen.getAllByTestId("pattern-card").map((c) => c.querySelector("h2")?.textContent);
    expect(titles()).toEqual(["Fatigue, rash", "Joint pain, stiffness"]);
    expect(screen.getAllByText("This is not a diagnosis.")).toHaveLength(2);
    expect(screen.getAllByText("Show what this pattern resembles")).toHaveLength(2);
    expect(await screen.findByText("A question that could help your clinician")).toBeInTheDocument();
    expect(screen.getByTestId("question-text").textContent).not.toMatch(/Zeta|Eta disease/);
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(titles()).toEqual(["Joint pain, stiffness", "Fatigue, rash"]));
    expect(answer).toHaveBeenCalledWith(expect.objectContaining({ feature_id: "HP:9", answer: "yes" }));
    expect(screen.getByText("Moved up")).toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toMatch(/order of the patterns changed/);
  });
});
