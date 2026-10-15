import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, X } from "lucide-react";
import { api } from "../api";
import type { Entity, Entry, Term } from "../types";
import { flagNote, splitQuotes } from "../lib";
import { ErrorBox, Loading, Spinner } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { useLiveEntry } from "./EntryCard";
import { CloudSaw } from "./CloudSaw";

export default function EntryPage() {
  const { id = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => api.entry(id), [id]);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "Not found"} retry={reload} />;
  return <Review initial={data} />;
}

function Review({ initial }: { initial: Entry }) {
  const entry = useLiveEntry(initial);
  const [local, setLocal] = useState<Record<string, Entity>>({});
  const [err, setErr] = useState<string | null>(null);
  const ents = entry.entities.map((e) => local[e.id] ?? e);
  const segs = splitQuotes(entry.text, ents.filter((e) => e.review !== "rejected").map((e) => e.quote));

  const patch = async (e: Entity, body: Parameters<typeof api.patchEntity>[1]) => {
    setErr(null);
    try { const u = await api.patchEntity(e.id, body); setLocal((l) => ({ ...l, [u.id]: u })); }
    catch (x) { setErr((x as Error).message); }
  };

  return (
    <div className="space-y-5">
      <Link to="/" className="btn-quiet btn px-0">Back to today</Link>
      <h1 className="text-3xl">Check what we found</h1>
      <p className="card whitespace-pre-wrap" aria-label="Your note">
        {segs.map((s, i) => s.quoted ? <mark key={i} className="quote text-ink">{s.text}</mark> : <span key={i}>{s.text}</span>)}
      </p>
      <CloudSaw entryId={entry.id} />
      <div aria-live="polite">
        {entry.extraction === "pending" && <Spinner label="Still reading your note" />}
        {entry.extraction === "failed" && (
          <div className="card"><p>We could not read this note.</p>
            <button className="btn mt-2" onClick={() => api.extract(entry.id).then((e) => setLocal(Object.fromEntries(e.entities.map((x) => [x.id, x])))).catch((x) => setErr(x.message))}>Try again</button></div>
        )}
      </div>
      {err && <p role="alert" className="text-strong text-sm">{err}</p>}
      <ul className="space-y-3">
        {ents.map((e) => <EntityRow key={e.id} e={e} onPatch={(b) => patch(e, b)} />)}
      </ul>
      {entry.extraction === "done" && ents.length === 0 && <p className="text-muted">No terms were found in this note.</p>}
    </div>
  );
}

function EntityRow({ e, onPatch }: { e: Entity; onPatch: (b: Parameters<typeof api.patchEntity>[1]) => void }) {
  const [fixing, setFixing] = useState(false);
  const decided = e.review === "confirmed" || e.review === "corrected";
  return (
    <li className="card" style={e.review === "rejected" ? { opacity: 0.6 } : undefined}>
      <p className="text-sm text-muted">You wrote: <mark className="quote text-ink">{e.quote}</mark></p>
      <p className="mt-1 font-bold">{e.negated && "No "}{e.family_history && "Relative: "}{e.canonical}</p>
      {e.review === "needs_review" && (
        <p className="text-sm mt-1 rounded-lg border px-2 py-1 chip-review">
          We are not sure about this one. <Link className="underline" to="/review">Open the review list</Link>
        </p>
      )}
      <p className="text-sm text-muted">{e.hpo_id ? `${e.hpo_label ?? ""} (${e.hpo_id})` : "No ontology code"}</p>
      {e.flags.map((f) => <p key={f} className="text-sm mt-1" style={{ color: "var(--moderate)" }}>{flagNote[f] ?? f.replace(/_/g, " ")}</p>)}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn" aria-pressed={decided} onClick={() => onPatch({ review: "confirmed" })}
          style={decided ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}><Check size={16} aria-hidden /> {decided ? "Confirmed" : "Confirm"}</button>
        <button className="btn" aria-pressed={e.review === "rejected"} onClick={() => onPatch({ review: "rejected" })}><X size={16} aria-hidden /> Not right</button>
        <button className="btn-quiet btn" onClick={() => setFixing(!fixing)} aria-expanded={fixing}>Fix term</button>
      </div>
      {fixing && <TermFix onPick={(t) => { onPatch({ hpo_id: t.hpo_id, canonical: t.label }); setFixing(false); }} />}
    </li>
  );
}

export function TermFix({ onPick }: { onPick: (t: Term) => void }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Term[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const search = (v: string) => {
    setQ(v);
    if (v.trim().length < 2) { setRes([]); return; }
    api.searchTerms(v.trim()).then(setRes).catch((x) => setErr(x.message));
  };
  return (
    <div className="mt-3">
      <label className="label" htmlFor="fix">Search the term list</label>
      <input id="fix" className="input" value={q} onChange={(e) => search(e.target.value)} placeholder="For example: joint pain" />
      {err && <p className="text-sm text-strong">{err}</p>}
      <ul className="mt-2 divide-y divide-line">
        {res.map((t) => (
          <li key={t.hpo_id}><button className="w-full text-left min-h-[44px] py-2 hover:text-accent" onClick={() => onPick(t)}>{t.label} <span className="text-muted text-sm">{t.hpo_id}</span></button></li>
        ))}
      </ul>
    </div>
  );
}
