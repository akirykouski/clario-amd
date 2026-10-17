import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { setLang } from "../i18n";

function stub(mode: "patient" | "clinic") {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    status: 200, ok: true,
    json: async () => (url.endsWith("/health") ? { ok: true, mode, llm: {}, demo_instance: false }
      : url.includes("/clinic/key") ? { public_key: "k", fingerprint: "ab:cd", clinic_name: "C" }
      : url.endsWith("/vault") ? { initialized: false, locked: true }
      : []),
  })));
}

beforeEach(() => {
  document.title = "Clario";
  delete document.documentElement.dataset.app;
  document.head.querySelectorAll("link[rel='icon']").forEach((n) => n.remove());
  const link = document.createElement("link");
  link.rel = "icon"; link.href = "/favicon-patient.svg";
  document.head.appendChild(link);
});
afterEach(() => { vi.unstubAllGlobals(); act(() => setLang("en")); });

const favicon = () => document.querySelector<HTMLLinkElement>("link[rel~='icon']")!.getAttribute("href");

describe("app identity", () => {
  it("clinic: role badge, data-app, tab title and favicon", async () => {
    stub("clinic");
    render(<MemoryRouter><App /></MemoryRouter>);
    const mark = await screen.findByTestId("app-mark");
    expect(mark).toHaveAttribute("data-role", "clinic");
    expect(mark).toHaveTextContent("Clario·Clinic");
    expect(document.documentElement.dataset.app).toBe("clinic");
    expect(document.title).toBe("Clario Clinic");
    expect(favicon()).toBe("/favicon-clinic.svg");
  });

  it("patient: role badge on the setup screen, data-app, tab title and favicon", async () => {
    stub("patient");
    render(<MemoryRouter initialEntries={["/setup"]}><App /></MemoryRouter>);
    const mark = await screen.findByTestId("app-mark");
    expect(mark).toHaveAttribute("data-role", "patient");
    expect(mark).toHaveTextContent("Clario·Patient");
    expect(document.documentElement.dataset.app).toBe("patient");
    expect(document.title).toBe("Clario Patient");
    expect(favicon()).toBe("/favicon-patient.svg");
  });

  it("Italian role names and tab title follow the language", async () => {
    stub("clinic");
    act(() => setLang("it"));
    render(<MemoryRouter><App /></MemoryRouter>);
    expect(await screen.findByTestId("app-mark")).toHaveTextContent("Clario·Clinica");
    await waitFor(() => expect(document.title).toBe("Clario Clinica"));
    act(() => setLang("en"));
    await waitFor(() => expect(document.title).toBe("Clario Clinic"));
  });
});
