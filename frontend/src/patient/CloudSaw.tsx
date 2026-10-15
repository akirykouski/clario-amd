import { useState } from "react";
import { Cloud } from "lucide-react";
import { api } from "../api";
import type { PrivacyKind, PrivacyPreview } from "../types";

export const kindLabel: Record<PrivacyKind, string> = {
  email: "Email", phone: "Phone", codice_fiscale: "Tax code", iban: "Bank account", date: "Date", address: "Address", name: "Name",
};

export interface Seg { text: string; kind?: PrivacyKind }

/** Cut `text` at the given spans (assumed non-overlapping). Spans carry the redaction kind. */
export function highlightSegments(text: string, spans: { start: number; end: number; type: PrivacyKind }[]): Seg[] {
  const out: Seg[] = [];
  let pos = 0;
  for (const s of [...spans].sort((a, b) => a.start - b.start)) {
    if (s.start > pos) out.push({ text: text.slice(pos, s.start) });
    out.push({ text: text.slice(s.start, s.end), kind: s.type });
    pos = s.end;
  }
  if (pos < text.length) out.push({ text: text.slice(pos) });
  return out;
}

function Column({ title, segs, testId }: { title: string; segs: Seg[]; testId: string }) {
  return (
    <div className="min-w-0">
      <h3 className="text-sm font-bold text-muted mb-1">{title}</h3>
      <p className="whitespace-pre-wrap break-words rounded-lg border border-line p-3 text-[15px]" data-testid={testId}>
        {segs.map((s, i) => s.kind
          ? <mark key={i} className="redact" title={kindLabel[s.kind]}>{s.text}</mark>
          : <span key={i}>{s.text}</span>)}
      </p>
    </div>
  );
}

export function CloudSawView({ p }: { p: PrivacyPreview }) {
  const n = p.replacements.length;
  const orig = highlightSegments(p.original, p.replacements.map((r) => ({ start: r.start, end: r.end, type: r.type })));
  const sent = highlightSegments(p.redacted, p.replacements.map((r) => ({ start: r.out_start, end: r.out_end, type: r.type })));
  const kinds = [...new Set(p.replacements.map((r) => kindLabel[r.type]))];
  return (
    <div className="mt-3 space-y-3">
      <p className="text-sm text-muted" aria-live="polite">
        {p.applied
          ? n ? `Before this note goes to the model, ${n} personal detail${n === 1 ? " is" : "s are"} replaced (${kinds.join(", ").toLowerCase()}).`
              : "Before this note goes to the model, nothing needed replacing."
          : "The model for this diary runs on this device, so nothing leaves it. If you switch to a cloud model, the right column is what it would see."}
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <Column title="What you wrote" segs={orig} testId="cloud-original" />
        <Column title={p.applied ? "What the cloud saw" : "What a cloud model would see"} segs={sent} testId="cloud-sent" />
      </div>
    </div>
  );
}

export function CloudSaw({ entryId, compact = false }: { entryId: string; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<PrivacyPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !data) api.privacyPreview(entryId).then(setData).catch((e: Error) => setErr(e.message));
  };
  return (
    <div>
      <button className={compact ? "btn-quiet btn px-0" : "btn"} aria-expanded={open} onClick={toggle}>
        <Cloud size={16} aria-hidden /> What the cloud saw
      </button>
      {open && err && <p role="alert" className="text-sm text-strong mt-2">{err}</p>}
      {open && !err && !data && <p className="text-sm text-muted mt-2">Loading</p>}
      {open && data && <CloudSawView p={data} />}
    </div>
  );
}
