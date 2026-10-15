import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Circle, HelpCircle } from "lucide-react";
import { api } from "../api";
import { fmtDate, reorderDelta } from "../lib";
import type { Answer, NextQuestion, Pattern } from "../types";
import { Empty, ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";

const lang: "en" | "it" = typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("it") ? "it" : "en";
const S = {
  en: {
    title: "Patterns to discuss with your clinician",
    intro: "Not a diagnosis. These are resemblances between what you recorded and published descriptions of conditions. Only terms you confirmed are used.",
    resembles: "Show what this pattern resembles", notDx: "This is not a diagnosis.",
    recorded: "What you recorded", missing: "Not recorded yet", missingHint: "Only add these if they are true for you.",
    time: "time", times: "times", to: "to", note: "note", related: "Related to the question",
    qTitle: "A question that could help your clinician", yes: "Yes", no: "No", unsure: "Not sure",
    saving: "Saving", saved: "Saved as a note in your diary. The list was recalculated.", unsureSaved: "Skipped. This question will not be asked again.",
    moved: "The order of the patterns changed.", same: "The order stayed the same.", another: "Another question",
    up: "Moved up", down: "Moved down", noQ: "No further question to ask for now.",
  },
  it: {
    title: "Schemi da discutere con il medico",
    intro: "Non è una diagnosi. Sono somiglianze tra ciò che hai annotato e le descrizioni pubblicate di alcune condizioni. Si usano solo i termini che hai confermato.",
    resembles: "Mostra a cosa somiglia questo schema", notDx: "Questa non è una diagnosi.",
    recorded: "Cosa hai annotato", missing: "Non ancora annotato", missingHint: "Aggiungili solo se sono veri per te.",
    time: "volta", times: "volte", to: "a", note: "nota", related: "Legato alla domanda",
    qTitle: "Una domanda che potrebbe aiutare il medico", yes: "Sì", no: "No", unsure: "Non so",
    saving: "Salvo", saved: "Salvata come nota nel diario. L'elenco è stato ricalcolato.", unsureSaved: "Saltata. Questa domanda non verrà riproposta.",
    moved: "L'ordine degli schemi è cambiato.", same: "L'ordine degli schemi non è cambiato.", another: "Un'altra domanda",
    up: "Salito", down: "Sceso", noQ: "Per ora non ci sono altre domande.",
  },
}[lang];

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
  const [q, setQ] = useState<NextQuestion | null>(null);
  const [state, setState] = useState<"loading" | "ask" | "saving" | "done" | "none">("loading");
  const [result, setResult] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setState("loading"); setErr(null);
    api.nextQuestion(lang).then((n) => { setQ(n); setState(n ? "ask" : "none"); onAsk(n); })
      .catch((e: Error) => { setErr(e.message); setState("none"); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onAsk = (n: NextQuestion | null) => onSplits(n?.splits ?? []);
  useEffect(() => { load(); }, [load]);

  async function answer(a: Answer) {
    if (!q) return;
    setState("saving"); setErr(null);
    try {
      await api.answerQuestion({ feature_id: q.feature_id, answer: a, question: q.question, lang });
      const changed = await onAnswered();
      setResult(a === "unsure" ? S.unsureSaved : `${S.saved} ${changed ? S.moved : S.same}`);
      setState("done"); onAsk(null);
    } catch (e) { setErr((e as Error).message); setState("ask"); }
  }

  if (state === "loading") return null;
  if (state === "none" && !err) return null;
  return (
    <section className="card space-y-3 border-accent" aria-labelledby="q-title" data-testid="next-question">
      <h2 id="q-title" className="text-xl flex items-center gap-2"><HelpCircle size={20} aria-hidden className="text-accent" />{S.qTitle}</h2>
      {err && <p role="alert" className="text-sm text-strong">{err}</p>}
      {q && (state === "ask" || state === "saving") && (
        <>
          <p className="text-lg" data-testid="question-text">{q.question}</p>
          <p className="text-sm text-muted">{q.why}</p>
          <div className="flex flex-wrap gap-2">
            {(["yes", "no", "unsure"] as Answer[]).map((a) => (
              <button key={a} className={a === "yes" ? "btn btn-primary" : "btn"} disabled={state === "saving"} onClick={() => answer(a)}>
                {a === "yes" ? S.yes : a === "no" ? S.no : S.unsure}
              </button>
            ))}
          </div>
        </>
      )}
      {state === "done" && (
        <>
          <p role="status">{result}</p>
          <button className="btn" onClick={load}>{S.another}</button>
        </>
      )}
    </section>
  );
}

export default function PatternsPage() {
  const { data, setData, error, loading, reload } = useAsync(() => api.patterns(), []);
  const [moves, setMoves] = useState<Record<string, number>>({});
  const [related, setRelated] = useState<string[]>([]);
  const pats: Pattern[] = data?.patterns ?? [];
  const order = pats.map((p) => p.disease_id).join();
  const ref = useReorderAnimation(order);

  async function afterAnswer(): Promise<boolean> {
    const prev = pats.map((p) => p.disease_id);
    const fresh = await api.patterns();
    const delta = reorderDelta(prev, fresh.patterns.map((p) => p.disease_id));
    setMoves(delta);
    setData(fresh);
    return Object.values(delta).some((d) => d !== 0);
  }

  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "No data"} retry={reload} />;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-3xl">{S.title}</h1>
        <p className="text-muted mt-1">{S.intro}</p>
      </header>
      {data.confirmed_terms < 3 && (
        <Empty title="Too early to show patterns">
          You have confirmed {data.confirmed_terms} {data.confirmed_terms === 1 ? "term" : "terms"}. Patterns need at least 3. Review your notes and confirm what is right.
        </Empty>
      )}
      {data.confirmed_terms >= 3 && data.patterns.length > 0 && <QuestionCard onAnswered={afterAnswer} onSplits={setRelated} />}
      <div className="space-y-5">
        {pats.map((p) => (
          <article key={p.disease_id} ref={ref(p.disease_id)} className="card space-y-3" data-testid="pattern-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-2xl">{p.neutral_label || "Recorded features"}</h2>
              <div className="flex flex-wrap items-center gap-2">
                {moves[p.disease_id] < 0 && <span className="chip"><ArrowUp size={14} aria-hidden />{S.up}</span>}
                {moves[p.disease_id] > 0 && <span className="chip"><ArrowDown size={14} aria-hidden />{S.down}</span>}
                {related.includes(p.disease_id) && <span className="chip">{S.related}</span>}
                <SignalPill signal={p.signal} />
              </div>
            </div>
            <section aria-label={S.recorded}>
              <h3 className="font-bold text-[15px]">{S.recorded}</h3>
              <ul className="mt-1 space-y-1 text-[15px]">
                {p.matched.map((m) => (
                  <li key={m.hpo_id}>{m.label}: {m.count} {m.count === 1 ? S.time : S.times}, {fmtDate(m.first_seen)} {S.to} {fmtDate(m.last_seen)}.{" "}
                    {m.entry_ids.slice(0, 4).map((id, i) => <Link key={id} to={`/entry/${id}`} className="underline underline-offset-4 mr-1">{S.note} {i + 1}</Link>)}
                  </li>
                ))}
              </ul>
            </section>
            {p.missing.length > 0 && (
              <section aria-label={S.missing}>
                <h3 className="font-bold text-[15px]">{S.missing}</h3>
                <p className="text-sm text-muted">{S.missingHint}</p>
                <ul className="mt-1 text-[15px]">{p.missing.map((t) => <li key={t.hpo_id} className="flex items-center gap-2 py-0.5"><Circle size={14} aria-hidden className="text-muted" />{t.label}</li>)}</ul>
              </section>
            )}
            <details className="border-t border-line pt-2">
              <summary className="cursor-pointer min-h-[44px] flex items-center font-bold text-[15px] text-accent">{S.resembles}</summary>
              <div className="space-y-1 pb-1">
                <p className="text-sm text-muted">{S.notDx}</p>
                <p className="text-lg font-bold">{p.disease_name}</p>
                <p>{p.rationale}</p>
              </div>
            </details>
          </article>
        ))}
      </div>
      {data.confirmed_terms >= 3 && data.patterns.length === 0 && <Empty title="No patterns to show yet">Keep writing. More confirmed notes make this clearer.</Empty>}
      {data.note && <p className="text-sm text-muted">{data.note}</p>}
    </div>
  );
}
