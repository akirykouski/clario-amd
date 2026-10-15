import { useEffect, useState } from "react";
import { Check, Pencil, Printer, X } from "lucide-react";
import { api } from "../api";
import type { Brief, BriefItem, BriefSection, SharePackage } from "../types";
import { canFinalize } from "../lib";
import { ErrorBox, Spinner } from "../components/ui";
import { useRun } from "./useRun";

const SECTIONS: { key: BriefSection; title: string }[] = [
  { key: "summary", title: "Summary" }, { key: "timeline", title: "Timeline" }, { key: "symptoms", title: "Symptoms" },
  { key: "labs", title: "Labs" }, { key: "medications", title: "Medications" }, { key: "patterns", title: "Patterns worth discussing" },
  { key: "questions", title: "Patient questions" },
];

export function jumpTo(entryId: string) {
  const el = document.getElementById(`entry-${entryId}`);
  if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.focus({ preventScroll: true }); }
}

export function FinalizeButton({ items, onClick, busy }: { items: BriefItem[]; onClick: () => void; busy?: boolean }) {
  const pending = items.filter((i) => i.review === "pending").length;
  return (
    <div>
      <button className="btn btn-primary" onClick={onClick} disabled={!canFinalize(items) || busy}>Finalize brief</button>
      {pending > 0 && <p className="text-sm text-muted mt-1" aria-live="polite">{pending} {pending === 1 ? "item" : "items"} still need review.</p>}
    </div>
  );
}

export function BriefPanel({ pkg, brief, setBrief }: { pkg: SharePackage; brief: Brief | null; setBrief: (b: Brief) => void }) {
  const { state, start } = useRun();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = brief ?? (state.status === "done" ? state.brief ?? null : null);
  useEffect(() => { if (state.status === "done" && state.brief) setBrief(state.brief); }, [state.status, state.brief]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = (it: BriefItem) => shown && setBrief({ ...shown, items: shown.items.map((x) => (x.id === it.id ? it : x)) });
  const review = async (it: BriefItem, r: BriefItem["review"], text?: string) => {
    setErr(null);
    try { update(await api.reviewItem(pkg.package_id, it.id, text !== undefined ? { review: r, text } : { review: r })); }
    catch (x) { setErr((x as Error).message); }
  };
  const finalize = async () => {
    setBusy(true); setErr(null);
    try { setBrief(await api.finalize(pkg.package_id)); } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };

  return (
    <aside className="lg:sticky lg:top-4 space-y-4" aria-label="Brief">
      <div className="no-print flex items-center justify-between gap-3">
        <h2 className="text-2xl">Brief</h2>
        <button className="btn btn-primary" onClick={() => start(pkg.package_id)} disabled={state.status === "running" || !!shown?.finalized}>
          {shown ? "Draft again" : "Draft brief"}
        </button>
      </div>

      <div aria-live="polite" className="no-print">
        {state.status === "running" && (
          <div className="card space-y-2">
            <Spinner label={state.message || "Drafting"} />
            <div className="h-1.5 bg-line rounded"><div className="h-1.5 rounded bg-accent transition-all" style={{ width: `${Math.round(state.progress * 100)}%` }} /></div>
            <p className="text-sm text-muted">{state.model ?? "model"}{state.tokensPerS ? ` · ${state.tokensPerS.toFixed(1)} tokens/s` : ""}</p>
          </div>
        )}
        {state.status === "error" && <ErrorBox error={state.error ?? "Drafting failed"} retry={() => start(pkg.package_id)} />}
        {state.status === "done" && <p className="text-sm text-muted">Drafted by {state.model ?? "the clinic model"}{state.tokensPerS ? ` at ${state.tokensPerS.toFixed(1)} tokens/s` : ""}. Review every item.</p>}
      </div>
      {err && <ErrorBox error={err} />}

      {!shown && state.status === "idle" && <p className="text-muted no-print">No brief yet. Drafting reads the shared entries and proposes items you accept, edit or reject.</p>}

      {shown && (
        <>
          <div className="no-print space-y-4">
            {SECTIONS.map((s) => {
              const items = shown.items.filter((i) => i.section === s.key);
              if (!items.length) return null;
              return (
                <section key={s.key} aria-label={s.title}>
                  <h3 className="text-lg mb-1">{s.title}</h3>
                  <ul className="space-y-2">{items.map((it) => <ItemRow key={it.id} it={it} locked={shown.finalized} onReview={review} />)}</ul>
                </section>
              );
            })}
            <div className="flex items-start gap-3 flex-wrap">
              {!shown.finalized && <FinalizeButton items={shown.items} onClick={finalize} busy={busy} />}
              {shown.finalized && (
                <>
                  <a className="btn" href={api.briefMdUrl(pkg.package_id)} target="_blank" rel="noreferrer">Open brief.md</a>
                  <button className="btn" onClick={() => window.print()}><Printer size={16} aria-hidden /> Print view</button>
                </>
              )}
            </div>
          </div>
          <PrintBrief pkg={pkg} brief={shown} />
        </>
      )}
    </aside>
  );
}

function ItemRow({ it, locked, onReview }: { it: BriefItem; locked: boolean; onReview: (it: BriefItem, r: BriefItem["review"], text?: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(it.text);
  const ai = it.origin === "ai";
  const tone = it.review === "accepted" || it.review === "edited" ? "var(--accent)" : it.review === "rejected" ? "var(--line)" : "var(--moderate)";
  return (
    <li className="card text-[15px]" style={{ borderLeft: `4px solid ${tone}`, opacity: it.review === "rejected" ? 0.6 : 1 }}>
      {editing ? (
        <div>
          <label htmlFor={`t-${it.id}`} className="label">Edit item</label>
          <textarea id={`t-${it.id}`} className="input min-h-[90px]" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex gap-2 mt-2">
            <button className="btn btn-primary" onClick={() => { onReview(it, "edited", text); setEditing(false); }} disabled={!text.trim()}>Save edit</button>
            <button className="btn" onClick={() => { setText(it.text); setEditing(false); }}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <p className={it.review === "rejected" ? "line-through" : ""}>{it.text}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="chip text-xs">{ai ? "AI draft" : "From patient"}</span>
            <span className="chip text-xs">{it.review}</span>
            {it.cites.map((c, i) => <button key={c} className="chip hover:border-accent" onClick={() => jumpTo(c)} aria-label={`Go to cited entry ${i + 1}`}>entry {i + 1}</button>)}
          </div>
          {ai && !locked && (
            <div className="mt-2 flex gap-2 flex-wrap">
              <button className="btn" onClick={() => onReview(it, "accepted")} aria-pressed={it.review === "accepted"}><Check size={16} aria-hidden /> Accept</button>
              <button className="btn" onClick={() => setEditing(true)}><Pencil size={16} aria-hidden /> Edit</button>
              <button className="btn" onClick={() => onReview(it, "rejected")} aria-pressed={it.review === "rejected"}><X size={16} aria-hidden /> Reject</button>
            </div>
          )}
        </>
      )}
    </li>
  );
}

function PrintBrief({ pkg, brief }: { pkg: SharePackage; brief: Brief }) {
  const kept = brief.items.filter((i) => i.review === "accepted" || i.review === "edited" || i.origin === "patient");
  const label = (id: string) => { const e = pkg.entries.find((x) => x.id === id); return e ? e.occurred_on : id; };
  return (
    <div className="print-only">
      <h1 style={{ fontSize: "20pt" }}>Clinical brief: {pkg.patient_alias}</h1>
      <p>{pkg.period[0]} to {pkg.period[1]}</p>
      {SECTIONS.map((s) => {
        const items = kept.filter((i) => i.section === s.key);
        if (!items.length) return null;
        return (
          <section key={s.key} style={{ marginTop: "10pt" }}>
            <h2 style={{ fontSize: "14pt" }}>{s.title}</h2>
            <ul>{items.map((i) => <li key={i.id}>{i.text}{i.cites.length > 0 && <em> ({i.cites.map(label).join(", ")})</em>}</li>)}</ul>
          </section>
        );
      })}
      <p style={{ marginTop: "16pt", fontSize: "9pt" }}>Prepared with Clario. AI-drafted items reviewed by the clinician.</p>
    </div>
  );
}
