import { NextResponse, type NextRequest } from "next/server";
import { AGENT_URL } from "@/lib/agent";
import { SESSION_COOKIE, authConfig, cookieOptions, safeReturnTo, seal, sessionTtl, siteOrigin } from "@/lib/auth";
import { SlidingWindowLimiter, clientKey } from "@/lib/ratelimit";

export const dynamic = "force-dynamic";

// Per client: 20 sign-in attempts per 15 minutes (the agent also locks a login after 10 failures).
const limiter = new SlidingWindowLimiter(20, 15 * 60_000);
const TRUST_PROXY = process.env.TRUST_PROXY === "true";

/** Checks the password with the agent's user directory and starts a session. */
export async function POST(req: NextRequest): Promise<Response> {
  const auth = authConfig();
  if (!auth || auth.mode !== "password") return NextResponse.redirect(new URL("/", req.url), 303);
  const origin = siteOrigin(auth, req);
  const form = await req.formData();
  const returnTo = safeReturnTo(String(form.get("returnTo") ?? "/"));
  const back = (error: string) => {
    const url = new URL("/login", origin);
    url.searchParams.set("error", error);
    url.searchParams.set("returnTo", returnTo);
    return NextResponse.redirect(url, 303);
  };
  if (limiter.check(clientKey(req.headers, null, TRUST_PROXY)) > 0) return back("locked");

  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_URL}/api/auth/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ login: String(form.get("login") ?? ""), password: String(form.get("password") ?? "") }),
    });
  } catch {
    return back("unavailable");
  }
  if (upstream.status === 401 || upstream.status === 422) return back("invalid");
  if (upstream.status === 429) return back("locked");
  if (!upstream.ok) return back("unavailable");
  const user = (await upstream.json()) as { email: string };
  const res = NextResponse.redirect(new URL(returnTo, origin), 303);
  res.cookies.set(SESSION_COOKIE, await seal(auth.secret, "session", { email: user.email }, sessionTtl),
    cookieOptions(auth, sessionTtl, origin));
  return res;
}
