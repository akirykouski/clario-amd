import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, X } from "lucide-react";
import { api } from "../api";
import type { Entity, Entry, Term } from "../types";
import { flagNote, splitQuotes } from "../lib";
import { ErrorBox, Loading, Spinner } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { entityName, getLang, termLabel, useT } from "../i18n";
import { useLiveEntry } from "./EntryCard";
import { CloudSaw } from "./CloudSaw";

export default function EntryPage() {
  const { t } = useT();
  const { id = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => api.entry(id), [id]);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.notFound")} retry={reload} />;
  return <Review initial={data} />;
}

function Review({ initial }: { initial: Entry }) {
  const { t } = useT();
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
      <Link to="/" className="btn-quiet btn px-0">{t("entryPage.back")}</Link>
      <h1 className="text-3xl">{t("entryPage.title")}</h1>
      <p className="card whitespace-pre-wrap" aria-label={t("entryPage.noteAria")}>
        {segs.map((s, i) => s.quoted ? <mark key={i} className="quote text-ink">{s.text}</mark> : <span key={i}>{s.text}</span>)}
      </p>
      <CloudSaw entryId={entry.id} />
      <div aria-live="polite">
        {entry.extraction === "pending" && <Spinner label={t("entry.stillReading")} />}
        {entry.extraction === "failed" && (
          <div className="card"><p>{t("entry.failed")}</p>
            <button className="btn mt-2" onClick={() => api.extract(entry.id).then((e) => setLocal(Object.fromEntries(e.entities.map((x) => [x.id, x])))).catch((x) => setErr(x.message))}>{t("common.tryAgain")}</button></div>
        )}
      </div>
      {err && <p role="alert" className="text-strong text-sm">{err}</p>}
      <ul className="space-y-3">
        {ents.map((e) => <EntityRow key={e.id} e={e} onPatch={(b) => patch(e, b)} />)}
      </ul>
      {entry.extraction === "done" && ents.length === 0 && <p className="text-muted">{t("entry.noTermsLong")}</p>}
    </div>
  );
}

function EntityRow({ e, onPatch }: { e: Entity; onPatch: (b: Parameters<typeof api.patchEntity>[1]) => void }) {
  const { t } = useT();
  const [fixing, setFixing] = useState(false);
  const decided = e.review === "confirmed" || e.review === "corrected";
  const label = e.hpo_label ? termLabel(e.hpo_id, e.hpo_label) : "";
  return (
    <li className="card" style={e.review === "rejected" ? { opacity: 0.6 } : undefined}>
      <p className="text-sm text-muted">{t("entryPage.youWrote")} <mark className="quote text-ink">{e.quote}</mark></p>
      <p className="mt-1 font-bold">{e.negated && t("term.absent")}{e.family_history && t("term.relative")}{entityName(e)}</p>
      {e.review === "needs_review" && (
        <p className="text-sm mt-1 rounded-lg border px-2 py-1 chip-review">
          {t("entryPage.unsure")}<Link className="underline" to="/review">{t("entryPage.openReview")}</Link>
        </p>
      )}
      <p className="text-sm text-muted">{e.hpo_id ? `${label} (${e.hpo_id})` : t("entryPage.noCode")}</p>
      {(e.onset_hint || e.severity !== null) && (
        <p className="text-sm text-muted">
          {e.onset_hint && t("entryPage.onset", { hint: e.onset_hint })}{e.onset_hint && e.severity !== null && " · "}{e.severity !== null && t("entryPage.severity", { n: e.severity })}
        </p>
      )}
      {e.flags.map((f) => <p key={f} className="text-sm mt-1" style={{ color: "var(--moderate)" }}>{flagNote(f)}</p>)}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn" aria-pressed={decided} onClick={() => onPatch({ review: "confirmed" })}
          style={decided ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}><Check size={16} aria-hidden /> {decided ? t("common.confirmed") : t("common.confirm")}</button>
        <button className="btn" aria-pressed={e.review === "rejected"} onClick={() => onPatch({ review: "rejected" })}><X size={16} aria-hidden /> {t("entryPage.notRight")}</button>
        <button className="btn-quiet btn" onClick={() => setFixing(!fixing)} aria-expanded={fixing}>{t("entryPage.fix")}</button>
      </div>
      {fixing && <TermFix onPick={(term) => { onPatch({ hpo_id: term.hpo_id }); setFixing(false); }} />}
    </li>
  );
}

export function TermFix({ onPick }: { onPick: (t: Term) => void }) {
  const { t } = useT();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Term[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const search = (v: string) => {
    setQ(v);
    if (v.trim().length < 2) { setRes([]); return; }
    api.searchTerms(v.trim(), getLang()).then(setRes).catch((x) => setErr(x.message));
  };
  return (
    <div className="mt-3">
      <label className="label" htmlFor="fix">{t("termfix.search")}</label>
      <input id="fix" className="input" value={q} onChange={(e) => search(e.target.value)} placeholder={t("termfix.placeholder")} />
      {err && <p className="text-sm text-strong">{err}</p>}
      <ul className="mt-2 divide-y divide-line">
        {res.map((term) => (
          <li key={term.hpo_id}><button className="w-full text-left min-h-[44px] py-2 hover:text-accent" onClick={() => onPick(term)}>{term.label} <span className="text-muted text-sm">{term.hpo_id}</span></button></li>
        ))}
      </ul>
    </div>
  );
}
