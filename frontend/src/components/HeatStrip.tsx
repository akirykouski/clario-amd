import type { HeatModel } from "../lib";
import { fmtDate } from "../lib";

export function cellOpacity(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return 0.25 + 0.75 * (count / max);
}

export function HeatStrip({ heat }: { heat: HeatModel }) {
  return (
    <div className="overflow-x-auto" role="table" aria-label="Confirmed terms by week">
      <div className="inline-block min-w-full">
        <div role="row" className="flex items-end ml-[140px] gap-1 mb-1">
          {heat.weeks.map((w) => <div role="columnheader" key={w} className="w-7 shrink-0 text-[10px] text-muted text-center">{fmtDate(w)}</div>)}
        </div>
        {heat.rows.map((r) => (
          <div role="row" key={r.hpo_id} className="flex items-center gap-1 mb-1">
            <div role="rowheader" className="w-[140px] shrink-0 pr-2 text-sm truncate" title={r.label}>{r.label}</div>
            {r.cells.map((c, i) => (
              <div role="cell" key={i} data-testid="heat-cell" data-count={c} aria-label={`${r.label}, week of ${heat.weeks[i]}: ${c}`}
                className="w-7 h-7 shrink-0 rounded-sm border border-line text-[11px] flex items-center justify-center"
                style={{ background: c > 0 ? `color-mix(in srgb, var(--accent) ${Math.round(cellOpacity(c, heat.max) * 100)}%, transparent)` : "transparent" }}>
                {c > 0 ? c : ""}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
