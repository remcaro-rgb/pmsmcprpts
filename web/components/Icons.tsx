// Small line icons (24-unit grid, drawn with the current text color).

const PATHS = {
  plus: "M12 5v14M5 12h14",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5",
  pin: "M9 4h6l-1 6 4 3H6l4-3-1-6zM12 13v7",
  edit: "M4 20h4L19 9l-4-4L4 16v4z",
  trash: "M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13",
  mic: "M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0zM5 11a7 7 0 0 0 14 0M12 18v3",
  send: "M5 12h14M13 6l6 6-6 6",
  up: "M7 10v10H4V10zM7 10l4-7c2 0 3 1 3 3v3h5c1 0 2 1 2 2l-2 7c0 1-1 2-2 2H7",
  down: "M7 14V4H4v10zM7 14l4 7c2 0 3-1 3-3v-3h5c1 0 2-1 2-2l-2-7c0-1-1-2-2-2H7",
  check: "m5 12 5 5 9-10",
  chevron: "m9 6 6 6-6 6",
  menu: "M4 7h16M4 12h16M4 17h16",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  refresh: "M20 11a8 8 0 1 0-2 6M20 5v6h-6",
  copy: "M8 8h12v12H8zM16 8V4H4v12h4",
  sheet: "M4 4h16v16H4zM9 9l6 6M15 9l-6 6",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 14h4M10 17h4",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  close: "M6 6l12 12M18 6 6 18",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10c1 1 1 2 1 3h6c0-1 0-2 1-3a6 6 0 0 0-4-10z",
  building: "M5 21V5l7-2v18M12 8h7v13M8 8h1M8 12h1M8 16h1M15 12h1M15 16h1M3 21h18",
  stop: "M7 7h10v10H7z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "size-4" }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/** A small trend line for a daily series (gaps are skipped). */
export function Sparkline({ values, tone }: { values: (number | null)[]; tone: "up" | "down" | "flat" }) {
  const points = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (points.length < 2) return null;
  const ys = points.map((p) => p[1]);
  const lo = Math.min(...ys);
  const span = Math.max(...ys) - lo || 1;
  const w = 100;
  const h = 24;
  const d = points
    .map(([i, v], k) => `${k ? "L" : "M"}${((i / (values.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - lo) / span) * (h - 4)).toFixed(1)}`)
    .join("");
  const color = tone === "down" ? "text-red-700 dark:text-red-400" : tone === "up" ? "text-green-700 dark:text-green-400" : "text-stone-400";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true" className={`mt-1 h-6 w-full ${color}`}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
