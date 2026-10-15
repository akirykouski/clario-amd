/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.VITE_API_TARGET || "http://localhost:8765";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target, changeOrigin: true } } },
  build: { outDir: "dist" },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: false },
});
