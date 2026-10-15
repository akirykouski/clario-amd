import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Brief, Entry, SharedLab, SharePackage } from "../types";
import { fmtDate, splitQuotes } from "../lib";
import { ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { BriefPanel } from "./BriefPanel";
import { useT } from "../i18n";

export default function PackagePage() {
  const { t } = useT();
  const { id = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => api.package(id), [id]);
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => {
    // ask the inbox first: a brief that does not exist yet would be a 404 in the console
    api.inbox().then((rows) => (rows.find((r) => r.package_id === id)?.brief_state !== "none" ? api.brief(id) : null))
      .then(setBrief).catch(() => setBrief(null));
  }, [id]);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.notFound")} retry={reload} />;
  return (
    <div>
      <div className="no-print mb-3"><Link to="/" className="text-accent underline underline-offset-4 text-sm">{t("pkg.inbox")}</Link></div>
      <div className="grid lg:grid-cols-2 gap-6 items-start">
        <div className="no-print min-w-0"><PackageView pkg={data} /></div>
        <div className="min-w-0"><BriefPanel pkg={data} brief={brief} setBrief={setBrief} /></div>
      </div>
    </div>
  );
}

function PackageView({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  const terms = new Map<string, { label: string; hpo: string | null; first: string; last: string; count: number }>();
  const mine = pkg.entities.filter((e) => !e.negated && !e.family_history);  // the patient's own terms only
  const family = pkg.entities.filter((e) => e.family_history && !e.negated);
  mine.forEach((e) => {
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
        <p className="text-muted text-sm">{t("share.range", { a: fmtDate(pkg.period[0]), b: fmtDate(pkg.period[1]) })} · {t("pkg.expiresShort", { date: fmtDate(pkg.expires_at) })}</p>
        <p className="text-sm font-bold mt-1" data-testid="pkg-counts">{t("pkg.mentions", { m: mine.length, t: terms.size })}</p>
      </header>
      {pkg.note && <section className="card" aria-label={t("pkg.patientNote")}><h2 className="text-lg">{t("pkg.patientNote")}</h2><p className="mt-1 whitespace-pre-wrap">{pkg.note}</p></section>}
      <section aria-labelledby="pt"><h2 id="pt" className="text-xl mb-2">{t("pkg.terms")}</h2>
        <div className="card p-0 overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-line">{(["pkg.term", "pkg.hpo", "pkg.first", "pkg.last", "pkg.count"] as const).map((h) => <th key={h} className="px-3 py-1.5">{t(h)}</th>)}</tr></thead>
          <tbody>{[...terms.values()].map((x) => (
            <tr key={x.label} className="border-b border-line last:border-0"><td className="px-3 py-1.5 font-bold">{x.label}</td><td className="px-3 py-1.5 font-mono">{x.hpo ?? t("pkg.none")}</td>
              <td className="px-3 py-1.5">{fmtDate(x.first)}</td><td className="px-3 py-1.5">{fmtDate(x.last)}</td><td className="px-3 py-1.5">{x.count}</td></tr>
          ))}</tbody></table></div>
      </section>
      {family.length > 0 && (
        <section aria-labelledby="pf"><h2 id="pf" className="text-xl mb-1">{t("pkg.family")}</h2>
          <p className="text-sm text-muted mb-2">{t("pkg.familyHint")}</p>
          <ul className="card space-y-1 text-sm">{family.map((f, i) => <li key={i}>{f.canonical} <span className="text-muted">({fmtDate(f.occurred_on)})</span></li>)}</ul>
        </section>
      )}
      {pkg.labs.length > 0 && <LabsTable labs={pkg.labs} />}
      {pkg.patterns.length > 0 && <Patterns pkg={pkg} />}
      <section aria-labelledby="et"><h2 id="et" className="text-xl mb-2">{t("pkg.entries")}</h2>
        <ol className="space-y-3">{entries.map((e) => <EntryRow key={e.id} e={e} pkg={pkg} />)}</ol>
      </section>
    </div>
  );
}

function EntryRow({ e, pkg }: { e: Entry; pkg: SharePackage }) {
  const { t } = useT();
  const quotes = pkg.entities.filter((s) => s.entry_id === e.id).map((s) => s.quote);
  return (
    <li id={`entry-${e.id}`} className="card scroll-mt-4 target:ring-2 target:ring-[var(--accent)]" tabIndex={-1}>
      <p className="text-sm text-muted">{fmtDate(e.occurred_on, { weekday: "short", day: "numeric", month: "short" })}{e.mood !== null && t("pkg.mood", { n: e.mood })}</p>
      <p className="whitespace-pre-wrap text-[15px]">{splitQuotes(e.text, quotes).map((s, i) => s.quoted ? <span key={i} className="clinic-quote">{s.text}</span> : <span key={i}>{s.text}</span>)}</p>
    </li>
  );
}

function Patterns({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  const strong = pkg.patterns.filter((p) => p.signal !== "weak");
  const weak = pkg.patterns.filter((p) => p.signal === "weak");
  const card = (p: SharePackage["patterns"][number], muted = false) => (
    <li key={p.disease_id} className="card" style={muted ? { opacity: 0.75 } : undefined}>
      <div className="flex justify-between gap-2 flex-wrap"><span className="font-bold">{p.disease_name}</span><SignalPill signal={p.signal} /></div>
      <p className="text-sm mt-1">{p.matched.map((m) => m.label).join(", ")}</p>
    </li>
  );
  return (
    <section aria-labelledby="pp"><h2 id="pp" className="text-xl mb-2">{t("pkg.patterns")}</h2>
      <ul className="space-y-2">{strong.map((p) => card(p))}</ul>
      {weak.length > 0 && (
        <details className="mt-2"><summary className="cursor-pointer min-h-[44px] flex items-center text-sm text-muted">{t("pkg.weak", { n: weak.length })}</summary>
          <ul className="space-y-2">{weak.map((p) => card(p, true))}</ul></details>
      )}
    </section>
  );
}

const labValue = (l: SharedLab) => `${l.value_text ?? (l.value_numeric ?? "?")}${l.unit ? " " + l.unit : ""}`;
const labRange = (l: SharedLab) => (l.ref_low === null && l.ref_high === null ? "" : `${l.ref_low ?? ""} - ${l.ref_high ?? ""}`);

function LabsTable({ labs }: { labs: SharedLab[] }) {
  const { t } = useT();
  const flag = (l: SharedLab) => (l.flag ? t(`pkg.lab.${l.flag}` as const) : "");
  return (
    <section aria-labelledby="pl" data-testid="pkg-labs"><h2 id="pl" className="text-xl mb-2">{t("pkg.labs")}</h2>
      <div className="card p-0 overflow-x-auto hidden sm:block"><table className="w-full text-sm">
        <thead><tr className="text-left text-muted border-b border-line">{(["pkg.lab.test", "pkg.lab.value", "pkg.lab.range", "pkg.lab.flag", "pkg.lab.date"] as const).map((h) => <th key={h} className="px-3 py-1.5">{t(h)}</th>)}<th className="px-3 py-1.5" /></tr></thead>
        <tbody>{labs.map((l, i) => (
          <tr key={i} className="border-b border-line last:border-0">
            <td className="px-3 py-1.5 font-bold">{l.test_name}</td><td className="px-3 py-1.5">{labValue(l)}</td>
            <td className="px-3 py-1.5">{labRange(l)}</td><td className="px-3 py-1.5">{flag(l)}</td>
            <td className="px-3 py-1.5">{fmtDate(l.date)}, {t("pkg.lab.page", { n: l.page })}</td>
            <td className="px-3 py-1.5 text-muted">{!l.reviewed && t("pkg.lab.unreviewed")}</td>
          </tr>))}</tbody></table></div>
      <ul className="space-y-2 sm:hidden">{labs.map((l, i) => (
        <li key={i} className="card text-sm">
          <p className="font-bold">{l.test_name}</p>
          <p>{labValue(l)}{flag(l) && ` · ${flag(l)}`}{labRange(l) && ` · ${labRange(l)}`}</p>
          <p className="text-muted">{fmtDate(l.date)}, {t("pkg.lab.page", { n: l.page })}{!l.reviewed && ` · ${t("pkg.lab.unreviewed")}`}</p>
        </li>))}</ul>
    </section>
  );
}
