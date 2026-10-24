import { describe, expect, it } from "vitest";
import { change, longDate, money, pct, pp, trend } from "./home";

describe("key figures", () => {
  it("writes percentages, points and changes", () => {
    expect(pct(0.7845, "es")).toBe("78.5%");
    expect(pct(null, "en")).toBe("–");
    expect(pp(0.061, "es")).toBe("+6.1 pp");
    expect(pp(-0.043, "en")).toBe("−4.3 pp");
    expect(change(0.0823, "en")).toBe("+8.2%");
    expect(change(null, "en")).toBeNull();
    expect(trend(-0.1)).toBe("down");
    expect(trend(0)).toBe("flat");
  });

  it("shortens money from a million up", () => {
    expect(money(412300, "COP", "es")).toMatch(/^COP\s412,300$/); // a no-break space
    expect(money(186_400_000, "COP", "en")).toMatch(/^COP\s?186\.4\s?M$/);
    expect(money(147.1, "EUR", "en")).toBe("€147");
    expect(money(147.1, "EUR", "es")).toBe("€147");
    expect(money(527_000, "EUR", "en", 100_000)).toBe("€527K");
  });

  it("writes the date in the website's language", () => {
    expect(longDate("2026-10-24", "es")).toBe("sábado, 24 de octubre");
    expect(longDate("2026-10-24", "en")).toBe("Saturday, October 24");
  });
});
