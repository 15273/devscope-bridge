/**
 * Logomark — the DevScope mark: a scope/radar reticle.
 *
 * Monochrome (uses currentColor) so it works on light and dark surfaces and at
 * any size. Set color via `text-*`, size via `className` width/height.
 */
export function Logomark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 1.5V5" />
      <path d="M12 19v3.5" />
      <path d="M1.5 12H5" />
      <path d="M19 12h3.5" />
      <circle cx="12" cy="12" r="1.25" fill="currentColor" stroke="none" />
    </svg>
  );
}
