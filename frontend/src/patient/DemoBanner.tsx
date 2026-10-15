import { useEffect, useRef } from "react";
import { FlaskConical } from "lucide-react";

export const DEMO_TEXT = "Demo server: synthetic data only. Do not enter real health information.";

/** Persistent, not dismissible. Publishes its height as --demo-h so sticky headers sit below it. */
export function DemoBanner() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--demo-h", `${el.offsetHeight}px`);
    set();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(set) : null;
    ro?.observe(el);
    return () => { ro?.disconnect(); document.documentElement.style.removeProperty("--demo-h"); };
  }, []);
  return (
    <div ref={ref} role="status" data-testid="demo-banner" className="no-print sticky top-0 z-40 w-full px-4 py-2 flex items-center justify-center gap-2 text-sm font-bold text-center border-b-2"
      style={{ background: "var(--danger-bg)", borderColor: "var(--moderate)", color: "var(--ink)" }}>
      <FlaskConical size={16} aria-hidden className="shrink-0" style={{ color: "var(--moderate)" }} />
      <span>{DEMO_TEXT}</span>
    </div>
  );
}
