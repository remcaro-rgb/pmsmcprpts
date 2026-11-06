import { describe, expect, it } from "vitest";
import { logQuery, percent } from "./fns";

describe("import progress", () => {
  it("is the share of planned calls made, below 100 until the import ends", () => {
    expect(percent(undefined)).toBe(0);
    expect(percent({ calls: 23, planned: 51 })).toBe(45);
    expect(percent({ calls: 0, planned: 51 })).toBe(1);
    expect(percent({ calls: 60, planned: 51 })).toBe(99);
  });
});

describe("import log filters", () => {
  it("send whole local days, the hotel, the statuses and the search", () => {
    const q = new URLSearchParams(logQuery({ from: "2026-11-01", to: "2026-11-06", hotel: "7", levels: ["error", "warning"], q: "pos" }).slice(1));
    expect(new Date(q.get("since")!).getTime()).toBe(new Date("2026-11-01T00:00:00").getTime());
    expect(new Date(q.get("until")!).getTime()).toBe(new Date("2026-11-07T00:00:00").getTime());
    expect(q.get("hotel")).toBe("7");
    expect(q.getAll("level")).toEqual(["error", "warning"]);
    expect(q.get("q")).toBe("pos");
    expect(q.has("before")).toBe(false);
    expect(new URLSearchParams(logQuery({ from: "2026-11-01", to: "2026-11-01", levels: ["info"], before: 42 }).slice(1)).get("before")).toBe("42");
  });
});
