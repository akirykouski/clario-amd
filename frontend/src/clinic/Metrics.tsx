import { api } from "../api";
import { useAsync } from "../components/useAsync";
import { useT } from "../i18n";
import type { DecisionCounts } from "../types";

/** "3 min 40 s" / "40 s", in the current language. */
export function useDuration() {
  const { t } = useT();
  return (seconds: number) => {
    const total = Math.max(0, Math.round(seconds));
    return total >= 60
      ? t("metrics.duration.min", { m: Math.floor(total / 60), s: total % 60 })
      : t("metrics.duration.sec", { s: total });
  };
}

/** Pilot metric for one brief: how many AI lines the clinician accepted, edited, rejected, and how long it took. */
export function DecisionLine({ counts, seconds, testId = "decision-line" }: { counts: DecisionCounts; seconds?: number | null; testId?: string }) {
  const { t } = useT();
  const dur = useDuration();
  return (
    <p className="text-sm text-muted no-print" data-testid={testId}>
      <span className="font-bold text-ink">{t("metrics.scopePackage")}</span> · {t("metrics.lines", { a: counts.accepted, e: counts.edited, r: counts.rejected })}
      {seconds != null && ` · ${t("metrics.finalizeTime", { d: dur(seconds) })}`}
    </p>
  );
}

/** Inbox header: one small strip over every finalized brief on this clinic server. Hidden until one is finalized. */
export function InboxMetrics() {
  const { t, tn } = useT();
  const dur = useDuration();
  const { data } = useAsync(() => api.clinicMetrics(), []);
  if (!data || data.finalized === 0) return null;
  const tiles = [["accepted", data.totals.accepted], ["edited", data.totals.edited], ["rejected", data.totals.rejected]] as const;
  return (
    <div className="card mb-3 py-2 px-3 flex flex-wrap items-center gap-x-5 gap-y-2" data-testid="inbox-metrics">
      <div className="min-w-0">
        <p className="text-sm font-bold">{t("metrics.scopeAll")}</p>
        <p className="text-xs text-muted">
          {tn("metrics.briefs", data.finalized)}
          {data.mean_review_seconds != null && ` · ${t("metrics.avgTime", { d: dur(data.mean_review_seconds) })}`}
        </p>
      </div>
      <dl className="flex gap-4 ml-auto" aria-label={t("metrics.lines", { a: data.totals.accepted, e: data.totals.edited, r: data.totals.rejected })}>
        {tiles.map(([k, n]) => (
          <div key={k} className="text-center" data-testid={`metric-${k}`}>
            <dd className="text-xl font-bold leading-none">{n}</dd>
            <dt className="text-xs text-muted">{t(`metrics.${k}` as const)}</dt>
          </div>))}
      </dl>
    </div>
  );
}
