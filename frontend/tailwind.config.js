/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)", panel: "var(--panel)", ink: "var(--ink)", muted: "var(--muted)",
        line: "var(--line)", accent: "var(--accent)", "accent-ink": "var(--accent-ink)",
        weak: "var(--weak)", moderate: "var(--moderate)", strong: "var(--strong)", mark: "var(--mark)",
        aqua: "var(--aqua)", lilac: "var(--lilac)", coral: "var(--coral)",
      },
      fontFamily: {
        display: ["'Funnel Display'", "system-ui", "sans-serif"],
        sans: ["'Funnel Sans'", "system-ui", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
