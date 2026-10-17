import { describe, expect, it } from "vitest";
import { formatNumber, messages, pickLocale, requestLocale } from "./i18n";

describe("pickLocale", () => {
  it("prefers the saved choice, then the browser's languages in order", () => {
    expect(pickLocale("es", "en-US,en;q=0.9")).toBe("es");
    expect(pickLocale("en", "es-MX")).toBe("en");
    expect(pickLocale(null, "es-MX,es;q=0.9,en;q=0.8")).toBe("es");
    expect(pickLocale(undefined, "pt-BR,pt;q=0.9,es;q=0.8,en;q=0.7")).toBe("es");
    expect(pickLocale(undefined, "en;q=0.5,es-AR;q=0.9")).toBe("es");
    expect(pickLocale("fr", "fr-FR")).toBe("en");
    expect(pickLocale(undefined, "es;q=0")).toBe("en");
    expect(pickLocale(undefined, null)).toBe("en");
  });

  it("reads the cookie and header of a request", () => {
    const req = new Request("http://x/", { headers: { cookie: "a=1; pms_lang=es", "accept-language": "en" } });
    expect(requestLocale(req)).toBe("es");
    expect(requestLocale(new Request("http://x/", { headers: { "accept-language": "es-CO" } }))).toBe("es");
  });
});

describe("messages", () => {
  it("has every English message in Spanish", () => {
    const en = messages("en");
    const es = messages("es");
    expect(Object.keys(es).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(es.tools).sort()).toEqual(Object.keys(en.tools).sort());
    expect(es.starters).toHaveLength(en.starters.length);
    expect(es.rows("1", true)).toBe("1 fila");
    expect(es.showingRows("50", "1,234")).toBe("Mostrando 50 de 1,234 filas");
  });

  it("formats numbers the Latin American way", () => {
    expect(formatNumber(1234567.891, "es", 2)).toBe("1,234,567.89");
    expect(formatNumber(1234567.891, "en")).toBe("1,234,568");
  });
});
