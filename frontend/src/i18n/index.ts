import { useSyncExternalStore } from "react";
import { en, type Key } from "./en";
import { it } from "./it";
import { hpoIt } from "./hpo.it";

export type Lang = "en" | "it";
export type { Key };
export const LANGS: Lang[] = ["en", "it"];
export const LANG_NAME: Record<Lang, string> = { en: "English", it: "Italiano" };
const STORE = "clario.lang";
const dict: Record<Lang, Record<Key, string>> = { en, it };

function detect(): Lang {
  try {
    const s = localStorage.getItem(STORE);
    if (s === "en" || s === "it") return s;
  } catch { /* storage blocked: fall through */ }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("it") ? "it" : "en";
}

let current: Lang = detect();
const listeners = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = current;

export function getLang(): Lang { return current; }
export function setLang(l: Lang) {
  if (l === current) return;
  current = l;
  try { localStorage.setItem(STORE, l); } catch { /* ignore */ }
  if (typeof document !== "undefined") document.documentElement.lang = l;
  listeners.forEach((f) => f());
}
const subscribe = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };

/** Re-renders the component when the language changes. */
export function useLang(): Lang { return useSyncExternalStore(subscribe, getLang, getLang); }

type Params = Record<string, string | number>;
/** Italian elision before the day numbers 8 and 11: "dal 11" -> "dall'11", "il 8" -> "l'8", "al 8" -> "all'8", "del 11" -> "dell'11". */
export function elideIt(s: string): string {
  return s.replace(/\b(dal|al|del|il) (8|11)(?!\d)/gi, (_, w: string, d: string) => {
    const base = { dal: "dall'", al: "all'", del: "dell'", il: "l'" }[w.toLowerCase() as "dal"];
    return (w[0] === w[0].toUpperCase() ? base[0].toUpperCase() + base.slice(1) : base) + d;
  });
}
const fill = (s: string, p?: Params) => {
  const out = p ? s.replace(/\{(\w+)\}/g, (_, k: string) => String(p[k] ?? `{${k}}`)) : s;
  return current === "it" ? elideIt(out) : out;
};

/** Translate a key in the current language. Works outside components; use useT() inside them so they re-render. */
export function t(key: Key, params?: Params): string { return fill(dict[current][key] ?? en[key], params); }
/** Plural: picks key_one when n is 1, else key_other. `n` is available as {n}. */
export function tn(base: string, n: number, params?: Params): string {
  return t(`${base}_${n === 1 ? "one" : "other"}` as Key, { n, ...params });
}

export function useT() {
  const lang = useLang();
  return { t, tn, lang };
}

/** Plain Italian name for an HPO term in Italian; otherwise the label as given. */
const LAY_EN: Record<string, string> = { "HP:0001025": "Hives" };
export function termLabel(hpoId: string | null | undefined, fallback: string): string {
  if (current === "en" && hpoId && LAY_EN[hpoId]) return LAY_EN[hpoId];
  return current === "it" && hpoId && hpoIt[hpoId] ? hpoIt[hpoId] : fallback;
}

/** Second line under a term for the patient: everyday label, never the HPO code. In Italian only when we have an
 * Italian name (never the English clinical label). Null when it would repeat the name already shown. */
export function patientTermLine(hpoId: string | null | undefined, label: string, shown: string): string | null {
  if (!hpoId) return null;
  const line = current === "it" ? hpoIt[hpoId] : (LAY_EN[hpoId] ?? label);
  if (!line) return null;
  const norm = (x: string) => x.replace(/^(not |no |non |niente )/i, "").trim().toLowerCase();
  return norm(line) === norm(shown) ? null : line;
}

/** Name of an extracted entity for the patient. In Italian, a term with no Italian name and no ontology code
 * (a trigger, a relative's condition) is shown as the patient's own words instead of an English clinical name. */
export function entityName(x: { hpo_id: string | null; canonical: string; quote?: string | null }): string {
  if (current === "it" && !x.hpo_id && x.quote) return x.quote;
  return termLabel(x.hpo_id, x.canonical);
}

/** Entry texts the server writes in English when it imports documents ("Imported documents (3 pages)"). */
export function entryText(text: string): string {
  const m = /^Imported documents \((\d+) pages?\)$/.exec(text);
  return m ? tn("entry.imported", Number(m[1])) : text;
}
