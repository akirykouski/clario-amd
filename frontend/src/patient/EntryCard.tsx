import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Entry } from "../types";
import { fmtDate, notifyReview } from "../lib";
import { entityName, entryText, useT } from "../i18n";
import { Spinner } from "../components/ui";
import { CloudSaw } from "./CloudSaw";

// One poll for every pending entry on screen: a single GET /api/entries every 2s while anyone is watching.
const watchers = new Map<string, Set<(e: Entry) => void>>();
let timer: ReturnType<typeof setInterval> | null = null;

function tick() {
  api.entries().then((list) => { for (const e of list) watchers.get(e.id)?.forEach((f) => f(e)); }).catch(() => {});
}

function watch(id: string, f: (e: Entry) => void): () => void {
  const set = watchers.get(id) ?? new Set();
  set.add(f);
  watchers.set(id, set);
  if (!timer) timer = setInterval(tick, 2000);
  return () => {
    set.delete(f);
    if (set.size === 0) watchers.delete(id);
    if (watchers.size === 0 && timer) { clearInterval(timer); timer = null; }
  };
}

/** Follows an entry while its extraction is pending (shared poll), and tells the nav badge when it finishes. */
export function useLiveEntry(initial: Entry, onChange?: (e: Entry) => void) {
  const [entry, setEntry] = useState(initial);
  const cb = useRef(onChange); cb.current = onChange;
  useEffect(() => setEntry(initial), [initial]);
  useEffect(() => {
    if (entry.extraction !== "pending") return;
    return watch(entry.id, (e) => {
      setEntry(e);
      cb.current?.(e);
      if (e.extraction !== "pending") notifyReview();
    });
  }, [entry.id, entry.extraction]);
  return entry;
}

export function EntryCard({ initial, onChange }: { initial: Entry; onChange?: (e: Entry) => void }) {
  const { t } = useT();
  const entry = useLiveEntry(initial, onChange);
  const [fresh, setFresh] = useState<Entry | null>(null);
  const shown = fresh && fresh.id === entry.id ? fresh : entry;
  const allCorrect = async () => { try { const r = await api.confirmAllInEntry(entry.id); setFresh(r.entry); onChange?.(r.entry); notifyReview(); } catch { /* the entry page still offers each term */ } };
  const name = entityName;
  const terms = shown.entities.filter((e) => e.review !== "rejected");
  return (
    <article className="card">
      <div className="flex justify-between text-sm text-muted">
        <time dateTime={entry.occurred_on}>{fmtDate(entry.occurred_on, { weekday: "short", day: "numeric", month: "short" })}</time>
        {entry.mood !== null && <span>{t("entry.mood", { n: entry.mood })}</span>}
      </div>
      <p className="mt-1 whitespace-pre-wrap line-clamp-4">{entryText(entry.text)}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5" aria-live="polite">
        {entry.extraction === "pending" && <Spinner label={t("entry.reading")} />}
        {entry.extraction === "failed" && <span className="text-sm text-muted">{t("entry.failedShort")}</span>}
        {entry.extraction === "done" && terms.length === 0 && <span className="text-sm text-muted">{t("entry.noTerms")}</span>}
        {terms.map((x) => x.review === "needs_review" ? (
          <Link key={x.id} to="/review" className="chip chip-review" title={t("entry.toReviewTitle")}>
            {x.negated && <span className="text-muted">{t("term.absentChip")}</span>}{x.type === "trigger" && <span className="text-muted">{t("term.contextChip")}</span>}{x.family_history && <span className="text-muted">{t("term.relativeChip")}</span>}{name(x)}
            <span className="text-xs font-bold"> {t("entry.toReviewTag")}</span>
          </Link>
        ) : (
          <span key={x.id} className="chip" style={x.review === "confirmed" || x.review === "corrected" ? { borderColor: "var(--accent)" } : undefined}>
            {x.negated && <span className="text-muted">{t("term.absentChip")}</span>}{x.type === "trigger" && <span className="text-muted">{t("term.contextChip")}</span>}{x.family_history && <span className="text-muted">{t("term.relativeChip")}</span>}{name(x)}
            {x.review === "auto" && <span className="text-muted text-xs"> {t("entry.toCheckTag")}</span>}
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-5">
        {shown.entities.some((x) => x.review === "auto") && <button className="btn" onClick={allCorrect}>{t("entry.allCorrect")}</button>}
        <Link className="btn-quiet btn px-0" to={`/entry/${entry.id}`}>{t("entry.reviewTerms")}</Link>
        <CloudSaw entryId={entry.id} compact />
      </div>
    </article>
  );
}
