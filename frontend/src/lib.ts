import type { BriefItem, Evidence, Signal } from "./types";

export const signalWord: Record<Signal, string> = {
  weak: "Weak signal", moderate: "Moderate signal", strong: "Strong signal",
};

export function canFinalize(items: BriefItem[]): boolean {
  return items.length > 0 && !items.some((i) => i.review === "pending");
}

// ---- heat strip math ----
export function weekStart(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  const dow = (d.getUTCDay() + 6) % 7; // Monday = 0
  d.setUTCDate(d.getUTCDate() - dow);
  return d.toISOString().slice(0, 10);
}

export interface HeatModel { weeks: string[]; rows: { hpo_id: string; label: string; cells: number[]; max: number }[]; max: number }

/** entryDates maps entry id -> occurred_on. Cell = number of distinct entries with the term in that week. */
export function buildHeat(terms: Evidence[], entryDates: Record<string, string>): HeatModel {
  const all: string[] = [];
  const perRow = terms.map((t) => {
    const counts = new Map<string, number>();
    for (const id of new Set(t.entry_ids)) {
      const d = entryDates[id];
      if (!d) continue;
      const w = weekStart(d);
      counts.set(w, (counts.get(w) ?? 0) + 1);
      all.push(w);
    }
    return { t, counts };
  });
  if (all.length === 0) return { weeks: [], rows: [], max: 0 };
  const sorted = [...all].sort();
  const weeks: string[] = [];
  const end = new Date(sorted[sorted.length - 1] + "T00:00:00Z");
  for (let d = new Date(sorted[0] + "T00:00:00Z"); d <= end; d.setUTCDate(d.getUTCDate() + 7)) {
    weeks.push(d.toISOString().slice(0, 10));
  }
  let max = 0;
  const rows = perRow.map(({ t, counts }) => {
    const cells = weeks.map((w) => counts.get(w) ?? 0);
    const m = Math.max(0, ...cells);
    max = Math.max(max, m);
    return { hpo_id: t.hpo_id, label: t.label, cells, max: m };
  });
  return { weeks, rows, max };
}

// ---- quote highlighting ----
export interface Seg { text: string; quoted: boolean }
export function splitQuotes(text: string, quotes: string[]): Seg[] {
  const ranges: [number, number][] = [];
  const lower = text.toLowerCase();
  for (const q of quotes) {
    if (!q) continue;
    const i = lower.indexOf(q.toLowerCase());
    if (i >= 0) ranges.push([i, i + q.length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  const out: Seg[] = [];
  let pos = 0;
  for (const [a, b] of merged) {
    if (a > pos) out.push({ text: text.slice(pos, a), quoted: false });
    out.push({ text: text.slice(a, b), quoted: true });
    pos = b;
  }
  if (pos < text.length) out.push({ text: text.slice(pos), quoted: false });
  return out;
}

export function fmtDate(iso: string, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }): string {
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", opts);
}
export function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
export function daysAgo(n: number): string {
  const d = new Date(); d.setDate(d.getDate() - n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
export const flagNote: Record<string, string> = {
  hpo_dropped: "Ontology code removed: it did not match your words.",
  negation_from_text: "Marked as absent because your words say you do not have it.",
  family_history_from_text: "Marked as a relative's, not yours.",
  quote_not_found: "We could not find these exact words in your note.",
};

/** Confidence as a whole-number percent for the bar; null when it was not measured. */
export function confidencePct(c: number | null): number | null {
  return c === null ? null : Math.round(Math.max(0, Math.min(1, c)) * 100);
}

/** How each id moved between two orderings: negative = moved up, positive = moved down. Ids missing from either are skipped. */
export function reorderDelta(before: string[], after: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const id of after) {
    const b = before.indexOf(id);
    if (b >= 0) out[id] = after.indexOf(id) - b;
  }
  return out;
}
