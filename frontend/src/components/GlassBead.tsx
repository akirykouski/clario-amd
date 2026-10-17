import { useId } from "react";

/** A candy-glass bead: the timeline's unit. Colour from the organ system, radius from the note count.
 *  Pure SVG (no filters): one radial body, a specular highlight, a caustic and a contact shadow. */
export function GlassBead({ color, count, size = 40 }: { color: string; count: number; size?: number }) {
  const id = useId().replace(/:/g, "");
  const r = count >= 3 ? 17 : count === 2 ? 14.5 : 12;
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden className="block overflow-visible">
      <defs>
        <radialGradient id={`b${id}`} cx="38%" cy="32%" r="72%">
          <stop offset="0%" stopColor={`color-mix(in srgb, ${color} 18%, #fff)`} />
          <stop offset="45%" stopColor={`color-mix(in srgb, ${color} 72%, #fff)`} />
          <stop offset="100%" stopColor={`color-mix(in srgb, ${color} 92%, #0b2a30)`} />
        </radialGradient>
      </defs>
      <ellipse cx="20" cy={20 + r + 2} rx={r * 0.8} ry={r * 0.22} fill={`color-mix(in srgb, ${color} 45%, transparent)`} opacity="0.55" />
      <circle cx="20" cy="20" r={r} fill={`url(#b${id})`} stroke="rgba(255,255,255,0.85)" strokeWidth="0.8" />
      <ellipse cx={20 - r * 0.32} cy={20 - r * 0.42} rx={r * 0.42} ry={r * 0.24} fill="#fff" opacity="0.85" transform={`rotate(-24 ${20 - r * 0.32} ${20 - r * 0.42})`} />
      <ellipse cx={20 + r * 0.28} cy={20 + r * 0.52} rx={r * 0.34} ry={r * 0.12} fill="#fff" opacity="0.35" />
    </svg>
  );
}

/** A glass vial with liquid filled to `level` of 10 (weekly mood). */
export function GlassVial({ level, color = "var(--lilac)", height = 44 }: { level: number | null; color?: string; height?: number }) {
  const id = useId().replace(/:/g, "");
  const h = 34;
  const fill = level === null ? 0 : Math.max(2, (level / 10) * h);
  return (
    <svg width={18} height={height} viewBox="0 0 18 44" aria-hidden className="block">
      <defs>
        <linearGradient id={`v${id}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={`color-mix(in srgb, ${color} 55%, #fff)`} />
          <stop offset="100%" stopColor={`color-mix(in srgb, ${color} 95%, #1a1f3a)`} />
        </linearGradient>
        <clipPath id={`c${id}`}><rect x="3" y="6" width="12" height="36" rx="6" /></clipPath>
      </defs>
      <rect x="2" y="2" width="14" height="5" rx="2" fill="#dfe8eb" stroke="rgba(20,50,58,0.18)" strokeWidth="0.6" />
      <rect x="3" y="6" width="12" height="36" rx="6" fill="rgba(255,255,255,0.55)" stroke="rgba(255,255,255,0.95)" strokeWidth="0.8" />
      <g clipPath={`url(#c${id})`}>
        <rect x="3" y={42 - fill} width="12" height={fill} fill={`url(#v${id})`} />
        <ellipse cx="9" cy={42 - fill} rx="6" ry="1.4" fill="#fff" opacity="0.45" />
      </g>
      <rect x="5" y="9" width="2.2" height="26" rx="1.1" fill="#fff" opacity="0.7" />
    </svg>
  );
}
