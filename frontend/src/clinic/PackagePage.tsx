import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Brief, Entry, SharePackage } from "../types";
import { fmtDate, splitQuotes } from "../lib";
import { ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { BriefPanel } from "./BriefPanel";

export default function PackagePage() {
  const { id = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => api.package(id), [id]);
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => { api.brief(id).then(setBrief).catch(() => setBrief(null)); }, [id]);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "Not found"} retry={reload} />;
  return (
    <div>
      <div className="no-print mb-3"><Link to="/" className="text-accent underline underline-offset-4 text-sm">Inbox</Link></div>
      <div className="grid lg:grid-cols-2 gap-6 items-start">
        <div className="no-print"><PackageView pkg={data} /></div>
        <BriefPanel pkg={data} brief={brief} setBrief={setBrief} />
      </div>
    </div>
  );
}

function PackageView({ pkg }: { pkg: SharePackage }) {
  const terms = new Map<string, { label: string; hpo: string | null; first: string; last: string; count: number }>();
  pkg.entities.filter((e) => !e.negated).forEach((e) => {
    const k = e.hpo_id ?? e.canonical;
    const t = terms.get(k);
    if (!t) terms.set(k, { label: e.canonical, hpo: e.hpo_id, first: e.occurred_on, last: e.occurred_on, count: 1 });
    else { t.count++; if (e.occurred_on < t.first) t.first = e.occurred_on; if (e.occurred_on > t.last) t.last = e.occurred_on; }
  });
  const entries = [...pkg.entries].sort((a, b) => a.occurred_on.localeCompare(b.occurred_on));
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl">{pkg.patient_alias}</h1>
        <p className="text-muted text-sm">{fmtDate(pkg.period[0])} to {fmtDate(pkg.period[1])} · expires {fmtDate(pkg.expires_at)}</p>
      </header>
      {pkg.note && <section className="card" aria-label="Patient note"><h2 className="text-lg">Patient note</h2><p className="mt-1 whitespace-pre-wrap">{pkg.note}</p></section>}
      <section aria-labelledby="pt"><h2 id="pt" className="text-xl mb-2">Confirmed terms</h2>
        <div className="card p-0 overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-line">{["Term", "HPO", "First", "Last", "Count"].map((h) => <th key={h} className="px-3 py-1.5">{h}</th>)}</tr></thead>
          <tbody>{[...terms.values()].map((t) => (
            <tr key={t.label} className="border-b border-line last:border-0"><td className="px-3 py-1.5 font-bold">{t.label}</td><td className="px-3 py-1.5 font-mono">{t.hpo ?? "none"}</td>
              <td className="px-3 py-1.5">{fmtDate(t.first)}</td><td className="px-3 py-1.5">{fmtDate(t.last)}</td><td className="px-3 py-1.5">{t.count}</td></tr>
          ))}</tbody></table></div>
      </section>
      {pkg.patterns.length > 0 && (
        <section aria-labelledby="pp"><h2 id="pp" className="text-xl mb-2">Patient-side patterns</h2>
          <ul className="space-y-2">{pkg.patterns.map((p) => (
            <li key={p.disease_id} className="card"><div className="flex justify-between gap-2 flex-wrap"><span className="font-bold">{p.disease_name}</span><SignalPill signal={p.signal} /></div>
              <p className="text-sm mt-1">{p.rationale}</p></li>
          ))}</ul>
        </section>
      )}
      <section aria-labelledby="et"><h2 id="et" className="text-xl mb-2">Entries</h2>
        <ol className="space-y-3">{entries.map((e) => <EntryRow key={e.id} e={e} pkg={pkg} />)}</ol>
      </section>
    </div>
  );
}

function EntryRow({ e, pkg }: { e: Entry; pkg: SharePackage }) {
  const quotes = pkg.entities.filter((s) => s.entry_id === e.id).map((s) => s.quote);
  return (
    <li id={`entry-${e.id}`} className="card scroll-mt-4 target:ring-2 target:ring-[var(--accent)]" tabIndex={-1}>
      <p className="text-sm text-muted">{fmtDate(e.occurred_on, { weekday: "short", day: "numeric", month: "short" })}{e.mood !== null && ` · mood ${e.mood}/10`}</p>
      <p className="whitespace-pre-wrap text-[15px]">{splitQuotes(e.text, quotes).map((s, i) => s.quoted ? <span key={i} className="clinic-quote">{s.text}</span> : <span key={i}>{s.text}</span>)}</p>
    </li>
  );
}
