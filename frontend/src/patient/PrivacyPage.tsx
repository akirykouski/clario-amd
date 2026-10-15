import { ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "../api";
import type { AiCall, PrivacyVerify } from "../types";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { tn, useT } from "../i18n";
import { fmtDate } from "../lib";

export function ChainStatus({ v }: { v: PrivacyVerify }) {
  const { t } = useT();
  return v.ok ? (
    <p role="status" className="inline-flex items-center gap-2 font-bold" style={{ color: "var(--accent)" }}>
      <ShieldCheck size={20} aria-hidden /> {tn("privacy.verified", v.count)}
    </p>
  ) : (
    <p role="alert" className="inline-flex items-center gap-2 font-bold text-strong">
      <ShieldAlert size={20} aria-hidden /> {t("privacy.broken", { id: v.broken_at ?? "" })}
    </p>
  );
}

export function CallRow({ c }: { c: AiCall }) {
  const { t } = useT();
  return (
    <li className="card" data-testid="ai-call">
      <div className="flex flex-wrap justify-between gap-x-3 text-sm text-muted">
        <span className="font-mono">{c.id}</span>
        <time dateTime={c.ts}>{fmtDate(c.ts, { dateStyle: "medium", timeStyle: "short" })}</time>
      </div>
      <p className="mt-1 font-bold">{t(`purpose.${c.purpose}`)} <span className="font-normal text-muted">{t("privacy.on", { backend: c.backend, model: c.model })}</span></p>
      <p className="text-sm">
        {c.redacted ? tn("privacy.replaced", c.replacements) : t("privacy.asWritten")}
        {c.images > 0 && tn("privacy.images", c.images)}
      </p>
      {c.redacted_preview && <p className="mt-1 text-sm text-muted break-words line-clamp-3">{c.redacted_preview}</p>}
    </li>
  );
}

export function CallLogPanel() {
  const { t } = useT();
  const verify = useAsync(() => api.privacyVerify(), []);
  const calls = useAsync(() => api.privacyCalls(50), []);
  if (verify.loading || calls.loading) return <Loading />;
  if (verify.error || calls.error || !verify.data || !calls.data)
    return <ErrorBox error={verify.error ?? calls.error ?? t("privacy.loadError")} retry={() => { verify.reload(); calls.reload(); }} />;
  return (
    <div className="space-y-4">
      <ChainStatus v={verify.data} />
      {calls.data.length === 0
        ? <Empty title={t("privacy.emptyTitle")}>{t("privacy.emptyText")}</Empty>
        : <ul className="space-y-3">{calls.data.map((c) => <CallRow key={c.id} c={c} />)}</ul>}
    </div>
  );
}

export default function PrivacyPage() {
  const { t } = useT();
  return (
    <div className="space-y-4">
      <h1 className="text-3xl">{t("privacy.title")}</h1>
      <p className="text-muted">{t("privacy.intro")}</p>
      <p className="text-sm text-muted">{t("cloud.pagesNote")}</p>
      <CallLogPanel />
    </div>
  );
}
