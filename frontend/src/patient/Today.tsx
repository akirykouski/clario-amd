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

export default function Today() {
  const { t, lang } = useT();
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

  return (
    <div className="space-y-6">
      {safety && <SafetyBanner notice={safety} onDismiss={() => setSafety(null)} />}
      <form onSubmit={save} className="space-y-3">
        <label htmlFor="today" className="block font-display text-3xl">{t("today.question")}</label>
        <div className="space-y-3" data-tour="today-write">
          <textarea id="today" className="input min-h-[140px] text-[17px]" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t("today.placeholder")} />
          <DictationButton onText={addSpoken} />
        </div>
        <div className="grid grid-cols-2 gap-3 items-end">
          <div>
            <label htmlFor="d" className="label">{t("today.date")}</label>
            <input id="d" type="date" className="input" value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 min-h-[44px] text-[15px]">
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
        <div className="sticky bottom-[72px] lg:static py-2 bg-paper/90">
          <button className="btn btn-primary w-full" disabled={busy || !text.trim()}>{busy ? t("today.saving") : t("today.save")}</button>
        </div>
      </form>

      <section aria-label={t("today.recentAria")} className="space-y-3">
        <h2 className="text-2xl">{t("today.recent")}</h2>
        {loading && <Loading />}
        {error && <ErrorBox error={error} retry={reload} />}
        {!loading && !error && entries.length === 0 && (
          <Empty title={t("today.emptyTitle")}>
            <p>{t("today.emptyText")}</p>
          </Empty>
        )}
        {entries.map((e, i) => <EntryCard key={e.id} initial={e} pii={pii[e.id] ?? 0} tour={i === tourIdx} />)}
      </section>
      <DemoMenu onLoaded={reload} open={!loading && entries.length === 0} />
    </div>
  );
}
