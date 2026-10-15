import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CloudSawView, highlightSegments } from "../patient/CloudSaw";
import { CallRow, ChainStatus } from "../patient/PrivacyPage";
import { buildUrl } from "../api";
import type { AiCall, PrivacyPreview } from "../types";

const preview: PrivacyPreview = {
  original: "Giulia here. Knees ache 6/10.", redacted: "[NAME] here. Knees ache 6/10.", applied: true, backend: "amd-vllm",
  replacements: [{ type: "name", start: 0, end: 6, out_start: 0, out_end: 6 }],
};

describe("highlightSegments", () => {
  it("cuts text at spans and keeps the rest", () => {
    expect(highlightSegments("Hi Anna, ok", [{ start: 3, end: 7, type: "name" }])).toEqual([
      { text: "Hi " }, { text: "Anna", kind: "name" }, { text: ", ok" }]);
  });
  it("handles no spans and spans at the edges", () => {
    expect(highlightSegments("plain", [])).toEqual([{ text: "plain" }]);
    expect(highlightSegments("[DATE]", [{ start: 0, end: 6, type: "date" }])).toEqual([{ text: "[DATE]", kind: "date" }]);
  });
});

describe("what the cloud saw", () => {
  it("shows both columns with replacements highlighted", () => {
    render(<CloudSawView p={preview} />);
    expect(screen.getByTestId("cloud-original").textContent).toContain("Giulia here");
    expect(screen.getByTestId("cloud-sent").textContent).toContain("[NAME] here");
    expect(screen.getByTestId("cloud-sent").textContent).not.toContain("Giulia");
    expect(screen.getByTestId("cloud-sent").querySelectorAll("mark.redact")).toHaveLength(1);
    expect(screen.getByTestId("cloud-original").querySelectorAll("mark.redact")).toHaveLength(1);
    expect(screen.getByText(/1 personal detail is replaced/)).toBeInTheDocument();
  });
  it("explains when nothing leaves the device", () => {
    render(<CloudSawView p={{ ...preview, applied: false }} />);
    expect(screen.getByText(/runs on this device/)).toBeInTheDocument();
  });
});

describe("call log view", () => {
  const call: AiCall = {
    id: "call_000002", seq: 2, ts: "2026-10-15T10:00:00.000+00:00", backend: "amd-vllm", model: "gemma-4-31b", purpose: "extract",
    redacted_preview: "[NAME] here", payload_sha256: "a", prev_hash: "b", hash: "c", redacted: true, replacements: 2, images: 0,
  };
  it("shows backend, model and redaction count", () => {
    render(<ul><CallRow c={call} /></ul>);
    expect(screen.getByText(/amd-vllm, gemma-4-31b/)).toBeInTheDocument();
    expect(screen.getByText(/2 details replaced/)).toBeInTheDocument();
  });
  it("reports verified and broken chains", () => {
    const { unmount } = render(<ChainStatus v={{ ok: true, broken_at: null, count: 3 }} />);
    expect(screen.getByRole("status").textContent).toMatch(/verified.*3 calls/i);
    unmount();
    render(<ChainStatus v={{ ok: false, broken_at: "call_000002", count: 3 }} />);
    expect(screen.getByRole("alert").textContent).toContain("broken at call_000002");
  });
  it("builds the privacy urls", () => {
    expect(buildUrl("/privacy/preview", { entry_id: "e_1" })).toBe("/api/privacy/preview?entry_id=e_1");
  });
});
