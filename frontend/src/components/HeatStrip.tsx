import { useState } from "react";
import { motion } from "framer-motion";
import type { HeatModel } from "../lib";
import { SYSTEM_COLOR, fmtDate } from "../lib";
import { termLabel, useT, type Key } from "../i18n";
import { GlassBead, GlassVial } from "./GlassBead";

export function cellOpacity(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return 0.25 + 0.75 * (count / max);
}

export interface HeatPick { hpo_id: string; label: string; week: string; entryIds: string[] }

const COL = "minmax(40px, 1fr)";

/** The bead rack: weeks across, symptoms down, one frosted groove per symptom, grouped by organ system.
 *  A week with notes holds a candy-glass bead (bigger for more notes). Hovering lights the row and the week;
 *  clicking a bead reports the notes behind it. Optional mood row of glass vials underneath. */
export function HeatStrip({ heat, mood, onPick, selected }: {
  heat: HeatModel; mood?: (number | null)[]; onPick?: (p: HeatPick) => void; selected?: { hpo_id: string; week: string } | null;
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
      <div className="min-w-[640px] relative">
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
                  <span className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[13px] font-semibold"
                    style={{ color: `color-mix(in srgb, ${color} 85%, #0b2a30)`, background: `color-mix(in srgb, ${color} 12%, rgba(255,255,255,0.7))`, border: `1px solid color-mix(in srgb, ${color} 30%, #fff)` }}>
                    <span aria-hidden className="w-2.5 h-2.5 rounded-full" style={{ background: color, boxShadow: `0 2px 4px -1px ${color}` }} />
                    {t(`sys.${r.group}` as Key)}
                  </span>
                </div>
              )}
              <div role="row" className="grid items-center gap-x-1.5 mb-1.5" style={{ gridTemplateColumns: cols }}>
                <div role="rowheader" title={label}
                  className={`min-w-0 pr-3 text-[14.5px] truncate transition-colors ${rowLit ? "text-ink font-semibold" : "text-ink/80"}`}>{label}</div>
                <div className="relative grid gap-x-1.5" style={{ gridColumn: "2 / -1", gridTemplateColumns: `repeat(${heat.weeks.length}, ${COL})` }}>
                <span aria-hidden className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-[34px] rounded-full transition-colors"
                  style={{ background: rowLit ? "rgba(255,255,255,0.78)" : "rgba(255,255,255,0.42)", boxShadow: "0 2px 6px -2px rgba(20,50,58,0.2) inset, 0 1px 0 0 rgba(255,255,255,0.95)" }} />
                {litCol >= 0 && <span aria-hidden className="absolute top-0 bottom-0 rounded-full bg-white/50 transition-[left] duration-200"
                  style={{ left: `calc(${litCol} * (100% + 6px) / ${heat.weeks.length})`, width: `calc((100% - ${(heat.weeks.length - 1) * 6}px) / ${heat.weeks.length})` }} />}
                {r.cells.map((c, i) => {
                  const week = heat.weeks[i];
                  const sel = selected?.hpo_id === r.hpo_id && selected?.week === week;
                  const aria = t("heat.cell", { label, week: fmtDate(week, { day: "numeric", month: "long" }), n: c });
                  if (c > 0 && onPick) {
                    return (
                      <button type="button" key={i} data-testid="heat-cell" data-count={c} aria-label={aria} aria-pressed={sel}
                        onMouseEnter={() => setHover({ row: r.hpo_id, col: i })} onFocus={() => setHover({ row: r.hpo_id, col: i })}
                        onClick={() => onPick({ hpo_id: r.hpo_id, label, week, entryIds: r.entryIds[i] })}
                        className="group relative h-12 flex items-center justify-center rounded-full outline-offset-0">
                        <motion.span className="relative block" initial={{ scale: 0.72 }} animate={{ scale: sel ? 1.18 : 1 }}
                          whileHover={{ scale: 1.22, y: -2 }} whileTap={{ scale: 0.92 }}
                          transition={{ type: "spring", stiffness: 420, damping: 26, delay: sel ? 0 : Math.min(0.5, (i * 0.03) + (ri * 0.01)) }}>
                          <GlassBead color={color} count={c} size={46} />
                          {c > 1 && <span className="absolute inset-0 flex items-center justify-center text-[11px] font-bold text-white tabular" style={{ textShadow: "0 1px 2px rgba(0,0,0,0.35)" }}>{c}</span>}
                        </motion.span>
                        {sel && <span aria-hidden className="absolute inset-1 rounded-full" style={{ boxShadow: `0 0 0 2px ${color}` }} />}
                        <span aria-hidden className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-20 whitespace-nowrap rounded-xl px-3 py-1.5 text-xs text-ink opacity-0 translate-y-1 transition-all duration-200 group-hover:opacity-100 group-hover:translate-y-0 group-focus-visible:opacity-100"
                          style={{ background: "rgba(255,255,255,0.92)", border: "1px solid var(--glass-edge)", boxShadow: "0 12px 24px -14px rgba(20,50,58,0.55)" }}>
                          <b className="font-semibold">{label}</b> · {fmtDate(week, { day: "numeric", month: "short" })} · {tn("today.dayNotes", c)}
                        </span>
                      </button>
                    );
                  }
                  return (
                    <div role="cell" key={i} data-testid="heat-cell" data-count={c} aria-label={aria}
                      onMouseEnter={() => setHover({ row: r.hpo_id, col: i })} className="relative h-12 flex items-center justify-center">
                      {c > 0 && <span className="relative"><GlassBead color={color} count={c} size={46} /></span>}
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
                {m !== null ? <GlassVial level={m} /> : <span className="h-11" />}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
