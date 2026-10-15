import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, X } from "lucide-react";
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
  const { data: loaded, error, loading, reload } = useAsync(() => api.package(id), [id]);
  const [decided, setDecided] = useState<SharePackage | null>(null);
  const data = decided && decided.package_id === id ? decided : loaded;
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
        <div className="no-print min-w-0"><PackageView pkg={data} onPackage={setDecided} /></div>
        <div className="min-w-0"><BriefPanel pkg={data} brief={brief} setBrief={setBrief} /></div>
      </div>
    </div>
  );
}

function PackageView({ pkg, onPackage }: { pkg: SharePackage; onPackage: (p: SharePackage) => void }) {
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
        <div className="card p-0 overflow-x-auto hidden sm:block"><table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-line">{(["pkg.term", "pkg.hpo", "pkg.first", "pkg.last", "pkg.count"] as const).map((h) => <th key={h} className="px-3 py-1.5">{t(h)}</th>)}</tr></thead>
          <tbody>{[...terms.values()].map((x) => (
            <tr key={x.label} className="border-b border-line last:border-0"><td className="px-3 py-1.5 font-bold">{x.label}</td><td className="px-3 py-1.5 font-mono">{x.hpo ?? t("pkg.none")}</td>
              <td className="px-3 py-1.5">{fmtDate(x.first)}</td><td className="px-3 py-1.5">{fmtDate(x.last)}</td><td className="px-3 py-1.5">{x.count}</td></tr>
          ))}</tbody></table></div>
        <ul className="space-y-2 sm:hidden" data-testid="terms-cards">{[...terms.values()].map((x) => (
          <li key={x.label} className="card text-sm">
            <p className="font-bold">{x.label}</p>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <dt className="text-muted">{t("pkg.hpo")}</dt><dd className="font-mono">{x.hpo ?? t("pkg.none")}</dd>
              <dt className="text-muted">{t("pkg.first")}</dt><dd>{fmtDate(x.first)}</dd>
              <dt className="text-muted">{t("pkg.last")}</dt><dd>{fmtDate(x.last)}</dd>
              <dt className="text-muted">{t("pkg.count")}</dt><dd>{x.count}</dd>
            </dl>
          </li>))}</ul>
      </section>
      {family.length > 0 && (
        <section aria-labelledby="pf"><h2 id="pf" className="text-xl mb-1">{t("pkg.family")}</h2>
          <p className="text-sm text-muted mb-2">{t("pkg.familyHint")}</p>
          <ul className="card space-y-1 text-sm">{family.map((f, i) => <li key={i}>{f.canonical} <span className="text-muted">({fmtDate(f.occurred_on)})</span></li>)}</ul>
        </section>
      )}
      {pkg.labs.length > 0 && <LabsHistory pkg={pkg} onPackage={onPackage} />}
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

function LabsHistory({ pkg, onPackage }: { pkg: SharePackage; onPackage: (p: SharePackage) => void }) {
  const { t, lang } = useT();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const tests = new Map<string, SharedLab[]>();
  [...pkg.labs].sort((a, b) => a.date.localeCompare(b.date) || a.page - b.page).forEach((l) => {
    const k = l.test_key || l.test_name;
    tests.set(k, [...(tests.get(k) ?? []), l]);
  });
  const name = (l: SharedLab) => (lang === "en" && l.name_en ? l.name_en : l.test_name);
  const flag = (l: SharedLab) => (l.flag ? t(`pkg.lab.${l.flag}` as const) : l.abnormal ? t("pkg.lab.positive") : "");
  const decide = async (l: SharedLab, d: "accepted" | "rejected" | "pending") => {
    setBusy(l.id); setErr(null);
    try { onPackage(await api.decideLab(pkg.package_id, l.id, d)); } catch (x) { setErr((x as Error).message); }
    setBusy(null);
  };
  const order = [...tests.values()].sort((a, b) => Number(b.some((l) => l.abnormal)) - Number(a.some((l) => l.abnormal)));
  return (
    <section aria-labelledby="pl" data-testid="pkg-labs"><h2 id="pl" className="text-xl mb-1">{t("pkg.labs")}</h2>
      <p className="text-sm text-muted mb-2">{t("pkg.lab.history")}</p>
      {err && <ErrorBox error={err} />}
      <ul className="space-y-2">{order.map((rows) => {
        const range = rows.map(labRange).find(Boolean);
        return (
          <li key={rows[0].test_key || rows[0].test_name} className="card text-sm" data-testid="lab-test">
            <div className="flex justify-between gap-2 flex-wrap"><p className="font-bold text-base">{name(rows[0])}</p>{range && <p className="text-muted">{t("pkg.lab.range")} {range}</p>}</div>
            <ol className="mt-1 divide-y divide-line">{rows.map((l) => {
              const f = flag(l);
              const pending = !l.reviewed && !l.decision;
              return (
                <li key={l.id || `${l.date}-${l.page}`} className="py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1" style={l.decision === "rejected" ? { opacity: 0.6 } : undefined}>
                  <span className="text-muted min-w-[7.5rem]">{fmtDate(l.date, { day: "numeric", month: "short", year: "numeric" })}</span>
                  <span className={`font-bold ${l.decision === "rejected" ? "line-through" : ""}`} style={l.abnormal ? { color: "var(--strong)" } : undefined}>{labValue(l)}</span>
                  {f && <span className="chip text-xs" style={l.abnormal ? { borderColor: "var(--strong)", color: "var(--strong)" } : undefined}>{f}</span>}
                  {!l.reviewed && !l.decision && <span className="chip text-xs">{t("pkg.lab.unreviewed")}</span>}
                  {l.decision && <span className="chip text-xs">{t(l.decision === "accepted" ? "pkg.lab.accepted" : "pkg.lab.rejected")}</span>}
                  {!l.reviewed && (
                    <span className="flex gap-2 ml-auto">
                      {pending ? (<>
                        <button className="btn" disabled={busy === l.id} onClick={() => decide(l, "accepted")}><Check size={16} aria-hidden /> {t("pkg.lab.accept")}</button>
                        <button className="btn" disabled={busy === l.id} onClick={() => decide(l, "rejected")}><X size={16} aria-hidden /> {t("pkg.lab.reject")}</button>
                      </>) : <button className="btn" disabled={busy === l.id} onClick={() => decide(l, "pending")}>{t("pkg.lab.undo")}</button>}
                    </span>
                  )}
                </li>);
            })}</ol>
          </li>);
      })}</ul>
    </section>
  );
}
