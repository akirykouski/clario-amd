import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowLeftRight, Check, MessageSquareQuote, Pencil, X } from "lucide-react";
import { api } from "../api";
import type { Brief, Decisions, Entry, LabCorrection, LabReading, Overview, OverviewLab, OverviewTerm, SharedLab, SharePackage, Term, TermCorrection, TermDecision } from "../types";
import { buildHeat, clinicFlagNote, fmtDate, fmtNum, pastWhen, splitQuotes, weeklyMood } from "../lib";
import { ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { HeatStrip, type HeatPick } from "../components/HeatStrip";
import { BriefPanel, jumpTo } from "./BriefPanel";
import { Differential } from "./Differential";
import { CareFacts, ComparePanel, SecondOpinionBanner } from "./SecondOpinion";
import { termLabel, tn, useT, type Key } from "../i18n";

// the patient's current terms: past history ("knee surgery 5 years ago") is listed apart and never lights up a week
const own = (pkg: SharePackage) => pkg.entities.filter((e) => !e.negated && !e.family_history && !e.past);
const pastOf = (pkg: SharePackage) => pkg.entities.filter((e) => e.past && !e.negated && !e.family_history);

export default function PackagePage() {
  const { t, lang } = useT();
  const { id = "" } = useParams();
  const { data: loaded, error, loading, reload } = useAsync(() => api.package(id), [id]);
  const [decided, setDecided] = useState<SharePackage | null>(null);  // the package again after a bulk lab decision
  const data = decided && decided.package_id === id ? decided : loaded;
  const [brief, setBrief] = useState<Brief | null>(null);
  const [decisions, setDecisions] = useState<Decisions>({ terms: {}, answers: [] });
  const [version, setVersion] = useState(0);  // bumps when a term decision changes the differential
  const [search] = useSearchParams();
  const asked = search.get("pane") === "brief" ? "brief" : "package";  // ?pane=brief opens the brief (the onboarding tour)
  const [pane, setPane] = useState<"package" | "brief">(asked); // below xl the two columns become one switchable page
  useEffect(() => { setPane(asked); }, [asked]);
  const fetchBrief = useCallback(() => {
    // ask the inbox first: a brief that does not exist yet would be a 404 in the console
    return api.inbox().then((rows) => (rows.find((r) => r.package_id === id)?.brief_state !== "none" ? api.brief(id, { lang }) : null))
      .then(setBrief).catch(() => setBrief(null));
  }, [id, lang]);
  useEffect(() => { fetchBrief(); }, [fetchBrief]);
  useEffect(() => { api.decisions(id).then(setDecisions).catch(() => {}); }, [id]);
  // a lab decision changes the brief's lab lines and what blocks finalizing: take both from the server
  const refreshAfterLab = () => {
    api.package(id).then(setDecided).catch(() => undefined);
    if (!brief?.finalized) api.brief(id, { lang }).then(setBrief).catch(() => undefined);
  };
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.notFound")} retry={reload} />;
  // a replaced term changes the package itself (new id and label): take the package, overview and brief lines again
  const refreshAfterReplace = () => {
    api.package(id).then(setDecided).catch(() => undefined);
    if (brief && !brief.finalized) api.brief(id, { lang }).then(setBrief).catch(() => undefined);
  };
  const decide = async (entId: string, d: TermDecision) => {
    const wasReplaced = decisions.terms[entId] === "corrected";
    try {
      setDecisions(await api.decideTerm(id, entId, d)); setVersion((v) => v + 1);
      if (wasReplaced) refreshAfterReplace();
    } catch { /* keep state */ }
  };
  const replace = async (entId: string, hpoId: string) => {
    try { setDecisions(await api.replaceTerm(id, entId, hpoId)); setVersion((v) => v + 1); refreshAfterReplace(); } catch { /* keep state */ }
  };
  // a checked reading starts (or stops) feeding the differential: bump `version` so the ranking is fetched again
  const decideLab = async (labId: string, d: TermDecision) => {
    try { setDecisions(await api.decideLab(id, labId, d)); setVersion((v) => v + 1); refreshAfterLab(); } catch { /* keep state */ }
  };
  const correctLab = async (labId: string, c: LabCorrection): Promise<boolean> => {
    try { setDecisions(await api.correctLab(id, labId, c)); setVersion((v) => v + 1); refreshAfterLab(); return true; } catch { return false; }
  };
  const decideLabs = async (b: { decision: TermDecision; page?: number; entry_id?: string | null }) => {
    try {
      setDecided(await api.decideLabs(id, b)); setDecisions(await api.decisions(id)); setVersion((v) => v + 1);
      if (!brief?.finalized) fetchBrief();
    } catch { /* keep state */ }
  };
  const unsigned = !!brief && !brief.finalized;  // an AI draft nobody has signed yet
  const seg = (k: "package" | "brief") => (
    <button key={k} role="tab" aria-selected={pane === k} className="btn flex-1" onClick={() => { setPane(k); window.scrollTo({ top: 0 }); }}
      style={pane === k ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
      {k === "package" ? t("pkg.panePackage") : t("pkg.paneBrief")}{k === "brief" && unsigned ? ` (${t("pkg.paneDraft")})` : ""}
    </button>
  );
  return (
    <div>
      <div className="no-print mb-3"><Link to="/" className="text-accent underline underline-offset-4 text-sm">{t("pkg.inbox")}</Link></div>
      <div role="tablist" aria-label={t("pkg.paneSwitch")} data-testid="pane-switch" data-tour-inset="top"
        className="xl:hidden no-print sticky top-0 z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2 mb-3 flex gap-2 bg-panel border-b border-line">
        {seg("package")}{seg("brief")}
      </div>
      <div className="grid xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] gap-6 items-start">
        <div className={`no-print min-w-0 space-y-5 ${pane === "brief" ? "hidden xl:block" : ""}`}>
          <SecondOpinionBanner pkg={data} />
          <Header pkg={data} brief={brief} version={version} />
          <ComparePanel pkg={data} finalized={!!brief?.finalized} />
          <CareFacts pkg={data} />
          <Differential pid={id} version={version} />
          <NeedsCheck pkg={data} decisions={decisions} onDecide={decide} onReplace={replace} onDecideLab={decideLab} onCorrectLab={correctLab} onDecideLabs={decideLabs} />
          <Heat pkg={data} />
          {data.labs.length > 0 && <LabsBlock labs={data.labs} decisions={decisions} />}
          <Details pkg={data} />
        </div>
        <div className={`min-w-0 ${pane === "package" ? "hidden xl:block print:block" : ""}`}><BriefPanel pkg={data} brief={brief} setBrief={setBrief} /></div>
      </div>
    </div>
  );
}

function Header({ pkg, brief, version = 0 }: { pkg: SharePackage; brief: Brief | null; version?: number }) {
  const { t, tn, lang } = useT();
  const [ov, setOv] = useState<Overview | null>(null);
  // `version` bumps after a term decision: a replaced term changes what the overview counts
  useEffect(() => { api.overview(pkg.package_id, lang).then(setOv).catch(() => setOv(null)); }, [pkg.package_id, lang, version]);
  const mine = own(pkg);
  const terms = new Set(mine.filter((e) => e.type !== "lab").map((e) => e.hpo_id ?? e.canonical.toLowerCase())).size;
  // the same set the glance lists and the lab table marks: tests with an out-of-range result
  const abnormal = ov ? ov.labs_off.length : new Set(pkg.labs.filter(isOff).map((l) => l.test_key || l.test_name)).size;
  const summary = brief?.items.find((i) => i.section === "summary" && i.origin === "ai" && i.review !== "rejected");
  const p = ov?.profile ?? pkg.profile;
  const who = [p?.sex ? t(`ov.${p.sex}` as Key) : null, p?.age ? t("ov.age", { age: p.age }) : null].filter(Boolean).join(", ");
  const term = (x: OverviewTerm, n: number) =>
    `${x.label} (${tn("ov.notes", n)}${x.max_severity !== null && x.max_severity >= 5 ? `, ${t("ov.upTo", { n: x.max_severity })}` : ""})`;
  return (
    <header className="space-y-3" data-tour="pkg-glance">
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
              <dd data-testid="ov-labs">{ov.labs_off.map((l) => glanceLab(l, t)).join(", ")}</dd></>}
            {(ov.past?.length ?? 0) > 0 && <><dt className="text-muted">{t("ov.past")}</dt>
              <dd data-testid="ov-past">{ov.past!.map((p) => `${p.label}, ${p.when}`).join("; ")}</dd></>}
            {ov.family.length > 0 && <><dt className="text-muted">{t("ov.family")}</dt><dd>{t("ov.familyRelative", { list: ov.family.join(", ") })}</dd></>}
            {ov.denied.length > 0 && <><dt className="text-muted">{t("ov.denied")}</dt><dd>{ov.denied.join(", ")}</dd></>}
            {ov.mood && <><dt className="text-muted">{t("ov.mood")}</dt><dd>{t("ov.moodLine", { avg: fmtNum(ov.mood.avg), trend: t(`ov.trend.${ov.mood.trend}` as Key) })}</dd></>}
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

function NeedsCheck({ pkg, decisions, onDecide, onReplace, onDecideLab, onCorrectLab, onDecideLabs }: {
  pkg: SharePackage; decisions: Decisions; onDecide: (id: string, d: TermDecision) => void; onReplace: (id: string, hpoId: string) => void;
  onDecideLab: (id: string, d: TermDecision) => void; onCorrectLab: (id: string, c: LabCorrection) => Promise<boolean>;
  onDecideLabs: (b: { decision: TermDecision; page?: number; entry_id?: string | null }) => void;
}) {
  const { t } = useT();
  // a replaced term arrives already checked (it carries the clinician's term): keep it listed so it can be undone
  const items = pkg.entities.filter((e) => e.id && (e.needs_review || decisions.terms[e.id] === "corrected"));
  const fixes = decisions.corrections ?? {};
  const flagsById = new Map(pkg.entries.flatMap((en) => en.entities.map((x) => [x.id, x.flags] as const)));
  const labs = pkg.labs.filter((l) => l.needs_review && l.id);
  if (!items.length && !labs.length) return null;
  const labDec: Record<string, TermDecision | undefined> = { ...Object.fromEntries(labs.map((l) => [l.id as string, l.decision ?? undefined])), ...decisions.labs };
  const openLabs = labs.filter((l) => !labDec[l.id as string]);
  const open = items.filter((e) => !decisions.terms[e.id as string]).length + openLabs.length;
  const pages = new Map<string, { entry: string | null; page: number; n: number }>();
  openLabs.forEach((l) => { const k = `${l.entry_id}|${l.page}`; pages.set(k, { entry: l.entry_id, page: l.page, n: (pages.get(k)?.n ?? 0) + 1 }); });
  return (
    <section aria-labelledby="chk" className="card space-y-2" style={{ borderLeft: "5px solid var(--moderate)" }} data-testid="needs-check" data-tour="needs-check">
      <h2 id="chk" className="text-xl flex items-center gap-2"><AlertTriangle size={20} aria-hidden style={{ color: "var(--moderate)" }} />{tn("check.title", open)}</h2>
      <p className="text-sm text-muted">{t("check.sub")}</p>
      {labs.length > 0 && <p className="text-sm text-muted" data-testid="lab-counts-note">{t("check.labCounts")}</p>}
      {openLabs.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="lab-bulk">
          <button className="btn btn-sm btn-primary" onClick={() => onDecideLabs({ decision: "confirmed" })}>
            <Check size={14} aria-hidden /> {t("pkg.lab.confirmEvery", { n: openLabs.length })}
          </button>
          {pages.size > 1 && [...pages.values()].map((g) => (
            <button key={`${g.entry}|${g.page}`} className="btn btn-sm" onClick={() => onDecideLabs({ decision: "confirmed", page: g.page, entry_id: g.entry })}>
              {tn("pkg.lab.confirmPage", g.n, { p: g.page })}
            </button>))}
        </div>
      )}
      <ul className="divide-y divide-line">
        {items.map((e) => {
          const fix: TermCorrection | undefined = decisions.terms[e.id as string] === "corrected" ? fixes[e.id as string] : undefined;
          const why = fix ? null : clinicFlagNote(flagsById.get(e.id as string) ?? []);
          return (
            <CheckRow key={e.id} decision={decisions.terms[e.id as string]} onDecide={(d) => onDecide(e.id as string, d)}
              title={`${e.past ? t("term.pastChip") : ""}${e.negated ? "No " : ""}${fix ? termLabel(fix.to, fix.label) : termLabel(e.hpo_id, e.canonical)}`} confidence={fix ? null : e.confidence}
              replacedFrom={fix ? termLabel(fix.from, fix.from_label) : undefined}
              replace={e.family_history ? undefined : { pid: pkg.package_id, entId: e.id as string, current: e.hpo_id, onPick: (h) => onReplace(e.id as string, h) }}
              sub={<>{t("check.wrote")}: <span className="clinic-quote">{e.quote}</span> · {fmtDate(e.occurred_on)}{why && <> · <span data-testid="check-why">{why}</span></>}</>} />
          );
        })}
        {labs.map((l) => (
          <LabCheckRow key={l.id} lab={l} decision={labDec[l.id as string]} was={decisions.lab_fixes?.[l.id as string]?.from ?? l.corrected_from ?? null}
            onDecide={(d) => onDecideLab(l.id as string, d)} onCorrect={(c) => onCorrectLab(l.id as string, c)} />
        ))}
      </ul>
    </section>
  );
}

type ReplaceTarget = { pid: string; entId: string; current: string | null; onPick: (hpoId: string) => void };

function CheckRow({ title, sub, confidence, decision, onDecide, replace, replacedFrom }: {
  title: string; sub: React.ReactNode; confidence?: number | null; decision?: TermDecision; onDecide: (d: TermDecision) => void;
  replace?: ReplaceTarget; replacedFrom?: string;
}) {
  const { t } = useT();
  const [picking, setPicking] = useState(false);
  const said = decision === "confirmed" ? t("check.confirmed") : decision === "corrected" ? t("check.replaced", { was: replacedFrom ?? "" }) : t("check.rejected");
  return (
    <li className="py-2 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className={`font-bold ${decision === "rejected" ? "line-through text-muted" : ""}`}>{title}
            {confidence !== null && confidence !== undefined && <span className="text-xs text-muted font-normal"> · {Math.round(confidence * 100)}%</span>}</p>
          <p className="text-sm text-muted">{sub}</p>
        </div>
        {decision ? (
          <div className="flex items-center gap-2 text-sm">
            <span style={{ color: decision === "rejected" ? "var(--muted)" : "var(--accent)" }}>{said}</span>
            <button className="btn-quiet btn px-1 min-h-[32px] text-sm" onClick={() => onDecide("pending")}>{t("check.undo")}</button>
          </div>
        ) : (
          <div className="flex gap-2">
            <button className="btn btn-sm" onClick={() => onDecide("confirmed")}><Check size={14} aria-hidden />{t("common.confirm")}</button>
            <button className="btn btn-sm" onClick={() => onDecide("rejected")}><X size={14} aria-hidden />{t("common.reject")}</button>
            {replace && (
              <button className="btn btn-sm" aria-expanded={picking} onClick={() => setPicking(!picking)}>
                <ArrowLeftRight size={14} aria-hidden />{t("check.replace")}
              </button>
            )}
          </div>
        )}
      </div>
      {replace && picking && !decision && (
        <ReplacePicker target={replace} onCancel={() => setPicking(false)} onPick={(h) => { setPicking(false); replace.onPick(h); }} />
      )}
    </li>
  );
}

/** One lab reading the code checks sent to the clinician: the value as read, why it waits, and its source (the printed
 * row cut from the report page) so the clinician compares it with the paper and confirms, rejects or corrects it. */
function LabCheckRow({ lab: l, decision, was, onDecide, onCorrect }: {
  lab: SharedLab; decision?: TermDecision; was: LabReading | null; onDecide: (d: TermDecision) => void;
  onCorrect: (c: LabCorrection) => Promise<boolean>;
}) {
  const { t, lang } = useT();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState(l.unit);
  const [failed, setFailed] = useState(false);
  const where = `${fmtDate(l.date)}, ${t("pkg.lab.page", { n: l.page })}`;
  const reasons = (l.checks ?? []).map((k) => t(`check.reason.${k}` as Key)).filter((x) => !x.startsWith("check.reason."));
  const wasText = was ? `${was.value_text ?? (was.value_numeric !== null ? fmtNum(was.value_numeric) : "?")}${was.unit ? " " + was.unit : ""}` : "";
  const said = decision === "confirmed" ? t("check.confirmed") : decision === "corrected" ? t("check.labCorrected", { was: wasText })
    : t("check.rejected");
  const startEdit = () => {
    setValue(l.value_text ?? (l.value_numeric !== null ? fmtNum(l.value_numeric) : "")); setUnit(l.unit); setFailed(false); setEditing(true);
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    const ok = await onCorrect({ value: value.trim(), unit: unit.trim() });
    setFailed(!ok);
    if (ok) setEditing(false);
  };
  return (
    <li className="py-2 space-y-2" data-testid="lab-check">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className={`font-bold ${decision === "rejected" ? "line-through text-muted" : ""}`}>{labName(l, lang)}: {labValue(l, t)}
            {l.confidence !== null && l.confidence !== undefined && !decision && <span className="text-xs text-muted font-normal"> · {Math.round(l.confidence * 100)}%</span>}</p>
          <p className="text-sm text-muted">{t("check.lab")} · {where}{labRange(l, t) && ` · ${labRange(l, t)}`}</p>
          {reasons.length > 0 && !decision && <p className="text-sm" style={{ color: "var(--moderate)" }} data-testid="lab-why">{t("check.labWhy", { list: reasons.join("; ") })}</p>}
        </div>
        {decision ? (
          <div className="flex items-center gap-2 text-sm">
            <span style={{ color: decision === "rejected" ? "var(--muted)" : "var(--accent)" }}>{said}</span>
            <button className="btn-quiet btn px-1 min-h-[32px] text-sm" onClick={() => onDecide("pending")}>{t("check.undo")}</button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-sm" onClick={() => onDecide("confirmed")}><Check size={14} aria-hidden />{t("common.confirm")}</button>
            <button className="btn btn-sm" onClick={() => onDecide("rejected")}><X size={14} aria-hidden />{t("common.reject")}</button>
            <button className="btn btn-sm" aria-expanded={editing} onClick={() => (editing ? setEditing(false) : startEdit())}>
              <Pencil size={14} aria-hidden />{t("check.labCorrect")}
            </button>
          </div>
        )}
      </div>
      {l.crop ? (
        <figure className="space-y-1" data-testid="lab-source">
          <figcaption className="text-xs text-muted">{t("check.labSource")} · {where}</figcaption>
          <img src={l.crop} alt={`${t("check.labSource")}: ${l.test_name}, ${where}`} className="max-w-full rounded border border-line bg-white" />
        </figure>
      ) : (
        <p className="text-xs text-muted" data-testid="lab-source">{t("check.labNoSource", { where })}</p>
      )}
      {editing && !decision && (
        <form className="rounded-lg border border-line p-3 space-y-2" onSubmit={submit} data-testid="lab-correct">
          <p className="text-sm font-bold">{t("check.labCorrectTitle")}</p>
          <div className="flex flex-wrap gap-2 items-end">
            <label className="text-sm flex flex-col gap-1">{t("check.labValue")}
              <input className="input w-36" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
            </label>
            <label className="text-sm flex flex-col gap-1">{t("check.labUnit")}
              <input className="input w-28" value={unit} onChange={(e) => setUnit(e.target.value)} />
            </label>
            <button type="submit" className="btn btn-sm btn-primary" disabled={!value.trim()}>{t("common.save")}</button>
            <button type="button" className="btn-quiet btn px-1 min-h-[32px] text-sm" onClick={() => setEditing(false)}>{t("common.cancel")}</button>
          </div>
          {failed && <p className="text-sm" role="alert" style={{ color: "var(--strong)" }}>{t("common.tryAgain")}</p>}
        </form>
      )}
    </li>
  );
}

/** Other ontology terms for the patient's words, plus a search over the whole term list. No model call. */
function ReplacePicker({ target, onPick, onCancel }: { target: ReplaceTarget; onPick: (hpoId: string) => void; onCancel: () => void }) {
  const { t, lang } = useT();
  const [cands, setCands] = useState<Term[] | null>(null);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Term[] | null>(null);
  useEffect(() => { api.termCandidates(target.pid, target.entId, lang).then(setCands).catch(() => setCands([])); }, [target.pid, target.entId, lang]);
  useEffect(() => {
    const v = q.trim();
    if (v.length < 3) { setFound(null); return; }
    const h = setTimeout(() => { api.searchTerms(v, lang).then(setFound).catch(() => setFound([])); }, 250);
    return () => clearTimeout(h);
  }, [q, lang]);
  const shown = (found ?? cands ?? []).filter((c) => c.hpo_id !== target.current);
  return (
    <div className="rounded-lg border border-line p-3 space-y-2" data-testid="replace-picker">
      <p className="text-sm font-bold">{t("check.replaceTitle")}</p>
      <input type="search" className="input w-full" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={t("check.replaceSearch")} aria-label={t("check.replaceSearch")} />
      {cands === null && found === null ? <p className="text-sm text-muted">{t("common.loading")}</p> : shown.length === 0 ? (
        <p className="text-sm text-muted">{t("check.replaceNone")}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {shown.map((c) => (
            <li key={c.hpo_id}>
              <button className="btn btn-sm" onClick={() => onPick(c.hpo_id)}>
                {c.label} <span className="font-mono text-xs text-muted">{c.hpo_id}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button className="btn-quiet btn px-1 min-h-[32px] text-sm" onClick={onCancel}>{t("common.cancel")}</button>
    </div>
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

type TFn = ReturnType<typeof useT>["t"];
const labName = (l: SharedLab, lang: string) => (lang === "en" && l.name_en ? l.name_en : l.test_name);
const labWord = (s: string, t: TFn) => s.replace(/^\s*(positivo|positive)\b/i, t("pkg.lab.positiveWord")).replace(/^\s*(negativo|negative)\b/i, t("pkg.lab.negativeWord"));
const labValue = (l: SharedLab, t: TFn) => `${l.value_text ? labWord(l.value_text, t) : l.value_numeric !== null ? fmtNum(l.value_numeric) : "?"}${l.unit ? " " + l.unit : ""}`;
const labRange = (l: SharedLab, t: TFn) => {
  const lo = l.ref_low === null ? null : fmtNum(l.ref_low), hi = l.ref_high === null ? null : fmtNum(l.ref_high);
  return lo !== null && hi !== null ? t("labs.rangeBoth", { lo, hi }) : hi !== null ? t("labs.rangeUpTo", { hi }) : lo !== null ? t("labs.rangeFrom", { lo }) : "";
};
const isOff = (l: SharedLab) => l.abnormal || l.flag === "low" || l.flag === "high" || l.flag === "positive";
/** "Sodium high (147 mmol/L)", "C4 high (48 mg/dL, now in range)", "ANA Positive 1:160 (now negative)" */
const glanceLab = (l: OverviewLab, t: TFn) => {
  const later = l.latest_in_range ? t(l.flag === "positive" ? "ov.nowNegative" : "ov.nowInRange") : "";
  if (l.flag === "positive") return `${l.name} ${labWord(l.value, t)}${later ? ` (${later})` : ""}`;
  return `${l.name} ${t(l.flag === "low" ? "ov.low" : "ov.high")} (${l.value}${l.unit ? " " + l.unit : ""}${later ? ", " + later : ""})`;
};

function LabsBlock({ labs: all, decisions }: { labs: SharedLab[]; decisions: Decisions }) {
  const { t } = useT();
  const rejected = decisions.labs ?? {};
  // a value the clinician rejected leaves the tables; a test reads as one history, oldest to newest
  const labs = all.filter((l) => l.decision !== "rejected" && !(l.id && rejected[l.id] === "rejected"))
    .sort((a, b) => (a.test_key || a.test_name).localeCompare(b.test_key || b.test_name) || a.date.localeCompare(b.date) || a.page - b.page);
  const off = labs.filter(isOff);
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
  const { t, lang } = useT();
  // a qualitative result ("Positive 1:160") says it in its value: no second word in the flag column
  const flag = (l: SharedLab) => (l.flag && l.value_numeric !== null ? t(`pkg.lab.${l.flag}` as const) : "");
  const note = (l: SharedLab) => (l.decision === "corrected" || l.corrected_from ? t("pkg.lab.corrected") : l.needs_review && !l.decision ? t("pkg.lab.unsure") : "");
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm">
      <thead><tr className="text-left text-muted border-b border-line">{(["pkg.lab.test", "pkg.lab.value", "pkg.lab.range", "pkg.lab.flag", "pkg.lab.date"] as const).map((h) => <th key={h} className="px-2 py-1.5">{t(h)}</th>)}<th className="px-2 py-1.5" /></tr></thead>
      <tbody>{labs.map((l, i) => (
        <tr key={l.id ?? i} className="border-b border-line last:border-0" data-testid="lab-row">
          <td className="px-2 py-1.5 font-bold">{labName(l, lang)}</td>
          <td className="px-2 py-1.5" style={isOff(l) ? { color: "var(--strong)", fontWeight: 700 } : undefined}>{labValue(l, t)}</td>
          <td className="px-2 py-1.5">{labRange(l, t)}</td><td className="px-2 py-1.5">{flag(l)}</td>
          <td className="px-2 py-1.5 whitespace-nowrap">{fmtDate(l.date, { day: "numeric", month: "short", year: "numeric" })}, {t("pkg.lab.page", { n: l.page })}</td>
          <td className="px-2 py-1.5 text-xs" style={{ color: "var(--moderate)" }}>{note(l)}</td>
        </tr>))}</tbody></table></div>
  );
}

function Details({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  const terms = new Map<string, { label: string; hpo: string | null; first: string; last: string; count: number; unsure: boolean }>();
  own(pkg).forEach((e) => {
    const k = e.hpo_id ?? e.canonical;
    const x = terms.get(k);
    if (!x) terms.set(k, { label: termLabel(e.hpo_id, e.canonical), hpo: e.hpo_id, first: e.occurred_on, last: e.occurred_on, count: 1, unsure: !!e.needs_review });
    else { x.count++; x.unsure ||= !!e.needs_review; if (e.occurred_on < x.first) x.first = e.occurred_on; if (e.occurred_on > x.last) x.last = e.occurred_on; }
  });
  const family = pkg.entities.filter((e) => e.family_history && !e.negated);
  const past = pastOf(pkg);
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
        {past.length > 0 && (
          <section aria-labelledby="pp" data-testid="pkg-past"><h2 id="pp" className="text-lg mb-1">{t("pkg.past")}</h2>
            <p className="text-sm text-muted mb-2">{t("pkg.pastHint")}</p>
            <ul className="space-y-1 text-sm">{past.map((p, i) => (
              <li key={p.id ?? i}><span className="font-bold">{termLabel(p.hpo_id, p.canonical)}</span>{p.hpo_id && <span className="font-mono text-muted"> {p.hpo_id}</span>}
                {" "}{pastWhen(p.past!, true)} <span className="text-muted">(<span className="clinic-quote">{p.quote}</span>, {t("pkg.pastNoted", { date: fmtDate(p.occurred_on) })})</span></li>
            ))}</ul>
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
