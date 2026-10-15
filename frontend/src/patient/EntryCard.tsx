import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Entry } from "../types";
import { fmtDate } from "../lib";
import { Spinner } from "../components/ui";

/** Polls GET /api/entries/{id} every 2s while extraction is pending. */
export function useLiveEntry(initial: Entry, onChange?: (e: Entry) => void) {
  const [entry, setEntry] = useState(initial);
  const cb = useRef(onChange); cb.current = onChange;
  useEffect(() => setEntry(initial), [initial]);
  useEffect(() => {
    if (entry.extraction !== "pending") return;
    const t = setInterval(() => {
      api.entry(entry.id).then((e) => { setEntry(e); cb.current?.(e); }).catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [entry.id, entry.extraction]);
  return entry;
}

export function EntryCard({ initial, onChange }: { initial: Entry; onChange?: (e: Entry) => void }) {
  const entry = useLiveEntry(initial, onChange);
  const terms = entry.entities.filter((e) => e.status !== "rejected");
  return (
    <article className="card">
      <div className="flex justify-between text-sm text-muted">
        <time dateTime={entry.occurred_on}>{fmtDate(entry.occurred_on, { weekday: "short", day: "numeric", month: "short" })}</time>
        {entry.mood !== null && <span>Mood {entry.mood}/10</span>}
      </div>
      <p className="mt-1 whitespace-pre-wrap line-clamp-4">{entry.text}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5" aria-live="polite">
        {entry.extraction === "pending" && <Spinner label="Reading your note" />}
        {entry.extraction === "failed" && <span className="text-sm text-muted">We could not read this note automatically. You can try again from the review page.</span>}
        {entry.extraction === "done" && terms.length === 0 && <span className="text-sm text-muted">No terms found.</span>}
        {terms.map((t) => (
          <span key={t.id} className="chip" style={t.status === "confirmed" ? { borderColor: "var(--accent)" } : undefined}>
            {t.negated && <span className="text-muted">no </span>}{t.canonical}{t.status === "suggested" && <span className="text-muted text-xs"> (to check)</span>}
          </span>
        ))}
      </div>
      <div className="mt-2"><Link className="btn-quiet btn px-0" to={`/entry/${entry.id}`}>Review terms</Link></div>
    </article>
  );
}
