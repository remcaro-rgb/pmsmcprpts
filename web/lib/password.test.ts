import { describe, expect, it } from "vitest";
import { passwordAccepted, passwordChallenge, passwordGate } from "./password";

const basic = (s: string) => "Basic " + btoa(String.fromCharCode(...new TextEncoder().encode(s)));

describe("passwordGate", () => {
  it("is off unless WEB_PASSWORD is set, and rejects weak settings", () => {
    expect(passwordGate({})).toBeNull();
    expect(passwordGate({ WEB_PASSWORD: "admin:correct-horse-battery" })).toEqual({
      user: "admin",
      password: "correct-horse-battery",
    });
    expect(passwordGate({ WEB_PASSWORD: "admin:pa:ss:word:12345" })?.password).toBe("pa:ss:word:12345");
    expect(() => passwordGate({ WEB_PASSWORD: "admin:short" })).toThrow("at least 12");
    expect(() => passwordGate({ WEB_PASSWORD: "no-colon-here-at-all" })).toThrow("user:password");
    expect(() => passwordGate({ WEB_PASSWORD: ":nouser-password" })).toThrow("user:password");
  });
});

describe("passwordAccepted", () => {
  const gate = { user: "admin", password: "contraseña-larga-1" };

  it("accepts only the exact user and password", () => {
    expect(passwordAccepted(gate, basic("admin:contraseña-larga-1"))).toBe(true);
    expect(passwordAccepted(gate, basic("admin:contraseña-larga-2"))).toBe(false);
    expect(passwordAccepted(gate, basic("Admin:contraseña-larga-1"))).toBe(false);
    expect(passwordAccepted(gate, basic("admin:contraseña-larga-1x"))).toBe(false);
    expect(passwordAccepted(gate, basic("admin"))).toBe(false);
    expect(passwordAccepted(gate, null)).toBe(false);
    expect(passwordAccepted(gate, "Bearer abc")).toBe(false);
    expect(passwordAccepted(gate, "Basic !!!")).toBe(false);
  });

  it("asks the browser for credentials", () => {
    const res = passwordChallenge();
    expect(res.status).toBe(401);
    expect(res.headers.get("www-authenticate")).toContain("Basic");
  });
});
