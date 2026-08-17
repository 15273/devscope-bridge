/**
 * ClaudeSpark — the small 8-petal asterisk that breathes while Claude is
 * working, echoing the spinner in the official Claude Code terminal. Pure
 * SVG (no icon-font glyph renders this shape consistently across platforms),
 * colored via the `claude` brand token and driven by the `spark-breathe`
 * keyframe (tailwind.config.js) — scale + opacity only, so the global
 * prefers-reduced-motion guard in tailwind.css freezes it on one frame.
 */
const PETAL_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315];

export function ClaudeSpark({ size = 14, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={`inline-block flex-shrink-0 origin-center animate-spark-breathe text-claude ${className}`}
      aria-hidden
    >
      {PETAL_ANGLES.map((angle) => (
        <rect
          key={angle}
          x="11.1"
          y="1.5"
          width="1.8"
          height="7.5"
          rx="0.9"
          fill="currentColor"
          transform={`rotate(${angle} 12 12)`}
        />
      ))}
    </svg>
  );
}
