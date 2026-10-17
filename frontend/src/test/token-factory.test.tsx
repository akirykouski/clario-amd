import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { api } from "../api";
import { ComputeBadge } from "../clinic/ClinicApp";
import { RunChips } from "../clinic/BriefPanel";
import { modelName, tokenFactoryLabel } from "../components/compute";

afterEach(() => vi.restoreAllMocks());

const tfHealth = { backend: "amd-token-factory", model: "Gemma-4-31B-IT", base_url_host: "developer.amd.com.cn", is_amd: true };

describe("AMD Token Factory label", () => {
  it("names the Gemma 4 model in plain words", () => {
    expect(modelName("Gemma-4-31B-IT")).toBe("Gemma 4 31B");
    expect(modelName("gemma4:e4b")).toBe("Gemma 4 E4B");
    expect(modelName("other-model")).toBe("other-model");
    expect(tokenFactoryLabel("amd-token-factory", "Gemma-4-31B-IT")).toBe("Gemma 4 31B · AMD Token Factory");
    expect(tokenFactoryLabel("amd-vllm", "Gemma-4-31B-IT")).toBeNull();
  });

  it("clinic header says Token Factory, not our own GPU", () => {
    render(<ComputeBadge llm={tfHealth} />);
    expect(screen.getByText("Gemma 4 31B · AMD Token Factory")).toBeInTheDocument();
    expect(screen.queryByText(/MI300X|vLLM/)).toBeNull();
  });

  it("own vLLM on AMD keeps its label", () => {
    render(<ComputeBadge llm={{ backend: "amd-vllm", model: "google/gemma-4-31B-it", is_amd: true }} />);
    expect(screen.getByText("AMD Instinct MI300X · vLLM")).toBeInTheDocument();
  });

  it("run chips show the Token Factory label and no GPU chip without telemetry", async () => {
    const gpu = vi.spyOn(api, "gpu").mockResolvedValue(null);
    render(<RunChips backend="amd-token-factory" model="Gemma-4-31B-IT" tokensPerS={30} latencyMs={1200} />);
    const chips = await screen.findByTestId("run-chips");
    expect(chips).toHaveTextContent("Gemma 4 31B · AMD Token Factory");
    expect(chips).toHaveTextContent("tokens/s");
    await vi.waitFor(() => expect(gpu).toHaveBeenCalled());
    expect(chips).not.toHaveTextContent("GPU");
  });
});
