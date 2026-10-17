import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Camera, Circle, ClipboardList, HelpCircle, PenLine, Send } from "lucide-react";
import { api } from "../api";
import { fmtDate, reorderDelta } from "../lib";
import type { Answer, NextQuestion, PatientEvidence, PatientPattern } from "../types";
import { Empty, ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { getLang, useT } from "../i18n";

const reduceMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** FLIP: when the order of ids changes, slide each card from its old position to its new one. */
function useReorderAnimation(order: string) {
  const els = useRef(new Map<string, HTMLElement>());
  const tops = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const next = new Map<string, number>();
    els.current.forEach((el, id) => {
      const top = el.offsetTop;
      next.set(id, top);
      const prev = tops.current.get(id);
      if (prev !== undefined && prev !== top && !reduceMotion() && el.animate) {
        el.animate([{ transform: `translateY(${prev - top}px)` }, { transform: "translateY(0)" }],
          { duration: 520, easing: "cubic-bezier(.2,.7,.2,1)" });
      }
    });
    tops.current = next;
  }, [order]);
  return useCallback((id: string) => (el: HTMLElement | null) => {
    if (el) els.current.set(id, el); else els.current.delete(id);
  }, []);
}

function QuestionCard({ onAnswered, onSplits }: { onAnswered: () => Promise<boolean>; onSplits: (ids: string[]) => void }) {
  const { t, lang } = useT();
  const [q, setQ] = useState<NextQuestion | null>(null);
  const [state, setState] = useState<"loading" | "ask" | "saving" | "done" | "none">("loading");
  const [result, setResult] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setState("loading"); setErr(null);
    api.nextQuestion(getLang()).then((n) => { setQ(n); setState(n ? "ask" : "none"); onAsk(n); })
      .catch((e: Error) => { setErr(e.message); setState("none"); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onAsk = (n: NextQuestion | null) => onSplits(n?.splits ?? []);
  useEffect(() => { load(); }, [load, lang]);

  async function answer(a: Answer) {
    if (!q) return;
    setState("saving"); setErr(null);
    try {
      await api.answerQuestion({ feature_id: q.feature_id, answer: a, question: q.question, lang: getLang() });
      const changed = await onAnswered();
      setResult(a === "unsure" ? t("patterns.unsureSaved") : `${t("patterns.saved")} ${changed ? t("patterns.moved") : t("patterns.same")}`);
      setState("done"); onAsk(null);
    } catch (e) { setErr((e as Error).message); setState("ask"); }
  }

  if (state === "loading") return null;
  if (state === "none" && !err) return null;
  return (
    <section className="card space-y-3 border-accent" aria-labelledby="q-title" data-testid="next-question">
      <h2 id="q-title" className="text-xl flex items-center gap-2"><HelpCircle size={20} aria-hidden className="text-accent" />{t("patterns.qTitle")}</h2>
      {err && <p role="alert" className="text-sm text-strong">{err}</p>}
      {q && (state === "ask" || state === "saving") && (
        <>
          <p className="text-lg" data-testid="question-text">{q.question}</p>
          <p className="text-sm text-muted">{q.why}</p>
          <div className="flex flex-wrap gap-2">
            {(["yes", "no", "unsure"] as Answer[]).map((a) => (
              <button key={a} className="btn" disabled={state === "saving"} onClick={() => answer(a)}>
                {a === "yes" ? t("patterns.yes") : a === "no" ? t("patterns.no") : t("patterns.unsure")}
              </button>
            ))}
          </div>
        </>
      )}
      {state === "done" && (
        <>
          <p role="status">{result}</p>
          <button className="btn" onClick={load}>{t("patterns.another")}</button>
        </>
      )}
    </section>
  );
}

/** The patient's own wording first, the clinical (HPO) name as subtext when it differs. */
function TermName({ label, clinical }: { label: string; clinical?: string | null }) {
  const cap = label.charAt(0).toUpperCase() + label.slice(1);
  return <span>{cap}{clinical && <span className="text-muted text-sm"> ({clinical})</span>}</span>;
}

export default function PatternsPage() {
  const { t, tn, lang } = useT();
  const span = (m: PatientEvidence) => {
    const a = fmtDate(m.first_seen), b = fmtDate(m.last_seen);
    if (m.count === 1) return t("patterns.span.one", { a });
    return m.first_seen === m.last_seen ? t("patterns.span.same", { n: m.count, a }) : t("patterns.span.range", { n: m.count, a, b });
  };
  const { data, setData, error, loading, reload } = useAsync(() => api.patterns(lang), [lang]);
  const [moves, setMoves] = useState<Record<string, number>>({});
  const [related, setRelated] = useState<string[]>([]);
  const pats: PatientPattern[] = data?.patterns ?? [];
  const order = pats.map((p) => p.card_id).join();
  const ref = useReorderAnimation(order);

  async function afterAnswer(): Promise<boolean> {
    const prev = pats.map((p) => `${p.card_id}:${p.signal}`);
    const fresh = await api.patterns(lang);
    const next = fresh.patterns.map((p) => `${p.card_id}:${p.signal}`);
    setMoves(reorderDelta(pats.map((p) => p.card_id), fresh.patterns.map((p) => p.card_id)));
    setData(fresh);
    return prev.join() !== next.join();
  }

  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.noData")} retry={reload} />;
  return (
    <div className="space-y-5" data-tour="patterns">
      <header>
        <h1 className="text-3xl">{t("patterns.title")}</h1>
        <p className="text-muted mt-1">{t("patterns.intro")}</p>
      </header>
      {data.confirmed_terms < 3 && (
        <Empty title={t("patterns.earlyTitle")}>
          {tn("patterns.earlyText", data.confirmed_terms)}
        </Empty>
      )}
      {data.confirmed_terms >= 3 && data.patterns.length > 0 && <QuestionCard onAnswered={afterAnswer} onSplits={setRelated} />}
      <div className="space-y-5">
        {pats.map((p) => (
          <article key={p.card_id} ref={ref(p.card_id)} className="card space-y-3" data-testid="pattern-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-2xl">{p.neutral_label || t("patterns.recordedFallback")}</h2>
              <div className="flex flex-wrap items-center gap-2">
                {moves[p.card_id] < 0 && <span className="chip"><ArrowUp size={14} aria-hidden />{t("patterns.up")}</span>}
                {moves[p.card_id] > 0 && <span className="chip"><ArrowDown size={14} aria-hidden />{t("patterns.down")}</span>}
                {related.includes(p.card_id) && <span className="chip">{t("patterns.related")}</span>}
                <SignalPill signal={p.signal} />
              </div>
            </div>
            <section aria-label={t("patterns.recorded")}>
              <h3 className="font-bold text-[15px]">{t("patterns.recorded")}</h3>
              <ul className="mt-1 space-y-1 text-[15px]">
                {p.matched.map((m) => (
                  <li key={m.hpo_id}><TermName label={m.label} clinical={m.clinical} />: {span(m)}.{" "}
                    {m.entry_ids.slice(0, 4).map((id, i) => <Link key={id} to={`/entry/${id}`} className="underline underline-offset-4 mr-2 whitespace-nowrap">{t("patterns.note")} {i + 1}</Link>)}
                  </li>
                ))}
              </ul>
            </section>
            {p.missing.length > 0 && (
              <section aria-label={t("patterns.missing")}>
                <h3 className="font-bold text-[15px]">{t("patterns.missing")}</h3>
                <p className="text-sm text-muted">{t("patterns.missingHint")}</p>
                <ul className="mt-1 text-[15px]">{p.missing.map((m) => <li key={m.hpo_id} className="flex items-center gap-2 py-0.5"><Circle size={14} aria-hidden className="text-muted" /><TermName label={m.label} clinical={m.clinical} /></li>)}</ul>
              </section>
            )}
            <div className="border-t border-line pt-2 space-y-1">
              <p>{p.rationale}</p>
            </div>
          </article>
        ))}
      </div>
      {data.confirmed_terms >= 3 && data.patterns.length === 0 && <Empty title={t("patterns.noneTitle")}>{t("patterns.noneText")}</Empty>}
      {pats.length > 0 && <PrepCard pats={pats} />}
    </div>
  );
}

/** What the patient can do before the visit: watch for the features not recorded yet, keep photos, write questions, share. */
function PrepCard({ pats }: { pats: PatientPattern[] }) {
  const { t } = useT();
  const watch = [...new Map(pats.flatMap((p) => p.missing).map((m) => [m.hpo_id, m.label])).values()].slice(0, 4);
  return (
    <section className="card space-y-3" aria-labelledby="prep" data-testid="prep-card">
      <h2 id="prep" className="text-xl flex items-center gap-2"><ClipboardList size={20} aria-hidden className="text-accent" />{t("patterns.prepTitle")}</h2>
      <ul className="space-y-2 text-[15px]">
        {watch.length > 0 && <li className="flex gap-2"><Circle size={16} aria-hidden className="text-muted mt-1 shrink-0" />{t("patterns.prepWatch", { list: watch.join(", ") })}</li>}
        <li className="flex gap-2"><Camera size={16} aria-hidden className="text-muted mt-1 shrink-0" />{t("patterns.prepPhoto")}</li>
        <li className="flex gap-2"><PenLine size={16} aria-hidden className="text-muted mt-1 shrink-0" />{t("patterns.prepAsk")}</li>
      </ul>
      <Link to="/share" className="btn btn-primary"><Send size={16} aria-hidden />{t("patterns.prepShare")}</Link>
    </section>
  );
}
