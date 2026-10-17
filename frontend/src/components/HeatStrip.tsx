import { useState } from "react";
import { motion } from "framer-motion";
import type { HeatModel } from "../lib";
import { SYSTEM_COLOR, fmtDate } from "../lib";
import { termLabel, useT, type Key } from "../i18n";
import { DayStrip, dayFlags } from "./DayStrip";

export function cellOpacity(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return 0.25 + 0.75 * (count / max);
}

export interface HeatPick { hpo_id: string; label: string; week: string; entryIds: string[] }

const COL = "minmax(68px, 1fr)";

/** The bead rack: weeks across, symptoms down, one frosted groove per symptom, grouped by organ system.
 *  A week with notes holds a candy-glass bead (bigger for more notes). Hovering lights the row and the week;
 *  clicking a bead reports the notes behind it. Optional mood row of glass vials underneath. */
export function HeatStrip({ heat, mood, onPick, selected, entryDates = {} }: {
  heat: HeatModel; mood?: (number | null)[]; onPick?: (p: HeatPick) => void; selected?: { hpo_id: string; week: string } | null;
  entryDates?: Record<string, string>;
}) {
  const { t, tn } = useT();
  const [hover, setHover] = useState<{ row: string; col: number } | null>(null);
  const groups = heat.rows.some((r) => r.group !== "other");
  const cols = `minmax(150px, 220px) repeat(${heat.weeks.length}, ${COL})`;
  const selCol = selected ? heat.weeks.indexOf(selected.week) : -1;
  const litCol = hover?.col ?? selCol;
  let prev = "";
  return (
    <div className="overflow-x-auto -mx-2 px-2 pb-2" role="table" aria-label={t("timeline.byWeek")} onMouseLeave={() => setHover(null)}>
      <div className="min-w-[860px] relative">
        <div role="row" className="grid items-end gap-x-1.5 mb-2 sticky top-0" style={{ gridTemplateColumns: cols }}>
          <span aria-hidden />
          {heat.weeks.map((w, i) => (
            <div role="columnheader" key={w}
              className={`text-center text-[11px] leading-tight rounded-xl py-1.5 tabular transition-colors ${litCol === i ? "bg-white/80 text-ink font-semibold shadow-[0_6px_14px_-10px_rgba(20,50,58,0.6)]" : "text-muted"}`}>
              {fmtDate(w, undefined, true)}
            </div>
          ))}
        </div>
        {heat.rows.map((r, ri) => {
          const color = SYSTEM_COLOR[r.group] ?? SYSTEM_COLOR.other;
          const head = groups && r.group !== prev;
          prev = r.group;
          const label = termLabel(r.hpo_id, r.label);
          const rowLit = hover?.row === r.hpo_id || selected?.hpo_id === r.hpo_id;
          return (
            <div key={r.hpo_id}>
              {head && (
                <div className="mt-4 mb-1.5 first:mt-0" data-testid="heat-group">
                  <span className="inline-flex items-center gap-2 text-[13px] font-semibold" style={{ color: `color-mix(in srgb, ${color} 80%, #0b2a30)` }}>
                    <span aria-hidden className="w-2.5 h-2.5 rounded-[3px]" style={{ background: color }} />
                    {t(`sys.${r.group}` as Key)}
                  </span>
                </div>
              )}
              <div role="row" className="grid items-center gap-x-1.5 mb-1.5" style={{ gridTemplateColumns: cols }}>
                <div role="rowheader" title={label}
                  className={`min-w-0 pr-3 text-[14.5px] truncate transition-colors ${rowLit ? "text-ink font-semibold" : "text-ink/80"}`}>{label}</div>
                <div className="relative grid gap-x-1.5" style={{ gridColumn: "2 / -1", gridTemplateColumns: `repeat(${heat.weeks.length}, ${COL})` }}>
                <span aria-hidden className="absolute inset-x-0 top-1/2 h-px transition-colors" style={{ background: rowLit ? `color-mix(in srgb, ${color} 40%, transparent)` : "rgba(20,50,58,0.08)" }} />
                {r.cells.map((c, i) => {
                  const week = heat.weeks[i];
                  const sel = selected?.hpo_id === r.hpo_id && selected?.week === week;
                  const aria = t("heat.cell", { label, week: fmtDate(week, { day: "numeric", month: "long" }), n: c });
                  const noted = [...new Set(r.entryIds[i].map((id) => entryDates[id]).filter(Boolean))].sort();
                  const days = dayFlags(noted);
                  const lit = rowLit || litCol === i;
                  if (c > 0 && onPick) {
                    return (
                      <button type="button" key={i} data-testid="heat-cell" data-count={c} aria-label={aria} aria-pressed={sel}
                        onMouseEnter={() => setHover({ row: r.hpo_id, col: i })} onFocus={() => setHover({ row: r.hpo_id, col: i })}
                        onClick={() => onPick({ hpo_id: r.hpo_id, label, week, entryIds: r.entryIds[i] })}
                        className="group relative h-10 flex items-center justify-center rounded-lg outline-offset-0">
                        <motion.span className="relative block rounded-[7px]" initial={{ scaleX: 0.6 }} animate={{ scaleX: 1, y: sel ? -1 : 0 }}
                          whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }}
                          style={{ boxShadow: sel ? `0 0 0 2px ${color}, 0 8px 16px -10px ${color}` : lit ? "0 8px 16px -12px rgba(20,50,58,0.55)" : "none" }}
                          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1], delay: Math.min(0.4, i * 0.025) }}>
                          <DayStrip days={days} color={color} lit={lit || sel} width={64} height={26} />
                        </motion.span>
                        <span aria-hidden className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-20 whitespace-nowrap rounded-xl px-3 py-1.5 text-xs text-ink opacity-0 translate-y-1 transition-all duration-200 group-hover:opacity-100 group-hover:translate-y-0 group-focus-visible:opacity-100"
                          style={{ background: "rgba(255,255,255,0.92)", border: "1px solid var(--glass-edge)", boxShadow: "0 12px 24px -14px rgba(20,50,58,0.55)" }}>
                          <b className="font-semibold">{label}</b> · {noted.length ? noted.map((d) => fmtDate(d, { weekday: "short", day: "numeric", month: "short" })).join(", ") : fmtDate(week, { day: "numeric", month: "short" })} · {tn("today.dayNotes", c)}
                        </span>
                      </button>
                    );
                  }
                  return (
                    <div role="cell" key={i} data-testid="heat-cell" data-count={c} aria-label={aria}
                      onMouseEnter={() => setHover({ row: r.hpo_id, col: i })} className="relative h-10 flex items-center justify-center">
                      {c > 0 ? <span className="relative"><DayStrip days={days} color={color} lit={false} width={64} height={26} /></span>
                        : <span aria-hidden className="relative w-1 h-1 rounded-full bg-[rgba(20,50,58,0.18)]" />}
                    </div>
                  );
                })}
                </div>
              </div>
            </div>
          );
        })}
        {mood && mood.some((m) => m !== null) && (
          <div role="row" className="grid items-end gap-x-1.5 mt-5 pt-4 border-t" style={{ gridTemplateColumns: cols, borderColor: "var(--glass-rim)" }} data-testid="heat-mood">
            <div role="rowheader" className="pr-3 text-[14.5px] text-ink/80">{t("timeline.mood")}</div>
            {mood.map((m, i) => (
              <div role="cell" key={i} className={`flex justify-center rounded-xl py-1 transition-colors ${litCol === i ? "bg-white/60" : ""}`} title={m === null ? "" : `${m}/10`}
                onMouseEnter={() => setHover({ row: "mood", col: i })}>
                {m !== null ? (
                  <span className="flex flex-col items-center gap-1">
                    <span className="text-[13px] font-semibold tabular text-ink">{m.toFixed(1)}</span>
                    <span aria-hidden className="block w-[56px] h-[5px] rounded-full bg-[rgba(20,50,58,0.08)] overflow-hidden"><span className="block h-full rounded-full bg-lilac" style={{ width: `${m * 10}%` }} /></span>
                  </span>
                ) : <span className="h-9" />}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
