/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.VITE_API_TARGET || "http://localhost:8765";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target, changeOrigin: true } } },
  build: { outDir: "dist" },
  // Dictation: transformers.js runs only inside the Whisper worker (its own chunk, loaded on the first mic tap).
  // ES worker format is needed for its dynamic imports; prebundling breaks its onnxruntime-web wasm loading in dev.
  worker: { format: "es" },
  optimizeDeps: { exclude: ["@huggingface/transformers"] },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: false },
});
