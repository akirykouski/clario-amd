import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useT, type Key } from "../i18n";

/** One onboarding step. `target` names a `data-tour` value; the first visible element with it gets a spotlight. */
export interface TourStep { title: Key; body: Key; target?: string }

const PAD = 6;
const FOCUSABLE = 'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** The visible element for a step, or null (hidden on this screen, on another page, or not rendered). */
function findTarget(name?: string): HTMLElement | null {
  if (!name) return null;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`))) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
  }
  return null;
}

/** "?" button for a header. Opens the tour on click only, never on first load. */
export function TourButton({ steps }: { steps: TourStep[] }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => { setOpen(false); btn.current?.focus(); }, []);
  return (
    <>
      <button ref={btn} type="button" className="btn !px-0 w-11 text-lg no-print" onClick={() => setOpen(true)}
        aria-label={t("tour.open")} title={t("tour.open")} aria-haspopup="dialog" data-testid="tour-open">
        <span aria-hidden>?</span>
      </button>
      {open && <Tour steps={steps} onClose={close} />}
    </>
  );
}

export function Tour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  const { t } = useT();
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const step = steps[i];
  const last = i === steps.length - 1;

  // Spotlight: find the step's element, bring it into view, follow it on scroll and resize.
  useLayoutEffect(() => {
    const el = findTarget(step.target);
    if (!el) { setRect(null); return; }
    el.scrollIntoView?.({ block: "center", behavior: "auto" });
    let frame = 0;
    const measure = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => setRect(el.getBoundingClientRect())); };
    setRect(el.getBoundingClientRect());
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", measure, true); window.removeEventListener("resize", measure); };
  }, [step.target]);

  useEffect(() => { card.current?.focus(); }, [i]);

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
    if (e.key !== "Tab" || !card.current) return;
    const items = Array.from(card.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0], end = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === card.current)) { e.preventDefault(); end.focus(); }
    else if (!e.shiftKey && active === end) { e.preventDefault(); first.focus(); }
  };

  // Card sits away from the spotlight: at the top when the element is low on screen, else at the bottom.
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;
  const place = !rect ? "top-1/2 -translate-y-1/2" : rect.top + rect.height / 2 > vh / 2 ? "top-4" : "bottom-4";

  // Portal to <body>: a header with backdrop-filter would otherwise become the containing block of `fixed`.
  return createPortal(
    <div className="fixed inset-0 z-50 no-print" onKeyDown={onKey}>
      <div className="absolute inset-0" style={rect ? undefined : { background: "rgba(0,0,0,0.5)" }} onClick={onClose} data-testid="tour-backdrop" />
      {rect && (
        <div aria-hidden data-testid="tour-spotlight" className="fixed rounded-xl pointer-events-none transition-all"
          style={{
            top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
            border: "3px solid var(--accent)", boxShadow: "0 0 0 9999px rgba(0,0,0,0.5)",
          }} />
      )}
      <div className={`absolute inset-x-0 px-4 flex justify-center pointer-events-none ${place}`}>
        <div ref={card} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" tabIndex={-1}
          className="card shadow-xl w-full max-w-md pointer-events-auto space-y-3 outline-none" data-testid="tour">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-muted font-bold" data-testid="tour-count">{t("tour.count", { n: i + 1, total: steps.length })}</p>
            <button type="button" className="btn btn-sm !px-0 w-9 -mt-1 -mr-1" onClick={onClose} aria-label={t("common.close")} title={t("common.close")}><X size={16} aria-hidden /></button>
          </div>
          <h2 id="tour-title" className="text-2xl">{t(step.title)}</h2>
          <p id="tour-body" className="text-[16px]">{t(step.body)}</p>
          <div className="flex items-center justify-between gap-2 pt-1">
            <button type="button" className="btn" onClick={() => setI(i - 1)} disabled={i === 0}>{t("tour.back")}</button>
            {last
              ? <button type="button" className="btn btn-primary" onClick={onClose}>{t("tour.done")}</button>
              : <button type="button" className="btn btn-primary" onClick={() => setI(i + 1)}>{t("tour.next")}</button>}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export const PATIENT_TOUR: TourStep[] = [
  { title: "tour.p1.title", body: "tour.p1.body", target: "today-write" },
  { title: "tour.p2.title", body: "tour.p2.body", target: "today-recent" },
  { title: "tour.p3.title", body: "tour.p3.body", target: "nav-timeline" },
  { title: "tour.p4.title", body: "tour.p4.body", target: "nav-share" },
  { title: "tour.p5.title", body: "tour.p5.body", target: "nav-privacy" },
];

export const CLINIC_TOUR: TourStep[] = [
  { title: "tour.c1.title", body: "tour.c1.body", target: "inbox" },
  { title: "tour.c2.title", body: "tour.c2.body", target: "pkg-glance" },
  { title: "tour.c3.title", body: "tour.c3.body", target: "needs-check" },
  { title: "tour.c4.title", body: "tour.c4.body", target: "ddx" },
  { title: "tour.c5.title", body: "tour.c5.body", target: "brief" },
];
