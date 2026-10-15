import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { DEMO_TEXT } from "../patient/DemoBanner";

afterEach(() => { vi.unstubAllGlobals(); });

function stubHealth(demo: boolean) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    status: 200, ok: true,
    json: async () => (url.endsWith("/health")
      ? { ok: true, mode: "clinic", llm: {}, demo_instance: demo }
      : url.includes("/clinic/key") ? { public_key: "k", fingerprint: "ab:cd", clinic_name: "C" } : []),
  })));
}

describe("demo banner", () => {
  it("shows when health says demo_instance", async () => {
    stubHealth(true);
    render(<MemoryRouter><App /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("demo-banner")).toBeTruthy());
    expect(screen.getByTestId("demo-banner").textContent).toContain(DEMO_TEXT);
  });
  it("is absent otherwise", async () => {
    stubHealth(false);
    render(<MemoryRouter><App /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Clinic")).toBeTruthy());
    expect(screen.queryByTestId("demo-banner")).toBeNull();
  });
});
