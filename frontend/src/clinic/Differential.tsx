import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, ExternalLink, FlaskConical, HelpCircle, RotateCcw, Sparkles } from "lucide-react";
import { api } from "../api";
import type { Answer, Condition, Differential as Ddx, OrganSystem } from "../types";
import { ErrorBox, SignalPill, Spinner } from "../components/ui";
import { useT, type Key } from "../i18n";

const pct = (f: number | null) => (f === null ? null : `${Math.round(f * 100)}%`);

/** Rank change per condition after an answer: negative = moved up. "new" when it was not in the list before. */
function moves(before: Condition[], after: Condition[]): Record<string, number | "new"> {
  const prev = new Map(before.map((c) => [c.disease_id, c.rank]));
  return Object.fromEntries(after.map((c) => [c.disease_id, prev.has(c.disease_id) ? c.rank - (prev.get(c.disease_id) as number) : "new"]));
}

/** Clinician-only: named conditions with recorded and missing features, and the next question that separates them. */
export function Differential({ pid, version }: { pid: string; version: number }) {
  const { t, lang } = useT();
  const [ddx, setDdx] = useState<Ddx | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [moved, setMoved] = useState<Record<string, number | "new">>({});

  useEffect(() => {
    setErr(null);
    api.ddx(pid, lang).then((d) => { setDdx(d); setMoved({}); }).catch((e: Error) => setErr(e.message));
  }, [pid, lang, version]);

  const answer = async (a: Answer) => {
    if (!ddx?.question) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.ddxAnswer(pid, { feature_id: ddx.question.feature_id, answer: a, lang });
      setMoved(moves(r.before, r.differential.conditions));
      setDdx(r.differential);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const reset = async () => {
    setBusy(true);
    try { setDdx(await api.ddxReset(pid, lang)); setMoved({}); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };

  return (
    <section aria-labelledby="ddx-title" className="card space-y-4" style={{ borderLeft: "5px solid var(--accent)" }} data-testid="ddx" data-tour="ddx">
      <div>
        <h2 id="ddx-title" className="text-2xl flex items-center gap-2"><Sparkles size={22} aria-hidden className="text-accent" />{t("ddx.title")}</h2>
        <p className="text-sm text-muted mt-1">{t("ddx.sub")}</p>
      </div>
      {err && <ErrorBox error={err} />}
      {!ddx && !err && <Spinner label={t("common.loading")} />}
      {ddx && (ddx.systems?.length ?? 0) > 0 && <SystemsRow systems={ddx.systems as OrganSystem[]} />}
      {ddx && ddx.conditions.length === 0 && <p className="text-muted">{ddx.note}</p>}
      {ddx && ddx.conditions.length > 0 && (
        <ol className="space-y-3">
          {ddx.conditions.map((c) => <ConditionCard key={c.disease_id} c={c} move={moved[c.disease_id]} />)}
        </ol>
      )}
      {ddx && ddx.conditions.length > 0 && (
        <div className="rounded-xl border-2 p-4 space-y-3" style={{ borderColor: "var(--accent)", background: "color-mix(in srgb, var(--accent) 6%, transparent)" }}
          aria-live="polite" data-testid="ddx-question">
          <h3 className="text-lg flex items-center gap-2"><HelpCircle size={18} aria-hidden className="text-accent" />{t("ddx.qTitle")}</h3>
          {ddx.question ? (
            <>
              <p className="text-xl font-bold">{ddx.question.question}</p>
              <p className="text-sm text-muted">{t("ddx.qSub")}</p>
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-muted mb-1">{t("ddx.freqTitle")}</p>
                <ul className="text-sm space-y-0.5">
                  {ddx.question.freq_by.map((f) => (
                    <li key={f.name} className="flex justify-between gap-3 max-w-md">
                      <span className="truncate">{f.name}</span>
                      <span className="font-bold tabular-nums">{f.freq === null ? t("ddx.freqUnknown") : f.freq === 0 ? t("ddx.freqNone") : pct(f.freq)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex flex-wrap gap-2">
                {(["yes", "no", "unsure"] as Answer[]).map((a) => (
                  <button key={a} className={a === "yes" ? "btn btn-primary" : "btn"} disabled={busy} onClick={() => answer(a)}>
                    {a === "yes" ? t("ddx.yes") : a === "no" ? t("ddx.no") : t("ddx.unsure")}
                  </button>
                ))}
                {busy && <Spinner />}
              </div>
            </>
          ) : <p className="text-muted">{t("ddx.noQuestion")}</p>}
          {ddx.answers.length > 0 && (
            <div className="border-t border-line pt-2 flex flex-wrap items-center gap-1.5" data-testid="ddx-findings">
              <span className="text-sm font-bold mr-1">{t("ddx.findings")}:</span>
              {ddx.answers.map((a) => (
                <span key={a.feature_id} className="chip text-sm">{a.label}: <b>{a.answer === "yes" ? t("ddx.yes") : a.answer === "no" ? t("ddx.no") : t("ddx.unsure")}</b></span>
              ))}
              <button className="btn-quiet btn px-1 text-sm min-h-[32px]" onClick={reset} disabled={busy}><RotateCcw size={14} aria-hidden />{t("ddx.reset")}</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ConditionCard({ c, move }: { c: Condition; move?: number | "new" }) {
  const { t } = useT();
  const db = c.disease_id.split(":")[0] === "ORPHA" ? "Orphanet" : c.disease_id.split(":")[0];
  return (
    <li className="rounded-xl border border-line p-3" style={c.signal ? undefined : { opacity: 0.85 }} data-testid="ddx-condition">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-lg font-bold leading-snug"><span className="text-muted mr-2 tabular-nums">{c.rank}.</span>{c.name}</p>
          <p className="text-xs text-muted">
            {c.full_name && c.full_name !== c.name && <span>{c.full_name} · </span>}
            {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="underline underline-offset-2 inline-flex items-center gap-0.5">{t("ddx.open", { db })} {c.disease_id}<ExternalLink size={11} aria-hidden /></a> : c.disease_id}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {typeof move === "number" && move < 0 && <span className="chip text-xs" style={{ color: "var(--accent)" }}><ArrowUp size={12} aria-hidden />{t("ddx.up", { n: -move })}</span>}
          {typeof move === "number" && move > 0 && <span className="chip text-xs"><ArrowDown size={12} aria-hidden />{t("ddx.down", { n: move })}</span>}
          {move === "new" && <span className="chip text-xs">{t("ddx.new")}</span>}
          {c.signal ? <SignalPill signal={c.signal} /> : <span className="chip text-xs text-muted">{t("ddx.weaker")}</span>}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-bold uppercase tracking-wide text-muted mr-1">{t("ddx.matched")}</span>
        {c.matched.map((m) => (
          <span key={m.hpo_id} className="chip text-sm" style={{ borderColor: "var(--accent)", background: "color-mix(in srgb, var(--accent) 10%, transparent)" }}>
            {m.label}{m.count > 1 && <span className="text-muted text-xs">×{m.count}</span>}
            {(m.labs ?? 0) > 0 && (
              <span className="text-xs text-muted inline-flex items-center gap-0.5" data-testid="ddx-from-labs" title={t("ddx.fromLabsTitle", { n: m.labs ?? 0 })}>
                <FlaskConical size={11} aria-hidden />{t("ddx.fromLabs")}
              </span>
            )}
          </span>
        ))}
      </div>
      {c.missing.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-bold uppercase tracking-wide text-muted mr-1">{t("ddx.missing")}</span>
          {c.missing.map((m) => (
            <span key={m.hpo_id} className="chip text-sm text-muted" style={{ borderStyle: "dashed" }}>
              {m.label}{m.freq !== null && <span className="text-xs">{pct(m.freq)}</span>}
            </span>
          ))}
        </div>
      )}
    </li>
  );
}

/** Which organ systems the recorded findings span, computed in code (backend `clinic_ddx.organ_systems`). Each chip shows
 * how many findings sit in that system; hover lists them, a tap opens them under the row. */
function SystemsRow({ systems }: { systems: OrganSystem[] }) {
  const { t, tn } = useT();
  const [open, setOpen] = useState<string | null>(null);
  const name = (key: string) => t(`ddx.org.${key}` as Key);
  const shown = systems.find((s) => s.key === open);
  return (
    <div className="space-y-2" data-testid="ddx-systems">
      <p className="text-xs font-bold uppercase tracking-wide text-muted">{tn("ddx.systems", systems.length)}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {systems.map((s, i) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            {i > 0 && <span aria-hidden className="text-muted">·</span>}
            <button type="button" className="chip text-sm font-bold" aria-pressed={open === s.key} data-testid="ddx-system"
              title={s.findings.map((f) => f.label).join(", ")} aria-label={t("ddx.systemFindings", { system: name(s.key), n: s.count })}
              onClick={() => setOpen(open === s.key ? null : s.key)}
              style={open === s.key ? { borderColor: "var(--accent)", background: "color-mix(in srgb, var(--accent) 10%, transparent)" } : undefined}>
              {name(s.key)}<span className="text-muted tabular-nums">{s.count}</span>
            </button>
          </span>
        ))}
      </div>
      {shown && (
        <ul className="flex flex-wrap gap-1.5" data-testid="ddx-system-findings" aria-label={name(shown.key)}>
          {shown.findings.map((f) => (
            <li key={f.hpo_id} className="chip text-sm">
              {f.label}{f.count > 1 && <span className="text-muted text-xs">×{f.count}</span>}
              {f.labs > 0 && (
                <span className="text-xs text-muted inline-flex items-center gap-0.5" title={t("ddx.fromLabsTitle", { n: f.labs })}>
                  <FlaskConical size={11} aria-hidden />{t("ddx.fromLabs")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">{t("ddx.systemsNote")}</p>
    </div>
  );
}
