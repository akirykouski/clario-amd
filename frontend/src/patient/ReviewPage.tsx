import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Pencil, X } from "lucide-react";
import { api } from "../api";
import type { ReviewItem } from "../types";
import { confidencePct, splitQuotes } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { entityName, termLabel, useT } from "../i18n";
import { refText } from "./LabsPage";
import { TermFix } from "./EntryPage";

export const REVIEW_EVENT = "clario-review-changed";

export function ConfidenceBar({ value }: { value: number | null }) {
  const { t } = useT();
  const pct = confidencePct(value);
  if (pct === null) return <p className="text-sm text-muted">{t("conf.none")}</p>;
  return (
    <div>
      <p className="text-sm text-muted">{t("conf.sure", { pct })}</p>
      <div role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={t("conf.aria", { pct })}
        className="mt-1 h-2 w-full max-w-xs rounded-full bg-line overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--moderate)" }} />
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const { t } = useT();
  const { data, error, loading, reload } = useAsync(() => api.review(), []);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("review.loadError")} retry={reload} />;
  const items = data.items.filter((i) => !gone.has(`${i.kind}:${i.id}`));

  const act = async (i: ReviewItem, action: "confirm" | "correct" | "reject", value?: string) => {
    setErr(null);
    try {
      await api.reviewAct(i.kind, i.id, action, value);
      setGone((g) => new Set(g).add(`${i.kind}:${i.id}`));
      window.dispatchEvent(new Event(REVIEW_EVENT));
    } catch (x) { setErr((x as Error).message); }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl">{t("review.title")}</h1>
        <p className="text-muted mt-1">{t("review.intro")}</p>
      </div>
      {err && <p role="alert" className="text-strong text-sm">{err}</p>}
      {items.length === 0 ? (
        <Empty title={t("review.emptyTitle")}>{t("review.emptyText")}<Link className="underline" to="/">{t("review.back")}</Link></Empty>
      ) : (
        <ul className="space-y-3" aria-label={t("review.listAria")}>
          {items.map((i) => <ReviewCard key={`${i.kind}:${i.id}`} item={i} onAct={(a, v) => act(i, a, v)} />)}
        </ul>
      )}
    </div>
  );
}

function ReviewCard({ item, onAct }: { item: ReviewItem; onAct: (a: "confirm" | "correct" | "reject", v?: string) => void }) {
  const { t } = useT();
  const [fixing, setFixing] = useState(false);
  const [text, setText] = useState("");
  const lab = item.kind === "lab";
  const segs = splitQuotes(item.source_excerpt, item.quote ? [item.quote] : []);
  const name = lab ? (item.canonical ?? item.display) : `${item.negated ? t("term.absent") : ""}${entityName({ hpo_id: item.value, canonical: item.canonical ?? item.display, quote: item.quote })}`;
  const range = lab ? refText({ ref_low: item.ref_low ?? null, ref_high: item.ref_high ?? null }) : "";
  return (
    <li className="card" style={{ borderColor: "var(--moderate)" }}>
      <p className="text-sm text-muted">{lab ? t("review.fromReport") : t("review.youWrote")}</p>
      <p className="whitespace-pre-wrap" aria-label={t("review.sourceAria")}>
        {segs.map((s, k) => s.quoted ? <mark key={k} className="quote text-ink">{s.text}</mark> : <span key={k}>{s.text}</span>)}
      </p>
      <p className="mt-3 font-bold">{lab ? `${name}: ${item.value}` : name}</p>
      <p className="text-sm text-muted">
        {lab
          ? [range && t("labs.printedRange", { range }), item.flag === "high" ? t("labs.high") : item.flag === "low" ? t("labs.low") : "", item.page ? t("review.page", { n: item.page }) : ""].filter(Boolean).join(" · ")
          : item.value ? `${termLabel(item.value, item.hpo_label ?? "")} (${item.value})` : t("entryPage.noCode")}
        {item.family_history && t("review.relative")}
      </p>
      <div className="mt-2"><ConfidenceBar value={item.confidence} /></div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn" onClick={() => onAct("confirm")}><Check size={16} aria-hidden /> {t("common.confirm")}</button>
        <button className="btn" onClick={() => setFixing(!fixing)} aria-expanded={fixing}><Pencil size={16} aria-hidden /> {t("common.correct")}</button>
        <button className="btn" onClick={() => onAct("reject")}><X size={16} aria-hidden /> {t("common.reject")}</button>
      </div>
      {fixing && (item.kind === "entity" ? (
        <TermFix onPick={(term) => { onAct("correct", term.hpo_id); setFixing(false); }} />
      ) : (
        <div className="mt-3 flex gap-2">
          <label className="sr-only" htmlFor={`v-${item.id}`}>{t("review.correctedValue")}</label>
          <input id={`v-${item.id}`} className="input" value={text} onChange={(e) => setText(e.target.value)} inputMode="decimal" />
          <button className="btn btn-primary" disabled={!text.trim()} onClick={() => onAct("correct", text.trim())}>{t("common.save")}</button>
        </div>
      ))}
    </li>
  );
}
