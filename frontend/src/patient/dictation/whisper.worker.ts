/// <reference lib="webworker" />
// Runs Whisper off the main thread. Audio arrives by postMessage and never leaves this worker;
// the only network traffic is the model files (huggingface.co) and the ONNX runtime (jsDelivr).
import { env, pipeline } from "@huggingface/transformers";
import { createLoader, transcribe, type FromWorker, type PipelineFactory, type ToWorker } from "./core";

env.allowLocalModels = false;
env.useBrowserCache = true;

const ctx = self as unknown as DedicatedWorkerGlobalScope;
const post = (m: FromWorker) => ctx.postMessage(m);

const load = createLoader(pipeline as unknown as PipelineFactory, (loaded, total) => post({ type: "progress", loaded, total }));

async function ready() {
  const pipe = await load();
  post({ type: "ready" });
  return pipe;
}

ctx.onmessage = async (e: MessageEvent<ToWorker>) => {
  const msg = e.data;
  try {
    if (msg.type === "load") { await ready(); return; }
    const pipe = await ready();
    const text = await transcribe(pipe, msg.audio, msg.lang);
    post({ type: "result", id: msg.id, text });
  } catch (err) {
    post({ type: "error", id: msg.type === "transcribe" ? msg.id : undefined, message: (err as Error).message || String(err) });
  }
};
