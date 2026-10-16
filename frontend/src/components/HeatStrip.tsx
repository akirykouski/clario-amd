import type { HeatModel } from "../lib";
import { SYSTEM_COLOR, fmtDate } from "../lib";
import { termLabel, useT, type Key } from "../i18n";

export function cellOpacity(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return 0.25 + 0.75 * (count / max);
}

export interface HeatPick { hpo_id: string; label: string; week: string; entryIds: string[] }

/** Weeks across, symptoms down, grouped and colored by organ system. Optional mood row underneath.
 * Clicking a filled cell reports the notes behind it. */
export function HeatStrip({ heat, mood, onPick, selected }: {
  heat: HeatModel; mood?: (number | null)[]; onPick?: (p: HeatPick) => void; selected?: { hpo_id: string; week: string } | null;
}) {
  const { t } = useT();
  const groups = heat.rows.some((r) => r.group !== "other");
  let prev = "";
  return (
    <div className="overflow-x-auto" role="table" aria-label={t("timeline.byWeek")}>
      <div className="inline-block min-w-full">
        <div role="row" className="flex items-end ml-[150px] gap-1 mb-1">
          {heat.weeks.map((w) => <div role="columnheader" key={w} className="w-7 shrink-0 text-[10px] text-muted text-center leading-tight">{fmtDate(w, undefined, true)}</div>)}
        </div>
        {heat.rows.map((r) => {
          const color = SYSTEM_COLOR[r.group] ?? SYSTEM_COLOR.other;
          const head = groups && r.group !== prev;
          prev = r.group;
          const label = termLabel(r.hpo_id, r.label);
          return (
            <div key={r.hpo_id}>
              {head && (
                <div className="text-[11px] font-bold uppercase tracking-wide mt-2 mb-0.5" style={{ color }} data-testid="heat-group">
                  {t(`sys.${r.group}` as Key)}
                </div>
              )}
              <div role="row" className="flex items-center gap-1 mb-1">
                <div role="rowheader" className="w-[150px] shrink-0 pr-2 text-sm truncate flex items-center gap-1.5" title={label}>
                  <span aria-hidden className="inline-block w-1.5 h-4 rounded-sm shrink-0" style={{ background: color }} />
                  <span className="truncate">{label}</span>
                </div>
                {r.cells.map((c, i) => {
                  const sel = selected?.hpo_id === r.hpo_id && selected?.week === heat.weeks[i];
                  const op = cellOpacity(c, heat.max);
                  const style = {
                    background: c > 0 ? `color-mix(in srgb, ${color} ${Math.round(op * 100)}%, transparent)` : "transparent",
                    color: op > 0.55 ? "#fff" : "var(--ink)",
                    outline: sel ? `2px solid ${color}` : undefined, outlineOffset: 1,
                  };
                  const aria = t("heat.cell", { label, week: fmtDate(heat.weeks[i], { day: "numeric", month: "long" }), n: c });
                  return c > 0 && onPick ? (
                    <button type="button" key={i} data-testid="heat-cell" data-count={c} aria-label={aria} aria-pressed={sel}
                      onClick={() => onPick({ hpo_id: r.hpo_id, label, week: heat.weeks[i], entryIds: r.entryIds[i] })}
                      className="w-7 h-7 shrink-0 rounded-sm border border-line text-[11px] font-bold flex items-center justify-center hover:scale-110 transition-transform"
                      style={style}>{c}</button>
                  ) : (
                    <div role="cell" key={i} data-testid="heat-cell" data-count={c} aria-label={aria}
                      className="w-7 h-7 shrink-0 rounded-sm border border-line text-[11px] font-bold flex items-center justify-center" style={style}>
                      {c > 0 ? c : ""}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        {mood && mood.some((m) => m !== null) && (
          <div role="row" className="flex items-end gap-1 mt-3" data-testid="heat-mood">
            <div role="rowheader" className="w-[150px] shrink-0 pr-2 text-sm text-muted">{t("timeline.mood")}</div>
            {mood.map((m, i) => (
              <div role="cell" key={i} className="w-7 h-8 shrink-0 flex items-end justify-center" title={m === null ? "" : `${m}/10`}>
                {m !== null && <div className="w-3 rounded-t-sm" style={{ height: `${Math.max(8, m * 10)}%`, background: "var(--muted)", opacity: 0.45 }} />}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
