import { useState } from "react";
import type { HeatModel, HeatRow } from "../lib";
import { SYSTEM_COLOR, fmtDate } from "../lib";
import { termLabel, useT, type Key } from "../i18n";

export function cellOpacity(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return 0.25 + 0.75 * (count / max);
}

export interface HeatPick { hpo_id: string; label: string; week: string; entryIds: string[] }

const tint = (c: string, p: number) => `color-mix(in srgb, ${c} ${Math.round(p)}%, transparent)`;
const short = (d: string) => fmtDate(d, { day: "numeric", month: "short" });

/** Clinical matrix: symptoms down, weeks across, a tinted cell per week with notes (darker for more notes),
 *  plus weeks present, first and last seen. Grouped by organ system or sorted by frequency. Optional mood row. */
export function HeatStrip({ heat, mood, onPick, selected }: {
  heat: HeatModel; mood?: (number | null)[]; onPick?: (p: HeatPick) => void; selected?: { hpo_id: string; week: string } | null;
  entryDates?: Record<string, string>;
}) {
  const { t } = useT();
  const [sort, setSort] = useState<"system" | "freq">("system");
  const n = heat.weeks.length;
  const stats = heat.rows.map((r) => {
    const present = r.cells.map((v, i) => (v > 0 ? i : -1)).filter((i) => i >= 0);
    return { r, weeks: present.length, first: present.length ? present[0] : -1, last: present.length ? present[present.length - 1] : -1 };
  });
  const rows = sort === "freq" ? [...stats].sort((a, b) => b.weeks - a.weeks || a.first - b.first) : stats;
  const groups = sort === "system" && heat.rows.some((r) => r.group !== "other");
  const span = n + 4;
  let prev = "";

  const cell = (r: HeatRow, v: number, i: number) => {
    const color = SYSTEM_COLOR[r.group] ?? SYSTEM_COLOR.other;
    const label = termLabel(r.hpo_id, r.label);
    const week = heat.weeks[i];
    const sel = selected?.hpo_id === r.hpo_id && selected?.week === week;
    const aria = t("heat.cell", { label, week: fmtDate(week, { day: "numeric", month: "long" }), n: v });
    const style = {
      background: v ? tint(color, 26 + 50 * (v / Math.max(1, heat.max))) : "rgba(20,50,58,0.045)",
      color: v ? `color-mix(in srgb, ${color} 78%, #0b2a30)` : "transparent",
      boxShadow: sel ? `0 0 0 2px ${color}` : undefined,
    };
    const cls = "w-full h-7 rounded-md text-[11px] font-semibold tabular flex items-center justify-center";
    return v > 0 && onPick ? (
      <button type="button" data-testid="heat-cell" data-count={v} aria-label={aria} aria-pressed={sel} title={aria}
        onClick={() => onPick({ hpo_id: r.hpo_id, label, week, entryIds: r.entryIds[i] })}
        className={`${cls} transition-transform hover:scale-[1.06] hover:shadow-[0_6px_12px_-8px_rgba(20,50,58,0.6)]`} style={style}>{v}</button>
    ) : (
      <div role="cell" data-testid="heat-cell" data-count={v} aria-label={aria} className={cls} style={style}>{v || ""}</div>
    );
  };

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex justify-end gap-1.5 mb-3" role="group" aria-label={t("tl.sortAria")}>
        {(["system", "freq"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={sort === s} onClick={() => setSort(s)} className={`chip !py-1 ${sort === s ? "chip-filled" : ""}`}>{t(`tl.sort.${s}` as Key)}</button>
        ))}
      </div>
      <table className="w-full min-w-[820px] border-separate" style={{ borderSpacing: "3px 3px" }} aria-label={t("timeline.byWeek")}>
        <thead>
          <tr className="text-[11px] text-muted">
            <th className="text-left font-semibold pr-3">{t("tl.symptom")}</th>
            {heat.weeks.map((w) => <th key={w} scope="col" className="font-medium tabular min-w-[44px]">{short(w)}</th>)}
            <th className="font-semibold pl-3 text-right">{t("tl.weeksCol")}</th>
            <th className="font-semibold pl-3 text-right">{t("tl.first")}</th>
            <th className="font-semibold pl-3 text-right">{t("tl.last")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.flatMap(({ r, weeks, first, last }) => {
            const color = SYSTEM_COLOR[r.group] ?? SYSTEM_COLOR.other;
            const head = groups && r.group !== prev;
            prev = r.group;
            const label = termLabel(r.hpo_id, r.label);
            const out = [];
            if (head) out.push(
              <tr key={`g-${r.group}`}>
                <td colSpan={span} className="pt-3 pb-0.5 text-[12.5px] font-semibold" style={{ color: `color-mix(in srgb, ${color} 80%, #0b2a30)` }} data-testid="heat-group">
                  {t(`sys.${r.group}` as Key)}
                </td>
              </tr>,
            );
            out.push(
              <tr key={r.hpo_id} className="text-[13.5px]">
                <th scope="row" className="pr-3 font-normal text-left truncate max-w-[240px]" title={label}>
                  <span aria-hidden className="inline-block w-2 h-2 rounded-[2px] mr-2 align-middle" style={{ background: color }} />{label}
                </th>
                {r.cells.map((v, i) => <td key={i} className="p-0">{cell(r, v, i)}</td>)}
                <td className="pl-3 text-right tabular font-semibold">{weeks}/{n}</td>
                <td className="pl-3 text-right tabular text-muted whitespace-nowrap">{first >= 0 ? short(heat.weeks[first]) : ""}</td>
                <td className="pl-3 text-right tabular text-muted whitespace-nowrap">{last >= 0 ? short(heat.weeks[last]) : ""}</td>
              </tr>,
            );
            return out;
          })}
          {mood && mood.some((m) => m !== null) && (
            <tr data-testid="heat-mood" className="text-[13px]">
              <th scope="row" className="pr-3 pt-3 font-normal text-left text-ink/80">{t("timeline.mood")}</th>
              {mood.map((m, i) => (
                <td key={i} className="pt-3 text-center tabular font-semibold" title={m === null ? "" : `${m}/10`}>
                  {m !== null ? m.toFixed(1) : ""}
                </td>
              ))}
              <td colSpan={3} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
