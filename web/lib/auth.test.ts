import { describe, expect, it } from "vitest";
import { authConfig, cookieOptions, isAllowed, safeReturnTo, seal, siteOrigin, unseal } from "./auth";

const ENV = {
  WEB_AUTH: "oidc",
  PMS_OIDC_ISSUER: "https://accounts.example.com/",
  PMS_OIDC_CLIENT_ID: "shared-id",
  PMS_OIDC_CLIENT_SECRET: "shared-secret",
  WEB_PUBLIC_URL: "https://pms.example.com/",
  WEB_SESSION_SECRET: "x".repeat(32),
  PMS_ALLOWED_DOMAINS: "Hotel.Example",
};

describe("authConfig", () => {
  it("is off unless WEB_AUTH=oidc", () => {
    expect(authConfig({})).toBeNull();
    expect(authConfig({ ...ENV, WEB_AUTH: "" })).toBeNull();
  });

  it("reuses the MCP server's provider settings unless the website has its own", () => {
    const c = authConfig(ENV)!;
    expect(c.issuer).toBe("https://accounts.example.com");
    expect(c.publicUrl).toBe("https://pms.example.com");
    expect([c.clientId, c.clientSecret]).toEqual(["shared-id", "shared-secret"]);
    const own = authConfig({ ...ENV, WEB_OIDC_CLIENT_ID: "web-id", WEB_OIDC_CLIENT_SECRET: "web-secret" })!;
    expect([own.clientId, own.clientSecret]).toEqual(["web-id", "web-secret"]);
  });

  it("rejects incomplete settings", () => {
    expect(() => authConfig({ ...ENV, WEB_PUBLIC_URL: "" })).toThrow("WEB_PUBLIC_URL");
    expect(() => authConfig({ ...ENV, WEB_SESSION_SECRET: "short" })).toThrow("at least 32");
    expect(() => authConfig({ ...ENV, PMS_ALLOWED_DOMAINS: "" })).toThrow("PMS_ALLOWED_EMAILS");
    expect(authConfig({ ...ENV, PMS_ALLOWED_DOMAINS: "", PMS_ALLOW_ANY_USER: "true" })).not.toBeNull();
  });
});

describe("password sign-in (WEB_AUTH=password)", () => {
  const PASSWORD = { WEB_AUTH: "password", WEB_SESSION_SECRET: "x".repeat(32) };

  it("needs only a session secret; the user directory decides who may sign in", () => {
    const c = authConfig(PASSWORD)!;
    expect(c.mode).toBe("password");
    expect(c.publicUrl).toBe("");
    expect(isAllowed(c, "anyone@anywhere.example")).toBe(true);
  });

  it("rejects a short secret and unknown modes", () => {
    expect(() => authConfig({ ...PASSWORD, WEB_SESSION_SECRET: "short" })).toThrow("at least 32");
    expect(() => authConfig({ WEB_AUTH: "magic" })).toThrow('"oidc", "password" or empty (it is "magic")');
    for (const value of [" password ", '"password"', "'Password'"]) {
      expect(authConfig({ ...PASSWORD, WEB_AUTH: value })?.mode).toBe("password");
    }
  });

  it("redirects to where the site is reached, behind a tunnel or proxy too", () => {
    const c = authConfig(PASSWORD)!;
    const direct = new Request("http://localhost:5050/admin");
    expect(siteOrigin(c, direct)).toBe("http://localhost:5050");
    const tunneled = new Request("http://web:3000/admin", {
      headers: { "x-forwarded-host": "pms.example.com", "x-forwarded-proto": "https" },
    });
    expect(siteOrigin(c, tunneled)).toBe("https://pms.example.com");
    expect(cookieOptions(c, 60, siteOrigin(c, tunneled)).secure).toBe(true);
    const fixed = authConfig({ ...PASSWORD, WEB_PUBLIC_URL: "https://reports.example.com/" })!;
    expect(siteOrigin(fixed, tunneled)).toBe("https://reports.example.com");
  });
});

describe("isAllowed", () => {
  it("matches emails and domains, ignoring case", () => {
    const c = authConfig({ ...ENV, PMS_ALLOWED_EMAILS: "Guest@Gmail.com" })!;
    expect(isAllowed(c, "ann@HOTEL.example")).toBe(true);
    expect(isAllowed(c, "guest@gmail.com")).toBe(true);
    expect(isAllowed(c, "other@gmail.com")).toBe(false);
    expect(isAllowed(c, "ann@hotel.example.evil.com")).toBe(false);
  });
});

describe("seal / unseal", () => {
  const secret = "s".repeat(32);

  it("round-trips the payload for the same purpose only", async () => {
    const token = await seal(secret, "session", { email: "ann@hotel.example" }, 60);
    expect(token).not.toContain("ann");
    expect((await unseal<{ email: string }>(secret, "session", token))?.email).toBe("ann@hotel.example");
    expect(await unseal(secret, "login", token)).toBeNull();
    expect(await unseal("t".repeat(32), "session", token)).toBeNull();
    expect(await unseal(secret, "session", token.slice(0, -2) + "AA")).toBeNull();
    expect(await unseal(secret, "session", undefined)).toBeNull();
  });

  it("expires", async () => {
    const token = await seal(secret, "session", { email: "a@b.c" }, -10);
    expect(await unseal(secret, "session", token)).toBeNull();
  });
});

describe("safeReturnTo", () => {
  it("only allows same-site paths", () => {
    expect(safeReturnTo("/?q=1")).toBe("/?q=1");
    expect(safeReturnTo(null)).toBe("/");
    expect(safeReturnTo("https://evil.example")).toBe("/");
    expect(safeReturnTo("//evil.example")).toBe("/");
    expect(safeReturnTo("/\\evil.example")).toBe("/");
  });
});

it("cookies are secure on https sites", () => {
  expect(cookieOptions(authConfig(ENV)!, 60).secure).toBe(true);
  expect(cookieOptions(authConfig({ ...ENV, WEB_PUBLIC_URL: "http://localhost:5050" })!, 60).secure).toBe(false);
});
