import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, FileText, PenLine, RotateCcw } from "lucide-react";
import { api } from "../api";
import type { Brief, BriefItem, BriefSection, BriefWarning, SharePackage, Specialty } from "../types";
import { fmtDate, fmtNum } from "../lib";
import { ErrorBox, Spinner } from "../components/ui";
import { tn, useT, type Key } from "../i18n";
import { useRun } from "./useRun";
import { DecisionLine } from "./Metrics";
import { tokenFactoryLabel } from "../components/compute";

const SECTIONS: BriefSection[] = ["summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"];
const sectionTitle = (s: BriefSection) => `brief.section.${s}` as Key;

export type Focus = "general" | Specialty;
export const FOCUSES: Focus[] = ["general", "rheumatology", "nephrology"];
/** The specialty query for the server: it filters and orders what goes into the PDF (#21). */
const specialtyOf = (f: Focus): Specialty | undefined => (f === "general" ? undefined : f);

export function SpecialtySelect({ value, onChange }: { value: Focus; onChange: (f: Focus) => void }) {
  const { t } = useT();
  return (
    <div className="no-print flex items-center gap-2 flex-wrap" data-testid="specialty">
      <label htmlFor="brief-specialty" className="text-sm font-bold text-muted">{t("brief.specialty")}</label>
      <select id="brief-specialty" className="input !w-auto" value={value} onChange={(e) => onChange(e.target.value as Focus)}>
        {FOCUSES.map((f) => <option key={f} value={f}>{t(`brief.specialty.${f}` as Key)}</option>)}
      </select>
    </div>
  );
}

export function countDecisions(items: BriefItem[]) {
  const c = { accepted: 0, edited: 0, rejected: 0 };
  for (const i of items) if (i.origin === "ai" && i.review !== "pending") c[i.review] += 1;
  return c;
}

export function jumpTo(entryId: string) {
  const el = document.getElementById(`entry-${entryId}`);
  const box = el?.closest("details");
  if (box) box.open = true;  // the full notes live in the collapsed details block
  if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.focus({ preventScroll: true }); }
}

const OFFLINE = "offline-fixtures";

/** Persistent run facts for the clinic screen: model, speed, latency and the GPU. Offline fixtures say so and show no speed. */
export function RunChips({ model, backend, tokensPerS, latencyMs }: { model?: string | null; backend?: string | null; tokensPerS?: number; latencyMs?: number }) {
  const { t } = useT();
  const [gpu, setGpu] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { api.gpu().then(setGpu).catch(() => setGpu(null)); }, [tokensPerS, latencyMs]);
  const offline = backend === OFFLINE;
  if (!model && !backend) return null;
  const name = gpu ? String(gpu.gpu_name ?? gpu.name ?? "") : "";
  const util = gpu && typeof gpu.util_pct === "number" ? ` ${Math.round(gpu.util_pct)}%` : "";
  return (
    <div className="no-print flex flex-wrap gap-1.5" data-testid="run-chips">
      <span className="chip text-xs">{offline ? t("brief.chipDemo") : tokenFactoryLabel(backend, model) ?? [backend, model].filter(Boolean).join(" · ")}</span>
      {!offline && tokensPerS ? <span className="chip text-xs">{t("brief.chipRate", { n: fmtNum(tokensPerS, 1) })}</span> : null}
      {!offline && latencyMs ? <span className="chip text-xs">{t("brief.chipLatency", { s: fmtNum(latencyMs / 1000, 1) })}</span> : null}
      {name && <span className="chip text-xs">{t("brief.chipGpu", { name })}{util}</span>}
    </div>
  );
}

const NAME_KEY = "clario.clinicianName";
function savedName(): string {
  try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; }
}
function saveName(n: string) {
  try { localStorage.setItem(NAME_KEY, n); } catch { /* private window: the name is typed again */ }
}

/** Generate brief -> one-page PDF marked "AI draft, not reviewed" -> Edit and sign (plain text, code checks as warnings)
 *  -> signed PDF. The PDF is rendered by the clinic server; the selected specialty filters what goes into it. */
export function BriefPanel({ pkg, brief, setBrief }: { pkg: SharePackage; brief: Brief | null; setBrief: (b: Brief) => void }) {
  const pendingLabs = pkg.labs.filter((l) => l.needs_review && !l.decision).length;
  const { t, lang } = useT();
  const { state, start } = useRun();
  const openedAt = useRef(Date.now()); // the panel mounts when the clinician opens the package
  const [copy, setCopy] = useState<"clinician" | "patient">("clinician");
  const [patientCopy, setPatientCopy] = useState<Brief | null>(null);
  const [focus, setFocus] = useState<Focus>("general");
  const [editing, setEditing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const shown = brief ?? (state.status === "done" ? state.brief ?? null : null);
  useEffect(() => { if (state.status === "done" && state.brief) { setBrief(state.brief); setEditing(false); } }, [state.status, state.brief]); // eslint-disable-line react-hooks/exhaustive-deps
  // the PDF is fetched again whenever the brief changes (a new draft, a lab decision, signing)
  const [rev, setRev] = useState(0);
  useEffect(() => { setRev((r) => r + 1); }, [shown]);

  const signed = !!shown?.finalized;
  useEffect(() => {
    if (!signed || copy !== "patient") return;
    setPatientCopy(null);
    api.brief(pkg.package_id, { audience: "patient", lang }).then(setPatientCopy).catch((x: Error) => setErr(x.message));
  }, [signed, copy, lang, pkg.package_id]);

  const pdfUrl = api.briefPdfUrl(pkg.package_id, { specialty: signed ? undefined : specialtyOf(focus), v: String(rev) });
  const modelLabel = state.backend === OFFLINE ? t("brief.chipDemo") : state.model ?? t("brief.clinicModel");

  return (
    <aside className="lg:sticky lg:top-4 space-y-4" aria-label={t("brief.title")} data-tour="brief">
      <div className="no-print flex items-center justify-between gap-3">
        <h2 className="text-2xl">{t("brief.title")}</h2>
        {!signed && !editing && (
          <button className="btn btn-primary" onClick={() => start(pkg.package_id, lang)} disabled={state.status === "running"}>
            {shown ? t("brief.draftAgain") : t("brief.draft")}
          </button>
        )}
      </div>

      <div aria-live="polite" className="no-print">
        {state.status === "running" && (
          <div className="card space-y-2">
            <Spinner label={state.progress < 0.1 ? t("brief.reading") : t("brief.drafting")} />
            <div className="h-1.5 bg-line rounded"><div className="h-1.5 rounded bg-accent transition-all" style={{ width: `${Math.round(state.progress * 100)}%` }} /></div>
            <p className="text-sm text-muted">{state.backend === OFFLINE ? t("brief.chipDemo") : state.model ?? t("brief.model")}{state.backend !== OFFLINE && state.tokensPerS ? ` · ${t("brief.tokens", { n: fmtNum(state.tokensPerS, 1) })}` : ""}</p>
          </div>
        )}
        {state.status === "error" && <ErrorBox error={state.error ?? t("brief.error")} retry={() => start(pkg.package_id, lang)} />}
        {state.status === "done" && !signed && <p className="text-sm text-muted">{t("brief.draftedBy", { model: modelLabel, rate: state.backend !== OFFLINE && state.tokensPerS ? t("brief.draftedRate", { n: fmtNum(state.tokensPerS, 1) }) : "" })}</p>}
      </div>
      {err && <ErrorBox error={err} />}
      <RunChips model={state.model ?? shown?.model} backend={state.backend ?? shown?.backend}
        tokensPerS={state.tokensPerS ?? shown?.stats?.tokens_per_s} latencyMs={state.latencyMs ?? shown?.stats?.latency_ms} />
      {shown?.pseudonymized && <p className="no-print text-xs text-muted" data-testid="sent-pseudonymised">{t("brief.sentPseudo")}</p>}

      {!shown && state.status === "idle" && <p className="text-muted no-print">{t("brief.none")}</p>}

      {shown && !signed && !editing && (
        <div className="space-y-3" data-testid="brief-draft">
          <SpecialtySelect value={focus} onChange={setFocus} />
          <PdfView url={pdfUrl} badge={t("brief.aiDraftBadge")} />
          <div className="flex gap-2 flex-wrap items-center">
            <button className="btn btn-primary" onClick={() => setEditing(true)}><PenLine size={16} aria-hidden /> {t("brief.editSign")}</button>
            <a className="btn" href={pdfUrl} target="_blank" rel="noreferrer"><ExternalLink size={16} aria-hidden /> {t("brief.openPdf")}</a>
          </div>
        </div>
      )}

      {shown && !signed && editing && (
        <BriefEditor pkg={pkg} focus={focus} pendingLabs={pendingLabs} onCancel={() => setEditing(false)}
          onSigned={(b) => { setBrief(b); setEditing(false); }} openedAt={openedAt.current} />
      )}

      {shown && signed && (
        <>
          <div role="tablist" aria-label={t("brief.title")} className="no-print flex gap-2">
            {(["clinician", "patient"] as const).map((c) => (
              <button key={c} role="tab" aria-selected={copy === c} className="btn flex-1" onClick={() => setCopy(c)}
                style={copy === c ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
                {c === "clinician" ? t("brief.copyClinician") : t("brief.copyPatient")}
              </button>
            ))}
          </div>
          {copy === "patient" ? <PatientCopy pkg={pkg} view={patientCopy} /> : (
            <div className="space-y-3" data-testid="brief-signed">
              <p className="text-sm font-bold" data-testid="signed-by">
                {t("brief.signedBy", { name: shown.signed_by ?? "?", date: fmtDate(shown.finalized_at ?? "", { day: "numeric", month: "short", year: "numeric" }) })}
                {shown.specialty ? ` · ${t(`brief.specialty.${shown.specialty}` as Key)}` : ""}
              </p>
              <PdfView url={pdfUrl} />
              <DecisionLine counts={countDecisions(shown.items)} seconds={shown.review_seconds} />
              <div className="flex gap-2 flex-wrap">
                <a className="btn btn-primary" href={pdfUrl} target="_blank" rel="noreferrer"><FileText size={16} aria-hidden /> {t("brief.openSignedPdf")}</a>
                <a className="btn" href={api.briefMdUrl(pkg.package_id)} target="_blank" rel="noreferrer">{t("brief.openMd")}</a>
              </div>
            </div>
          )}
        </>
      )}
    </aside>
  );
}

function PdfView({ url, badge }: { url: string; badge?: string }) {
  const { t } = useT();
  return (
    <div className="relative">
      {badge && <span className="chip text-xs absolute top-2 left-2 z-10" style={{ borderColor: "var(--moderate)", background: "var(--amber-bg)", color: "var(--ink)" }} data-testid="draft-badge">{badge}</span>}
      <iframe title={t("brief.pdfTitle")} src={url} className="w-full rounded-lg border border-line bg-panel" style={{ height: "min(78vh, 900px)" }} />
    </div>
  );
}

/** Plain text editor for the draft: sections kept as "## Title", one "- line" per item. Code checks (citation check,
 *  hedge validator, diagnostic or dosing words) run on the server as the clinician types and show as warnings; only
 *  lab readings that still need a check block signing. */
function BriefEditor({ pkg, focus, pendingLabs, onCancel, onSigned, openedAt }: {
  pkg: SharePackage; focus: Focus; pendingLabs: number; onCancel: () => void; onSigned: (b: Brief) => void; openedAt: number;
}) {
  const { t } = useT();
  const [text, setText] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<BriefWarning[]>([]);
  const [name, setName] = useState(savedName);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const first = useRef(true);
  const load = () => {
    setErr(null);
    api.briefText(pkg.package_id, specialtyOf(focus))
      .then((r) => { first.current = true; setText(r.text); setWarnings(r.warnings); })
      .catch((x: Error) => setErr(x.message));
  };
  useEffect(load, [pkg.package_id, focus]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (text === null) return;
    if (first.current) { first.current = false; return; }  // the loaded text came with its warnings
    const id = setTimeout(() => {
      api.checkBrief(pkg.package_id, text, specialtyOf(focus)).then((r) => setWarnings(r.warnings)).catch(() => undefined);
    }, 400);
    return () => clearTimeout(id);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  const sign = async () => {
    if (text === null) return;
    setBusy(true); setErr(null);
    try {
      saveName(name.trim());
      onSigned(await api.signBrief(pkg.package_id, { text, clinician: name.trim(), specialty: specialtyOf(focus), seconds: (Date.now() - openedAt) / 1000 }));
    } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };
  if (text === null) return err ? <ErrorBox error={err} retry={load} /> : <Spinner label={t("common.loading")} />;
  const shownWarnings = warnings.filter((w) => w.kind !== "labs_pending");
  return (
    <div className="space-y-3 no-print" data-testid="brief-editor">
      {focus !== "general" && <p className="text-sm text-muted">{t("brief.focusFixed", { sp: t(`brief.specialty.${focus}` as Key) })}</p>}
      <div>
        <label htmlFor="brief-text" className="label">{t("brief.editorLabel")}</label>
        <p className="text-sm text-muted mb-1">{t("brief.editorHint")}</p>
        <textarea id="brief-text" className="input font-mono text-[13px] leading-snug" style={{ minHeight: "min(60vh, 640px)" }}
          value={text} onChange={(e) => setText(e.target.value)} spellCheck />
      </div>
      <section aria-label={t("brief.warnings")} aria-live="polite" data-testid="brief-warnings" className="space-y-1.5">
        {shownWarnings.length === 0
          ? <p className="text-sm text-muted">{t("brief.noWarnings")}</p>
          : shownWarnings.map((w, i) => (
            <div key={i} className="rounded-lg border p-2 text-sm" style={{ borderColor: "var(--moderate)", background: "var(--amber-bg)" }} role="note" data-testid="brief-warning">
              <p className="flex gap-1.5 items-start"><AlertTriangle size={15} className="shrink-0 mt-0.5" aria-hidden /><span>{w.message}</span></p>
              {w.line && <p className="text-muted mt-0.5 truncate" title={w.line}>{w.line}</p>}
            </div>
          ))}
      </section>
      <div>
        <label htmlFor="brief-signer" className="label">{t("brief.signName")}</label>
        <input id="brief-signer" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
      </div>
      {err && <ErrorBox error={err} />}
      <div className="flex gap-2 flex-wrap items-start">
        <div>
          <button className="btn btn-primary" onClick={sign} disabled={busy || !name.trim() || !text.trim() || pendingLabs > 0}>
            <PenLine size={16} aria-hidden /> {t("brief.sign")}
          </button>
          {pendingLabs > 0 && <p className="text-sm text-muted mt-1" aria-live="polite" data-testid="labs-pending">{tn("pkg.labsPending", pendingLabs)}</p>}
        </div>
        <button className="btn" onClick={load} disabled={busy}><RotateCcw size={16} aria-hidden /> {t("brief.reset")}</button>
        <button className="btn" onClick={onCancel} disabled={busy}>{t("common.cancel")}</button>
      </div>
    </div>
  );
}

function PatientCopy({ pkg, view }: { pkg: SharePackage; view: Brief | null }) {
  const { t, lang } = useT();
  if (!view) return <Spinner label={t("common.loading")} />;
  return (
    <div className="space-y-4" data-testid="patient-copy">
      <p className="text-sm text-muted no-print">{t("brief.copyPatientHint")}</p>
      {view.items.length === 0 && <p className="text-muted">{t("brief.copyPatientEmpty")}</p>}
      {SECTIONS.map((s) => {
        const items = view.items.filter((i) => i.section === s);
        if (!items.length) return null;
        return (
          <section key={s} aria-label={t(sectionTitle(s))}>
            <h3 className="text-lg mb-1">{t(sectionTitle(s))}</h3>
            <ul className="space-y-2">{items.map((it) => <li key={it.id} className="card text-[15px]">{it.kind === "patient_note" && <span className="block text-sm font-bold text-muted">{t("brief.patientNoteOwn")}</span>}{it.text}</li>)}</ul>
          </section>
        );
      })}
      <div className="no-print flex gap-3 flex-wrap">
        <a className="btn" href={api.briefMdUrl(pkg.package_id, { audience: "patient", lang })} target="_blank" rel="noreferrer">{t("brief.openPatientMd")}</a>
      </div>
    </div>
  );
}
