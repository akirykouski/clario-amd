import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { driver, type Driver, type DriveStep, type PopoverDOM, type Side, type State } from "driver.js";
import "driver.js/dist/driver.css";
import "./tour.css";
import { api } from "../api";
import { t, useT, type Key } from "../i18n";

/** One onboarding step: the screen it lives on and the `data-tour` element it spotlights there. */
export interface TourStep {
  title: Key;
  body: Key;
  /** Path (and query) of the screen for this step; the tour navigates there first. */
  route?: string;
  /** `data-tour` value of the element to spotlight. Missing on screen: a centred card, still blurred. */
  target?: string;
  /** Extra selector for content that loads after the target (the spotlight waits for it, then sizes once). */
  ready?: string;
  side?: Side;
}

/** A tour is a fixed list or one built when "?" is pressed (the clinic needs its inbox first). */
export type TourPlan = TourStep[] | (() => Promise<TourStep[]>);

const PAD = 10;
const RADIUS = 14;
const WAIT_MS = 2500;
const CLOSE_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

const reducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const frame = () => new Promise<void>((r) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => r()) : setTimeout(r, 16)));

/** The visible element for a `data-tour` name, or null. */
export function findTarget(name?: string): HTMLElement | null {
  if (!name) return null;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`))) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
  }
  return null;
}

const isReady = (s: TourStep) => !!findTarget(s.target) && (!s.ready || !!document.querySelector(s.ready));

/** Resolves when the step's element (and its async content) is on screen, or after `ms`. */
function waitForStep(s: TourStep, ms: number): Promise<void> {
  if (!s.target || isReady(s)) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => { obs.disconnect(); clearTimeout(timer); resolve(); };
    const obs = new MutationObserver(() => { if (isReady(s)) done(); });
    const timer = setTimeout(done, ms);
    obs.observe(document.body, { childList: true, subtree: true, attributes: true });
  });
}

/** Height covered at the top (sticky header) and bottom (phone tab bar) by elements marked `data-tour-inset`. */
function insets() {
  let top = 0, bottom = 0;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("[data-tour-inset]"))) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (el.dataset.tourInset === "bottom") bottom = Math.max(bottom, r.height);
    else top = Math.max(top, (parseFloat(getComputedStyle(el).top) || 0) + r.height);
  }
  return { top, bottom };
}

/** Scroll so the element sits in the middle of the free area (with the card under it on narrow screens),
 *  or at the top when that does not fit, before driver.js looks. */
function bringIntoView(el: HTMLElement) {
  const r = el.getBoundingClientRect();
  const { top, bottom } = insets();
  const free = window.innerHeight - top - bottom;
  const h = r.height + PAD * 2;
  const block = hasSideRoom(r) ? h : h + 14 + CARD_H;
  const want = block <= free - 24 ? top + (free - block) / 2 + PAD : top + 16 + PAD;
  if (Math.abs(r.top - want) > 2) window.scrollTo({ top: Math.max(0, window.scrollY + r.top - want), behavior: "instant" as ScrollBehavior });
}

function roundedRect(x: number, y: number, w: number, h: number, r: number) {
  const k = Math.max(0, Math.min(r, w / 2, h / 2));
  return `M${x + k} ${y}H${x + w - k}A${k} ${k} 0 0 1 ${x + w} ${y + k}V${y + h - k}A${k} ${k} 0 0 1 ${x + w - k} ${y + h}`
    + `H${x + k}A${k} ${k} 0 0 1 ${x} ${y + h - k}V${y + k}A${k} ${k} 0 0 1 ${x + k} ${y}Z`;
}

/** Room the card needs beside a target (width + gap) and, on narrow screens, below or above it. */
const SIDE_ROOM = 400;
const CARD_H = 320;
const hasSideRoom = (r: DOMRect) => window.innerWidth - r.right >= SIDE_ROOM || r.left >= SIDE_ROOM;

/**
 * The element driver.js should spotlight. A target taller than the free screen gets a stand-in box over its top
 * part, so the window shows the start of it crisp and the card still fits beside or under it.
 */
function spotlightFor(el: HTMLElement, proxy: HTMLElement): HTMLElement {
  const r = el.getBoundingClientRect();
  const { top, bottom } = insets();
  const free = window.innerHeight - top - bottom - 32 - PAD * 2;
  const max = Math.max(140, hasSideRoom(r) ? free : free - CARD_H);
  if (r.height <= max) { proxy.remove(); return el; }
  Object.assign(proxy.style, {
    position: "absolute", pointerEvents: "none", visibility: "hidden",
    left: `${r.left + window.scrollX}px`, top: `${r.top + window.scrollY}px`, width: `${r.width}px`, height: `${max}px`,
  });
  document.body.append(proxy);
  return proxy;
}

export interface TourRun { stop: () => void }

/**
 * Runs a tour that drives the app: each step navigates to its screen, waits for its element and spotlights it.
 * driver.js handles steps, keys and the popover; the blur layer and the glow ring follow its stage every frame.
 */
export function startTour(steps: TourStep[], opts: { navigate: (to: string) => void; where: () => string; onEnd?: () => void }): TourRun {
  const start = opts.where();
  const total = steps.length;
  let seq = 0;
  let ended = false;
  let raf = 0;
  const animated = !reducedMotion();

  const blur = document.createElement("div");
  blur.className = "clario-tour-blur no-print";
  blur.setAttribute("aria-hidden", "true");
  blur.dataset.testid = "tour-blur";
  const ring = document.createElement("div");
  ring.className = "clario-tour-ring no-print";
  ring.setAttribute("aria-hidden", "true");
  ring.dataset.testid = "tour-spotlight";
  document.body.append(blur, ring);
  const proxy = document.createElement("div");
  proxy.className = "clario-tour-proxy";
  proxy.setAttribute("aria-hidden", "true");
  const shown: (HTMLElement | null)[] = steps.map(() => null);

  const decorate = (p: PopoverDOM, { state }: { state: State }) => {
    const i = state.activeIndex ?? 0;
    p.wrapper.dataset.testid = "tour";
    p.wrapper.setAttribute("aria-modal", "true");
    const top = document.createElement("div");
    top.className = "clario-tour-top";
    if (total > 1) {
      const dots = document.createElement("div");
      dots.className = "clario-tour-dots";
      dots.setAttribute("aria-hidden", "true");
      for (let n = 0; n < total; n++) {
        const d = document.createElement("span");
        d.className = `clario-tour-dot${n < i ? " is-done" : n === i ? " is-active" : ""}`;
        dots.append(d);
      }
      top.append(dots);
    }
    const count = document.createElement("span");
    count.className = "clario-tour-count";
    count.dataset.testid = "tour-count";
    count.textContent = t("tour.count", { n: i + 1, total });
    top.append(count);
    p.wrapper.insertBefore(top, p.title);
    p.closeButton.innerHTML = CLOSE_ICON;
    p.closeButton.setAttribute("aria-label", t("common.close"));
    p.closeButton.title = t("common.close");
    p.wrapper.append(p.closeButton); // after the buttons in tab order; it is placed top right by CSS
  };

  const d: Driver = driver({
    steps: steps.map((s, i): DriveStep => ({
      element: (() => shown[i] ?? findTarget(s.target)) as () => Element,
      popover: {
        title: t(s.title), description: t(s.body), side: s.side ?? "bottom", align: "center",
        showButtons: i === 0 ? ["next", "close"] : ["next", "previous", "close"],
      },
    })),
    animate: animated,
    duration: 300,
    smoothScroll: false,
    allowClose: true,
    overlayClickBehavior: "close",
    stagePadding: PAD,
    stageRadius: RADIUS,
    popoverOffset: 14,
    disableActiveInteraction: true,
    showProgress: false,
    popoverClass: "clario-tour",
    nextBtnText: t("tour.next"),
    prevBtnText: t("tour.back"),
    doneBtnText: t("tour.done"),
    onPopoverRender: decorate,
    onHighlighted: () => { d.getState("popover")?.nextButton?.focus(); },
    onNextClick: () => { const i = d.getActiveIndex() ?? 0; if (i >= total - 1) end(); else void go(i + 1); },
    onPrevClick: () => { const i = d.getActiveIndex() ?? 0; if (i > 0) void go(i - 1); },
    onCloseClick: () => end(),
    onDestroyStarted: () => end(), // Esc and a click on the dimmed page
  });

  // Each frame: copy driver's stage (animated between steps) into the blur hole and the ring, and re-measure
  // a target whose size or position changed after it was highlighted (content that loads late).
  let last = "";
  const tick = () => {
    if (ended) return;
    const el = d.getState("activeElement") as Element | undefined;
    const pos = d.getState("__activeStagePosition") as { x: number; y: number; width: number; height: number } | undefined;
    // a detached element is the previous screen's, while the next screen renders: blur everything meanwhile
    const centred = !el || el.id === "driver-dummy-element" || !el.isConnected || !pos;
    let key = "c";
    if (!centred && pos) {
      const x = pos.x - PAD, y = pos.y - PAD, w = pos.width + PAD * 2, h = pos.height + PAD * 2;
      key = `${x.toFixed(1)},${y.toFixed(1)},${w.toFixed(1)},${h.toFixed(1)},${window.innerWidth},${window.innerHeight}`;
      if (key !== last) {
        const W = window.innerWidth, H = window.innerHeight;
        blur.style.clipPath = `path(evenodd, "M0 0H${W}V${H}H0Z ${roundedRect(x, y, w, h, RADIUS)}")`;
        ring.style.transform = `translate(${x}px, ${y}px)`;
        ring.style.width = `${w}px`;
        ring.style.height = `${h}px`;
        ring.classList.add("is-on");
        ring.classList.toggle("is-clamped", el === proxy);
      }
      if (!d.getState("__transitionCallback")) {
        const r = el!.getBoundingClientRect();
        if (Math.abs(r.x - pos.x) > 0.5 || Math.abs(r.y - pos.y) > 0.5 || Math.abs(r.width - pos.width) > 0.5 || Math.abs(r.height - pos.height) > 0.5) d.refresh();
      }
    } else if (last !== "c") {
      blur.style.clipPath = "";
      ring.classList.remove("is-on");
    }
    last = key;
    raf = requestAnimationFrame(tick);
  };

  async function go(i: number) {
    const my = ++seq;
    const s = steps[i];
    const pop = d.getState("popover") as PopoverDOM | undefined;
    if (pop) { pop.nextButton.disabled = true; pop.previousButton.disabled = true; }
    const moved = !!s.route && s.route !== opts.where();
    if (moved) opts.navigate(s.route!);
    await frame();
    await waitForStep(s, WAIT_MS);
    await frame(); // let the screen lay out once more (fonts, async rows) before measuring
    if (ended || my !== seq) return;
    const found = findTarget(s.target);
    const el = found ? spotlightFor(found, proxy) : null;
    shown[i] = el;
    if (el) bringIntoView(el);
    else if (moved) window.scrollTo({ top: 0 });
    await frame(); // driver.js re-measures on the scroll event; start the move after that
    await frame();
    if (ended || my !== seq) return;
    // Same screen: the window glides to the next element. New screen: it appears there (nothing to glide from).
    d.setConfig({ ...d.getConfig(), animate: animated && !moved });
    if (!d.isActive()) d.drive(i); else d.moveTo(i);
  }

  function end() {
    if (ended) return;
    ended = true;
    seq++;
    cancelAnimationFrame(raf);
    d.destroy();
    blur.remove();
    ring.remove();
    proxy.remove();
    if (opts.where() !== start) opts.navigate(start);
    opts.onEnd?.();
  }

  raf = requestAnimationFrame(tick);
  void go(0);
  return { stop: end };
}

/** "?" button for a header. Opens the tour on click only, never on first load. */
export function TourButton({ steps }: { steps: TourPlan }) {
  const { t: tt } = useT();
  const nav = useNavigate();
  const loc = useLocation();
  const here = useRef("");
  here.current = loc.pathname + loc.search;
  const navRef = useRef(nav);
  navRef.current = nav;
  const run = useRef<TourRun | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => () => run.current?.stop(), []);

  const open = async () => {
    if (run.current) return;
    run.current = { stop: () => {} };
    const list = typeof steps === "function" ? await steps() : steps;
    run.current = startTour(list, {
      navigate: (to) => navRef.current(to),
      where: () => here.current,
      onEnd: () => { run.current = null; setTimeout(() => btn.current?.focus(), 0); },
    });
  };

  return (
    <button ref={btn} type="button" className="btn !px-0 w-11 text-lg no-print" onClick={open}
      aria-label={tt("tour.open")} title={tt("tour.open")} aria-haspopup="dialog" data-testid="tour-open">
      <span aria-hidden>?</span>
    </button>
  );
}

export const PATIENT_TOUR: TourStep[] = [
  { title: "tour.p1.title", body: "tour.p1.body", route: "/", target: "today-write", side: "right" },
  { title: "tour.p2.title", body: "tour.p2.body", route: "/", target: "today-recent", side: "right" },
  { title: "tour.p3.title", body: "tour.p3.body", route: "/timeline", target: "timeline-heat", ready: '[data-testid="heat-cell"]', side: "bottom" },
  { title: "tour.p4.title", body: "tour.p4.body", route: "/share", target: "share-period", side: "right" },
  { title: "tour.p5.title", body: "tour.p5.body", route: "/privacy", target: "privacy-log", side: "right" },
];

/** Clinic steps open the first package in the inbox. With an empty inbox the card says how to get one. */
export function clinicTour(packageId: string | null): TourStep[] {
  if (!packageId) return [{ title: "tour.c0.title", body: "tour.c0.body", route: "/", target: "inbox-empty" }];
  const p = `/p/${packageId}`;
  return [
    { title: "tour.c1.title", body: "tour.c1.body", route: "/", target: "inbox", side: "bottom" },
    { title: "tour.c2.title", body: "tour.c2.body", route: p, target: "pkg-glance", ready: '[data-testid="pkg-overview"]', side: "right" },
    { title: "tour.c3.title", body: "tour.c3.body", route: p, target: "needs-check", side: "right" },
    { title: "tour.c4.title", body: "tour.c4.body", route: p, target: "ddx", ready: '[data-testid="ddx-question"]', side: "right" },
    { title: "tour.c5.title", body: "tour.c5.body", route: `${p}?pane=brief`, target: "brief", side: "left" },
  ];
}

export const CLINIC_TOUR: TourPlan = async () => {
  const rows = await api.inbox().catch(() => []);
  return clinicTour(rows[0]?.package_id ?? null);
};
