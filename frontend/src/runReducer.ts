import type { Brief, RunEvent } from "./types";

export interface RunState {
  status: "idle" | "running" | "done" | "error";
  stage: string; message: string; progress: number;
  model?: string; backend?: string; tokensPerS?: number; latencyMs?: number;
  brief?: Brief; error?: string;
}

export const initialRun: RunState = { status: "idle", stage: "", message: "", progress: 0 };

export type RunAction = { type: "start" } | { type: "event"; event: RunEvent } | { type: "fail"; error: string };

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "start":
      return { ...initialRun, status: "running", message: "Starting" };
    case "fail":
      return { ...state, status: "error", error: action.error };
    case "event": {
      const e = action.event;
      const base: RunState = {
        ...state,
        stage: e.stage ?? state.stage,
        message: e.message ?? state.message,
        progress: typeof e.progress === "number" ? Math.max(0, Math.min(1, e.progress)) : state.progress,
        model: e.model ?? state.model,
        backend: e.backend ?? state.backend,
        tokensPerS: typeof e.tokens_per_s === "number" ? e.tokens_per_s : state.tokensPerS,
        latencyMs: typeof e.latency_ms === "number" ? e.latency_ms : state.latencyMs,
      };
      if (e.stage === "done") {
        return { ...base, status: "done", progress: 1, brief: (e.payload as Brief) ?? state.brief };
      }
      if (e.stage === "error") {
        return { ...base, status: "error", error: e.message ?? "Drafting failed" };
      }
      return { ...base, status: "running" };
    }
  }
}
