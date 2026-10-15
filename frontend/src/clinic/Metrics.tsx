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
      {t("metrics.lines", { a: counts.accepted, e: counts.edited, r: counts.rejected })}
      {seconds != null && ` · ${t("metrics.finalizeTime", { d: dur(seconds) })}`}
    </p>
  );
}

/** Inbox header: totals over every finalized brief on this clinic server. Hidden until one is finalized. */
export function InboxMetrics() {
  const { t, tn } = useT();
  const dur = useDuration();
  const { data } = useAsync(() => api.clinicMetrics(), []);
  if (!data || data.finalized === 0) return null;
  return (
    <p className="text-sm text-muted mb-3" data-testid="inbox-metrics">
      {tn("metrics.briefs", data.finalized)} · {t("metrics.lines", { a: data.totals.accepted, e: data.totals.edited, r: data.totals.rejected })}
      {data.mean_review_seconds != null && ` · ${t("metrics.avgTime", { d: dur(data.mean_review_seconds) })}`}
    </p>
  );
}
