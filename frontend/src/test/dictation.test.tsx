import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { setLang } from "../i18n";
import { api } from "../api";
import type { FromWorker, PipelineFactory, ToWorker } from "../patient/dictation/core";
import { createLoader, toMono16k, transcribe, MODEL_ID } from "../patient/dictation/core";

// The browser glue (microphone, MediaRecorder, AudioContext, Worker) is replaced: no model, no audio.
const engine = vi.hoisted(() => ({
  supported: true,
  permission: "unknown" as "denied" | "unknown",
  startError: null as Error | null,
  workers: [] as FakeWorker[],
}));

class FakeWorker {
  posted: ToWorker[] = [];
  onmessage: ((e: MessageEvent<FromWorker>) => void) | null = null;
  onerror: (() => void) | null = null;
  terminate = vi.fn();
  postMessage(m: ToWorker) { this.posted.push(m); }
  emit(m: FromWorker) { act(() => { this.onmessage?.({ data: m } as MessageEvent<FromWorker>); }); }
}

vi.mock("../patient/dictation/engine", () => ({
  dictationSupported: () => engine.supported,
  micPermission: async () => engine.permission,
  createWorker: () => { const w = new FakeWorker(); engine.workers.push(w); return w; },
  startRecording: async () => {
    if (engine.startError) throw engine.startError;
    return { stop: async () => new Blob(["x"]), cancel: vi.fn() };
  },
  decodeTo16k: async () => new Float32Array(16000),
}));

import { DictationButton } from "../patient/dictation/Dictation";
import Today from "../patient/Today";

function Harness() {
  return <DictationButton onText={(s) => { document.getElementById("out")!.textContent = s; }} />;
}

beforeEach(() => {
  engine.supported = true; engine.permission = "unknown"; engine.startError = null; engine.workers = [];
  setLang("en");
});
afterEach(() => { vi.restoreAllMocks(); setLang("en"); });

const mic = () => screen.getByRole("button", { name: /speak your note|stop and turn|detta la nota|ferma/i });
const lastTranscribe = (w: FakeWorker) => w.posted.filter((m) => m.type === "transcribe").pop() as Extract<ToWorker, { type: "transcribe" }>;

describe("dictation button", () => {
  it("downloads nothing until the first tap", async () => {
    render(<Harness />);
    expect(screen.getByText(/audio is not sent anywhere/i)).toBeInTheDocument();
    await act(async () => {});
    expect(engine.workers).toHaveLength(0);
    expect(mic()).toBeEnabled();
  });

  it("is disabled with a reason when the browser cannot record", () => {
    engine.supported = false;
    render(<Harness />);
    const b = screen.getByRole("button", { name: /does not work in this browser/i });
    expect(b).toBeDisabled();
    expect(b.closest("span")).toHaveAttribute("title", expect.stringMatching(/does not work in this browser/i));
  });

  it("is disabled when the microphone is already blocked", async () => {
    engine.permission = "denied";
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: /microphone is blocked/i })).toBeDisabled());
  });

  it("walks recording, first-time preparing with progress, transcribing, then hands over the text", async () => {
    render(<><Harness /><p id="out" /></>);
    await act(async () => { fireEvent.click(mic()); });
    expect(screen.getByRole("status")).toHaveTextContent(/listening/i);
    const w = engine.workers[0];
    expect(w.posted[0]).toEqual({ type: "load" });
    w.emit({ type: "progress", loaded: 25, total: 100 });

    await act(async () => { fireEvent.click(mic()); });
    expect(screen.getByRole("status")).toHaveTextContent("Preparing speech model (first time only), 25%");
    const job = lastTranscribe(w);
    expect(job.lang).toBe("en");
    expect(job.audio).toBeInstanceOf(Float32Array);

    w.emit({ type: "ready" });
    expect(screen.getByRole("status")).toHaveTextContent(/turning speech into text/i);
    w.emit({ type: "result", id: job.id, text: "Headache since the morning." });
    expect(document.getElementById("out")!.textContent).toBe("Headache since the morning.");
    expect(screen.queryByRole("status")).toBeNull();

    // Second recording: the model is ready, so it goes straight to transcribing, same worker.
    await act(async () => { fireEvent.click(mic()); });
    await act(async () => { fireEvent.click(mic()); });
    expect(screen.getByRole("status")).toHaveTextContent(/turning speech into text/i);
    expect(engine.workers).toHaveLength(1);
  });

  it("follows the Italian UI language", async () => {
    setLang("it");
    render(<Harness />);
    expect(screen.getByText(/audio non viene inviato/i)).toBeInTheDocument();
    await act(async () => { fireEvent.click(mic()); });
    expect(screen.getByRole("status")).toHaveTextContent(/ti ascolto/i);
    await act(async () => { fireEvent.click(mic()); });
    expect(lastTranscribe(engine.workers[0]).lang).toBe("it");
  });

  it("turns a refused permission into a disabled button", async () => {
    engine.startError = Object.assign(new Error("no"), { name: "NotAllowedError" });
    render(<Harness />);
    await act(async () => { fireEvent.click(mic()); });
    expect(screen.getByRole("button", { name: /microphone is blocked/i })).toBeDisabled();
  });

  it("says so when nothing was heard or the model failed", async () => {
    render(<Harness />);
    await act(async () => { fireEvent.click(mic()); });
    await act(async () => { fireEvent.click(mic()); });
    const w = engine.workers[0];
    w.emit({ type: "result", id: lastTranscribe(w).id, text: "" });
    expect(screen.getByRole("status")).toHaveTextContent(/no speech heard/i);
    await act(async () => { fireEvent.click(mic()); });
    await act(async () => { fireEvent.click(mic()); });
    w.emit({ type: "error", id: lastTranscribe(w).id, message: "boom" });
    expect(screen.getByRole("status")).toHaveTextContent(/could not turn the speech into text/i);
    expect(mic()).toBeEnabled();
  });
});

describe("today page", () => {
  it("puts the transcript in the note field, after any typed text, for editing before save", async () => {
    vi.spyOn(api, "entries").mockResolvedValue([]);
    vi.spyOn(api, "privacyCounts").mockResolvedValue({});
    const add = vi.spyOn(api, "addEntry");
    render(<MemoryRouter><Today /></MemoryRouter>);
    const box = screen.getByLabelText(/how was today/i) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Tired." } });
    await act(async () => { fireEvent.click(mic()); });
    await act(async () => { fireEvent.click(mic()); });
    const w = engine.workers[0];
    w.emit({ type: "ready" });
    w.emit({ type: "result", id: lastTranscribe(w).id, text: "Knees hurt after the walk." });
    expect(box.value).toBe("Tired. Knees hurt after the walk.");
    expect(add).not.toHaveBeenCalled();
  });
});

describe("core", () => {
  it("loads the pipeline once and reports total progress", async () => {
    const pipe = vi.fn();
    const factory = vi.fn(async (_t: string, _m: string, o: { progress_callback: (p: object) => void }) => {
      o.progress_callback({ status: "progress", loaded: 1, total: 2 });
      o.progress_callback({ status: "progress_total", loaded: 5, total: 10 });
      return pipe;
    });
    const seen: number[][] = [];
    const load = createLoader(factory as unknown as PipelineFactory, (l, t) => seen.push([l, t]));
    expect(await load()).toBe(pipe);
    await load();
    expect(factory).toHaveBeenCalledTimes(1);
    expect(factory.mock.calls[0][1]).toBe(MODEL_ID);
    expect(seen).toEqual([[5, 10]]);
  });

  it("asks Whisper for the chosen language and tidies the text", async () => {
    const pipe = vi.fn(async (_a: Float32Array, _o: Record<string, unknown>) => ({ text: "  Mal di  testa \n da ieri. " }));
    expect(await transcribe(pipe, new Float32Array(4), "it")).toBe("Mal di testa da ieri.");
    expect(pipe.mock.calls[0][1]).toMatchObject({ language: "italian", task: "transcribe" });
  });

  it("downmixes to mono and resamples to 16 kHz", () => {
    const l = new Float32Array(48000).fill(1);
    const r = new Float32Array(48000).fill(0);
    const out = toMono16k([l, r], 48000);
    expect(out.length).toBe(16000);
    expect(out[100]).toBeCloseTo(0.5);
    expect(toMono16k([new Float32Array([0.2, 0.4])], 16000)).toEqual(new Float32Array([0.2, 0.4]));
  });
});
