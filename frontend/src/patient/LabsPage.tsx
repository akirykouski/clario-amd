import { useState } from "react";
import { Link } from "react-router-dom";
import { FileUp } from "lucide-react";
import { api } from "../api";
import { fmtDate, fmtNum, notifyReview, prettyUnit } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { isOfflineBackend, useHealth } from "../components/useHealth";
import { t, useT } from "../i18n";
import type { LabPatch, LabTest, LabValue } from "../types";

const num = (n: number) => fmtNum(n);
/** "Positivo 1:160" -> "pos", "Negativo" -> "neg": a qualitative result, never "High" or "Low". */
export function qualKind(v: Pick<LabValue, "value_numeric" | "value_text">): "pos" | "neg" | null {
  if (v.value_numeric !== null || !v.value_text) return null;
  if (/^\s*posit/i.test(v.value_text)) return "pos";
  if (/^\s*negat/i.test(v.value_text)) return "neg";
  return null;
}
/** "Positivo 1:160" -> "Positive 1:160" in English; the Italian word stays. Any other text is unchanged. */
export function qualText(text: string): string {
  const q = qualKind({ value_numeric: null, value_text: text });
  return q ? text.replace(/^\s*\w+/, q === "pos" ? t("labs.positive") : t("labs.negative")) : text;
}
export const valueText = (v: LabValue) => {
  if (v.value_numeric !== null) return num(v.value_numeric);
  return qualText(v.value_text ?? "");
};

// Test names as the report prints them (Italian) -> English, for the generator's tests.
const LAB_EN: Record<string, string> = {
  "proteine urinarie": "Urine protein", "sodio": "Sodium", "pcr": "CRP", "glicemia": "Glucose", "emoglobina": "Hemoglobin",
  "neutrofili": "Neutrophils", "ematocrito": "Hematocrit", "ves": "ESR", "potassio": "Potassium", "creatinina": "Creatinine",
  "piastrine": "Platelets", "vitamina d": "Vitamin D", "colesterolo totale": "Total cholesterol", "sideremia": "Serum iron",
  "globuli bianchi": "White blood cells", "globuli rossi": "Red blood cells", "azotemia": "Blood urea nitrogen",
  "linfociti": "Lymphocytes",
};
/** Name to show, and the report's own name when it differs (English UI only). */
export function labName(name: string, lang: string): { main: string; printed: string | null } {
  const en = lang === "en" ? LAB_EN[name.trim().toLowerCase()] : undefined;
  return en && en.toLowerCase() !== name.trim().toLowerCase() ? { main: en, printed: name } : { main: name, printed: null };
}
export function refText(r: Pick<LabTest, "ref_low" | "ref_high">): string {
  if (r.ref_low !== null && r.ref_high !== null) return t("labs.rangeBoth", { lo: num(r.ref_low), hi: num(r.ref_high) });
  if (r.ref_high !== null) return t("labs.rangeUpTo", { hi: num(r.ref_high) });
  if (r.ref_low !== null) return t("labs.rangeFrom", { lo: num(r.ref_low) });
  return "";
}

function FlagPill({ v }: { v: LabValue }) {
  const q = qualKind(v);
  // A qualitative result says "Positive" in its own value; it never gets a High or Low pill.
  const word = q ? "" : v.flag === "high" ? t("labs.high") : v.flag === "low" ? t("labs.low") : "";
  if (!word) return null;
  return (
    <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-bold whitespace-nowrap"
      style={{ color: "var(--strong)", borderColor: "var(--strong)" }}>{word}</span>
  );
}

function Spark({ values }: { values: LabValue[] }) {
  const pts = values.filter((v) => v.value_numeric !== null).map((v) => v.value_numeric as number);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1;
  const xy = pts.map((p, i) => `${(i / (pts.length - 1)) * 96 + 2},${26 - ((p - lo) / span) * 22}`);
  const last = xy[xy.length - 1].split(",");
  return (
    <svg width="100" height="30" viewBox="0 0 100 30" role="img" aria-label={t("labs.trend", { n: pts.length })} className="shrink-0">
      <polyline points={xy.join(" ")} fill="none" stroke="var(--muted)" strokeWidth="1.5" />
      <circle cx={last[0]} cy={last[1]} r="3" fill="var(--accent)" />
    </svg>
  );
}

export function LabRow({ v, unit, onAct }: { v: LabValue; unit: string; onAct: (id: string, b: LabPatch) => Promise<void> }) {
  const { t: tt } = useT();
  const offline = isOfflineBackend(useHealth());
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
    <li data-testid="lab-row" data-review={v.review} className="py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm text-muted whitespace-nowrap min-w-[4.75rem]">{fmtDate(v.date, { day: "numeric", month: "short", year: "2-digit" })}</span>
        <span className="font-bold tabular-nums" style={qualKind(v) === "pos" ? { color: "var(--strong)" } : undefined}>{valueText(v)} <span className="font-normal text-muted text-sm">{unit}</span></span>
        <FlagPill v={v} />
        {review && <span className="text-sm text-muted">{v.confidence !== null && !offline ? tt("labs.needsLookSure") : tt("labs.needsLook")}</span>}
        {review && !editing && <button className="btn-quiet btn px-0 min-h-[32px] text-sm" disabled={busy} onClick={() => setEditing(true)}>{tt("labs.fix")}</button>}
        {v.review === "confirmed" && <span className="text-sm text-muted">{tt("common.confirmed")}</span>}
        {v.review === "corrected" && <span className="text-sm text-muted">{tt("labs.corrected")}</span>}
      </div>
      {review && editing && (
        <form className="flex flex-wrap items-end gap-2 mt-2" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <label className="flex-1 min-w-[7rem]"><span className="label">{tt("labs.value")}</span><input className="input" value={val} onChange={(e) => setVal(e.target.value)} inputMode="decimal" /></label>
          <label className="w-28"><span className="label">{tt("labs.unit")}</span><input className="input" value={u} onChange={(e) => setU(e.target.value)} /></label>
          <button className="btn btn-primary" type="submit" disabled={busy || !val.trim()}>{tt("common.save")}</button>
          <button className="btn" type="button" onClick={() => setEditing(false)}>{tt("common.cancel")}</button>
        </form>
      )}
    </li>
  );
}

export default function LabsPage() {
  const { t, tn, lang } = useT();
  const { data, error, loading, reload, setData } = useAsync(() => api.labs(), []);
  const [err, setErr] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.noData")} retry={reload} />;

  const act = async (id: string, b: LabPatch) => {
    setErr(null);
    try { await api.patchLab(id, b); setData(await api.labs()); notifyReview(); } catch (e) { setErr((e as Error).message); }
  };

  const byName = (x: LabTest, y: LabTest) => labName(x.test_name, lang).main.localeCompare(labName(y.test_name, lang).main, lang);
  const tests = [...data.tests].sort(byName);
  const needsLook = (x: LabTest) => x.out_of_range || x.values.some((v) => v.review === "needs_review");
  const attention = tests.filter(needsLook), calm = tests.filter((x) => !needsLook(x));
  const card = (x: LabTest) => { const nm = labName(x.test_name, lang); const unit = prettyUnit(x.unit); return (
            <article key={x.test_key} className="card space-y-2" aria-label={nm.main}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-xl">{nm.main}{nm.printed && <span className="ml-2 text-sm font-sans text-muted">{nm.printed}</span>}</h2>
                  <p className="text-sm text-muted">{unit}{unit && refText(x) ? ", " : ""}{refText(x) && t("labs.printedRange", { range: refText(x) })}</p>
                </div>
                <Spark values={x.values} />
              </div>
              <ul className="divide-y divide-line">
                {x.values.map((v) => <LabRow key={v.id} v={v} unit={unit} onAct={act} />)}
              </ul>
            </article>
  ); };

  return (
    <div className="space-y-5" data-tour="labs">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl">{t("labs.title")}</h1>
          <p className="text-muted mt-1">{t("labs.intro")}</p>
        </div>
        <Link to="/import" className="btn btn-primary"><FileUp size={16} aria-hidden /> {t("labs.import")}</Link>
      </header>
      {err && <ErrorBox error={err} />}
      {data.tests.length === 0 ? (
        <Empty title={t("labs.emptyTitle")}>{t("labs.emptyText")}</Empty>
      ) : (
        <>
          <p className="text-lg font-bold" data-testid="lab-summary">
            {t("labs.summary", { n: data.n_results, tests: data.tests.length, out: data.out_of_range })}
            {data.needs_review > 0 && <span className="font-normal">{t("labs.summaryReview", { review: data.needs_review })}</span>}
          </p>
          {attention.map(card)}
          {calm.length > 0 && (
            <details className="card" data-testid="labs-in-range">
              <summary className="cursor-pointer min-h-[44px] flex items-center font-bold">{tn("labs.inRange", calm.length)}</summary>
              <div className="space-y-3 mt-2">{calm.map(card)}</div>
            </details>
          )}
        </>
      )}
    </div>
  );
}
