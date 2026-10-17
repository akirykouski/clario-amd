import { getLang, t, type Key } from "./i18n";
import type { BriefItem, Evidence } from "./types";

/** Fired whenever the review queue may have changed (extraction finished, a decision, an import), so the nav badge refetches. */
export const REVIEW_EVENT = "clario-review-changed";
export function notifyReview(): void {
  window.dispatchEvent(new Event(REVIEW_EVENT));
}

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

export interface HeatRow { hpo_id: string; label: string; group: string; cells: number[]; entryIds: string[][]; max: number }
export interface HeatModel { weeks: string[]; rows: HeatRow[]; max: number }

/** Organ-system groups in display order (keys from GET /api/terms/systems). */
export const SYSTEM_ORDER = ["skin", "joints", "kidney", "blood", "immune", "nervous", "heart", "lungs", "digestive", "eye",
  "endocrine", "metabolism", "head", "general", "other"];
export const SYSTEM_COLOR: Record<string, string> = {
  skin: "#C2410C", joints: "#1D4ED8", kidney: "#7C3AED", blood: "#B91C1C", immune: "#0F766E", nervous: "#A16207",
  heart: "#BE185D", lungs: "#0369A1", digestive: "#4D7C0F", eye: "#6D28D9", endocrine: "#9333EA", metabolism: "#57534E",
  head: "#C2410C", general: "#64748B", other: "#64748B",
};

/** entryDates maps entry id -> occurred_on. Cell = number of distinct entries with the term in that week.
 * With `systems` (hpo id -> organ-system key) rows are grouped by system, then sorted by how often they appear. */
export function buildHeat(terms: Evidence[], entryDates: Record<string, string>, systems?: Record<string, string>): HeatModel {
  const all: string[] = [];
  const perRow = terms.map((t) => {
    const byWeek = new Map<string, string[]>();
    for (const id of new Set(t.entry_ids)) {
      const d = entryDates[id];
      if (!d) continue;
      const w = weekStart(d);
      byWeek.set(w, [...(byWeek.get(w) ?? []), id]);
      all.push(w);
    }
    return { t, byWeek };
  });
  if (all.length === 0) return { weeks: [], rows: [], max: 0 };
  const sorted = [...all].sort();
  const weeks: string[] = [];
  const end = new Date(sorted[sorted.length - 1] + "T00:00:00Z");
  for (let d = new Date(sorted[0] + "T00:00:00Z"); d <= end; d.setUTCDate(d.getUTCDate() + 7)) {
    weeks.push(d.toISOString().slice(0, 10));
  }
  let max = 0;
  const rows: HeatRow[] = perRow.map(({ t, byWeek }) => {
    const entryIds = weeks.map((w) => byWeek.get(w) ?? []);
    const cells = entryIds.map((ids) => ids.length);
    const m = Math.max(0, ...cells);
    max = Math.max(max, m);
    return { hpo_id: t.hpo_id, label: t.label, group: systems?.[t.hpo_id] ?? "other", cells, entryIds, max: m };
  });
  if (systems) {
    const rank = (g: string) => { const i = SYSTEM_ORDER.indexOf(g); return i < 0 ? SYSTEM_ORDER.length : i; };
    const total = (r: HeatRow) => r.cells.reduce((a, b) => a + b, 0);
    rows.sort((a, b) => rank(a.group) - rank(b.group) || total(b) - total(a));
  }
  return { weeks, rows, max };
}

/** Average mood per heat-map week (null when no note that week had a mood). */
export function weeklyMood(weeks: string[], entries: { occurred_on: string; mood: number | null }[]): (number | null)[] {
  return weeks.map((w) => {
    const ms = entries.filter((e) => e.mood !== null && weekStart(e.occurred_on) === w).map((e) => e.mood as number);
    return ms.length ? Math.round((ms.reduce((a, b) => a + b, 0) / ms.length) * 10) / 10 : null;
  });
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

/** BCP 47 locale for dates and numbers in the current UI language. */
export function locale(): string {
  return getLang() === "it" ? "it-IT" : "en-GB";
}
/** A number in the UI language: decimal comma in Italian. `digits` fixes the fraction digits; without it up to 3 are kept. */
export function fmtNum(n: number, digits?: number): string {
  const o: Intl.NumberFormatOptions = digits === undefined
    ? { useGrouping: false, maximumFractionDigits: 3 }
    : { useGrouping: false, minimumFractionDigits: digits, maximumFractionDigits: digits };
  return new Intl.NumberFormat(locale(), o).format(n);
}
/** A plain decimal string from the server ("5.4") shown in the UI language ("5,4"); any other text is returned as is. */
export function fmtNumText(s: string): string {
  // Plain decimals inside text ("0.39 mg/dL") follow the locale; ratios such as "1:80" have no decimal point and stay.
  return s.replace(/-?\d+\.\d+/g, (m) => fmtNum(Number(m)));
}
/** Dates in the current year read "2 Nov"; any other year adds it ("2 Nov 2025"), so a past date never looks like a future one. */
export function fmtDate(iso: string, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }, forceNoYear = false): string {
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  if (isNaN(d.getTime())) return iso;
  const o = { ...opts };
  const named = o.dateStyle || o.timeStyle;
  if (!named && !forceNoYear && o.day && o.month && (!o.year || o.year === "2-digit")) {
    if (o.year === "2-digit" || d.getFullYear() !== new Date().getFullYear()) o.year = "numeric";
  }
  return new Intl.DateTimeFormat(locale(), o).format(d);
}
/** Lab units as they are printed on a report: "10^3/uL" -> "10³/µL", "ug/dL" -> "µg/dL". */
export function prettyUnit(u: string): string {
  const sup: Record<string, string> = { "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹" };
  return u.replace(/10\^(\d+)/g, (_, d: string) => "10" + [...d].map((c) => sup[c]).join(""))
    .replace(/\bu(?=[A-Za-z]{1,2}\b|L\b)/g, "µ").replace(/\bmcg\b/g, "µg");
}

export function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
export function daysAgo(n: number): string {
  const d = new Date(); d.setDate(d.getDate() - n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
/** Flags a patient may read about, in plain words. Technical ones (hpo_dropped, no_hpo, onset_dropped, fixed_by_*)
 *  stay on the clinic side (`clinicFlagNote`). */
const PATIENT_FLAGS = ["negation_from_text", "family_history_from_text", "quote_not_found"];
/** Plain-words note for a flag the extractor set on an entity, or null when the patient should not see it. */
export function flagNote(flag: string): string | null {
  return PATIENT_FLAGS.includes(flag) ? t(`flag.${flag}` as Key) : null;
}
/** Why a term is in the clinician's check list (the guardrail's technical reason), or null. */
export function clinicFlagNote(flags: string[]): string | null {
  if (flags.includes("hpo_dropped")) return t("check.why.hpo_dropped");
  if (flags.includes("no_hpo")) return t("check.why.no_hpo");
  return null;
}

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
