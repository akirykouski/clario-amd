import { useEffect, useState } from "react";
import { api } from "../api";
import type { Entry, SafetyNotice } from "../types";
import { today } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { EntryCard } from "./EntryCard";
import { SafetyBanner } from "./SafetyBanner";

export default function Today() {
  const { data, setData, error, loading, reload } = useAsync(() => api.entries(), []);
  const [text, setText] = useState("");
  const [date, setDate] = useState(today());
  const [useMood, setUseMood] = useState(false);
  const [mood, setMood] = useState(5);
  const [busy, setBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [safety, setSafety] = useState<SafetyNotice | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true); setSaveErr(null);
    try {
      const r = await api.addEntry({ text: text.trim(), occurred_on: date, mood: useMood ? mood : null });
      setData([r.entry, ...(data ?? [])]);
      setSafety(r.safety);
      setText("");
    } catch (x) { setSaveErr((x as Error).message); }
    finally { setBusy(false); }
  };

  const demo = async () => {
    setDemoBusy(true);
    try { await api.demo(); await reload(); } catch (x) { setSaveErr((x as Error).message); }
    setDemoBusy(false);
  };

  useEffect(() => { document.title = "Today · Clario"; }, []);
  const entries: Entry[] = data ?? [];

  return (
    <div className="space-y-6">
      {safety && <SafetyBanner notice={safety} onDismiss={() => setSafety(null)} />}
      <form onSubmit={save} className="space-y-3">
        <label htmlFor="today" className="block font-display text-3xl">How was today?</label>
        <textarea id="today" className="input min-h-[140px] text-[17px]" value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Write it the way you would tell a friend. Pain, tiredness, what you ate, what helped." />
        <div className="grid grid-cols-2 gap-3 items-end">
          <div>
            <label htmlFor="d" className="label">Date</label>
            <input id="d" type="date" className="input" value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 min-h-[44px] text-[15px]">
            <input type="checkbox" className="w-5 h-5 accent-[var(--accent)]" checked={useMood} onChange={(e) => setUseMood(e.target.checked)} />
            Add a mood score
          </label>
        </div>
        {useMood && (
          <div>
            <label htmlFor="mood" className="label">Mood: {mood} of 10 (0 is low)</label>
            <input id="mood" type="range" min={0} max={10} value={mood} onChange={(e) => setMood(+e.target.value)} className="w-full h-11 accent-[var(--accent)]" />
          </div>
        )}
        {saveErr && <p role="alert" className="text-strong text-sm">{saveErr}</p>}
        <div className="sticky bottom-[72px] md:static py-2 bg-paper/90">
          <button className="btn btn-primary w-full" disabled={busy || !text.trim()}>{busy ? "Saving" : "Save note"}</button>
        </div>
      </form>

      <section aria-label="Recent entries" className="space-y-3">
        <h2 className="text-2xl">Recent notes</h2>
        {loading && <Loading />}
        {error && <ErrorBox error={error} retry={reload} />}
        {!loading && !error && entries.length === 0 && (
          <Empty title="Nothing written yet">
            <p>Your first note can be one line.</p>
            <button className="btn-quiet btn mt-2" onClick={demo} disabled={demoBusy}>{demoBusy ? "Loading" : "Load demo diary (Giulia)"}</button>
          </Empty>
        )}
        {entries.map((e) => <EntryCard key={e.id} initial={e} />)}
      </section>
    </div>
  );
}
