import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { api, ApiError, buildUrl, onLocked } from "../api";
import { initialRun, runReducer } from "../runReducer";
import { SignalPill } from "../components/ui";
import { FinalizeButton } from "../clinic/BriefPanel";
import { HeatStrip } from "../components/HeatStrip";
import { buildHeat, weekStart, splitQuotes } from "../lib";
import type { BriefItem, Brief } from "../types";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("builds urls and skips empty params", () => {
    expect(buildUrl("/entries", { since: "2026-01-01", until: undefined })).toBe("/api/entries?since=2026-01-01");
    expect(buildUrl("/clinic/key", { url: "http://x:8800/a b" })).toBe("/api/clinic/key?url=http%3A%2F%2Fx%3A8800%2Fa%20b");
    expect(buildUrl("/health")).toBe("/api/health");
  });
  it("calls the locked handler on 423", async () => {
    const h = vi.fn(); onLocked(h);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 423, ok: false, statusText: "Locked", json: async () => ({}) }));
    await expect(api.entries()).rejects.toMatchObject({ status: 423 });
    expect(h).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
  it("raises ApiError on 401 without redirect", async () => {
    const h = vi.fn(); onLocked(h);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 401, ok: false, statusText: "x", json: async () => ({ detail: "bad" }) }));
    const err = await api.unlock("x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(h).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
  it("sends JSON bodies", async () => {
    const f = vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", f);
    await api.setup("a long passphrase");
    expect(f).toHaveBeenCalledWith("/api/vault/setup", expect.objectContaining({ method: "POST", body: JSON.stringify({ passphrase: "a long passphrase" }) }));
    vi.unstubAllGlobals();
  });
});

describe("run reducer", () => {
  it("tracks progress, model, tokens/s and the final brief", () => {
    let s = runReducer(initialRun, { type: "start" });
    expect(s.status).toBe("running");
    s = runReducer(s, { type: "event", event: { stage: "draft", message: "Drafting", progress: 0.4, model: "gemma-4-31b", tokens_per_s: 42.5 } });
    expect(s).toMatchObject({ status: "running", progress: 0.4, model: "gemma-4-31b", tokensPerS: 42.5 });
    const brief = { package_id: "p", items: [] } as unknown as Brief;
    s = runReducer(s, { type: "event", event: { stage: "done", payload: brief } });
    expect(s.status).toBe("done"); expect(s.progress).toBe(1); expect(s.brief).toBe(brief); expect(s.model).toBe("gemma-4-31b");
  });
  it("handles error events and failures", () => {
    let s = runReducer(initialRun, { type: "start" });
    s = runReducer(s, { type: "event", event: { stage: "error", message: "boom" } });
    expect(s).toMatchObject({ status: "error", error: "boom" });
    expect(runReducer(initialRun, { type: "fail", error: "x" }).status).toBe("error");
  });
});

describe("signal pill", () => {
  it.each([["weak", "Weak signal"], ["moderate", "Moderate signal"], ["strong", "Strong signal"]] as const)("%s renders words", (sig, word) => {
    const { container } = render(<SignalPill signal={sig} />);
    expect(screen.getByText(word)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/%|\d/);
  });
});

const item = (id: string, review: BriefItem["review"]): BriefItem => ({ id, section: "summary", text: id, cites: [], origin: "ai", review });
describe("finalize button", () => {
  it("is disabled while any item is pending", () => {
    render(<FinalizeButton items={[item("a", "accepted"), item("b", "pending")]} onClick={() => {}} />);
    expect(screen.getByRole("button", { name: /finalize/i })).toBeDisabled();
    expect(screen.getByText(/1 item still need review/)).toBeInTheDocument();
  });
  it("is enabled once all are reviewed", () => {
    render(<FinalizeButton items={[item("a", "accepted"), item("b", "rejected"), item("c", "edited")]} onClick={() => {}} />);
    expect(screen.getByRole("button", { name: /finalize/i })).toBeEnabled();
  });
});

describe("heat strip", () => {
  const dates = { e1: "2026-03-02", e2: "2026-03-04", e3: "2026-03-17" }; // Mon, Wed, Tue two weeks later
  const terms = [{ hpo_id: "HP:1", label: "Fatigue", entry_ids: ["e1", "e2", "e3"], first_seen: "", last_seen: "", count: 3 },
                 { hpo_id: "HP:2", label: "Rash", entry_ids: ["e3"], first_seen: "", last_seen: "", count: 1 }];
  it("weekStart is Monday", () => { expect(weekStart("2026-03-04")).toBe("2026-03-02"); expect(weekStart("2026-03-08")).toBe("2026-03-02"); });
  it("buckets entries into continuous weeks", () => {
    const h = buildHeat(terms, dates);
    expect(h.weeks).toEqual(["2026-03-02", "2026-03-09", "2026-03-16"]);
    expect(h.rows[0].cells).toEqual([2, 0, 1]);
    expect(h.rows[1].cells).toEqual([0, 0, 1]);
    expect(h.max).toBe(2);
  });
  it("renders one cell per term and week", () => {
    render(<HeatStrip heat={buildHeat(terms, dates)} />);
    expect(screen.getAllByTestId("heat-cell")).toHaveLength(6);
  });
  it("handles empty input", () => { expect(buildHeat([], {}).rows).toEqual([]); });
});

describe("splitQuotes", () => {
  it("marks verbatim spans case-insensitively", () => {
    expect(splitQuotes("My knees hurt badly", ["knees hurt"])).toEqual([
      { text: "My ", quoted: false }, { text: "knees hurt", quoted: true }, { text: " badly", quoted: false }]);
  });
});
