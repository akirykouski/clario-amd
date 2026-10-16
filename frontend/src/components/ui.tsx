import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useT } from "../i18n";
import type { Signal } from "../types";

// Tier colours stay clear of the red that marks a high lab value.
const sigColor: Record<Signal, string> = { weak: "var(--weak)", moderate: "var(--moderate)", strong: "var(--accent)" };

export function SignalPill({ signal }: { signal: Signal }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-sm font-bold min-h-[32px]"
        style={{ color: sigColor[signal], borderColor: sigColor[signal] }}>
        <span aria-hidden className="inline-block w-2 h-2 rounded-full" style={{ background: sigColor[signal] }} />
        {t(`signal.${signal}`)}
      </button>
      {open && <span role="note" className="card absolute right-0 top-full z-10 mt-1 block w-64 text-sm font-normal text-ink shadow-lg">{t(`signal.explain.${signal}`)}</span>}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  const { t } = useT();
  return <span role="status" className="inline-flex items-center gap-1.5 text-muted text-sm"><Loader2 className="animate-spin" size={14} aria-hidden />{label ?? t("common.working")}</span>;
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  const { t } = useT();
  return (
    <div role="alert" className="card border-strong text-sm">
      <p>{error}</p>
      {retry && <button className="btn mt-2" onClick={retry}>{t("common.tryAgain")}</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="card text-center py-8"><p className="font-display text-xl">{title}</p><div className="text-muted mt-1">{children}</div></div>;
}

export function Loading({ label }: { label?: string }) {
  const { t } = useT();
  return <div className="py-8 flex justify-center"><Spinner label={label ?? t("common.loading")} /></div>;
}
