import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import { api } from "../api";
import { Differential } from "../clinic/Differential";
import { setLang } from "../i18n";
import type { Differential as Ddx } from "../types";

afterEach(() => { vi.restoreAllMocks(); act(() => setLang("en")); });

const ddx: Ddx = {
  conditions: [
    { disease_id: "ORPHA:536", name: "Systemic lupus erythematosus", full_name: "Systemic lupus erythematosus", signal: "moderate", score: 0.35,
      rank: 1, url: "https://www.orpha.net/en/disease/detail/536",
      matched: [
        { hpo_id: "HP:0025300", label: "Malar rash", count: 3, labs: 0, freq: null },
        { hpo_id: "HP:0000093", label: "Proteinuria", count: 1, labs: 2, freq: null },
        { hpo_id: "HP:0003493", label: "Antinuclear antibody positivity", count: 0, labs: 2, freq: null },
      ],
      missing: [] },
  ],
  question: null, answers: [], n_terms: 3, note: "",
};

const chip = (box: HTMLElement, label: string) => within(box).getByText(label, { exact: false }).closest(".chip") as HTMLElement;

describe("conditions to consider: lab-derived features", () => {
  it("marks recorded features that come from labs, in English and Italian", async () => {
    vi.spyOn(api, "ddx").mockResolvedValue(ddx);
    render(<Differential pid="pkg_1" version={0} />);
    const card = (await screen.findAllByTestId("ddx-condition"))[0];
    expect(within(card).getAllByTestId("ddx-from-labs")).toHaveLength(2);
    const ana = chip(card, "Antinuclear antibody positivity");
    expect(ana).toHaveTextContent("from labs");
    expect(ana).not.toHaveTextContent("×");  // no note mentions it
    expect(within(ana).getByTestId("ddx-from-labs")).toHaveAttribute("title", "Out-of-range lab results: 2");
    expect(chip(card, "Proteinuria")).toHaveTextContent("from labs");  // notes and labs: one chip, still marked
    expect(chip(card, "Malar rash")).not.toHaveTextContent("from labs");

    act(() => setLang("it"));
    const it_ = (await screen.findAllByTestId("ddx-condition"))[0];
    expect(within(it_).getAllByText("dagli esami")).toHaveLength(2);
  });
});

describe("conditions to consider: organ systems row", () => {
  const withSystems: Ddx = {
    ...ddx,
    systems: [
      { key: "skin", count: 2, findings: [{ hpo_id: "HP:0025300", label: "Malar rash", count: 3, labs: 0 }, { hpo_id: "HP:0001596", label: "Alopecia", count: 1, labs: 0 }] },
      { key: "kidney", count: 1, findings: [{ hpo_id: "HP:0000093", label: "Proteinuria", count: 1, labs: 2 }] },
      { key: "blood", count: 1, findings: [{ hpo_id: "HP:0001903", label: "Anemia", count: 0, labs: 1 }] },
    ],
  };

  it("shows each system with its count, and its findings on hover and tap, in English and Italian", async () => {
    vi.spyOn(api, "ddx").mockResolvedValue(withSystems);
    render(<Differential pid="pkg_1" version={0} />);
    const row = await screen.findByTestId("ddx-systems");
    expect(row).toHaveTextContent("Recorded findings span 3 organ systems");
    const chips = within(row).getAllByTestId("ddx-system");
    expect(chips.map((c) => c.textContent)).toEqual(["Skin2", "Kidneys1", "Blood1"]);
    expect(chips[0]).toHaveAttribute("title", "Malar rash, Alopecia");
    expect(within(row).queryByTestId("ddx-system-findings")).toBeNull();
    act(() => chips[1].click());
    const list = within(row).getByTestId("ddx-system-findings");
    expect(list).toHaveTextContent("Proteinuria");
    expect(list).toHaveTextContent("from labs");
    expect(chips[1]).toHaveAttribute("aria-pressed", "true");
    act(() => chips[1].click());
    expect(within(row).queryByTestId("ddx-system-findings")).toBeNull();

    act(() => setLang("it"));
    const it_ = await screen.findByTestId("ddx-systems");
    expect(it_).toHaveTextContent("I reperti registrati riguardano 3 apparati");
    expect(within(it_).getAllByTestId("ddx-system").map((c) => c.textContent)).toEqual(["Pelle2", "Reni1", "Sangue1"]);
  });

  it("leaves the row out when no system is recorded", async () => {
    vi.spyOn(api, "ddx").mockResolvedValue({ ...ddx, systems: [] });
    render(<Differential pid="pkg_1" version={0} />);
    await screen.findAllByTestId("ddx-condition");
    expect(screen.queryByTestId("ddx-systems")).toBeNull();
  });
});
