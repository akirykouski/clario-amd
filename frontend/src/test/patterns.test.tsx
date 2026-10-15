import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { reorderDelta } from "../lib";
import PatternsPage from "../patient/PatternsPage";
import type { PatientPattern } from "../types";

afterEach(() => vi.restoreAllMocks());

const pat = (id: string, label: string): PatientPattern => ({
  card_id: id, signal: "moderate", neutral_label: label,
  matched: [
    { hpo_id: "HP:1", label: "unusual tiredness", clinical: "Fatigue", entry_ids: ["e1"], first_seen: "2026-03-01", last_seen: "2026-03-05", count: 2 },
    { hpo_id: "HP:2", label: "hair loss", clinical: "Alopecia", entry_ids: ["e2"], first_seen: "2026-03-10", last_seen: "2026-03-10", count: 1 },
  ],
  missing: [{ hpo_id: "HP:3", label: "itchy skin", clinical: "Pruritus" }],
  rationale: "Some of what you recorded often shows up together. This may be worth discussing with your doctor.",
});
const A = pat("c_1", "Fatigue, rash"), B = pat("c_2", "Joint pain, stiffness");

describe("reorderDelta", () => {
  it("is negative for items that moved up and skips new ids", () => {
    expect(reorderDelta(["a", "b", "c"], ["c", "a", "x"])).toEqual({ c: -2, a: 1 });
  });
});

describe("patterns page", () => {
  it("leads with evidence in everyday words, shows no condition name, and reorders after an answer", async () => {
    const get = vi.spyOn(api, "patterns");
    get.mockResolvedValueOnce({ patterns: [A, B], confirmed_terms: 5, note: "" });
    get.mockResolvedValue({ patterns: [B, A], confirmed_terms: 6, note: "" });
    vi.spyOn(api, "nextQuestion").mockResolvedValue({
      feature_id: "HP:9", question: "Do you ever notice a dry mouth?", why: "Your answer may help tell apart two of the patterns shown here.",
      ig: 0.5, splits: ["c_1", "c_2"], question_source: "template",
    });
    const answer = vi.spyOn(api, "answerQuestion").mockResolvedValue({ before: [], after: [], entry_id: "e9" });
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Patterns to discuss with your clinician" })).toBeInTheDocument();
    const titles = () => screen.getAllByTestId("pattern-card").map((c) => c.querySelector("h2")?.textContent);
    expect(titles()).toEqual(["Fatigue, rash", "Joint pain, stiffness"]);
    expect(screen.getAllByText("This is not a diagnosis.")).toHaveLength(2);
    expect(screen.queryByText("Show what this pattern resembles")).toBeNull();
    expect(screen.getAllByText(/^Unusual tiredness/)[0].textContent).toBe("Unusual tiredness (Fatigue)");
    expect(screen.getAllByText(/2 times, 1 Mar to 5 Mar/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/once, 10 Mar/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/1 time, /)).toBeNull();
    expect(await screen.findByText("A question that could help your clinician")).toBeInTheDocument();
    expect(screen.getByTestId("question-text").textContent).not.toMatch(/syndrome|disease/i);
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(titles()).toEqual(["Joint pain, stiffness", "Fatigue, rash"]));
    expect(answer).toHaveBeenCalledWith(expect.objectContaining({ feature_id: "HP:9", answer: "yes" }));
    expect(screen.getByText("Moved up")).toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toMatch(/order of the patterns changed/);
  });
});
