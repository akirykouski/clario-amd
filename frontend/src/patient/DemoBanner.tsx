import { useEffect, useRef } from "react";
import { FlaskConical } from "lucide-react";
import { en } from "../i18n/en";
import { useT } from "../i18n";

export const DEMO_TEXT = en["demo.banner"];

/** Persistent, not dismissible. Publishes its height as --demo-h so sticky headers sit below it. */
export function DemoBanner() {
  const { t } = useT();
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
    <div ref={ref} role="status" data-testid="demo-banner" className="no-print sticky top-0 z-40 w-full px-4 py-2 flex items-center justify-center gap-2 text-sm font-semibold text-center border-b"
      style={{ background: "rgba(255, 228, 214, 0.78)", borderColor: "rgba(255, 138, 107, 0.45)", color: "var(--ink)", WebkitBackdropFilter: "blur(14px)", backdropFilter: "blur(14px)" }}>
      <FlaskConical size={16} aria-hidden className="shrink-0" style={{ color: "var(--moderate)" }} />
      <span>{t("demo.banner")}</span>
    </div>
  );
}
