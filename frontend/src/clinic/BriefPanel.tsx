import { useEffect, useRef, useState } from "react";
import { ExternalLink, FileText, PenLine } from "lucide-react";
import { api } from "../api";
import type { Brief, BriefItem, BriefSection, SharePackage, Specialty } from "../types";
import { fmtDate, fmtNum } from "../lib";
import { ErrorBox, Spinner } from "../components/ui";
import { useT, type Key } from "../i18n";
import { BriefEditor } from "./BriefEditor";
import { useRun } from "./useRun";
import { DecisionLine } from "./Metrics";
import { tokenFactoryLabel } from "../components/compute";

const SECTIONS: BriefSection[] = ["summary", "timeline", "symptoms", "negatives", "findings", "labs", "medications", "patterns", "questions"];
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
export function RunChips({ model, backend, tokensPerS, latencyMs, precomputed }: { model?: string | null; backend?: string | null; tokensPerS?: number; latencyMs?: number; precomputed?: string | null }) {
  const { t } = useT();
  const [gpu, setGpu] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { api.gpu().then(setGpu).catch(() => setGpu(null)); }, [tokensPerS, latencyMs]);
  const offline = backend === OFFLINE;
  if (!model && !backend) return null;
  const name = gpu ? String(gpu.gpu_name ?? gpu.name ?? "") : "";
  const util = gpu && typeof gpu.util_pct === "number" ? ` ${Math.round(gpu.util_pct)}%` : "";
  return (
    <div className="no-print flex flex-wrap gap-1.5" data-testid="run-chips">
      <span className="chip text-xs" data-testid="run-chip-model">
        {offline ? t("brief.chipDemo") : precomputed
          ? t("brief.chipPrecomputed", { model: tokenFactoryLabel(backend, model) ?? [backend, model].filter(Boolean).join(" · "), date: fmtDate(precomputed, { day: "numeric", month: "short", year: "numeric" }) })
          : tokenFactoryLabel(backend, model) ?? [backend, model].filter(Boolean).join(" · ")}
      </span>
      {!offline && tokensPerS ? <span className="chip text-xs">{t("brief.chipRate", { n: fmtNum(tokensPerS, 1) })}</span> : null}
      {!offline && latencyMs ? <span className="chip text-xs">{t("brief.chipLatency", { s: fmtNum(latencyMs / 1000, 1) })}</span> : null}
      {name && !precomputed && <span className="chip text-xs">{t("brief.chipGpu", { name })}{util}</span>}
    </div>
  );
}

/** Generate brief -> one-page PDF marked "AI draft, not reviewed" -> Edit and sign (cards, code checks on their lines)
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
    <aside className={`${editing ? "" : "lg:sticky lg:top-4"} space-y-4`} aria-label={t("brief.title")} data-tour="brief">
      <div className="no-print flex items-center justify-between gap-3">
        <h2 className="text-2xl">{t("brief.title")}</h2>
        {!signed && !editing && (shown?.precomputed
          ? <button className="btn" onClick={() => start(pkg.package_id, lang, true)} disabled={state.status === "running"}>{t("brief.regenerateLive")}</button>
          : <button className="btn btn-primary" onClick={() => start(pkg.package_id, lang)} disabled={state.status === "running"}>
            {shown ? t("brief.draftAgain") : t("brief.draft")}
          </button>)}
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
        {state.status === "done" && !signed && shown?.precomputed && <p className="text-sm text-muted" data-testid="drafted-precomputed">{t("brief.draftedPrecomputed", { model: tokenFactoryLabel(shown.backend, shown.model) ?? shown.model ?? "", date: fmtDate(shown.precomputed, { day: "numeric", month: "short", year: "numeric" }) })}</p>}
        {state.status === "done" && !signed && !shown?.precomputed && <p className="text-sm text-muted">{t("brief.draftedBy", { model: modelLabel, rate: state.backend !== OFFLINE && state.tokensPerS ? t("brief.draftedRate", { n: fmtNum(state.tokensPerS, 1) }) : "" })}</p>}
      </div>
      {err && <ErrorBox error={err} />}
      <RunChips model={state.model ?? shown?.model} backend={state.backend ?? shown?.backend}
        tokensPerS={state.tokensPerS ?? shown?.stats?.tokens_per_s} latencyMs={state.latencyMs ?? shown?.stats?.latency_ms}
        precomputed={shown?.precomputed} />
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
        <BriefEditor pkg={pkg} specialty={specialtyOf(focus)} focusLabel={focus === "general" ? undefined : t(`brief.specialty.${focus}` as Key)} pendingLabs={pendingLabs} onCancel={() => setEditing(false)}
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
        <a className="btn btn-primary" href={api.briefPatientPdfUrl(pkg.package_id, lang)} target="_blank" rel="noreferrer" data-testid="patient-pdf"><FileText size={16} aria-hidden /> {t("brief.openPatientPdf")}</a>
      </div>
    </div>
  );
}
