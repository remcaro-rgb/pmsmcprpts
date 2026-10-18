import type { ChartLayout, ChartPayload } from "./chat";

/** Index of the x position nearest to `x` (viewBox units), or null outside the plot. */
export function nearestIndex(kind: ChartPayload["kind"], layout: ChartLayout, x: number): number | null {
  const { left, right } = layout.plot;
  const slack = kind === "bar" ? (right - left) / layout.x_positions.length / 2 : 12;
  if (x < left - slack || x > right + slack) return null;
  let best = 0;
  layout.x_positions.forEach((p, i) => {
    if (Math.abs(p - x) < Math.abs(layout.x_positions[best] - x)) best = i;
  });
  return best;
}
