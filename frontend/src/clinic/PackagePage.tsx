import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, X } from "lucide-react";
import { api } from "../api";
import type { Brief, Entry, SharedLab, SharePackage } from "../types";
import { fmtDate, fmtNum, splitQuotes } from "../lib";
import { ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { BriefPanel } from "./BriefPanel";
import { termLabel, tn, useT } from "../i18n";

export default function PackagePage() {
  const { t, lang } = useT();
  const { id = "" } = useParams();
  const { data: loaded, error, loading, reload } = useAsync(() => api.package(id), [id]);
  const [decided, setDecided] = useState<SharePackage | null>(null);
  const data = decided && decided.package_id === id ? decided : loaded;
  const [brief, setBrief] = useState<Brief | null>(null);
  const [pane, setPane] = useState<"package" | "brief">("package"); // below lg the two columns become one switchable page
  const fetchBrief = useCallback(() => {
    // ask the inbox first: a brief that does not exist yet would be a 404 in the console
    return api.inbox().then((rows) => (rows.find((r) => r.package_id === id)?.brief_state !== "none" ? api.brief(id, { lang }) : null))
      .then(setBrief).catch(() => setBrief(null));
  }, [id, lang]);
  useEffect(() => { fetchBrief(); }, [fetchBrief]);
  // a lab decision changes the brief's lab lines: take the rebuilt brief from the server
  const onPackage = (p: SharePackage) => { setDecided(p); if (brief && !brief.finalized) api.brief(id, { lang }).then(setBrief).catch(() => undefined); };
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.notFound")} retry={reload} />;
  const open = brief ? brief.items.filter((i) => i.review === "pending").length : 0;
  const seg = (k: "package" | "brief") => (
    <button key={k} role="tab" aria-selected={pane === k} className="btn flex-1" onClick={() => { setPane(k); window.scrollTo({ top: 0 }); }}
      style={pane === k ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
      {k === "package" ? t("pkg.panePackage") : t("pkg.paneBrief")}{k === "brief" && open > 0 ? ` (${open})` : ""}
    </button>
  );
  return (
    <div>
      <div className="no-print mb-3"><Link to="/" className="text-accent underline underline-offset-4 text-sm">{t("pkg.inbox")}</Link></div>
      <div role="tablist" aria-label={t("pkg.paneSwitch")} data-testid="pane-switch"
        className="lg:hidden no-print sticky top-0 z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2 mb-3 flex gap-2 bg-panel border-b border-line">
        {seg("package")}{seg("brief")}
      </div>
      <div className="grid lg:grid-cols-2 gap-6 items-start">
        <div className={`no-print min-w-0 ${pane === "brief" ? "hidden lg:block" : ""}`}><PackageView pkg={data} onPackage={onPackage} /></div>
        <div className={`min-w-0 ${pane === "package" ? "hidden lg:block print:block" : ""}`}><BriefPanel pkg={data} brief={brief} setBrief={setBrief} /></div>
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
    if (!t) terms.set(k, { label: termLabel(e.hpo_id, e.canonical), hpo: e.hpo_id, first: e.occurred_on, last: e.occurred_on, count: 1 });
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
            <tr key={x.hpo ?? x.label} className="border-b border-line last:border-0"><td className="px-3 py-1.5 font-bold">{x.label}</td><td className="px-3 py-1.5 font-mono">{x.hpo ?? t("pkg.none")}</td>
              <td className="px-3 py-1.5">{fmtDate(x.first)}</td><td className="px-3 py-1.5">{fmtDate(x.last)}</td><td className="px-3 py-1.5">{x.count}</td></tr>
          ))}</tbody></table></div>
        <ul className="card p-0 divide-y divide-line sm:hidden" data-testid="terms-cards">{[...terms.values()].map((x) => (
          <li key={x.hpo ?? x.label} className="px-3 py-2 text-sm flex items-baseline gap-2 min-w-0">
            <span className="font-bold truncate">{x.label}</span>
            {x.hpo && <span className="font-mono text-xs text-muted shrink-0">{x.hpo}</span>}
            <span className="ml-auto text-muted shrink-0 whitespace-nowrap">{x.count}× · {fmtDate(x.first)}{x.first !== x.last ? `, ${fmtDate(x.last)}` : ""}</span>
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
      <p className="text-sm mt-1">{p.matched.map((m) => termLabel(m.hpo_id, m.label)).join(", ")}</p>
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

type Decision = "accepted" | "rejected" | "pending";

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
  const word = (s: string) => s.replace(/^\s*(positivo|positive)\b/i, t("pkg.lab.positiveWord")).replace(/^\s*(negativo|negative)\b/i, t("pkg.lab.negativeWord"));
  const value = (l: SharedLab) => `${l.value_text ? word(l.value_text) : l.value_numeric !== null ? fmtNum(l.value_numeric) : "?"}${l.unit ? " " + l.unit : ""}`;
  const range = (l: SharedLab) => {
    const lo = l.ref_low === null ? null : fmtNum(l.ref_low), hi = l.ref_high === null ? null : fmtNum(l.ref_high);
    return lo !== null && hi !== null ? t("labs.rangeBoth", { lo, hi }) : hi !== null ? t("labs.rangeUpTo", { hi }) : lo !== null ? t("labs.rangeFrom", { lo }) : "";
  };
  // one flag, never two: a text result that reads positive is already in the value
  const flag = (l: SharedLab) => (l.flag ? t(`pkg.lab.${l.flag}` as const) : "");
  const isPending = (l: SharedLab) => !l.reviewed && !l.decision;
  const run = async (key: string, f: () => Promise<SharePackage>) => {
    setBusy(key); setErr(null);
    try { onPackage(await f()); } catch (x) { setErr((x as Error).message); }
    setBusy(null);
  };
  const decide = (l: SharedLab, d: Decision) => run(l.id, () => api.decideLab(pkg.package_id, l.id, d));
  const pending = pkg.labs.filter(isPending);
  const pages = new Map<string, { entry: string | null; page: number; n: number }>();
  pending.forEach((l) => { const k = `${l.entry_id}|${l.page}`; pages.set(k, { entry: l.entry_id, page: l.page, n: (pages.get(k)?.n ?? 0) + 1 }); });
  const order = [...tests.values()].sort((a, b) => Number(b.some((l) => l.abnormal)) - Number(a.some((l) => l.abnormal)));
  const row = (l: SharedLab) => {
    const f = flag(l);
    return (
      <li key={l.id || `${l.date}-${l.page}`} className="py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1" style={l.decision === "rejected" ? { opacity: 0.6 } : undefined}>
        <span className="text-muted min-w-[7.5rem]">{fmtDate(l.date, { day: "numeric", month: "short", year: "numeric" })}</span>
        <span className={`font-bold ${l.decision === "rejected" ? "line-through" : ""}`} style={l.abnormal ? { color: "var(--strong)" } : undefined}>{value(l)}</span>
        {f && <span className="chip text-xs" style={l.abnormal ? { borderColor: "var(--strong)", color: "var(--strong)" } : undefined}>{f}</span>}
        {l.reviewed && <span className="chip text-xs">{t("pkg.lab.checked")}</span>}
        {isPending(l) && <span className="chip text-xs chip-review">{t("pkg.lab.unreviewed")}</span>}
        {l.decision && <span className="chip text-xs">{t(l.decision === "accepted" ? "pkg.lab.accepted" : "pkg.lab.rejected")}</span>}
        {!l.reviewed && (
          <span className="flex gap-2 ml-auto">
            {isPending(l) ? (<>
              <button className="btn" disabled={busy === l.id} onClick={() => decide(l, "accepted")}><Check size={16} aria-hidden /> {t("pkg.lab.accept")}</button>
              <button className="btn" disabled={busy === l.id} onClick={() => decide(l, "rejected")}><X size={16} aria-hidden /> {t("pkg.lab.reject")}</button>
            </>) : <button className="btn" disabled={busy === l.id} onClick={() => decide(l, "pending")}>{t("pkg.lab.undo")}</button>}
          </span>
        )}
      </li>
    );
  };
  return (
    <section aria-labelledby="pl" data-testid="pkg-labs"><h2 id="pl" className="text-xl mb-1">{t("pkg.labs")}</h2>
      <p className="text-sm text-muted mb-2">{t("pkg.lab.history")}</p>
      {err && <ErrorBox error={err} />}
      {pending.length > 0 && (
        <div className="card mb-2 space-y-2 text-sm" data-testid="lab-bulk">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-bold">{t("pkg.lab.pages")}</p>
            <button className="btn btn-primary" disabled={busy !== null} onClick={() => run("all", () => api.decideLabs(pkg.package_id, { decision: "accepted" }))}>
              <Check size={16} aria-hidden /> {t("pkg.lab.acceptEvery", { n: pending.length })}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">{[...pages.values()].map((g) => (
            <button key={`${g.entry}|${g.page}`} className="btn" disabled={busy !== null}
              onClick={() => run(`p${g.page}`, () => api.decideLabs(pkg.package_id, { decision: "accepted", page: g.page, entry_id: g.entry }))}>
              {tn("pkg.lab.acceptPage", g.n, { p: g.page })}
            </button>))}
          </div>
        </div>
      )}
      <ul className="space-y-2">{order.map((rows) => {
        const key = rows[0].test_key || rows[0].test_name;
        const open = rows.filter(isPending);
        const latest = rows[rows.length - 1];
        const rng = rows.map(range).find(Boolean);
        if (open.length === 0) {  // every row is checked or decided: one line, rows on demand (and Undo)
          const f = flag(latest);
          return (
            <li key={key} className="card text-sm py-2" data-testid="lab-test">
              <details>
                <summary className="cursor-pointer min-h-[44px] flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-bold text-base">{name(rows[0])}</span>
                  <span className="font-bold" style={latest.abnormal ? { color: "var(--strong)" } : undefined}>{value(latest)}</span>
                  {f && <span className="chip text-xs" style={latest.abnormal ? { borderColor: "var(--strong)", color: "var(--strong)" } : undefined}>{f}</span>}
                  <span className="text-muted ml-auto">{rows.some((l) => l.decision) ? tn("pkg.lab.decided", rows.filter((l) => l.decision).length) : t("pkg.lab.checked")}</span>
                </summary>
                <div className="mt-1">
                  {rng && <p className="text-muted">{t("pkg.lab.range")} {rng}</p>}
                  <ol className="mt-1 divide-y divide-line">{rows.map(row)}</ol>
                </div>
              </details>
            </li>);
        }
        return (
          <li key={key} className="card text-sm" data-testid="lab-test">
            <div className="flex justify-between gap-2 flex-wrap items-center">
              <p className="font-bold text-base">{name(rows[0])}</p>
              <span className="flex items-center gap-3 flex-wrap">
                {rng && <span className="text-muted">{t("pkg.lab.range")} {rng}</span>}
                {open.length > 1 && (
                  <button className="btn" disabled={busy !== null} onClick={() => run(`t${key}`, () => api.decideLabs(pkg.package_id, { decision: "accepted", test_key: key }))}>
                    <Check size={16} aria-hidden /> {t("pkg.lab.acceptAll", { n: open.length })}
                  </button>)}
              </span>
            </div>
            <ol className="mt-1 divide-y divide-line">{rows.map(row)}</ol>
          </li>);
      })}</ul>
    </section>
  );
}
