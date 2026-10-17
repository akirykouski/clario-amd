import { motion } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useT } from "../i18n";
import { today } from "../lib";

// The week as a seven-compartment organizer. Colours cycle aqua, lilac, coral so neighbouring days never match.
const HUES = ["var(--aqua)", "var(--lilac)", "var(--coral)"];
const LIQUID = { type: "spring", stiffness: 380, damping: 30, mass: 0.9 } as const;

export function iso(d: Date) {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0"), day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
export function parseIso(s: string) { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
export function weekOf(day: string): string[] {
  const d = parseIso(day);
  const monday = new Date(d); monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => { const x = new Date(monday); x.setDate(monday.getDate() + i); return iso(x); });
}
export function shiftWeek(day: string, by: number) { const d = parseIso(day); d.setDate(d.getDate() + 7 * by); return iso(d); }

export function WeekOrganizer({ selected, counts, onSelect }: { selected: string; counts: Record<string, number>; onSelect: (day: string) => void }) {
  const { t, tn, lang } = useT();
  const days = weekOf(selected);
  const now = today();
  const locale = lang === "it" ? "it-IT" : "en-GB";
  const thisWeek = days.includes(now);
  const nextStart = weekOf(shiftWeek(selected, 1))[0];
  const fmt = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" });
  const ranged = fmt as Intl.DateTimeFormat & { formatRange?: (a: Date, b: Date) => string };
  const range = ranged.formatRange ? ranged.formatRange(parseIso(days[0]), parseIso(days[6])) : `${fmt.format(parseIso(days[0]))} - ${fmt.format(parseIso(days[6]))}`;
  return (
    <section aria-label={t("today.week")} className="no-print relative z-10">
      <div className="flex items-center justify-between gap-3 mb-4">
        <p className="text-sm font-semibold text-muted tabular">{thisWeek ? t("today.week") : range}</p>
        <div className="flex items-center gap-1.5">
          <button type="button" className="btn btn-sm !px-0 w-9" onClick={() => onSelect(shiftWeek(selected, -1))} aria-label={t("today.prevWeek")} title={t("today.prevWeek")}><ChevronLeft size={16} aria-hidden /></button>
          <button type="button" className="btn btn-sm !px-0 w-9" disabled={nextStart > now} onClick={() => onSelect(shiftWeek(selected, 1) > now ? now : shiftWeek(selected, 1))} aria-label={t("today.nextWeek")} title={t("today.nextWeek")}><ChevronRight size={16} aria-hidden /></button>
        </div>
      </div>
      <div className="grid grid-cols-7 gap-2.5 sm:gap-3.5">
        {days.map((day, i) => {
          const n = counts[day] ?? 0;
          const d = parseIso(day);
          const future = day > now;
          const isSel = day === selected;
          return (
            <button key={day} type="button" className="compartment" aria-pressed={isSel} data-empty={n === 0}
              disabled={future} style={{ ["--c" as string]: HUES[i % 3], opacity: future ? 0.4 : undefined }}
              onClick={() => onSelect(day)}
              aria-label={`${d.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })}, ${tn("today.dayNotes", n)}`}>
              <span className="text-[13px] font-semibold text-ink/80 capitalize">{d.toLocaleDateString(locale, { weekday: "short" })}</span>
              <span className="text-[30px] leading-none font-semibold tracking-[-0.03em] tabular">{d.getDate()}</span>
              <span className={`mt-1.5 min-w-[26px] px-2 h-[22px] inline-flex items-center justify-center rounded-full text-xs font-semibold tabular ${n ? "bg-white/85 text-ink" : "text-ink/75"}`}>
                {day === now ? t("today.title") : n}
              </span>
              <span className="latch" aria-hidden />
              {isSel && <motion.span layoutId="day-neck" className={`neck ${i === 0 ? "neck-first" : i === 6 ? "neck-last" : ""}`} transition={LIQUID} aria-hidden />}
            </button>
          );
        })}
      </div>
    </section>
  );
}
