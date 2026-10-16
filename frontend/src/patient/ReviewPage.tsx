import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronDown, Pencil, X } from "lucide-react";
import { api } from "../api";
import type { ReviewItem } from "../types";
import { fmtNumText, notifyReview, splitQuotes } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { entityName, patientTermLine, useT } from "../i18n";
import { isOfflineBackend, useHealth } from "../components/useHealth";
import { labName, qualText, refText } from "./LabsPage";
import { TermFix } from "./EntryPage";

/** Reading quality in words. Percentages stay out of patient screens, and out of the offline demo model entirely. */
export function ConfidenceBar({ value }: { value: number | null }) {
  const { t } = useT();
  const offline = isOfflineBackend(useHealth());
  if (value === null) return <p className="text-sm text-muted">{t("conf.none")}</p>;
  return <p className="text-sm font-bold" style={{ color: "var(--moderate)" }}>{offline ? t("conf.check") : t("conf.sure")}</p>;
}

const GROUP_FROM = 4;  // this many lab items with the same confidence collapse under one line

type Row = { item: ReviewItem } | { group: ReviewItem[]; conf: number };

function rowsOf(items: ReviewItem[]): Row[] {
  const byConf = new Map<number, ReviewItem[]>();
  for (const i of items) if (i.kind === "lab" && i.confidence !== null) byConf.set(i.confidence, [...(byConf.get(i.confidence) ?? []), i]);
  const grouped = new Set<number>([...byConf].filter(([, l]) => l.length >= GROUP_FROM).map(([c]) => c));
  const rows: Row[] = [];
  const seen = new Set<number>();
  for (const i of items) {
    if (i.kind === "lab" && i.confidence !== null && grouped.has(i.confidence)) {
      if (!seen.has(i.confidence)) { seen.add(i.confidence); rows.push({ group: byConf.get(i.confidence)!, conf: i.confidence }); }
    } else rows.push({ item: i });
  }
  return rows;
}

export default function ReviewPage() {
  const { t, tn } = useT();
  const { data, error, loading, reload } = useAsync(() => api.review(), []);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [autoDone, setAutoDone] = useState(false);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("review.loadError")} retry={reload} />;
  const items = data.items.filter((i) => !gone.has(`${i.kind}:${i.id}`));
  const autoLeft = autoDone ? 0 : data.auto ?? 0;

  const act = async (i: ReviewItem, action: "confirm" | "correct" | "reject", value?: string) => {
    setErr(null);
    try {
      await api.reviewAct(i.kind, i.id, action, value);
      setGone((g) => new Set(g).add(`${i.kind}:${i.id}`));
      notifyReview();
    } catch (x) { setErr((x as Error).message); }
  };

  const confirmGroup = async (rows: ReviewItem[]) => {
    for (const i of rows) await act(i, "confirm");
  };

  const confirmAuto = async () => {
    setErr(null);
    try { await api.confirmAuto(); setAutoDone(true); notifyReview(); } catch (x) { setErr((x as Error).message); }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl">{t("review.title")}</h1>
        <p className="text-muted mt-1">{t("review.intro")}</p>
      </div>
      {err && <p role="alert" className="text-strong text-sm">{err}</p>}
      {autoLeft > 0 && (
        <section className="card space-y-2" data-testid="auto-terms">
          <p>{tn("review.auto", autoLeft)}</p>
          <button className="btn" onClick={confirmAuto}><Check size={16} aria-hidden /> {t("review.autoAll", { n: autoLeft })}</button>
        </section>
      )}
      {items.length === 0 && autoLeft === 0 ? (
        <Empty title={t("review.emptyTitle")}>{t("review.emptyText")}<Link className="underline" to="/">{t("review.back")}</Link></Empty>
      ) : (
        <ul className="space-y-3" aria-label={t("review.listAria")}>
          {rowsOf(items).map((r) => "item" in r
            ? <ReviewCard key={`${r.item.kind}:${r.item.id}`} item={r.item} onAct={(a, v) => act(r.item, a, v)} />
            : (
              <li key={`group:${r.conf}`}>
                <details className="card group" style={{ borderColor: "var(--moderate)" }} data-testid="review-group">
                  <summary className="cursor-pointer min-h-[44px] flex items-center justify-between gap-3 font-bold">
                    {t("review.labGroup", { n: r.group.length })}
                    <ChevronDown size={18} aria-hidden className="shrink-0 transition-transform group-open:rotate-180" />
                  </summary>
                  <button className="btn mt-2" data-testid="group-confirm-all" onClick={() => confirmGroup(r.group)}><Check size={16} aria-hidden /> {t("review.autoAll", { n: r.group.length })}</button>
                  <ul className="space-y-3 mt-2">
                    {r.group.map((i) => <ReviewCard key={`${i.kind}:${i.id}`} item={i} grouped onAct={(a, v) => act(i, a, v)} />)}
                  </ul>
                </details>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

function ReviewCard({ item, onAct, grouped = false }: { item: ReviewItem; grouped?: boolean; onAct: (a: "confirm" | "correct" | "reject", v?: string) => void }) {
  const { t, lang } = useT();
  const [fixing, setFixing] = useState(false);
  const [text, setText] = useState("");
  const lab = item.kind === "lab";
  const segs = splitQuotes(item.source_excerpt, item.quote ? [item.quote] : []);
  const name = lab ? labName(item.canonical ?? item.display, lang) : null;
  const termName = lab ? "" : `${item.negated ? t("term.absent") : ""}${entityName({ hpo_id: item.value, canonical: item.canonical ?? item.display, quote: item.quote })}`;
  const qual = lab && qualText(item.value ?? "") !== (item.value ?? "");
  const range = lab ? refText({ ref_low: item.ref_low ?? null, ref_high: item.ref_high ?? null }) : "";
  return (
    <li className={grouped ? "rounded-lg border border-line p-3" : "card"} style={grouped ? undefined : { borderColor: "var(--moderate)" }}>
      <p className="text-sm text-muted">{lab ? t("review.fromReport") : t("review.youWrote")}</p>
      {/* A lab item is already one line (name, value, range): the value is shown once, below. */}
      {!lab && (
        <p className="whitespace-pre-wrap" aria-label={t("review.sourceAria")}>
          {segs.map((s, k) => s.quoted ? <mark key={k} className="quote text-ink">{s.text}</mark> : <span key={k}>{s.text}</span>)}
        </p>
      )}
      <p className={lab ? "font-bold" : "mt-3 font-bold"}>
        {lab && name ? <>{name.main}: {fmtNumText(qualText(item.value ?? ""))}{name.printed && <span className="ml-2 text-sm font-normal text-muted">{name.printed}</span>}</> : termName}
      </p>
      <p className="text-sm text-muted">
        {lab
          ? [range && t("labs.printedRange", { range }), qual ? "" : item.flag === "high" ? t("labs.high") : item.flag === "low" ? t("labs.low") : "", item.page ? t("review.page", { n: item.page }) : ""].filter(Boolean).join(" · ")
          : patientTermLine(item.value, item.hpo_label ?? "", termName) ?? ""}
        {item.family_history && t("review.relative")}
      </p>
      {!grouped && <div className="mt-2"><ConfidenceBar value={item.confidence} /></div>}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <button className="btn !px-2 whitespace-nowrap" onClick={() => onAct("confirm")}><Check size={16} aria-hidden /> {t("common.confirm")}</button>
        <button className="btn !px-2 whitespace-nowrap" onClick={() => setFixing(!fixing)} aria-expanded={fixing}><Pencil size={16} aria-hidden /> {t("common.correct")}</button>
        <button className="btn !px-2 whitespace-nowrap" onClick={() => onAct("reject")}><X size={16} aria-hidden /> {t("common.reject")}</button>
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
