// Browser glue for dictation: support checks, microphone, recording, decoding, worker.
// Tests replace this module with a mock, so nothing here runs under jsdom.
import { SAMPLE_RATE, toMono16k } from "./core";

export function dictationSupported(): boolean {
  if (typeof window === "undefined" || !window.isSecureContext) return false;
  return !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined" && typeof Worker !== "undefined"
    && typeof AudioContext !== "undefined";
}

/** "denied" when the browser already knows the user blocked the microphone, else "unknown". */
export async function micPermission(): Promise<"denied" | "unknown"> {
  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    return status.state === "denied" ? "denied" : "unknown";
  } catch {
    return "unknown";
  }
}

export function createWorker(): Worker {
  return new Worker(new URL("./whisper.worker.ts", import.meta.url), { type: "module" });
}

export type Recording = { stop: () => Promise<Blob>; cancel: () => void };

export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  const release = () => stream.getTracks().forEach((t) => t.stop());
  recorder.start();
  return {
    stop: () => new Promise<Blob>((resolve) => {
      recorder.onstop = () => { release(); resolve(new Blob(chunks, { type: recorder.mimeType })); };
      recorder.stop();
    }),
    cancel: () => { recorder.onstop = release; if (recorder.state !== "inactive") recorder.stop(); else release(); },
  };
}

/** Decodes a recording to 16 kHz mono Float32, the input Whisper expects. */
export async function decodeTo16k(blob: Blob): Promise<Float32Array> {
  const bytes = await blob.arrayBuffer();
  const ac = new AudioContext({ sampleRate: SAMPLE_RATE });
  try {
    const buf = await ac.decodeAudioData(bytes);
    const channels = Array.from({ length: buf.numberOfChannels }, (_, i) => buf.getChannelData(i));
    return toMono16k(channels, buf.sampleRate);
  } finally {
    void ac.close();
  }
}
