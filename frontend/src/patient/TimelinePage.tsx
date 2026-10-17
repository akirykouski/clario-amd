import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { SYSTEM_COLOR } from "../lib";
import { Link } from "react-router-dom";
import { api } from "../api";
import { buildHeat, fmtDate, pastWhen, weeklyMood } from "../lib";
import type { Entity, Entry, PastRef } from "../types";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { HeatStrip, type HeatPick } from "../components/HeatStrip";
import { entityName, entryText, termLabel, useT } from "../i18n";

/** Oldest first: childhood, then dated references, then undated ones (same order as the server's past.sort_key). */
function pastOrder(p: PastRef): string {
  if (p.kind === "childhood") return "0";
  return p.approx_date ? `1${p.approx_date}` : "2";
}

/** The patient's past history ("knee surgery 5 years ago", "da bambina avevo l'asma"): one line per term, kept out of
 *  the heat map because it did not happen in the week of the note. */
export function pastHistory(entries: Entry[]): Entity[] {
  const out = new Map<string, Entity>();
  for (const e of entries) for (const x of e.entities) {
    if (!x.past || x.negated || x.family_history || x.review === "rejected") continue;
    const k = x.hpo_id ?? x.canonical.toLowerCase();
    const had = out.get(k);
    if (!had || pastOrder(x.past) < pastOrder(had.past!)) out.set(k, x);
  }
  return [...out.values()].sort((a, b) => pastOrder(a.past!).localeCompare(pastOrder(b.past!)));
}

export default function TimelinePage() {
  const { t, lang } = useT();
  const { data, error, loading, reload } = useAsync(() => api.timeline(lang), [lang]);
  const [pick, setPick] = useState<HeatPick | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { if (pick) panel.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" }); }, [pick]);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.noData")} retry={reload} />;
  if (data.days.length === 0) return <Empty title={t("timeline.emptyTitle")}>{t("timeline.emptyText")}</Empty>;
  const dates: Record<string, string> = {};
  const byId: Record<string, Entry> = {};
  data.days.forEach((d) => d.entries.forEach((e) => { dates[e.id] = d.date; byId[e.id] = e; }));
  const heat = buildHeat(data.terms, dates, data.systems ?? {});
  const mood = weeklyMood(heat.weeks, Object.values(byId));
  const past = pastHistory(Object.values(byId));
  const picked = pick ? pick.entryIds.map((id) => byId[id]).filter(Boolean) : [];
  return (
    <div className="space-y-6">
      <h1 className="font-display text-[34px] sm:text-[40px] leading-tight font-semibold tracking-[-0.03em]">{t("timeline.title")}</h1>
      <section aria-labelledby="hs" className="glass p-6 sm:p-8" data-tour="timeline-heat">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 mb-5">
          <div>
            <h2 id="hs" className="text-2xl">{t("timeline.byWeek")}</h2>
            {heat.rows.length > 0 && <p className="text-[15px] text-muted mt-1">{t("timeline.pick")}</p>}
          </div>
          {heat.rows.length > 0 && (
            <p aria-hidden className="flex items-center gap-1 text-[13px] text-muted">
              {[30, 52, 76].map((p) => <span key={p} className="w-5 h-5 rounded-[5px]" style={{ background: `color-mix(in srgb, var(--accent) ${p}%, transparent)` }} />)}
              <span className="ml-2 max-w-[340px]">{t("timeline.legend")}</span>
            </p>
          )}
        </div>
        {heat.rows.length === 0 ? <p className="text-muted mt-1">{t("timeline.confirmHint")}</p> : (
          <>
            <HeatStrip heat={heat} mood={mood} selected={pick}
              onPick={(p) => setPick(pick && pick.hpo_id === p.hpo_id && pick.week === p.week ? null : p)} />
          </>
        )}
        <AnimatePresence initial={false}>
        {pick && (
          <motion.div ref={panel} key={`${pick.hpo_id}-${pick.week}`} initial={{ opacity: 0.4, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="mt-6 rounded-[24px] p-5 sm:p-6" style={{ background: "rgba(255,255,255,0.7)", border: "1px solid var(--glass-edge)", boxShadow: "0 1px 0 0 #fff inset, 0 18px 36px -22px rgba(20,50,58,0.45)" }}
            aria-live="polite" data-testid="heat-picked">
            <div className="flex items-start justify-between gap-4">
              <p className="font-semibold text-[17px] flex items-center gap-2">
                <span aria-hidden className="w-3 h-3 rounded-[3px]" style={{ background: SYSTEM_COLOR[(data.systems ?? {})[pick.hpo_id] ?? "other"] ?? SYSTEM_COLOR.other }} />
                {t("timeline.notesFor", { label: pick.label, date: fmtDate(pick.week) })}
              </p>
              <button type="button" className="btn btn-sm !px-0 w-9 shrink-0" onClick={() => setPick(null)} aria-label={t("common.close")} title={t("common.close")}><X size={15} aria-hidden /></button>
            </div>
            <ul className="mt-4 grid gap-3 md:grid-cols-2">
              {picked.map((e, i) => (
                <motion.li key={e.id} initial={{ opacity: 0.4, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05, duration: 0.3, ease: [0.16, 1, 0.3, 1] }}>
                  <Link to={`/entry/${e.id}`} className="block card !p-4 transition-transform hover:-translate-y-0.5">
                    <span className="text-muted text-sm">{fmtDate(e.occurred_on, { weekday: "short", day: "numeric", month: "short" })}</span>
                    <span className="block text-[15px] mt-1 line-clamp-3">{entryText(e.text)}</span>
                  </Link>
                </motion.li>
              ))}
            </ul>
          </motion.div>
        )}
        </AnimatePresence>
      </section>
      {past.length > 0 && (
        <section aria-labelledby="ph" className="card" data-testid="timeline-past">
          <h2 id="ph" className="text-xl">{t("timeline.past")}</h2>
          <p className="text-sm text-muted mb-2">{t("timeline.pastHint")}</p>
          <ul className="space-y-1">{past.map((x) => (
            <li key={x.id} className="text-[15px]">
              <Link to={`/entry/${x.entry_id}`} className="underline underline-offset-4">{entityName(x)}</Link>
              <span className="text-muted"> {pastWhen(x.past!)}</span>
            </li>
          ))}</ul>
        </section>
      )}
      <details className="card">
        <summary className="cursor-pointer min-h-[44px] flex items-center text-xl font-display">{t("timeline.allDays")}</summary>
        <ol className="space-y-3 mt-2">
          {[...data.days].reverse().filter((d) => d.entries.some((e) => e.text.trim())).map((d) => (
            <li key={d.date} className="border-t border-line pt-2">
              <p className="font-bold">{fmtDate(d.date, { weekday: "long", day: "numeric", month: "long" })}</p>
              {d.entries.filter((e) => e.text.trim()).map((e) => <p key={e.id} className="text-[15px] mt-1 line-clamp-2"><Link to={`/entry/${e.id}`} className="underline underline-offset-4">{entryText(e.text)}</Link></p>)}
              <div className="mt-2 flex flex-wrap gap-1.5">{[...new Map(d.terms.map((x) => [x.hpo_id, x])).values()].map((x) => <span key={x.hpo_id} className="chip">{termLabel(x.hpo_id, x.label)}</span>)}</div>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}
