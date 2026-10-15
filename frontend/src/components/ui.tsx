import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { signalWord } from "../lib";
import type { Signal } from "../types";

const sigColor: Record<Signal, string> = { weak: "var(--weak)", moderate: "var(--moderate)", strong: "var(--strong)" };

export function SignalPill({ signal }: { signal: Signal }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-sm font-bold"
      style={{ color: sigColor[signal], borderColor: sigColor[signal] }}>
      <span aria-hidden className="inline-block w-2 h-2 rounded-full" style={{ background: sigColor[signal] }} />
      {signalWord[signal]}
    </span>
  );
}

export function Spinner({ label = "Working" }: { label?: string }) {
  return <span role="status" className="inline-flex items-center gap-1.5 text-muted text-sm"><Loader2 className="animate-spin" size={14} aria-hidden />{label}</span>;
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div role="alert" className="card border-strong text-sm">
      <p>{error}</p>
      {retry && <button className="btn mt-2" onClick={retry}>Try again</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="card text-center py-8"><p className="font-display text-xl">{title}</p><div className="text-muted mt-1">{children}</div></div>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="py-8 flex justify-center"><Spinner label={label} /></div>;
}
