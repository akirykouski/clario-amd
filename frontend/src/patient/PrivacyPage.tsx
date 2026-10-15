import { ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "../api";
import type { AiCall, PrivacyVerify } from "../types";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";

export function ChainStatus({ v }: { v: PrivacyVerify }) {
  return v.ok ? (
    <p role="status" className="inline-flex items-center gap-2 font-bold" style={{ color: "var(--accent)" }}>
      <ShieldCheck size={20} aria-hidden /> Log verified. {v.count} call{v.count === 1 ? "" : "s"}, none changed.
    </p>
  ) : (
    <p role="alert" className="inline-flex items-center gap-2 font-bold text-strong">
      <ShieldAlert size={20} aria-hidden /> Log broken at {v.broken_at}. A record was changed or removed.
    </p>
  );
}

export function CallRow({ c }: { c: AiCall }) {
  return (
    <li className="card" data-testid="ai-call">
      <div className="flex flex-wrap justify-between gap-x-3 text-sm text-muted">
        <span className="font-mono">{c.id}</span>
        <time dateTime={c.ts}>{new Date(c.ts).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time>
      </div>
      <p className="mt-1 font-bold">{c.purpose.replace("_", " ")} <span className="font-normal text-muted">on {c.backend}, {c.model}</span></p>
      <p className="text-sm">
        {c.redacted ? `${c.replacements} detail${c.replacements === 1 ? "" : "s"} replaced before sending` : "Sent as written (model on a trusted machine)"}
        {c.images > 0 && `, ${c.images} image${c.images === 1 ? "" : "s"}`}
      </p>
      {c.redacted_preview && <p className="mt-1 text-sm text-muted break-words line-clamp-3">{c.redacted_preview}</p>}
    </li>
  );
}

export function CallLogPanel() {
  const verify = useAsync(() => api.privacyVerify(), []);
  const calls = useAsync(() => api.privacyCalls(50), []);
  if (verify.loading || calls.loading) return <Loading />;
  if (verify.error || calls.error || !verify.data || !calls.data)
    return <ErrorBox error={verify.error ?? calls.error ?? "Could not load the log"} retry={() => { verify.reload(); calls.reload(); }} />;
  return (
    <div className="space-y-4">
      <ChainStatus v={verify.data} />
      {calls.data.length === 0
        ? <Empty title="No model calls yet">Each time a note or brief goes to a model, it is listed here.</Empty>
        : <ul className="space-y-3">{calls.data.map((c) => <CallRow key={c.id} c={c} />)}</ul>}
    </div>
  );
}

export default function PrivacyPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-3xl">What left this device</h1>
      <p className="text-muted">Every call to a model is written to a chain of hashes. Change or remove one record and the check below fails. The log keeps a short redacted preview, never your full text.</p>
      <CallLogPanel />
    </div>
  );
}
