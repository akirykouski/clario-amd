import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Pencil, X } from "lucide-react";
import { api } from "../api";
import type { ReviewItem } from "../types";
import { confidencePct, splitQuotes } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { TermFix } from "./EntryPage";

export const REVIEW_EVENT = "clario-review-changed";

export function ConfidenceBar({ value }: { value: number | null }) {
  const pct = confidencePct(value);
  if (pct === null) return <p className="text-sm text-muted">Confidence not measured</p>;
  return (
    <div>
      <p className="text-sm text-muted">We are {pct}% sure</p>
      <div role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={`Confidence ${pct} percent`}
        className="mt-1 h-2 w-full max-w-xs rounded-full bg-line overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--moderate)" }} />
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const { data, error, loading, reload } = useAsync(() => api.review(), []);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "Could not load the list"} retry={reload} />;
  const items = data.items.filter((i) => !gone.has(`${i.kind}:${i.id}`));

  const act = async (i: ReviewItem, action: "confirm" | "correct" | "reject", value?: string) => {
    setErr(null);
    try {
      await api.reviewAct(i.kind, i.id, action, value);
      setGone((g) => new Set(g).add(`${i.kind}:${i.id}`));
      window.dispatchEvent(new Event(REVIEW_EVENT));
    } catch (x) { setErr((x as Error).message); }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl">To review</h1>
        <p className="text-muted mt-1">We were not sure about these. Nothing here counts toward patterns or goes to a clinic until you decide.</p>
      </div>
      {err && <p role="alert" className="text-strong text-sm">{err}</p>}
      {items.length === 0 ? (
        <Empty title="Nothing to review">Everything we were unsure about has been checked. <Link className="underline" to="/">Back to today</Link></Empty>
      ) : (
        <ul className="space-y-3" aria-label="Items to review">
          {items.map((i) => <ReviewCard key={`${i.kind}:${i.id}`} item={i} onAct={(a, v) => act(i, a, v)} />)}
        </ul>
      )}
    </div>
  );
}

function ReviewCard({ item, onAct }: { item: ReviewItem; onAct: (a: "confirm" | "correct" | "reject", v?: string) => void }) {
  const [fixing, setFixing] = useState(false);
  const [text, setText] = useState("");
  const segs = splitQuotes(item.source_excerpt, item.quote ? [item.quote] : []);
  return (
    <li className="card" style={{ borderColor: "var(--moderate)" }}>
      <p className="text-sm text-muted">You wrote</p>
      <p className="whitespace-pre-wrap" aria-label="Source text">
        {segs.map((s, k) => s.quoted ? <mark key={k} className="quote text-ink">{s.text}</mark> : <span key={k}>{s.text}</span>)}
      </p>
      <p className="mt-3 font-bold">{item.display}</p>
      <p className="text-sm text-muted">
        {item.kind === "entity" ? (item.value ? `${item.hpo_label ?? ""} (${item.value})` : "No ontology code") : item.value}
        {item.family_history && " · about a relative"}
      </p>
      <div className="mt-2"><ConfidenceBar value={item.confidence} /></div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn" onClick={() => onAct("confirm")}><Check size={16} aria-hidden /> Confirm</button>
        <button className="btn" onClick={() => setFixing(!fixing)} aria-expanded={fixing}><Pencil size={16} aria-hidden /> Correct</button>
        <button className="btn" onClick={() => onAct("reject")}><X size={16} aria-hidden /> Reject</button>
      </div>
      {fixing && (item.kind === "entity" ? (
        <TermFix onPick={(t) => { onAct("correct", t.hpo_id); setFixing(false); }} />
      ) : (
        <div className="mt-3 flex gap-2">
          <label className="sr-only" htmlFor={`v-${item.id}`}>Corrected value</label>
          <input id={`v-${item.id}`} className="input" value={text} onChange={(e) => setText(e.target.value)} />
          <button className="btn btn-primary" disabled={!text.trim()} onClick={() => onAct("correct", text.trim())}>Save</button>
        </div>
      ))}
    </li>
  );
}
