import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import ImportPage from "../patient/ImportPage";
import type { BatchEvent, Health } from "../types";

class FakeSource {
  static last: FakeSource | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { FakeSource.last = this; }
  close() {}
  emit(e: BatchEvent) { this.onmessage?.({ data: JSON.stringify(e) }); }
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("sample referti import", () => {
  it("says the sample results were read earlier and shows no speed or reader", async () => {
    vi.stubGlobal("EventSource", FakeSource);
    vi.spyOn(api, "health").mockResolvedValue({ llm: { backend: "amd-token-factory", model: "Gemma-4-31B-IT" } } as unknown as Health);
    vi.spyOn(api, "demoDocuments").mockResolvedValue({ batch_id: "b_1", pages: 3, entry_id: "e_1" });
    render(<MemoryRouter initialEntries={["/import?samples=1"]}><ImportPage /></MemoryRouter>);
    await vi.waitFor(() => expect(FakeSource.last).not.toBeNull());
    act(() => FakeSource.last!.emit({ batch_id: "b_1", pages_done: 3, pages_total: 3, pages_per_sec: 0, gpu: null, errors: 0, labs: 48,
                            needs_review: 0, done: true, elapsed_s: 0, backend: "amd-token-factory", model: null, precomputed: true }));
    expect(await screen.findByTestId("precomputed")).toHaveTextContent("read earlier on AMD Token Factory");
    expect(screen.queryByTestId("pps")).toBeNull();
    expect(screen.queryByTestId("reader")).toBeNull();
  });
});
