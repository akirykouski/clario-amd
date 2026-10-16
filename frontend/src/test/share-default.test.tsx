import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api";
import { resetHealthCache } from "../components/useHealth";
import SharePage from "../patient/SharePage";

afterEach(() => { vi.restoreAllMocks(); resetHealthCache(); try { localStorage.clear(); } catch { /* ignore */ } });

describe("share page clinic address", () => {
  it("takes the server preset (CLARIO_CLINIC_URL) from health", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, mode: "patient", llm: {}, clinic_url: "https://clinic.example.org" });
    render(<MemoryRouter><SharePage /></MemoryRouter>);
    await waitFor(() => expect((screen.getByRole("textbox", { name: /address/i }) as HTMLInputElement).value).toBe("https://clinic.example.org"));
  });
  it("falls back to localhost:8800 when the server has none", async () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, mode: "patient", llm: {}, clinic_url: null });
    render(<MemoryRouter><SharePage /></MemoryRouter>);
    await waitFor(() => expect(api.health).toHaveBeenCalled());
    expect((screen.getByRole("textbox", { name: /address/i }) as HTMLInputElement).value).toBe("http://localhost:8800");
  });
});
