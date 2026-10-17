// Speech-to-text core shared by the browser Web Worker (whisper.worker.ts) and the headless
// check (src/test/dictation.headless.test.ts). Audio stays in memory; only model files are fetched.

export const MODEL_ID = "onnx-community/whisper-base";
// q8 encoder (23 MB) + q8 merged decoder (54 MB): about 77 MB of model files, cached by the browser.
export const MODEL_DTYPE = { encoder_model: "q8", decoder_model_merged: "q8" } as const;
export const SAMPLE_RATE = 16000;

export type DictationLang = "en" | "it";

// Messages between the page and the worker.
export type ToWorker = { type: "load" } | { type: "transcribe"; id: number; audio: Float32Array; lang: DictationLang };
export type FromWorker =
  | { type: "progress"; loaded: number; total: number }
  | { type: "ready" }
  | { type: "result"; id: number; text: string }
  | { type: "error"; id?: number; message: string };

type ProgressInfo = { status: string; loaded?: number; total?: number };
type AsrOutput = { text: string } | { text: string }[];
export type AsrPipeline = (audio: Float32Array, options: Record<string, unknown>) => Promise<AsrOutput>;
export type PipelineFactory = (
  task: "automatic-speech-recognition",
  model: string,
  options: { dtype: typeof MODEL_DTYPE; device: string; progress_callback: (p: ProgressInfo) => void },
) => Promise<unknown>;

export function whisperLanguage(lang: DictationLang): string {
  return lang === "it" ? "italian" : "english";
}

/** Loads the pipeline once; later calls reuse the same promise. */
// device: "wasm" in the browser; the headless Node check passes "cpu" (onnxruntime-node), same model files.
export function createLoader(factory: PipelineFactory, onProgress: (loaded: number, total: number) => void, device = "wasm") {
  let pending: Promise<AsrPipeline> | null = null;
  return function load(): Promise<AsrPipeline> {
    if (!pending) {
      pending = factory("automatic-speech-recognition", MODEL_ID, {
        dtype: MODEL_DTYPE,
        device,
        progress_callback: (p) => {
          if (p.status === "progress_total" && typeof p.loaded === "number" && typeof p.total === "number") onProgress(p.loaded, p.total);
        },
      }).then((p) => p as AsrPipeline);
      pending.catch(() => { pending = null; });
    }
    return pending;
  };
}

export async function transcribe(pipe: AsrPipeline, audio: Float32Array, lang: DictationLang): Promise<string> {
  const out = await pipe(audio, {
    language: whisperLanguage(lang),
    task: "transcribe",
    chunk_length_s: 30,
    stride_length_s: 5,
  });
  const text = Array.isArray(out) ? out.map((o) => o.text).join(" ") : out.text;
  return text.replace(/\s+/g, " ").trim();
}

/** Downmixes channels and resamples linearly to 16 kHz. */
export function toMono16k(channels: Float32Array[], sampleRate: number): Float32Array {
  const n = channels[0]?.length ?? 0;
  const mono = new Float32Array(n);
  for (const ch of channels) for (let i = 0; i < n; i++) mono[i] += ch[i] / channels.length;
  if (sampleRate === SAMPLE_RATE) return mono;
  const ratio = sampleRate / SAMPLE_RATE;
  const outLen = Math.floor(n / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, n - 1);
    const frac = pos - i0;
    out[i] = mono[i0] * (1 - frac) + mono[i1] * frac;
  }
  return out;
}
