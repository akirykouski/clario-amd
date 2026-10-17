import { CircleHelp } from "lucide-react";
import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { driver, type Driver, type DriveStep, type PopoverDOM, type State } from "driver.js";
import "driver.js/dist/driver.css";
import "./tour.css";
import { api } from "../api";
import { getLang, setLang, t, useT, type Key } from "../i18n";
import { daysAgo, today } from "../lib";

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
  /**
   * Last step only: its button gets this label and runs `run` when clicked (the patient tour hands over to the clinic).
   * `run` resolves to null when done, which ends the tour, or to an error to show on the card.
   */
  action?: { label: Key; run: () => Promise<string | null> };
}

/** Fired after the tour loads the demo diary, so screens that already fetched their data fetch it again. */
export const TOUR_DATA_EVENT = "clario:tour-data";

/** Id prefix of the demo persona's diary entries (backend `demo.DEMO_ENTRY_PREFIX`). */
const DEMO_ENTRY_PREFIX = "e_demo_";

/** A tour is a fixed list or one built when it opens (the clinic needs its inbox first). `pkg`: from a `?pkg=` link. */
export type TourPlan = TourStep[] | ((opts: { pkg?: string }) => Promise<TourStep[]>);

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

/** The card is docked: bottom right on wide screens, a full-width bottom sheet on phones (see tour.css). */
const DOCK_W = 380;
const DOCK_GAP = 24;
const PHONE = 640;
const isPhone = () => window.innerWidth < PHONE;
const estimateCard = () => (isPhone() ? 300 : 250);

/** The part of the screen a target can use: below the sticky header, above the tab bar and clear of the card. */
function freeArea(r: DOMRect, cardH: number) {
  const { top, bottom } = insets();
  const floor = window.innerHeight - bottom;
  if (isPhone()) return { top, end: Math.min(floor, window.innerHeight - cardH - 12) };
  const cardLeft = window.innerWidth - DOCK_GAP - Math.min(DOCK_W, window.innerWidth - DOCK_GAP * 2);
  const besideCard = r.right + PAD + 16 <= cardLeft;
  return { top, end: besideCard ? floor : Math.min(floor, window.innerHeight - DOCK_GAP - cardH - 16) };
}

/** Scroll so the element sits in the middle of its free area, or at its top when taller, before driver.js looks. */
function bringIntoView(el: HTMLElement, cardH: number) {
  const r = el.getBoundingClientRect();
  const { top, end } = freeArea(r, cardH);
  const free = end - top;
  const h = r.height + PAD * 2;
  const want = h <= free - 16 ? top + (free - h) / 2 + PAD : top + 12 + PAD;
  if (Math.abs(r.top - want) > 2) window.scrollTo({ top: Math.max(0, window.scrollY + r.top - want), behavior: "instant" as ScrollBehavior });
}

function roundedRect(x: number, y: number, w: number, h: number, r: number) {
  const k = Math.max(0, Math.min(r, w / 2, h / 2));
  return `M${x + k} ${y}H${x + w - k}A${k} ${k} 0 0 1 ${x + w} ${y + k}V${y + h - k}A${k} ${k} 0 0 1 ${x + w - k} ${y + h}`
    + `H${x + k}A${k} ${k} 0 0 1 ${x} ${y + h - k}V${y + k}A${k} ${k} 0 0 1 ${x + k} ${y}Z`;
}

/**
 * The element driver.js should spotlight. A target taller than its free area gets a stand-in box over its top
 * part, so the window shows the start of it crisp and the docked card never covers it.
 */
function spotlightFor(el: HTMLElement, proxy: HTMLElement, cardH: number): HTMLElement {
  const r = el.getBoundingClientRect();
  const { top, end } = freeArea(r, cardH);
  const max = Math.max(120, end - top - 24 - PAD * 2);
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

  let cardH = 0;      // tallest card over all steps, measured once: the docked card keeps one size
  let shownIndex = -1; // step the dots move from
  const dotClass = (n: number, i: number) => `clario-tour-dot${n < i ? " is-done" : n === i ? " is-active" : ""}`;

  /** Height of the card with each step's text in it; the largest becomes the card's fixed height. */
  const measure = (p: PopoverDOM) => {
    const keep = [p.title.innerHTML, p.description.innerHTML];
    let max = 0;
    for (const s of steps) {
      p.title.innerHTML = t(s.title);
      p.description.innerHTML = t(s.body);
      max = Math.max(max, p.wrapper.getBoundingClientRect().height);
    }
    [p.title.innerHTML, p.description.innerHTML] = keep;
    return Math.ceil(max);
  };

  const decorate = (p: PopoverDOM, { state }: { state: State }) => {
    const i = state.activeIndex ?? 0;
    const from = shownIndex < 0 ? i : shownIndex;
    p.wrapper.dataset.testid = "tour";
    p.wrapper.setAttribute("aria-modal", "true");
    if (shownIndex < 0) p.wrapper.classList.add("is-first");
    p.wrapper.classList.toggle("is-centred", !steps[i]?.target);
    const top = document.createElement("div");
    top.className = "clario-tour-top";
    const dots: HTMLElement[] = [];
    if (total > 1) {
      const row = document.createElement("div");
      row.className = "clario-tour-dots";
      row.setAttribute("aria-hidden", "true");
      for (let n = 0; n < total; n++) {
        const dot = document.createElement("span");
        dot.className = dotClass(n, from);
        dots.push(dot);
        row.append(dot);
      }
      top.append(row);
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
    if (!cardH) cardH = measure(p);
    if (cardH) p.wrapper.style.minHeight = `${cardH}px`;
    if (from !== i) requestAnimationFrame(() => dots.forEach((dot, n) => { dot.className = dotClass(n, i); }));
    shownIndex = i;
  };

  const d: Driver = driver({
    steps: steps.map((s, i): DriveStep => ({
      element: (() => shown[i] ?? findTarget(s.target)) as () => Element,
      popover: {
        title: t(s.title), description: t(s.body),
        showButtons: i === 0 ? ["next", "close"] : ["next", "previous", "close"],
        ...(s.action ? { doneBtnText: t(s.action.label) } : {}),
      },
    })),
    animate: animated,
    duration: 300,
    smoothScroll: false,
    allowClose: true,
    overlayClickBehavior: "close",
    stagePadding: PAD,
    stageRadius: RADIUS,
    disableActiveInteraction: true,
    showProgress: false,
    popoverClass: "clario-tour",
    nextBtnText: t("tour.next"),
    prevBtnText: t("tour.back"),
    doneBtnText: t("tour.done"),
    onPopoverRender: decorate,
    // focus for Enter and screen readers, without the keyboard ring when the tour opened from a click or a link
    onHighlighted: () => { d.getState("popover")?.nextButton?.focus({ focusVisible: false } as FocusOptions); },
    onNextClick: () => {
      const i = d.getActiveIndex() ?? 0;
      if (i < total - 1) { void go(i + 1); return; }
      const action = steps[i].action;
      if (!action) { end(); return; }
      const pop = d.getState("popover") as PopoverDOM | undefined;
      if (pop) { pop.nextButton.disabled = true; pop.previousButton.disabled = true; }
      // started inside the click, so a new tab it opens is not blocked
      void action.run().then((err) => {
        if (!err) { end(); return; }
        if (pop) {
          pop.description.textContent = err;
          pop.description.setAttribute("role", "alert");
          pop.nextButton.disabled = false; pop.previousButton.disabled = false;
        }
      });
    },
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
    } else {
      if (last !== "c") {
        blur.style.clipPath = "";
        ring.classList.remove("is-on");
      }
      // driver.js cuts a padded hole around its zero-size stand-in, which shows as a dot mid-screen: fill it
      const hole = document.querySelector<SVGPathElement>(".driver-overlay path");
      const full = `M0 0H${window.innerWidth}V${window.innerHeight}H0Z`;
      if (hole && hole.getAttribute("d") !== full) hole.setAttribute("d", full);
    }
    last = key;
    raf = requestAnimationFrame(tick);
  };

  async function go(i: number) {
    const my = ++seq;
    const s = steps[i];
    const pop = d.getState("popover") as PopoverDOM | undefined;
    if (pop) { pop.nextButton.disabled = true; pop.previousButton.disabled = true; pop.wrapper.classList.add("is-leaving"); }
    const moved = !!s.route && s.route !== opts.where();
    if (moved) opts.navigate(s.route!);
    await frame();
    await waitForStep(s, WAIT_MS);
    await frame(); // let the screen lay out once more (fonts, async rows) before measuring
    if (ended || my !== seq) return;
    const found = findTarget(s.target);
    const room = cardH || estimateCard();
    const el = found ? spotlightFor(found, proxy, room) : null;
    shown[i] = el;
    if (el) bringIntoView(el, room);
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

  // `?tour=1` (the patient tour's hand-over link, with `pkg` = the package it sent) opens the tour once the screen
  // loads, then leaves the address clean
  useEffect(() => {
    const q = new URLSearchParams(loc.search);
    if (q.get("tour") !== "1") return;
    const pkg = q.get("pkg") ?? undefined;
    const lang = q.get("lang");
    if (lang === "en" || lang === "it") setLang(lang);
    q.delete("tour"); q.delete("pkg"); q.delete("lang");
    const rest = q.toString();
    here.current = loc.pathname + (rest ? `?${rest}` : "");
    nav(here.current, { replace: true });
    void open(pkg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = async (pkg?: string) => {
    if (run.current) return;
    run.current = { stop: () => {} };
    const list = typeof steps === "function" ? await steps({ pkg }) : steps;
    run.current = startTour(list, {
      navigate: (to) => navRef.current(to),
      where: () => here.current,
      onEnd: () => { run.current = null; setTimeout(() => btn.current?.focus(), 0); },
    });
  };

  return (
    <button ref={btn} type="button" className="btn !px-0 w-11 text-lg no-print" onClick={() => void open()}
      aria-label={tt("tour.open")} title={tt("tour.open")} aria-haspopup="dialog" data-testid="tour-open">
      <CircleHelp size={18} aria-hidden />
    </button>
  );
}

/**
 * Patient steps. `empty`: no notes yet, so steps 2 and 3 point at where terms and weeks will appear. `clinic`: the
 * clinic this server shares with; a last step hands over to its console, where the clinic tour starts. `demo`: the
 * diary holds only the synthetic demo patient, so the hand-over shares it first and the clinic opens that package.
 * Anything else is never sent from the tour: the person shares it on the Share screen.
 */
export function patientTour({ empty, clinic, demo }: { empty: boolean; clinic?: string | null; demo?: boolean }): TourStep[] {
  const steps: TourStep[] = [
    { title: "tour.p1.title", body: "tour.p1.body", route: "/", target: "today-write" },
    empty
      ? { title: "tour.p2.title", body: "tour.p2.bodyEmpty", route: "/", target: "today-understood" }
      : { title: "tour.p2.title", body: "tour.p2.body", route: "/", target: "today-recent" },
    { title: "tour.p3.title", body: empty ? "tour.p3.bodyEmpty" : "tour.p3.body", route: "/timeline", target: "timeline-heat",
      ready: empty ? undefined : '[data-testid="heat-cell"]' },
    { title: "tour.pd.title", body: "tour.pd.body", route: "/patterns", target: "patterns" },
    { title: "tour.pl.title", body: "tour.pl.body", route: "/labs", target: "labs" },
    { title: "tour.p4.title", body: "tour.p4.body", route: "/share", target: "share-period" },
    { title: "tour.p5.title", body: "tour.p5.body", route: "/privacy", target: "privacy-log" },
  ];
  const base = clinic?.replace(/\/+$/, "");
  if (!base) return steps;
  steps.push({
    title: "tour.p6.title", body: demo ? "tour.p6.bodyDemo" : "tour.p6.body", route: "/share",
    action: {
      label: "tour.toClinic",
      run: async () => {
        const tab = window.open("", "_blank"); // opened inside the click; the address is set once the package is sent
        let to = `${base}/?tour=1&lang=${getLang()}`; // the clinic is another origin: carry the language over
        if (demo) {
          try {
            const sent = await api.share({ clinic_url: base, since: daysAgo(84), until: today(), include_patterns: true,
                                           expires_hours: 72, include_profile: true });
            to += `&pkg=${encodeURIComponent(sent.package_id)}`;
          } catch (x) {
            tab?.close();
            console.error("tour hand-over: share failed", x);
            return t("tour.shareFailed");
          }
        }
        if (tab) tab.location.href = to; else window.location.assign(to);
        return null;
      },
    },
  });
  return steps;
}

/** With an empty diary on the demo server the tour loads the synthetic demo patient first, so every step has content. */
export const PATIENT_TOUR: TourPlan = async () => {
  const [health, entries] = await Promise.all([api.health().catch(() => null), api.entries().catch(() => [])]);
  const onDemo = !!health?.demo_instance;
  let empty = entries.length === 0;
  // only the persona's own notes (ids from POST /api/demo) count as the demo diary; a note someone typed does not
  let demoOnly = !empty && entries.every((e) => e.id.startsWith(DEMO_ENTRY_PREFIX));
  if (empty && onDemo) {
    try {
      await api.demo(getLang() === "it" ? "giulia_it" : "giulia");
      empty = false;
      demoOnly = true;
      window.dispatchEvent(new Event(TOUR_DATA_EVENT));
    } catch { /* the empty-diary steps still explain each screen */ }
  }
  return patientTour({ empty, clinic: health?.clinic_url, demo: onDemo && demoOnly });
};

/** Clinic steps open the first package in the inbox. With an empty inbox the card says how to get one. */
export function clinicTour(packageId: string | null): TourStep[] {
  if (!packageId) return [{ title: "tour.c0.title", body: "tour.c0.body", route: "/", target: "inbox-empty" }];
  const p = `/p/${packageId}`;
  return [
    { title: "tour.c1.title", body: "tour.c1.body", route: "/", target: "inbox" },
    { title: "tour.c2.title", body: "tour.c2.body", route: p, target: "pkg-glance", ready: '[data-testid="pkg-overview"]' },
    { title: "tour.c3.title", body: "tour.c3.body", route: p, target: "needs-check" },
    { title: "tour.c4.title", body: "tour.c4.body", route: p, target: "ddx", ready: '[data-testid="ddx-question"]' },
    { title: "tour.c5.title", body: "tour.c5.body", route: `${p}?pane=brief`, target: "brief" },
  ];
}

/** Opens the package a hand-over link names when it is in the inbox, else the newest one. */
export const CLINIC_TOUR: TourPlan = async ({ pkg } = {}) => {
  const rows = await api.inbox().catch(() => []);
  const pick = rows.find((r) => r.package_id === pkg) ?? rows[0];
  return clinicTour(pick?.package_id ?? null);
};
