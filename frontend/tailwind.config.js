/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)", panel: "var(--panel)", ink: "var(--ink)", muted: "var(--muted)",
        line: "var(--line)", accent: "var(--accent)", "accent-ink": "var(--accent-ink)",
        weak: "var(--weak)", moderate: "var(--moderate)", strong: "var(--strong)", mark: "var(--mark)",
      },
      fontFamily: {
        display: ["Newsreader", "Georgia", "serif"],
        sans: ["'Atkinson Hyperlegible'", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
