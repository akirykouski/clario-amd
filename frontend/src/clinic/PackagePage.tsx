import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, Check, MessageSquareQuote, X } from "lucide-react";
import { api } from "../api";
import type { Brief, Decisions, Entry, Overview, OverviewTerm, SharedLab, SharePackage, TermDecision } from "../types";
import { buildHeat, fmtDate, splitQuotes, weeklyMood } from "../lib";
import { ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { HeatStrip, type HeatPick } from "../components/HeatStrip";
import { BriefPanel, jumpTo } from "./BriefPanel";
import { Differential } from "./Differential";
import { tn, useT, type Key } from "../i18n";

const own = (pkg: SharePackage) => pkg.entities.filter((e) => !e.negated && !e.family_history);

export default function PackagePage() {
  const { t } = useT();
  const { id = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => api.package(id), [id]);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [decisions, setDecisions] = useState<Decisions>({ terms: {}, answers: [] });
  const [version, setVersion] = useState(0);  // bumps when a term decision changes the differential
  useEffect(() => {
    // ask the inbox first: a brief that does not exist yet would be a 404 in the console
    api.inbox().then((rows) => (rows.find((r) => r.package_id === id)?.brief_state !== "none" ? api.brief(id) : null))
      .then(setBrief).catch(() => setBrief(null));
    api.decisions(id).then(setDecisions).catch(() => {});
  }, [id]);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.notFound")} retry={reload} />;
  const decide = async (entId: string, d: TermDecision) => {
    try { setDecisions(await api.decideTerm(id, entId, d)); setVersion((v) => v + 1); } catch { /* keep state */ }
  };
  const decideLab = async (labId: string, d: TermDecision) => {
    try { setDecisions(await api.decideLab(id, labId, d)); } catch { /* keep state */ }
  };
  return (
    <div>
      <div className="no-print mb-3"><Link to="/" className="text-accent underline underline-offset-4 text-sm">{t("pkg.inbox")}</Link></div>
      <div className="grid xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] gap-6 items-start">
        <div className="no-print min-w-0 space-y-5">
          <Header pkg={data} brief={brief} />
          <Differential pid={id} version={version} />
          <NeedsCheck pkg={data} decisions={decisions} onDecide={decide} onDecideLab={decideLab} />
          <Heat pkg={data} />
          {data.labs.length > 0 && <LabsBlock labs={data.labs} decisions={decisions} />}
          <Details pkg={data} />
        </div>
        <div className="min-w-0"><BriefPanel pkg={data} brief={brief} setBrief={setBrief} /></div>
      </div>
    </div>
  );
}

function Header({ pkg, brief }: { pkg: SharePackage; brief: Brief | null }) {
  const { t, tn, lang } = useT();
  const [ov, setOv] = useState<Overview | null>(null);
  useEffect(() => { api.overview(pkg.package_id, lang).then(setOv).catch(() => setOv(null)); }, [pkg.package_id, lang]);
  const mine = own(pkg);
  const terms = new Set(mine.filter((e) => e.type !== "lab").map((e) => e.hpo_id ?? e.canonical.toLowerCase())).size;
  const abnormal = new Set(pkg.labs.filter((l) => l.flag === "low" || l.flag === "high").map((l) => l.test_name)).size;
  const summary = brief?.items.find((i) => i.section === "summary" && i.origin === "ai" && i.review !== "rejected");
  const p = ov?.profile ?? pkg.profile;
  const who = [p?.sex ? t(`ov.${p.sex}` as Key) : null, p?.age ? t("ov.age", { age: p.age }) : null].filter(Boolean).join(", ");
  const term = (x: OverviewTerm, n: number) =>
    `${x.label} (${tn("ov.notes", n)}${x.max_severity !== null && x.max_severity >= 5 ? `, ${t("ov.upTo", { n: x.max_severity })}` : ""})`;
  return (
    <header className="space-y-3">
      <div>
        <h1 className="text-3xl">{pkg.patient_alias}{who && <span className="text-xl text-muted font-sans ml-3" data-testid="pkg-who">{who}</span>}</h1>
        <p className="text-muted text-sm">{t("share.range", { a: fmtDate(pkg.period[0]), b: fmtDate(pkg.period[1]) })} · {t("pkg.expiresShort", { date: fmtDate(pkg.expires_at) })}</p>
        <p className="text-sm font-bold mt-1" data-testid="pkg-glance">{t("pkg.glance", { notes: pkg.entries.length, weeks: ov?.weeks ?? "?", terms, labs: abnormal })}</p>
        <p className="sr-only" data-testid="pkg-counts">{t("pkg.mentions", { m: mine.length, t: terms })}</p>
      </div>
      <section className="card space-y-3" data-testid="pkg-why" aria-labelledby="ov-title">
        <h2 id="ov-title" className="text-xl">{t("ov.title")}</h2>
        <div className="rounded-lg p-3" style={{ background: "color-mix(in srgb, var(--accent) 7%, transparent)" }}>
          <p className="text-xs font-bold uppercase tracking-wide text-muted flex items-center gap-1.5"><MessageSquareQuote size={14} aria-hidden />{t("ov.asks")}</p>
          {pkg.note ? <p className="text-lg mt-0.5">“{pkg.note}”</p>
            : ov?.asks.length ? ov.asks.slice(0, 2).map((a) => (
              <p key={a.entry_id} className="text-lg mt-0.5">“{a.text}” <button className="text-sm text-muted underline underline-offset-2" onClick={() => jumpTo(a.entry_id)}>{t("ov.asksFromNotes", { date: fmtDate(a.date) })}</button></p>
            )) : <p className="text-muted mt-0.5">{t("ov.noAsk")}</p>}
        </div>
        {ov && (
          <dl className="grid sm:grid-cols-[11rem_1fr] gap-x-4 gap-y-1.5 text-[15px]" data-testid="pkg-overview">
            {ov.frequent.length > 0 && <><dt className="text-muted">{t("ov.frequent")}</dt><dd>{ov.frequent.map((x) => term(x, x.count)).join(", ")}</dd></>}
            {ov.recent.length > 0 && <><dt className="text-muted">{t("ov.recent")}</dt>
              <dd>{ov.recent.map((x) => term(x, x.recent_count)).join(", ")}{ov.new.length > 0 && <span className="font-bold">{"; "}{t("ov.new", { list: ov.new.join(", ") })}</span>}</dd></>}
            {ov.first && <><dt className="text-muted">{t("ov.first")}</dt><dd>{ov.first.label}, {fmtDate(ov.first.first)}</dd></>}
            {ov.labs_off.length > 0 && <><dt className="text-muted">{t("ov.labs")}</dt>
              <dd>{ov.labs_off.map((l) => `${l.name} ${t(l.flag === "low" ? "ov.low" : "ov.high")} (${l.value}${l.unit ? " " + l.unit : ""})`).join(", ")}</dd></>}
            {ov.family.length > 0 && <><dt className="text-muted">{t("ov.family")}</dt><dd>{t("ov.familyRelative", { list: ov.family.join(", ") })}</dd></>}
            {ov.denied.length > 0 && <><dt className="text-muted">{t("ov.denied")}</dt><dd>{ov.denied.join(", ")}</dd></>}
            {ov.mood && <><dt className="text-muted">{t("ov.mood")}</dt><dd>{t("ov.moodLine", { avg: ov.mood.avg, trend: t(`ov.trend.${ov.mood.trend}` as Key) })}</dd></>}
          </dl>
        )}
        {summary && (
          <div className="border-t border-line pt-2">
            <p className="text-xs font-bold uppercase tracking-wide text-muted">{t("pkg.aiSummary")}</p>
            <p className="text-[15px] mt-0.5">{summary.text}</p>
          </div>
        )}
      </section>
    </header>
  );
}

function NeedsCheck({ pkg, decisions, onDecide, onDecideLab }: {
  pkg: SharePackage; decisions: Decisions; onDecide: (id: string, d: TermDecision) => void; onDecideLab: (id: string, d: TermDecision) => void;
}) {
  const { t } = useT();
  const items = pkg.entities.filter((e) => e.needs_review && e.id);
  const labs = pkg.labs.filter((l) => l.needs_review && l.id);
  if (!items.length && !labs.length) return null;
  const labDec = decisions.labs ?? {};
  const open = items.filter((e) => !decisions.terms[e.id as string]).length + labs.filter((l) => !labDec[l.id as string]).length;
  return (
    <section aria-labelledby="chk" className="card space-y-2" style={{ borderLeft: "5px solid var(--moderate)" }} data-testid="needs-check">
      <h2 id="chk" className="text-xl flex items-center gap-2"><AlertTriangle size={20} aria-hidden style={{ color: "var(--moderate)" }} />{tn("check.title", open)}</h2>
      <p className="text-sm text-muted">{t("check.sub")}</p>
      <ul className="divide-y divide-line">
        {items.map((e) => (
          <CheckRow key={e.id} decision={decisions.terms[e.id as string]} onDecide={(d) => onDecide(e.id as string, d)}
            title={`${e.negated ? "No " : ""}${e.canonical}`} confidence={e.confidence}
            sub={<>{t("check.wrote")}: <span className="clinic-quote">{e.quote}</span> · {fmtDate(e.occurred_on)}</>} />
        ))}
        {labs.map((l) => (
          <CheckRow key={l.id} decision={labDec[l.id as string]} onDecide={(d) => onDecideLab(l.id as string, d)}
            title={`${l.test_name}: ${labValue(l)}`} confidence={l.confidence}
            sub={<>{t("check.lab")} · {fmtDate(l.date)}, {t("pkg.lab.page", { n: l.page })}{labRange(l) && ` · ${labRange(l)}`}</>} />
        ))}
      </ul>
    </section>
  );
}

function CheckRow({ title, sub, confidence, decision, onDecide }: {
  title: string; sub: React.ReactNode; confidence?: number | null; decision?: TermDecision; onDecide: (d: TermDecision) => void;
}) {
  const { t } = useT();
  return (
    <li className="py-2 flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <p className={`font-bold ${decision === "rejected" ? "line-through text-muted" : ""}`}>{title}
          {confidence !== null && confidence !== undefined && <span className="text-xs text-muted font-normal"> · {Math.round(confidence * 100)}%</span>}</p>
        <p className="text-sm text-muted">{sub}</p>
      </div>
      {decision ? (
        <div className="flex items-center gap-2 text-sm">
          <span style={{ color: decision === "confirmed" ? "var(--accent)" : "var(--muted)" }}>{decision === "confirmed" ? t("check.confirmed") : t("check.rejected")}</span>
          <button className="btn-quiet btn px-1 min-h-[32px] text-sm" onClick={() => onDecide("pending")}>{t("check.undo")}</button>
        </div>
      ) : (
        <div className="flex gap-2">
          <button className="btn btn-sm" onClick={() => onDecide("confirmed")}><Check size={14} aria-hidden />{t("common.confirm")}</button>
          <button className="btn btn-sm" onClick={() => onDecide("rejected")}><X size={14} aria-hidden />{t("common.reject")}</button>
        </div>
      )}
    </li>
  );
}

function Heat({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  const [systems, setSystems] = useState<Record<string, string>>({});
  const [pick, setPick] = useState<HeatPick | null>(null);
  const terms = useMemo(() => {
    const m = new Map<string, { hpo_id: string; label: string; entry_ids: string[]; first_seen: string; last_seen: string; count: number }>();
    own(pkg).filter((e) => e.type !== "lab").forEach((e) => {
      const k = e.hpo_id ?? e.canonical;
      const cur = m.get(k) ?? { hpo_id: k, label: e.canonical, entry_ids: [], first_seen: e.occurred_on, last_seen: e.occurred_on, count: 0 };
      if (!cur.entry_ids.includes(e.entry_id)) { cur.entry_ids.push(e.entry_id); cur.count++; }
      m.set(k, cur);
    });
    return [...m.values()];
  }, [pkg]);
  const ids = terms.map((x) => x.hpo_id).filter((x) => x.startsWith("HP:"));
  useEffect(() => { if (ids.length) api.termSystems(ids).then(setSystems).catch(() => {}); }, [ids.join()]); // eslint-disable-line react-hooks/exhaustive-deps
  const dates: Record<string, string> = Object.fromEntries(pkg.entries.map((e) => [e.id, e.occurred_on]));
  const heat = buildHeat(terms, dates, systems);
  if (!heat.rows.length) return null;
  const byId = Object.fromEntries(pkg.entries.map((e) => [e.id, e]));
  return (
    <section aria-labelledby="ht" className="card" data-testid="pkg-heat">
      <h2 id="ht" className="text-xl mb-2">{t("pkg.heat")}</h2>
      <HeatStrip heat={heat} mood={weeklyMood(heat.weeks, pkg.entries)} selected={pick}
        onPick={(p) => setPick(pick && pick.hpo_id === p.hpo_id && pick.week === p.week ? null : p)} />
      {pick && (
        <ul className="mt-3 border-t border-line pt-2 space-y-1" aria-live="polite">
          {pick.entryIds.map((eid) => byId[eid] && (
            <li key={eid} className="text-[15px]"><span className="text-muted text-sm mr-2">{fmtDate(byId[eid].occurred_on)}</span>
              <button className="text-left underline underline-offset-4" onClick={() => jumpTo(eid)}>{byId[eid].text}</button></li>
          ))}
        </ul>
      )}
    </section>
  );
}

const labValue = (l: SharedLab) => `${l.value_text ?? (l.value_numeric ?? "?")}${l.unit ? " " + l.unit : ""}`;
const labRange = (l: SharedLab) => (l.ref_low === null && l.ref_high === null ? "" : `${l.ref_low ?? ""} - ${l.ref_high ?? ""}`);

function LabsBlock({ labs: all, decisions }: { labs: SharedLab[]; decisions: Decisions }) {
  const { t } = useT();
  const rejected = decisions.labs ?? {};
  const labs = all.filter((l) => !l.id || rejected[l.id] !== "rejected");  // a value the clinician rejected leaves the tables
  const off = labs.filter((l) => l.flag === "low" || l.flag === "high");
  return (
    <section aria-labelledby="pl" data-testid="pkg-labs" className="card space-y-2">
      <h2 id="pl" className="text-xl">{t("pkg.labsAbnormal")}</h2>
      {off.length > 0 ? <LabsTable labs={off} /> : <p className="text-sm text-muted">-</p>}
      <details>
        <summary className="cursor-pointer min-h-[44px] flex items-center text-sm text-accent underline underline-offset-4">{t("pkg.labsAll", { n: labs.length })}</summary>
        <LabsTable labs={labs} />
      </details>
    </section>
  );
}

function LabsTable({ labs }: { labs: SharedLab[] }) {
  const { t } = useT();
  const flag = (l: SharedLab) => (l.flag ? t(`pkg.lab.${l.flag}` as const) : "");
  const note = (l: SharedLab) => (l.needs_review ? t("pkg.lab.unsure") : !l.reviewed ? t("pkg.lab.unreviewed") : "");
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm">
      <thead><tr className="text-left text-muted border-b border-line">{(["pkg.lab.test", "pkg.lab.value", "pkg.lab.range", "pkg.lab.flag", "pkg.lab.date"] as const).map((h) => <th key={h} className="px-2 py-1.5">{t(h)}</th>)}<th className="px-2 py-1.5" /></tr></thead>
      <tbody>{labs.map((l, i) => (
        <tr key={i} className="border-b border-line last:border-0">
          <td className="px-2 py-1.5 font-bold">{l.test_name}</td>
          <td className="px-2 py-1.5" style={l.flag === "low" || l.flag === "high" ? { color: "var(--strong)", fontWeight: 700 } : undefined}>{labValue(l)}</td>
          <td className="px-2 py-1.5">{labRange(l)}</td><td className="px-2 py-1.5">{flag(l)}</td>
          <td className="px-2 py-1.5 whitespace-nowrap">{fmtDate(l.date)}, {t("pkg.lab.page", { n: l.page })}</td>
          <td className="px-2 py-1.5 text-xs" style={{ color: l.needs_review ? "var(--moderate)" : "var(--muted)" }}>{note(l)}</td>
        </tr>))}</tbody></table></div>
  );
}

function Details({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  const terms = new Map<string, { label: string; hpo: string | null; first: string; last: string; count: number; unsure: boolean }>();
  own(pkg).forEach((e) => {
    const k = e.hpo_id ?? e.canonical;
    const x = terms.get(k);
    if (!x) terms.set(k, { label: e.canonical, hpo: e.hpo_id, first: e.occurred_on, last: e.occurred_on, count: 1, unsure: !!e.needs_review });
    else { x.count++; x.unsure ||= !!e.needs_review; if (e.occurred_on < x.first) x.first = e.occurred_on; if (e.occurred_on > x.last) x.last = e.occurred_on; }
  });
  const family = pkg.entities.filter((e) => e.family_history && !e.negated);
  const entries = [...pkg.entries].sort((a, b) => a.occurred_on.localeCompare(b.occurred_on));
  return (
    <details className="card" data-testid="pkg-details">
      <summary className="cursor-pointer min-h-[44px] flex items-center font-bold">{t("pkg.details")}</summary>
      <div className="space-y-5 mt-3">
        <section aria-labelledby="pt"><h2 id="pt" className="text-lg mb-2">{t("pkg.terms")}</h2>
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="text-left text-muted border-b border-line">{(["pkg.term", "pkg.hpo", "pkg.first", "pkg.last", "pkg.count"] as const).map((h) => <th key={h} className="px-2 py-1.5">{t(h)}</th>)}</tr></thead>
            <tbody>{[...terms.values()].map((x) => (
              <tr key={x.label} className="border-b border-line last:border-0"><td className="px-2 py-1.5 font-bold">{x.label}{x.unsure && <span className="text-xs font-normal" style={{ color: "var(--moderate)" }}> · {t("pkg.unsure")}</span>}</td><td className="px-2 py-1.5 font-mono">{x.hpo ?? t("pkg.none")}</td>
                <td className="px-2 py-1.5">{fmtDate(x.first)}</td><td className="px-2 py-1.5">{fmtDate(x.last)}</td><td className="px-2 py-1.5">{x.count}</td></tr>
            ))}</tbody></table></div>
        </section>
        {family.length > 0 && (
          <section aria-labelledby="pf"><h2 id="pf" className="text-lg mb-1">{t("pkg.family")}</h2>
            <p className="text-sm text-muted mb-2">{t("pkg.familyHint")}</p>
            <ul className="space-y-1 text-sm">{family.map((f, i) => <li key={i}>{f.canonical} <span className="text-muted">({fmtDate(f.occurred_on)})</span></li>)}</ul>
          </section>
        )}
        <section aria-labelledby="et"><h2 id="et" className="text-lg mb-2">{t("pkg.entries")}</h2>
          <ol className="space-y-3">{entries.map((e) => <EntryRow key={e.id} e={e} pkg={pkg} />)}</ol>
        </section>
      </div>
    </details>
  );
}

function EntryRow({ e, pkg }: { e: Entry; pkg: SharePackage }) {
  const { t } = useT();
  const quotes = pkg.entities.filter((s) => s.entry_id === e.id).map((s) => s.quote);
  return (
    <li id={`entry-${e.id}`} className="border border-line rounded-xl p-3 scroll-mt-4 target:ring-2 target:ring-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)] outline-none" tabIndex={-1}>
      <p className="text-sm text-muted">{fmtDate(e.occurred_on, { weekday: "short", day: "numeric", month: "short" })}{e.mood !== null && t("pkg.mood", { n: e.mood })}</p>
      <p className="whitespace-pre-wrap text-[15px]">{splitQuotes(e.text, quotes).map((s, i) => s.quoted ? <span key={i} className="clinic-quote">{s.text}</span> : <span key={i}>{s.text}</span>)}</p>
    </li>
  );
}
