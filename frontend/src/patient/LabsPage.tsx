import { useState } from "react";
import { Link } from "react-router-dom";
import { FileUp } from "lucide-react";
import { api } from "../api";
import { fmtDate } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import type { LabPatch, LabTest, LabValue } from "../types";

const num = (n: number) => String(Math.round(n * 1000) / 1000);
export const valueText = (v: LabValue) => (v.value_numeric !== null ? num(v.value_numeric) : v.value_text ?? "");
export function refText(t: Pick<LabTest, "ref_low" | "ref_high">): string {
  if (t.ref_low !== null && t.ref_high !== null) return `${num(t.ref_low)} to ${num(t.ref_high)}`;
  if (t.ref_high !== null) return `up to ${num(t.ref_high)}`;
  if (t.ref_low !== null) return `from ${num(t.ref_low)}`;
  return "";
}

function FlagPill({ flag }: { flag: LabValue["flag"] }) {
  if (flag !== "low" && flag !== "high") return null;
  return (
    <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-bold"
      style={{ color: "var(--strong)", borderColor: "var(--strong)" }}>{flag === "high" ? "High" : "Low"}</span>
  );
}

function Spark({ values }: { values: LabValue[] }) {
  const pts = values.filter((v) => v.value_numeric !== null).map((v) => v.value_numeric as number);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1;
  const xy = pts.map((p, i) => `${(i / (pts.length - 1)) * 96 + 2},${26 - ((p - lo) / span) * 22}`);
  const last = xy[xy.length - 1].split(",");
  return (
    <svg width="100" height="30" viewBox="0 0 100 30" role="img" aria-label={`Trend over ${pts.length} results`} className="shrink-0">
      <polyline points={xy.join(" ")} fill="none" stroke="var(--muted)" strokeWidth="1.5" />
      <circle cx={last[0]} cy={last[1]} r="3" fill="var(--accent)" />
    </svg>
  );
}

export function LabRow({ v, unit, onAct }: { v: LabValue; unit: string; onAct: (id: string, b: LabPatch) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(valueText(v));
  const [u, setU] = useState(unit);
  const [busy, setBusy] = useState(false);
  const review = v.review === "needs_review";
  const act = async (b: LabPatch) => { setBusy(true); try { await onAct(v.id, b); setEditing(false); } finally { setBusy(false); } };
  const save = () => {
    const n = Number(val.replace(",", "."));
    const isNum = val.trim() !== "" && Number.isFinite(n);
    return act({ action: "correct", unit: u, ...(isNum ? { value_numeric: n } : { value_text: val.trim() }) });
  };
  return (
    <li data-testid="lab-row" data-review={v.review} className="py-2 px-2 -mx-2 rounded-lg"
      style={review ? { background: "color-mix(in srgb, var(--moderate) 14%, transparent)" } : undefined}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm text-muted w-16">{fmtDate(v.date, { day: "numeric", month: "short", year: "2-digit" })}</span>
        <span className="font-bold tabular-nums">{valueText(v)} <span className="font-normal text-muted text-sm">{unit}</span></span>
        <FlagPill flag={v.flag} />
        {review && <span className="text-sm font-bold" style={{ color: "var(--moderate)" }}>Needs a look{v.confidence !== null ? `, ${Math.round(v.confidence * 100)}% sure` : ""}</span>}
        {v.review === "confirmed" && <span className="text-sm text-muted">Confirmed</span>}
        {v.review === "corrected" && <span className="text-sm text-muted">Corrected by you</span>}
      </div>
      {review && !editing && (
        <div className="flex flex-wrap gap-2 mt-2">
          <button className="btn" disabled={busy} onClick={() => act({ action: "confirm" })}>Confirm</button>
          <button className="btn" disabled={busy} onClick={() => setEditing(true)}>Correct</button>
          <button className="btn" disabled={busy} onClick={() => act({ action: "reject" })}>Reject</button>
        </div>
      )}
      {review && editing && (
        <form className="flex flex-wrap items-end gap-2 mt-2" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <label className="flex-1 min-w-[7rem]"><span className="label">Value</span><input className="input" value={val} onChange={(e) => setVal(e.target.value)} inputMode="decimal" /></label>
          <label className="w-28"><span className="label">Unit</span><input className="input" value={u} onChange={(e) => setU(e.target.value)} /></label>
          <button className="btn btn-primary" type="submit" disabled={busy || !val.trim()}>Save</button>
          <button className="btn" type="button" onClick={() => setEditing(false)}>Cancel</button>
        </form>
      )}
    </li>
  );
}

export default function LabsPage() {
  const { data, error, loading, reload, setData } = useAsync(() => api.labs(), []);
  const [err, setErr] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "No data"} retry={reload} />;

  const act = async (id: string, b: LabPatch) => {
    setErr(null);
    try { await api.patchLab(id, b); setData(await api.labs()); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl">Lab history</h1>
          <p className="text-muted mt-1">Every test across your documents, in time order. Values flagged high or low are compared with the range printed on the report.</p>
        </div>
        <Link to="/import" className="btn btn-primary"><FileUp size={16} aria-hidden /> Import documents</Link>
      </header>
      {err && <ErrorBox error={err} />}
      {data.tests.length === 0 ? (
        <Empty title="No lab results yet">Import a PDF or photos of your reports and the results will appear here.</Empty>
      ) : (
        <>
          <p className="text-sm text-muted" data-testid="lab-summary">
            {data.n_results} results, {data.tests.length} tests, {data.out_of_range} outside the printed range, {data.needs_review} waiting for your check.
          </p>
          {data.tests.map((t) => (
            <article key={t.test_key} className="card space-y-2" aria-label={t.test_name}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-xl">{t.test_name}</h2>
                  <p className="text-sm text-muted">{t.unit}{t.unit && refText(t) ? ", " : ""}{refText(t) && `printed range ${refText(t)}`}</p>
                </div>
                <Spark values={t.values} />
              </div>
              <ul className="divide-y divide-line">
                {t.values.map((v) => <LabRow key={v.id} v={v} unit={t.unit} onAct={act} />)}
              </ul>
            </article>
          ))}
        </>
      )}
    </div>
  );
}
