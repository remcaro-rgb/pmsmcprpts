import { describe, expect, it } from "vitest";
import { SlidingWindowLimiter, clientKey, parseLimit } from "./ratelimit";

describe("SlidingWindowLimiter", () => {
  it("allows up to the limit per key within the window", () => {
    let now = 0;
    const limiter = new SlidingWindowLimiter(2, 60_000, () => now);
    expect(limiter.check("a")).toBe(0);
    expect(limiter.check("a")).toBe(0);
    expect(limiter.check("a")).toBe(60);
    expect(limiter.check("b")).toBe(0);
    now = 30_000;
    expect(limiter.check("a")).toBe(30);
    now = 60_001;
    expect(limiter.check("a")).toBe(0);
  });
});

describe("helpers", () => {
  it("parses limits with a fallback", () => {
    expect(parseLimit("5/60")).toEqual({ limit: 5, windowMs: 60_000 });
    expect(parseLimit("nonsense")).toEqual({ limit: 20, windowMs: 600_000 });
    expect(parseLimit(undefined)).toEqual({ limit: 20, windowMs: 600_000 });
  });

  it("keys by user, else by trusted forwarded IP", () => {
    const h = new Headers({ "x-forwarded-for": "1.2.3.4, 10.0.0.1" });
    expect(clientKey(h, "ann@hotel.example", true)).toBe("user:ann@hotel.example");
    expect(clientKey(h, null, true)).toBe("ip:1.2.3.4");
    expect(clientKey(h, null, false)).toBe("ip:local");
  });
});
