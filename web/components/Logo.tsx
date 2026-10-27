// The Goliatt brand: the "g" mark (app icon) and the "goliatt" wordmark, drawn as SVG so they
// stay sharp at any size.

export const BRAND_BLUE = "#0468BF";

/** The "g" with its smile and tick, white on a blue rounded square. */
export function GoliattMark({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" aria-hidden="true" className={`shrink-0 ${className}`}>
      <rect width="100" height="100" rx="22" fill={BRAND_BLUE} />
      <circle cx="47" cy="44" r="14.5" fill="none" stroke="#fff" strokeWidth="9" />
      <path d="M62 20h9v10z" fill="#fff" />
      <path d="M29 62a18 18 0 0 0 36 0a18 8 0 0 1-36 0z" fill="#fff" />
    </svg>
  );
}

/** The "goliatt" wordmark, drawn with the current text color. */
export function GoliattWordmark({ className = "h-8" }: { className?: string }) {
  return (
    <svg viewBox="0 6 120 48" role="img" aria-label="goliatt" className={`shrink-0 ${className}`}>
      <g fill="none" stroke="currentColor" strokeWidth="5">
        <circle cx="11" cy="30" r="7.5" />
        <circle cx="34" cy="30" r="7.5" />
        <path d="M49 11v29M58 22v18" />
        <circle cx="74" cy="30" r="7.5" />
        <path d="M84 21v19M96 12v28M91 22h10M111 12v28M106 22h10" />
      </g>
      <circle cx="58" cy="14.5" r="3" fill="currentColor" />
      <path d="M2 43a9 9 0 0 0 18 0a9 4 0 0 1-18 0z" fill="currentColor" />
    </svg>
  );
}
