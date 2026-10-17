import { useState } from "react";
import { ArrowLeftRight, EyeOff, Lock } from "lucide-react";
import { api } from "../api";
import type { Comparison, CompareRow, PriorTest, SharePackage, TriedTreatment } from "../types";
import { fmtDate } from "../lib";
import { ErrorBox, Spinner } from "../components/ui";
import { tn, useT, type Key } from "../i18n";

/** Second opinion: the clinic server holds the previous doctor's conclusions back; this says so, first thing on the page. */
export function SecondOpinionBanner({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  if (!pkg.second_opinion) return null;
  return (
    <section className="card card-accent space-y-1" role="note" data-testid="so-banner">
      <p className="font-bold flex items-center gap-2"><EyeOff size={18} aria-hidden className="text-accent" />{t("so.banner")}</p>
      <p className="text-sm text-muted">{t("so.bannerSub")}</p>
    </section>
  );
}

const bad = (x: TriedTreatment) => x.effect === "none" || x.effect === "worse";

/** Facts about earlier care, for every package: what was tried (with its effect) and what was tested (with the result). */
export function CareFacts({ pkg }: { pkg: SharePackage }) {
  const { t } = useT();
  const tried = pkg.tried ?? [];
  const tested = pkg.tested ?? [];
  if (!tried.length && !tested.length) return null;
  const when = (d?: string | null) => (d ? fmtDate(d, { day: "numeric", month: "short" }) : "-");
  return (
    <section className="card space-y-3" data-testid="so-facts" aria-labelledby="so-tried">
      {tried.length > 0 && <div>
        <h2 id="so-tried" className="text-xl mb-1">{t("so.tried")}</h2>
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-line">{(["so.treatment", "so.started", "so.duration", "so.effect"] as Key[]).map((h) => <th key={h} className="px-2 py-1.5">{t(h)}</th>)}</tr></thead>
          <tbody>{tried.map((x, i) => (
            <tr key={i} className="border-b border-line last:border-0 align-top" data-testid="so-tried-row">
              <td className="px-2 py-1.5"><span className="font-bold">{x.treatment}</span>{x.note && <span className="block text-muted">{x.note}</span>}</td>
              <td className="px-2 py-1.5 whitespace-nowrap">{when(x.started)}</td>
              <td className="px-2 py-1.5 whitespace-nowrap">{x.duration ?? "-"}</td>
              <td className="px-2 py-1.5 whitespace-nowrap" style={bad(x) ? { color: "var(--strong)", fontWeight: 700 } : undefined}>{t(`effect.${x.effect}` as Key)}</td>
            </tr>))}</tbody></table></div>
      </div>}
      {tested.length > 0 && <div>
        <h2 className="text-xl mb-1">{t("so.tested")}</h2>
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-line">{(["so.test", "so.result", "so.date"] as Key[]).map((h) => <th key={h} className="px-2 py-1.5">{t(h)}</th>)}</tr></thead>
          <tbody>{tested.map((x: PriorTest, i) => (
            <tr key={i} className="border-b border-line last:border-0" data-testid="so-tested-row">
              <td className="px-2 py-1.5 font-bold">{x.test}</td>
              <td className="px-2 py-1.5" style={x.abnormal ? { color: "var(--strong)", fontWeight: 700 } : undefined}>{x.result}</td>
              <td className="px-2 py-1.5 whitespace-nowrap">{when(x.date)}</td>
            </tr>))}</tbody></table></div>
      </div>}
    </section>
  );
}

/** After this doctor signs: the previous doctor's conclusions next to this doctor's, disagreements marked. */
export function ComparePanel({ pkg, finalized }: { pkg: SharePackage; finalized: boolean }) {
  const { t, lang } = useT();
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!pkg.second_opinion) return null;
  const open = async () => {
    setBusy(true); setErr(null);
    try { setCmp(await api.compare(pkg.package_id, lang)); } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };
  if (!cmp) return (
    <section className="card space-y-2 no-print" data-testid="so-compare">
      <button className="btn btn-primary" onClick={open} disabled={!finalized || busy}>
        {finalized ? <ArrowLeftRight size={16} aria-hidden /> : <Lock size={16} aria-hidden />}{t("so.compare")}
      </button>
      {!finalized && <p className="text-sm text-muted">{t("so.compareLocked")}</p>}
      {busy && <Spinner />}
      {err && <ErrorBox error={err} />}
    </section>
  );
  if (!cmp.previous || !cmp.current) return (
    <section className="card no-print" data-testid="so-compare"><p className="text-muted">{t("so.noPrevious")}</p></section>
  );
  const prev = cmp.previous;
  const cur = cmp.current;
  return (
    <section className="card space-y-4" data-testid="so-compare" aria-labelledby="so-cmp">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="so-cmp" className="text-xl flex items-center gap-2"><ArrowLeftRight size={20} aria-hidden className="text-accent" />{t("so.compare")}</h2>
        <button className="btn btn-sm no-print" onClick={() => setCmp(null)}>{t("so.hide")}</button>
      </div>
      <p className="font-bold" data-testid="so-disagree" style={cmp.disagreements ? { color: "var(--strong)" } : undefined}>{tn("so.disagree", cmp.disagreements)}</p>
      <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="so-rows">
        <thead><tr className="text-left text-muted border-b border-line">
          <th className="px-2 py-1.5">{t("so.conditions")}</th>
          <th className="px-2 py-1.5">{t("so.previous")} <span className="font-normal">({t("so.previousBy", { who: prev.clinician, date: prev.date ? fmtDate(prev.date) : "?" })})</span></th>
          <th className="px-2 py-1.5">{t("so.yours")}</th><th className="px-2 py-1.5" />
        </tr></thead>
        <tbody>{cmp.rows.map((r) => <Row key={`${r.disease_id ?? ""}|${r.name}`} r={r} />)}</tbody>
      </table></div>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="space-y-2" data-testid="so-previous">
          <h3 className="text-lg">{t("so.previous")}</h3>
          <Lines title={t("so.accepted")} lines={prev.accepted} />
          <Lines title={t("so.rejected")} lines={prev.rejected} />
          {prev.notes && <div><p className="text-[13px] font-semibold text-muted">{t("so.notes")}</p><p className="text-sm">{prev.notes}</p></div>}
        </div>
        <div className="space-y-2" data-testid="so-yours">
          <h3 className="text-lg">{t("so.yours")}</h3>
          <p className="text-sm text-muted">{t("so.yoursSub")}</p>
          <Lines title={t("so.accepted")} lines={cur.accepted} />
          <Lines title={t("so.rejected")} lines={cur.rejected} />
        </div>
      </div>
      {cmp.since_previous.length > 0 && (
        <div className="rounded-lg p-3" style={{ background: "var(--amber-bg)" }} data-testid="so-after">
          <p className="text-[13px] font-semibold">{t("so.after")}</p>
          <p className="text-sm text-muted">{t("so.afterSub")}</p>
          <p className="text-sm mt-1">{cmp.since_previous.join(", ")}</p>
        </div>
      )}
    </section>
  );
}

function Row({ r }: { r: CompareRow }) {
  const { t } = useT();
  const differs = !r.agree;
  return (
    <tr className="border-b border-line last:border-0" data-testid="so-row" data-agree={r.agree ? "yes" : "no"}
      style={differs ? { background: "color-mix(in srgb, var(--strong) 7%, transparent)" } : undefined}>
      <td className="px-2 py-1.5 font-bold">{r.name}</td>
      <td className="px-2 py-1.5">{r.previous ? t(r.previous === "diagnosis" ? "so.diagnosis" : "so.considered") : <span className="text-muted">{t("so.notNamed")}</span>}</td>
      <td className="px-2 py-1.5">{r.current_rank ? t("so.rank", { n: r.current_rank }) : <span className="text-muted">{t("so.notNamed")}</span>}</td>
      <td className="px-2 py-1.5"><span className="chip text-xs" style={differs ? { borderColor: "var(--strong)", color: "var(--strong)" } : undefined}>{differs ? t("so.differs") : t("so.agree")}</span></td>
    </tr>
  );
}

function Lines({ title, lines }: { title: string; lines: string[] }) {
  const { t } = useT();
  return (
    <div>
      <p className="text-[13px] font-semibold text-muted">{title}</p>
      {lines.length ? <ul className="list-disc pl-5 text-sm space-y-0.5">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
        : <p className="text-sm text-muted">{t("so.none")}</p>}
    </div>
  );
}
