import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { en } from "../i18n/en";
import { it as itDict } from "../i18n/it";
import { hpoIt } from "../i18n/hpo.it";
import { entityName, entryText, getLang, setLang, t, tn, termLabel } from "../i18n";
import { LangSwitch } from "../components/LangSwitch";
import { SignalPill } from "../components/ui";
import { DemoMenu } from "../patient/DemoMenu";
import PatternsPage from "../patient/PatternsPage";
import ReviewPage from "../patient/ReviewPage";
import { gpuLoad, gpuName } from "../patient/ImportPage";
import { fmtDate } from "../lib";
import type { PatientPattern, ReviewItem } from "../types";

const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, removeItem: (k: string) => { m.delete(k); }, clear: () => m.clear() }; };
beforeEach(() => { vi.stubGlobal("localStorage", mem()); setLang("en"); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); setLang("en"); });

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join();

describe("dictionaries", () => {
  it("Italian has exactly the English keys and the same placeholders", () => {
    expect(Object.keys(itDict).sort()).toEqual(Object.keys(en).sort());
    for (const k of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(itDict[k]), k).toBe(placeholders(en[k]));
      expect(itDict[k].trim().length, k).toBeGreaterThan(0);
    }
  });
  it("every plural base has _one and _other in both languages", () => {
    const bases = new Set(Object.keys(en).filter((k) => /_(one|other)$/.test(k)).map((k) => k.replace(/_(one|other)$/, "")));
    for (const b of bases) for (const d of [en, itDict] as Record<string, string>[]) { expect(d[`${b}_one`]).toBeTruthy(); expect(d[`${b}_other`]).toBeTruthy(); }
  });
  it("copy rules: no em dash, no exclamation mark", () => {
    for (const s of [...Object.values(en), ...Object.values(itDict), ...Object.values(hpoIt)]) expect(s).not.toMatch(/[—!]/);
  });
  it("the Italian term table equals the backend one", () => {
    const backend = JSON.parse(readFileSync(resolve(__dirname, "../../../backend/clario/data/hpo_it.json"), "utf8"));
    expect(hpoIt).toEqual(backend);
  });
});

describe("language state", () => {
  it("switches, persists in localStorage and survives blocked storage", () => {
    expect(t("nav.today")).toBe("Today");
    setLang("it");
    expect(t("nav.today")).toBe("Oggi");
    expect(localStorage.getItem("clario.lang")).toBe("it");
    expect(document.documentElement.lang).toBe("it");
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    expect(() => setLang("en")).not.toThrow();
    expect(getLang()).toBe("en");
  });
  it("fills params and plurals", () => {
    expect(t("nav.toReview", { n: 3 })).toBe("3 to review");
    expect(tn("privacy.verified", 1)).toMatch(/1 call,/);
    expect(tn("privacy.verified", 3)).toMatch(/3 calls,/);
    setLang("it");
    expect(tn("privacy.verified", 3)).toMatch(/3 chiamate/);
    expect(fmtDate("2026-03-04", { month: "long" })).toBe("marzo");
  });
  it("names Italian terms plainly and falls back to the patient's own words", () => {
    setLang("it");
    expect(termLabel("HP:0012378", "Fatigue")).toBe("Stanchezza");
    expect(termLabel("HP:9999999", "Odd term")).toBe("Odd term");
    expect(entityName({ hpo_id: null, canonical: "Systemic lupus erythematosus", quote: "il lupus" })).toBe("il lupus");
    expect(entryText("Imported documents (3 pages)")).toBe("Documenti importati (3 pagine)");
    setLang("en");
    expect(entityName({ hpo_id: null, canonical: "Sun exposure", quote: "sunny" })).toBe("Sun exposure");
    expect(entryText("Imported documents (1 page)")).toBe("Imported documents (1 page)");
  });
  it("the switcher flips the words on screen", async () => {
    render(<><LangSwitch /><SignalPill signal="strong" /></>);
    expect(screen.getByText("Strong signal")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Italiano/ }));
    expect(screen.getByText("Segnale forte")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Italiano/ })).toHaveAttribute("aria-pressed", "true");
  });
});

const pat: PatientPattern = {
  card_id: "c_1", signal: "moderate",
  neutral_label: "Arrossamento a farfalla sul viso, caduta dei capelli",
  matched: [{ hpo_id: "HP:0025300", label: "Arrossamento a farfalla sul viso", clinical: "Malar rash", entry_ids: ["e1"], first_seen: "2026-03-01", last_seen: "2026-03-05", count: 2 }],
  missing: [], rationale: "Potrebbe valere la pena parlarne con il medico.",
};

describe("Italian screens", () => {
  it("patterns page: title, intro and the card text are Italian; the server gets lang=it", async () => {
    setLang("it");
    const get = vi.spyOn(api, "patterns").mockResolvedValue({ patterns: [pat], confirmed_terms: 5, note: "" });
    const nq = vi.spyOn(api, "nextQuestion").mockResolvedValue({
      feature_id: "HP:0002017", question: "Ti capita di avere nausea e vomito?", why: "La tua risposta potrebbe aiutare il medico.",
      ig: 0.3, splits: [], question_source: "template" });
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Schemi da discutere col medico" })).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("it");
    expect(await screen.findByText("Una domanda che potrebbe aiutare il medico")).toBeInTheDocument();
    expect(nq).toHaveBeenCalledWith("it");
    expect(screen.queryByText("Mostra a cosa somiglia questo schema")).toBeNull();
    expect(screen.getByText("Questa non è una diagnosi.")).toBeInTheDocument();
    expect(screen.getByText("Segnale moderato")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sì" })).toBeInTheDocument();
    expect(screen.getByText(/2 volte, dal 1 mar al 5 mar/)).toBeInTheDocument();
  });

  it("review queue shows a lab row next to entities, in Italian", async () => {
    setLang("it");
    const lab: ReviewItem = {
      kind: "lab", id: "l1", entry_id: null, canonical: "Colesterolo totale", display: "Colesterolo totale: 264 mg/dL", value: "264 mg/dL",
      confidence: 0.55, source_excerpt: "Colesterolo totale   264 mg/dL   (0 - 200)", quote: null, flag: "high", page: 1, unit: "mg/dL",
      ref_low: 0, ref_high: 200,
    };
    const ent: ReviewItem = { kind: "entity", id: "x1", entry_id: "e1", display: "No Febbre", canonical: "Fever", value: "HP:0001945", confidence: 0.6,
      source_excerpt: "Forse ho un po' di febbre", quote: "febbre", hpo_label: "Fever", negated: true };
    vi.spyOn(api, "review").mockResolvedValue({ items: [ent, lab], count: 2 });
    const act = vi.spyOn(api, "reviewAct").mockResolvedValue({ ok: true, count: 1 });
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Da rivedere" })).toBeInTheDocument();
    expect(screen.getByText("Colesterolo totale: 264 mg/dL")).toBeInTheDocument();
    expect(screen.getByText(/intervallo stampato da 0 a 200 · Alto · Pagina 1/)).toBeInTheDocument();
    expect(screen.getByText("Assente: Febbre")).toBeInTheDocument();
    expect(screen.getAllByText("Lettura incerta")).toHaveLength(2);
    const buttons = screen.getAllByRole("button", { name: /Conferma/ });
    await userEvent.click(buttons[1]);
    expect(act).toHaveBeenCalledWith("lab", "l1", "confirm", undefined);
  });

  it("demo menu loads the Italian persona and switches the app to Italian", async () => {
    const demo = vi.spyOn(api, "demo").mockResolvedValue({ ok: true, entries: 19, persona: "giulia_it", lang: "it" });
    const loaded = vi.fn();
    render(<MemoryRouter><DemoMenu onLoaded={loaded} open /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Giulia (IT)" }));
    await userEvent.click(screen.getByRole("button", { name: "Load diary" }));
    await waitFor(() => expect(demo).toHaveBeenCalledWith("giulia_it"));
    await waitFor(() => expect(loaded).toHaveBeenCalled());
    expect(getLang()).toBe("it");
    expect(await screen.findByText("Caricate 19 note.")).toBeInTheDocument();
  });
});

describe("gpu reading", () => {
  it("reads the shape GET /api/system/gpu returns", () => {
    const g = { gpu_name: "AMD Instinct MI300X", util_pct: 61.4, vram_used_gb: 3, vram_total_gb: 192 };
    expect(gpuLoad(g)).toBe(61);
    expect(gpuName(g)).toBe("AMD Instinct MI300X");
    expect(gpuName({})).toBe("GPU");
  });
});
