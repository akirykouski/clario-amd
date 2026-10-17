/** One week as a seven-day strip (Monday first): the days a symptom was noted are filled in its organ-system colour.
 *  A miniature of the week organizer, read like a clinical log. Flat, precise, no ornament. */
export function DayStrip({ days, color, lit = false, width = 56, height = 22 }: {
  days: boolean[]; color: string; lit?: boolean; width?: number; height?: number;
}) {
  const gap = 2, pad = 3;
  const w = (width - pad * 2 - gap * 6) / 7;
  const any = days.some(Boolean);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="block">
      <rect x="0.5" y="0.5" width={width - 1} height={height - 1} rx="6"
        fill={lit ? "rgba(255,255,255,0.95)" : any ? "rgba(255,255,255,0.78)" : "rgba(255,255,255,0.35)"}
        stroke={any ? `color-mix(in srgb, ${color} 35%, rgba(20,50,58,0.12))` : "rgba(20,50,58,0.08)"} />
      {days.map((on, i) => (
        <rect key={i} x={pad + i * (w + gap)} y={pad} width={w} height={height - pad * 2} rx="1.6"
          fill={on ? color : "rgba(20,50,58,0.07)"} opacity={on ? 1 : 1} />
      ))}
    </svg>
  );
}

/** Day index (Monday 0) of each date inside its week. */
export function dayFlags(dates: string[]): boolean[] {
  const flags = Array(7).fill(false) as boolean[];
  for (const d of dates) {
    const x = new Date(`${d}T00:00:00Z`);
    flags[(x.getUTCDay() + 6) % 7] = true;
  }
  return flags;
}
