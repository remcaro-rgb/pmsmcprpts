// Optional site-wide password (WEB_PASSWORD="user:password"), checked with HTTP Basic auth before
// anything else. Meant for sharing a copy quickly (e.g. a Cloudflare quick tunnel) without setting
// up an identity provider; WEB_AUTH=oidc is the full sign-in.

export const MIN_PASSWORD = 12;

export type PasswordGate = { user: string; password: string };

/** Null when WEB_PASSWORD is unset. Throws when it's set but unusable. */
export function passwordGate(env: Record<string, string | undefined> = process.env): PasswordGate | null {
  const spec = env.WEB_PASSWORD ?? "";
  if (!spec) return null;
  const i = spec.indexOf(":");
  const user = i > 0 ? spec.slice(0, i) : "";
  const password = i > 0 ? spec.slice(i + 1) : "";
  if (!user || !password) throw new Error('WEB_PASSWORD must look like "user:password".');
  if (password.length < MIN_PASSWORD) throw new Error(`WEB_PASSWORD needs a password of at least ${MIN_PASSWORD} characters.`);
  return { user, password };
}

function sameText(a: string, b: string): boolean {
  // Compare every character so the time taken doesn't reveal how much of a guess was right.
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

/** Whether an Authorization header carries the right user and password. */
export function passwordAccepted(gate: PasswordGate, authorization: string | null): boolean {
  const match = /^Basic\s+([A-Za-z0-9+/=]+)\s*$/i.exec(authorization ?? "");
  if (!match) return false;
  let decoded: string;
  try {
    decoded = new TextDecoder().decode(Uint8Array.from(atob(match[1]), (c) => c.charCodeAt(0)));
  } catch {
    return false;
  }
  const i = decoded.indexOf(":");
  if (i < 0) return false;
  // Evaluate both so a wrong user name takes as long as a wrong password.
  const userOk = sameText(decoded.slice(0, i), gate.user);
  const passwordOk = sameText(decoded.slice(i + 1), gate.password);
  return userOk && passwordOk;
}

/** The 401 that makes the browser ask for the user name and password. */
export function passwordChallenge(): Response {
  return new Response("Sign in to continue.", {
    status: 401,
    headers: { "www-authenticate": 'Basic realm="Hotel Super Intelligence", charset="UTF-8"', "content-type": "text/plain; charset=utf-8" },
  });
}
