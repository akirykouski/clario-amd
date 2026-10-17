import { useState } from "react";
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
      <h1 className="text-3xl">{t("timeline.title")}</h1>
      <section aria-labelledby="hs" className="card" data-tour="timeline-heat">
        <h2 id="hs" className="text-xl">{t("timeline.byWeek")}</h2>
        {heat.rows.length === 0 ? <p className="text-muted mt-1">{t("timeline.confirmHint")}</p> : (
          <>
            <p className="text-sm text-muted mb-2">{t("timeline.pick")}</p>
            <HeatStrip heat={heat} mood={mood} onPick={(p) => setPick(pick && pick.hpo_id === p.hpo_id && pick.week === p.week ? null : p)}
              selected={pick} />
          </>
        )}
        {pick && (
          <div className="mt-3 border-t border-line pt-3" aria-live="polite" data-testid="heat-picked">
            <p className="font-bold">{t("timeline.notesFor", { label: pick.label, date: fmtDate(pick.week) })}</p>
            <ul className="mt-1 space-y-1">
              {picked.map((e) => (
                <li key={e.id} className="text-[15px]">
                  <span className="text-muted text-sm mr-2">{fmtDate(e.occurred_on, { weekday: "short", day: "numeric", month: "short" })}</span>
                  <Link to={`/entry/${e.id}`} className="underline underline-offset-4">{entryText(e.text)}</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
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
