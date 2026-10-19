// Website sign-in (server side only) with an encrypted session cookie. Two modes:
// - WEB_AUTH=password: accounts in the user directory (email or unique ID and password), checked by
//   the agent; administrators manage them in /admin.
// - WEB_AUTH=oidc: OpenID Connect (e.g. Google) with an email/domain allowlist; the same provider
//   and allowlist as the MCP server's connector sign-in can be reused.

import { EncryptJWT, jwtDecrypt } from "jose";

export const SESSION_COOKIE = "pms_session";
export const LOGIN_COOKIE = "pms_login";
export const USER_HEADER = "x-pms-user";
const SESSION_HOURS = 12;
const LOGIN_MINUTES = 10;

export type AuthMode = "oidc" | "password";

export type AuthConfig = {
  mode: AuthMode;
  issuer: string;
  clientId: string;
  clientSecret: string;
  publicUrl: string; // where the website is reachable, for the redirect URI ("" in password mode: the request's)
  allowedEmails: Set<string>;
  allowedDomains: Set<string>;
  allowAnyUser: boolean;
  allowHttp: boolean; // tests only: plain-HTTP identity provider
  secret: string;
};

const csv = (v: string | undefined) =>
  new Set((v ?? "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean));

/** Null when sign-in is off. Throws when it's on but misconfigured. */
export function authConfig(env: Record<string, string | undefined> = process.env): AuthConfig | null {
  // Tolerate spaces and quotes copied into .env.
  const mode = (env.WEB_AUTH ?? "").trim().replace(/^(["'])(.*)\1$/, "$2").trim().toLowerCase();
  if (mode === "password") {
    const secret = env.WEB_SESSION_SECRET ?? "";
    if (secret.length < 32) throw new Error("WEB_SESSION_SECRET must be at least 32 characters.");
    return {
      mode: "password",
      issuer: "",
      clientId: "",
      clientSecret: "",
      publicUrl: (env.WEB_PUBLIC_URL ?? "").replace(/\/$/, ""),
      allowedEmails: new Set(),
      allowedDomains: new Set(),
      allowAnyUser: true, // the user directory decides, through the agent
      allowHttp: false,
      secret,
    };
  }
  if (mode && mode !== "oidc") throw new Error(`WEB_AUTH must be "oidc", "password" or empty (it is ${JSON.stringify(env.WEB_AUTH)}).`);
  if (mode !== "oidc") return null;
  const config: AuthConfig = {
    mode: "oidc",
    issuer: (env.PMS_OIDC_ISSUER ?? "").replace(/\/$/, ""),
    clientId: env.WEB_OIDC_CLIENT_ID || env.PMS_OIDC_CLIENT_ID || "",
    clientSecret: env.WEB_OIDC_CLIENT_SECRET || env.PMS_OIDC_CLIENT_SECRET || "",
    publicUrl: (env.WEB_PUBLIC_URL ?? "").replace(/\/$/, ""),
    allowedEmails: csv(env.PMS_ALLOWED_EMAILS),
    allowedDomains: csv(env.PMS_ALLOWED_DOMAINS),
    allowAnyUser: env.PMS_ALLOW_ANY_USER === "true",
    allowHttp: env.PMS_OIDC_ALLOW_HTTP === "true",
    secret: env.WEB_SESSION_SECRET ?? "",
  };
  const missing = Object.entries({
    PMS_OIDC_ISSUER: config.issuer,
    WEB_OIDC_CLIENT_ID: config.clientId,
    WEB_OIDC_CLIENT_SECRET: config.clientSecret,
    WEB_PUBLIC_URL: config.publicUrl,
  }).filter(([, v]) => !v).map(([k]) => k);
  if (missing.length) throw new Error(`WEB_AUTH=oidc needs ${missing.join(", ")}.`);
  if (config.secret.length < 32) throw new Error("WEB_SESSION_SECRET must be at least 32 characters.");
  if (!config.allowedEmails.size && !config.allowedDomains.size && !config.allowAnyUser) {
    throw new Error("Set PMS_ALLOWED_EMAILS and/or PMS_ALLOWED_DOMAINS (or PMS_ALLOW_ANY_USER=true).");
  }
  return config;
}

export function isAllowed(config: AuthConfig, email: string): boolean {
  const e = email.toLowerCase();
  return config.allowAnyUser || config.allowedEmails.has(e) || config.allowedDomains.has(e.split("@").pop() ?? "");
}

async function key(secret: string, purpose: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${purpose}:${secret}`));
  return new Uint8Array(digest);
}

/** Encrypted, integrity-protected token (JWE, A256GCM) carrying `payload`. */
export async function seal(secret: string, purpose: string, payload: Record<string, unknown>, ttlSeconds: number) {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(`${ttlSeconds}s`)
    .setAudience(purpose)
    .encrypt(await key(secret, purpose));
}

export async function unseal<T>(secret: string, purpose: string, token: string | undefined): Promise<T | null> {
  if (!token) return null;
  try {
    const { payload } = await jwtDecrypt(token, await key(secret, purpose), { audience: purpose });
    return payload as T;
  } catch {
    return null;
  }
}

export const sessionTtl = SESSION_HOURS * 3600;
export const loginTtl = LOGIN_MINUTES * 60;

export type Session = { email: string };
export type PendingLogin = { state: string; nonce: string; verifier: string; returnTo: string };

/** Only same-site relative paths, so the login can't bounce users to another site. */
export function safeReturnTo(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") ? value : "/";
}

/** Where the site is reached: the configured public URL, else the request's own origin (as seen by
 * the browser, behind a proxy or tunnel). */
export function siteOrigin(config: AuthConfig, req: Request): string {
  if (config.publicUrl) return config.publicUrl;
  const url = new URL(req.url);
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? url.host;
  const proto = req.headers.get("x-forwarded-proto") ?? url.protocol.replace(":", "");
  return `${proto.split(",")[0].trim()}://${host.split(",")[0].trim()}`;
}

export function cookieOptions(config: AuthConfig, maxAge: number, origin = config.publicUrl) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: origin.startsWith("https://"),
    path: "/",
    maxAge,
  };
}
