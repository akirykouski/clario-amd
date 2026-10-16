import { useEffect, useRef, useState } from "react";
import { Check, Pencil, Printer, X } from "lucide-react";
import { api } from "../api";
import type { Brief, BriefItem, BriefSection, SharePackage } from "../types";
import { canFinalize, fmtDate, fmtNum } from "../lib";
import { ErrorBox, Spinner } from "../components/ui";
import { tn, useT, type Key } from "../i18n";
import { useRun } from "./useRun";
import { DecisionLine } from "./Metrics";

const SECTIONS: BriefSection[] = ["summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"];
const sectionTitle = (s: BriefSection) => `brief.section.${s}` as Key;

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
      <span className="chip text-xs">{offline ? t("brief.chipDemo") : [backend, model].filter(Boolean).join(" · ")}</span>
      {!offline && tokensPerS ? <span className="chip text-xs">{t("brief.chipRate", { n: fmtNum(tokensPerS, 1) })}</span> : null}
      {!offline && latencyMs ? <span className="chip text-xs">{t("brief.chipLatency", { s: fmtNum(latencyMs / 1000, 1) })}</span> : null}
      {name && <span className="chip text-xs">{t("brief.chipGpu", { name })}{util}</span>}
    </div>
  );
}

export function FinalizeButton({ items, onClick, busy, pendingLabs = 0 }: { items: BriefItem[]; onClick: () => void; busy?: boolean; pendingLabs?: number }) {
  const { t } = useT();
  const pending = items.filter((i) => i.review === "pending" && i.origin === "ai").length;
  return (
    <div>
      <button className="btn btn-primary" onClick={onClick} disabled={!canFinalize(items) || pendingLabs > 0 || busy}>{t("brief.finalize")}</button>
      {pending > 0 && <p className="text-sm text-muted mt-1" aria-live="polite">{tn("brief.pending", pending)}</p>}
      {pendingLabs > 0 && <p className="text-sm text-muted mt-1" aria-live="polite" data-testid="labs-pending">{tn("pkg.labsPending", pendingLabs)}</p>}
    </div>
  );
}

export function BriefPanel({ pkg, brief, setBrief }: { pkg: SharePackage; brief: Brief | null; setBrief: (b: Brief) => void }) {
  const pendingLabs = pkg.labs.filter((l) => l.needs_review && !l.decision).length;
  const { t, lang } = useT();
  const { state, start } = useRun();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const openedAt = useRef(Date.now()); // the panel mounts when the clinician opens the package
  const [copy, setCopy] = useState<"clinician" | "patient">("clinician");
  const [patientCopy, setPatientCopy] = useState<Brief | null>(null);
  const shown = brief ?? (state.status === "done" ? state.brief ?? null : null);
  useEffect(() => { if (state.status === "done" && state.brief) setBrief(state.brief); }, [state.status, state.brief]); // eslint-disable-line react-hooks/exhaustive-deps

  const finalized = !!shown?.finalized;
  useEffect(() => {
    if (!finalized || copy !== "patient") return;
    setPatientCopy(null);
    api.brief(pkg.package_id, { audience: "patient", lang }).then(setPatientCopy).catch((x: Error) => setErr(x.message));
  }, [finalized, copy, lang, pkg.package_id]);

  const update = (it: BriefItem) => shown && setBrief({ ...shown, items: shown.items.map((x) => (x.id === it.id ? it : x)) });
  const review = async (it: BriefItem, r: BriefItem["review"], text?: string) => {
    setErr(null);
    try { update(await api.reviewItem(pkg.package_id, it.id, text !== undefined ? { review: r, text } : { review: r })); }
    catch (x) { setErr((x as Error).message); }
  };
  const finalize = async () => {
    setBusy(true); setErr(null);
    try { setBrief(await api.finalize(pkg.package_id, (Date.now() - openedAt.current) / 1000)); } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };

  return (
    <aside className="lg:sticky lg:top-4 space-y-4" aria-label={t("brief.title")}>
      <div className="no-print flex items-center justify-between gap-3">
        <h2 className="text-2xl">{t("brief.title")}</h2>
        <button className="btn btn-primary" onClick={() => start(pkg.package_id, lang)} disabled={state.status === "running" || finalized}>
          {shown ? t("brief.draftAgain") : t("brief.draft")}
        </button>
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
        {state.status === "done" && <p className="text-sm text-muted">{t("brief.draftedBy", { model: state.backend === OFFLINE ? t("brief.chipDemo") : state.model ?? t("brief.clinicModel"), rate: state.backend !== OFFLINE && state.tokensPerS ? t("brief.draftedRate", { n: fmtNum(state.tokensPerS, 1) }) : "" })}</p>}
      </div>
      {err && <ErrorBox error={err} />}
      <RunChips model={state.model ?? shown?.model} backend={state.backend ?? shown?.backend}
        tokensPerS={state.tokensPerS ?? shown?.stats?.tokens_per_s} latencyMs={state.latencyMs ?? shown?.stats?.latency_ms} />

      {!shown && state.status === "idle" && <p className="text-muted no-print">{t("brief.none")}</p>}

      {shown && (
        <>
          {finalized && (
            <div role="tablist" aria-label={t("brief.title")} className="no-print flex gap-2">
              {(["clinician", "patient"] as const).map((c) => (
                <button key={c} role="tab" aria-selected={copy === c} className="btn flex-1" onClick={() => setCopy(c)}
                  style={copy === c ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
                  {c === "clinician" ? t("brief.copyClinician") : t("brief.copyPatient")}
                </button>
              ))}
            </div>
          )}
          {copy === "patient" && finalized ? (
            <PatientCopy pkg={pkg} view={patientCopy} />
          ) : (
            <>
              <div className="no-print space-y-4">
                {SECTIONS.map((s) => {
                  const items = shown.items.filter((i) => i.section === s);
                  if (!items.length) return null;
                  return (
                    <section key={s} aria-label={t(sectionTitle(s))}>
                      <h3 className="text-lg mb-1">{t(sectionTitle(s))}</h3>
                      <ul className="space-y-2">{items.map((it) => <ItemRow key={it.id} it={it} pkg={pkg} locked={shown.finalized} onReview={review} />)}</ul>
                    </section>
                  );
                })}
                {shown.items.some((i) => i.origin === "ai" && i.review !== "pending") && (
                  <DecisionLine counts={countDecisions(shown.items)} seconds={shown.finalized ? shown.review_seconds : null} />
                )}
                <div className="flex items-start gap-3 flex-wrap">
                  {!shown.finalized && <FinalizeButton items={shown.items} onClick={finalize} busy={busy} pendingLabs={pendingLabs} />}
                  {shown.finalized && (
                    <>
                      <a className="btn" href={api.briefMdUrl(pkg.package_id)} target="_blank" rel="noreferrer">{t("brief.openMd")}</a>
                      <button className="btn" onClick={() => window.print()}><Printer size={16} aria-hidden /> {t("brief.print")}</button>
                    </>
                  )}
                </div>
              </div>
              <PrintBrief pkg={pkg} brief={shown} />
            </>
          )}
        </>
      )}
    </aside>
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
            <ul className="space-y-2">{items.map((it) => <li key={it.id} className="card text-[15px]">{noteLabel(it, true) && <span className="block text-sm font-bold text-muted">{t(noteLabel(it, true) as Key)}</span>}{it.text}</li>)}</ul>
          </section>
        );
      })}
      <div className="no-print flex gap-3 flex-wrap">
        <a className="btn" href={api.briefMdUrl(pkg.package_id, { audience: "patient", lang })} target="_blank" rel="noreferrer">{t("brief.openPatientMd")}</a>
      </div>
    </div>
  );
}

/** The patient's own question has no label in its text: the UI says whose words these are. */
const noteLabel = (it: BriefItem, own = false): Key | null => (it.kind === "patient_note" ? (own ? "brief.patientNoteOwn" : "brief.patientNote") : null);

function FlagReason({ it, pkg }: { it: BriefItem; pkg: SharePackage }) {
  const { t } = useT();
  const date = (id: string) => pkg.entries.find((e) => e.id === id)?.occurred_on;
  const cited = it.cites.map((c, i) => { const d = date(c); return d ? `${t("brief.entryN", { n: i + 1 })}, ${fmtDate(d)}` : t("brief.entryN", { n: i + 1 }); }).join("; ");
  const term = `"${it.flag_term ?? ""}"`;
  const dates = [...new Set((it.flag_entries ?? []).map(date).filter((d): d is string => !!d))].sort().slice(0, 3).map((d) => fmtDate(d)).join(", ");
  return (
    <p className="mt-2 text-sm" role="note" data-testid="flag-reason">
      {t("brief.flagWhy", { term, cited })} {dates ? t("brief.flagWhere", { term, dates }) : t("brief.flagNowhere")}
    </p>
  );
}

function ItemRow({ it, pkg, locked, onReview }: { it: BriefItem; pkg: SharePackage; locked: boolean; onReview: (it: BriefItem, r: BriefItem["review"], text?: string) => void }) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [text, setText] = useState(it.text);
  const ai = it.origin === "ai";
  const flagged = it.flag === "citation_mismatch";
  const tone = it.review === "accepted" || it.review === "edited" ? "var(--accent)" : it.review === "rejected" ? "var(--line)" : "var(--moderate)";
  const origin = ai ? t("brief.aiDraft") : it.origin === "document" ? t("brief.fromDocuments") : it.from_question ? t("brief.askedByApp") : t("brief.fromPatient");
  const lead = noteLabel(it);
  if (ai && !locked && it.review !== "pending" && !editing) {  // decided: one line and an Undo
    return (
      <li className="card text-[15px] py-2 flex items-center gap-2" style={{ borderLeft: `4px solid ${tone}` }} data-testid="item-decided">
        <span className="chip text-xs shrink-0">{t(`brief.review.${it.review}`)}</span>
        <span className={`truncate min-w-0 flex-1 ${it.review === "rejected" ? "line-through text-muted" : ""}`} title={it.text}>{it.text}</span>
        <button className="btn shrink-0" onClick={() => onReview(it, "pending")}>{t("brief.undo")}</button>
      </li>
    );
  }
  return (
    <li className="card !py-3 text-[15px]" style={{ borderLeft: `4px solid ${tone}`, opacity: it.review === "rejected" ? 0.6 : 1, background: flagged && it.review === "pending" ? "var(--amber-bg)" : undefined }}>
      {editing ? (
        <div>
          <label htmlFor={`t-${it.id}`} className="label">{t("brief.editItem")}</label>
          <textarea id={`t-${it.id}`} className="input min-h-[90px]" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex gap-2 mt-2">
            <button className="btn btn-primary" onClick={() => { onReview(it, "edited", text); setEditing(false); setConfirming(false); }} disabled={!text.trim()}>{t("brief.saveEdit")}</button>
            <button className="btn" onClick={() => { setText(it.text); setEditing(false); }}>{t("common.cancel")}</button>
          </div>
        </div>
      ) : (
        <>
          {lead && <p className="text-sm font-bold text-muted">{t(lead)}</p>}
          <p className={it.review === "rejected" ? "line-through" : ""}>{it.text}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="chip text-xs">{origin}</span>
            <span className="chip text-xs">{t(`brief.review.${it.review}`)}</span>
            {flagged && <span className="chip text-xs" style={{ borderColor: "var(--moderate)", color: "var(--ink)", background: "var(--amber-bg)" }} role="note">{t("brief.flagged")}</span>}
            {it.cites.map((c, i) => <button key={c} className="chip hover:border-accent" onClick={() => jumpTo(c)} aria-label={t("brief.goTo", { n: i + 1 })}>{t("brief.entryN", { n: i + 1 })}</button>)}
            {(it.pages ?? []).map((p) => <span key={`p${p}`} className="chip text-xs">{t("brief.reportPage", { n: p })}</span>)}
          </div>
          {flagged && it.review === "pending" && <FlagReason it={it} pkg={pkg} />}
          {ai && !locked && confirming && (
            <div className="mt-2 space-y-2" data-testid="flag-confirm">
              <p className="text-sm font-bold">{t("brief.flagConfirm")}</p>
              <div className="flex gap-1.5 flex-wrap">
                <button className="btn btn-sm" onClick={() => setEditing(true)}><Pencil size={14} aria-hidden /> {t("brief.edit")}</button>
                <button className="btn btn-sm" onClick={() => { setConfirming(false); onReview(it, "accepted"); }}><Check size={14} aria-hidden /> {t("brief.acceptAnyway")}</button>
                <button className="btn btn-sm" onClick={() => setConfirming(false)}>{t("common.cancel")}</button>
              </div>
            </div>
          )}
          {ai && !locked && !confirming && (
            <div className="mt-2 flex gap-1.5 flex-wrap">
              <button className="btn btn-sm" onClick={() => (flagged ? setConfirming(true) : onReview(it, "accepted"))} aria-pressed={it.review === "accepted"}
                style={it.review === "accepted" ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}><Check size={14} aria-hidden /> {t("brief.accept")}</button>
              <button className="btn btn-sm" onClick={() => setEditing(true)}><Pencil size={14} aria-hidden /> {t("brief.edit")}</button>
              <button className="btn btn-sm" onClick={() => onReview(it, "rejected")} aria-pressed={it.review === "rejected"}><X size={14} aria-hidden /> {t("brief.reject")}</button>
            </div>
          )}
        </>
      )}
    </li>
  );
}

function PrintBrief({ pkg, brief }: { pkg: SharePackage; brief: Brief }) {
  const { t } = useT();
  const kept = brief.items.filter((i) => i.review === "accepted" || i.review === "edited" || i.origin === "patient");
  const label = (id: string) => { const e = pkg.entries.find((x) => x.id === id); return e ? fmtDate(e.occurred_on) : id; };
  return (
    <div className="print-only">
      <h1 style={{ fontSize: "20pt" }}>{t("brief.printTitle", { alias: pkg.patient_alias })}</h1>
      <p>{t("brief.printTo", { a: fmtDate(pkg.period[0], { day: "numeric", month: "long", year: "numeric" }), b: fmtDate(pkg.period[1], { day: "numeric", month: "long", year: "numeric" }) })}</p>
      {SECTIONS.map((s) => {
        const items = kept.filter((i) => i.section === s);
        if (!items.length) return null;
        return (
          <section key={s} style={{ marginTop: "10pt" }}>
            <h2 style={{ fontSize: "14pt" }}>{t(sectionTitle(s))}</h2>
            <ul>{items.map((i) => <li key={i.id}>{noteLabel(i) ? `${t(noteLabel(i) as Key)}: ` : ""}{i.text}{i.cites.length > 0 && <em> ({i.cites.map(label).join(", ")})</em>}</li>)}</ul>
          </section>
        );
      })}
      <p style={{ marginTop: "16pt", fontSize: "9pt" }}>{t("brief.printFooter")}</p>
    </div>
  );
}
