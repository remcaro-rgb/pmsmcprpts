import { describe, expect, it } from "vitest";
import { nearestIndex } from "./chart";
import type { ChartLayout } from "./chat";

const layout: ChartLayout = {
  svg_light: "", svg_dark: "", width: 800, height: 450,
  plot: { left: 100, right: 700, top: 50, bottom: 400 },
  x_positions: [100, 400, 700],
};

describe("nearestIndex", () => {
  it("snaps to the nearest x inside the plot", () => {
    expect(nearestIndex("line", layout, 120)).toBe(0);
    expect(nearestIndex("line", layout, 560)).toBe(2);
    expect(nearestIndex("line", layout, 540)).toBe(1);
  });

  it("ignores the margins, with half a band of slack for bars", () => {
    expect(nearestIndex("line", layout, 40)).toBeNull();
    expect(nearestIndex("line", layout, 790)).toBeNull();
    // Bars get half a band of slack (600 / 3 / 2 = 100) so the outer bars' bands count.
    expect(nearestIndex("bar", layout, 20)).toBe(0);
    expect(nearestIndex("bar", layout, 805)).toBeNull();
  });
});
