import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Circle, HelpCircle } from "lucide-react";
import { api } from "../api";
import { fmtDate, reorderDelta } from "../lib";
import type { Answer, NextQuestion, Pattern } from "../types";
import { Empty, ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { getLang, termLabel, useT } from "../i18n";

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
              <button key={a} className={a === "yes" ? "btn btn-primary" : "btn"} disabled={state === "saving"} onClick={() => answer(a)}>
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

export default function PatternsPage() {
  const { t, tn, lang } = useT();
  const { data, setData, error, loading, reload } = useAsync(() => api.patterns(lang), [lang]);
  const [moves, setMoves] = useState<Record<string, number>>({});
  const [related, setRelated] = useState<string[]>([]);
  const pats: Pattern[] = data?.patterns ?? [];
  const order = pats.map((p) => p.disease_id).join();
  const ref = useReorderAnimation(order);

  async function afterAnswer(): Promise<boolean> {
    const prev = pats.map((p) => p.disease_id);
    const fresh = await api.patterns(lang);
    const delta = reorderDelta(prev, fresh.patterns.map((p) => p.disease_id));
    setMoves(delta);
    setData(fresh);
    return Object.values(delta).some((d) => d !== 0);
  }

  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.noData")} retry={reload} />;
  return (
    <div className="space-y-5">
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
          <article key={p.disease_id} ref={ref(p.disease_id)} className="card space-y-3" data-testid="pattern-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-2xl">{p.neutral_label || t("patterns.recordedFallback")}</h2>
              <div className="flex flex-wrap items-center gap-2">
                {moves[p.disease_id] < 0 && <span className="chip"><ArrowUp size={14} aria-hidden />{t("patterns.up")}</span>}
                {moves[p.disease_id] > 0 && <span className="chip"><ArrowDown size={14} aria-hidden />{t("patterns.down")}</span>}
                {related.includes(p.disease_id) && <span className="chip">{t("patterns.related")}</span>}
                <SignalPill signal={p.signal} />
              </div>
            </div>
            <section aria-label={t("patterns.recorded")}>
              <h3 className="font-bold text-[15px]">{t("patterns.recorded")}</h3>
              <ul className="mt-1 space-y-1 text-[15px]">
                {p.matched.map((m) => (
                  <li key={m.hpo_id}>{termLabel(m.hpo_id, m.label)}: {m.count} {m.count === 1 ? t("patterns.time") : t("patterns.times")}, {fmtDate(m.first_seen)} {t("patterns.to")} {fmtDate(m.last_seen)}.{" "}
                    {m.entry_ids.slice(0, 4).map((id, i) => <Link key={id} to={`/entry/${id}`} className="underline underline-offset-4 mr-1">{t("patterns.note")} {i + 1}</Link>)}
                  </li>
                ))}
              </ul>
            </section>
            {p.missing.length > 0 && (
              <section aria-label={t("patterns.missing")}>
                <h3 className="font-bold text-[15px]">{t("patterns.missing")}</h3>
                <p className="text-sm text-muted">{t("patterns.missingHint")}</p>
                <ul className="mt-1 text-[15px]">{p.missing.map((t) => <li key={t.hpo_id} className="flex items-center gap-2 py-0.5"><Circle size={14} aria-hidden className="text-muted" />{termLabel(t.hpo_id, t.label)}</li>)}</ul>
              </section>
            )}
            <details className="border-t border-line pt-2">
              <summary className="cursor-pointer min-h-[44px] flex items-center font-bold text-[15px] text-accent">{t("patterns.resembles")}</summary>
              <div className="space-y-1 pb-1">
                <p className="text-sm text-muted">{t("patterns.notDx")}</p>
                <p className="text-lg font-bold">{p.disease_name}</p>
                <p>{p.rationale}</p>
              </div>
            </details>
          </article>
        ))}
      </div>
      {data.confirmed_terms >= 3 && data.patterns.length === 0 && <Empty title={t("patterns.noneTitle")}>{t("patterns.noneText")}</Empty>}
      {data.note && <p className="text-sm text-muted">{data.note}</p>}
    </div>
  );
}
