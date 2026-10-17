// @vitest-environment node
// Opt-in check that runs real Whisper through the same core the browser worker uses.
// Downloads the model (about 77 MB) once, so it is skipped unless asked for:
//   DICTATION_WAV_EN=en.wav DICTATION_WAV_IT=it.wav npx vitest run src/test/dictation.headless.test.ts
// WAV files: 16-bit PCM, e.g. `say -o x.aiff "..."; afconvert -f WAVE -d LEI16@16000 -c 1 x.aiff x.wav`.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { createLoader, toMono16k, transcribe, type DictationLang, type PipelineFactory } from "../patient/dictation/core";

const files: [DictationLang, string | undefined][] = [["en", process.env.DICTATION_WAV_EN], ["it", process.env.DICTATION_WAV_IT]];
const wanted = files.filter(([, f]) => !!f) as [DictationLang, string][];

function readWav(path: string): Float32Array {
  const b = readFileSync(path);
  let off = 12, rate = 16000, channels = 1, bits = 16;
  while (off < b.length - 8) {
    const id = b.toString("ascii", off, off + 4);
    const size = b.readUInt32LE(off + 4);
    if (id === "fmt ") { channels = b.readUInt16LE(off + 10); rate = b.readUInt32LE(off + 12); bits = b.readUInt16LE(off + 22); }
    if (id === "data") {
      if (bits !== 16) throw new Error("16-bit PCM WAV expected");
      const frames = Math.floor(size / 2 / channels);
      const chans = Array.from({ length: channels }, () => new Float32Array(frames));
      for (let i = 0; i < frames; i++) for (let c = 0; c < channels; c++) chans[c][i] = b.readInt16LE(off + 8 + (i * channels + c) * 2) / 32768;
      return toMono16k(chans, rate);
    }
    off += 8 + size + (size % 2);
  }
  throw new Error("no data chunk");
}

describe.skipIf(wanted.length === 0)("headless Whisper", () => {
  it("transcribes the given WAV files", async () => {
    const { pipeline, env } = await import("@huggingface/transformers");
    if (process.env.DICTATION_CACHE_DIR) env.cacheDir = process.env.DICTATION_CACHE_DIR;
    const load = createLoader(pipeline as unknown as PipelineFactory, () => {}, "cpu");
    const pipe = await load();
    for (const [lang, path] of wanted) {
      const t0 = Date.now();
      const text = await transcribe(pipe, readWav(path), lang);
      console.log(`[${lang}] ${((Date.now() - t0) / 1000).toFixed(1)} s: ${text}`);
      expect(text.length).toBeGreaterThan(0);
    }
  }, 600_000);
});
