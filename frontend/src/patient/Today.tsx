import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Entry, SafetyNotice } from "../types";
import { today } from "../lib";
import { useT } from "../i18n";
import { DemoMenu } from "./DemoMenu";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { EntryCard } from "./EntryCard";
import { SafetyBanner } from "./SafetyBanner";
import { DictationButton } from "./dictation/Dictation";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { ChevronRight, X } from "lucide-react";
import { WeekOrganizer } from "./Week";
import { entityName } from "../i18n";
import { TOUR_DATA_EVENT } from "../components/Tour";

export default function Today() {
  const { t, tn, lang } = useT();
  const { data, setData, error, loading, reload } = useAsync(() => api.entries(), []);
  const [text, setText] = useState("");
  const [date, setDate] = useState(today());
  const [useMood, setUseMood] = useState(false);
  const [mood, setMood] = useState(5);
  const [busy, setBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [safety, setSafety] = useState<SafetyNotice | null>(null);
  const [pii, setPii] = useState<Record<string, number>>({});
  const n = data?.length ?? 0;
  useEffect(() => { api.privacyCounts().then(setPii).catch(() => setPii({})); }, [n]);
  useEffect(() => {
    window.addEventListener(TOUR_DATA_EVENT, reload);
    return () => window.removeEventListener(TOUR_DATA_EVENT, reload);
  }, [reload]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true); setSaveErr(null);
    try {
      const r = await api.addEntry({ text: text.trim(), occurred_on: date, mood: useMood ? mood : null, lang });
      setData([r.entry, ...(data ?? [])]);
      setSafety(r.safety);
      setText("");
    } catch (x) { setSaveErr((x as Error).message); }
    finally { setBusy(false); }
  };

  // Dictated text is appended so a typed start is kept; the user edits it before saving.
  const addSpoken = useCallback((spoken: string) => {
    setText((prev) => (prev.trim() ? `${prev.trimEnd()} ${spoken}` : spoken));
  }, []);

  useEffect(() => { document.title = `${t("today.title")} · ${t("app.tabTitle", { role: t("app.role.patient") })}`; }, [t, lang]);
  const entries: Entry[] = data ?? [];
  // The onboarding tour points at a note with an unsure (dashed) term, else one with terms, else the newest.
  const unsure = entries.findIndex((e) => e.entities?.some((x) => x.review === "needs_review"));
  const withTerms = entries.findIndex((e) => (e.entities?.length ?? 0) > 0);
  const tourIdx = unsure >= 0 ? unsure : Math.max(withTerms, 0);

  const dayIdx = (new Date(`${date}T12:00:00`).getDay() + 6) % 7;
  const counts: Record<string, number> = {};
  for (const e of entries) counts[e.occurred_on] = (counts[e.occurred_on] ?? 0) + 1;
  const dayTerms = entries.filter((e) => e.occurred_on === date).flatMap((e) => (e.entities ?? []).map((x) => ({ ...x, entryId: e.id })));

  return (
    <div className="space-y-8">
      {safety && <SafetyBanner notice={safety} onDismiss={() => setSafety(null)} />}
      <WeekOrganizer selected={date} counts={counts} onSelect={setDate} />
      <div className={`glass tray ${dayIdx === 0 ? "open-first" : dayIdx === 6 ? "open-last" : ""} p-6 sm:p-8 lg:p-10 grid gap-8 lg:gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(240px,300px)]`}>
        <form onSubmit={save} className="space-y-4 min-w-0">
          <label htmlFor="today" className="block font-display text-[34px] sm:text-[44px] leading-[1.06] font-semibold tracking-[-0.035em]">
            {date === today() ? t("today.question") : t("today.questionDay", { day: new Date(`${date}T12:00:00`).toLocaleDateString(lang === "it" ? "it-IT" : "en-GB", { weekday: "long", day: "numeric", month: "long" }) })}
          </label>
          <div className="space-y-3" data-tour="today-write">
            <textarea id="today" className="input min-h-[170px] !text-[19px] !leading-relaxed !px-5 !py-4 !rounded-[22px]" value={text} onChange={(e) => setText(e.target.value)}
              placeholder={t("today.placeholder")} />
            <DictationButton onText={addSpoken} />
          </div>
          <div className="grid sm:grid-cols-2 gap-3 items-end">
            <div>
              <label htmlFor="d" className="label">{t("today.date")}</label>
              <input id="d" type="date" className="input tabular" value={date} max={today()} onChange={(e) => e.target.value && setDate(e.target.value)} />
            </div>
            <label className="flex items-center gap-2.5 min-h-[46px] text-[15px]">
              <input type="checkbox" className="w-5 h-5 accent-[var(--accent)]" checked={useMood} onChange={(e) => setUseMood(e.target.checked)} />
              {t("today.addMood")}
            </label>
          </div>
          {useMood && (
            <div>
              <label htmlFor="mood" className="label">{t("today.mood", { n: mood })}</label>
              <input id="mood" type="range" min={0} max={10} value={mood} onChange={(e) => setMood(+e.target.value)} className="w-full h-11 accent-[var(--accent)]" />
            </div>
          )}
          {saveErr && <p role="alert" className="text-strong text-sm">{saveErr}</p>}
          <div className="sticky bottom-[72px] lg:static pt-1">
            <button className="btn btn-primary w-full sm:w-auto sm:min-w-[220px] min-h-[52px] text-base" disabled={busy || !text.trim()}>{busy ? t("today.saving") : t("today.save")}</button>
          </div>
        </form>
        <aside aria-label={t("today.understood")} data-tour="today-understood" className="lg:border-l lg:pl-10 min-w-0" style={{ borderColor: "var(--glass-rim)" }}>
          <h2 className="text-xl">{t("today.understood")}</h2>
            <motion.div key={date} initial={{ opacity: 0.55, y: 6 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }} className="mt-4">
              {dayTerms.length === 0
                ? <p className="text-muted text-[15px]">{t("today.understoodEmpty")}</p>
                : <ul className="flex flex-wrap gap-2">
                    {dayTerms.map((x) => (
                      <li key={x.id}>
                        <Link to={`/entry/${x.entryId}`} title={t("entry.edit")}
                          className={`group chip !text-[15px] !px-3.5 !py-1.5 cursor-pointer transition-transform hover:-translate-y-0.5 hover:shadow-[0_10px_18px_-12px_rgba(20,50,58,0.6)] ${x.review === "rejected" ? "chip-struck" : x.review === "needs_review" ? "chip-review" : "chip-filled"}`}>
                          {x.negated && <span className="text-muted">{t("term.absentChip")}</span>}{x.family_history && <span className="text-muted">{t("term.relativeChip")}</span>}{entityName(x)}
                          {x.review === "rejected" && <X size={13} aria-hidden className="text-muted" />}
                          {x.review === "needs_review" && <span aria-hidden className="text-xs text-muted">?</span>}
                          <ChevronRight size={14} aria-hidden className="-mr-1 text-muted opacity-40 transition-opacity group-hover:opacity-100" />
                        </Link>
                      </li>
                    ))}
                  </ul>}
              {dayTerms.length > 0 && (
                <p className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-muted">
                  <span className="inline-flex items-center gap-1.5"><span aria-hidden className="w-3.5 h-3.5 rounded-full chip-filled border" />{t("today.legendCounted")}</span>
                  <span className="inline-flex items-center gap-1.5"><span aria-hidden className="w-3.5 h-3.5 rounded-full chip-review" />{t("today.legendUnsure")}</span>
                </p>
              )}
              <p className="mt-6 text-sm text-muted tabular">{tn("today.dayNotes", counts[date] ?? 0)}</p>
            </motion.div>
        </aside>
      </div>

      <section aria-label={t("today.recentAria")} className="space-y-4">
        <h2 className="text-2xl">{t("today.recent")}</h2>
        {loading && <Loading />}
        {error && <ErrorBox error={error} retry={reload} />}
        {!loading && !error && entries.length === 0 && (
          <Empty title={t("today.emptyTitle")}>
            <p>{t("today.emptyText")}</p>
          </Empty>
        )}
        <div className="grid gap-4 lg:grid-cols-2 items-start">
          {entries.map((e, i) => <EntryCard key={e.id} initial={e} pii={pii[e.id] ?? 0} tour={i === tourIdx}
            onChange={(u) => setData((d) => d?.map((x) => (x.id === u.id ? u : x)) ?? d)} />)}
        </div>
      </section>
      <DemoMenu onLoaded={reload} open={!loading && entries.length === 0} />
    </div>
  );
}
