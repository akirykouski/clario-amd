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
const fill = (s: string, p?: Params) => (p ? s.replace(/\{(\w+)\}/g, (_, k: string) => String(p[k] ?? `{${k}}`)) : s);

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
export function termLabel(hpoId: string | null | undefined, fallback: string): string {
  return current === "it" && hpoId && hpoIt[hpoId] ? hpoIt[hpoId] : fallback;
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
