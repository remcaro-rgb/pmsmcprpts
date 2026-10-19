import * as client from "openid-client";
import { NextResponse, type NextRequest } from "next/server";
import {
  LOGIN_COOKIE,
  SESSION_COOKIE,
  authConfig,
  cookieOptions,
  isAllowed,
  seal,
  sessionTtl,
  unseal,
  type PendingLogin,
} from "@/lib/auth";
import { oidcClient } from "@/lib/oidc";
import { messages, requestLocale } from "@/lib/i18n";
import { messagePage } from "@/lib/pages";

export const dynamic = "force-dynamic";

/** The provider returns here: verify the code and ID token, check the allowlist, start a session. */
export async function GET(req: NextRequest): Promise<Response> {
  const auth = authConfig();
  if (!auth || auth.mode !== "oidc") return NextResponse.redirect(new URL("/", req.url));
  const locale = requestLocale(req);
  const t = messages(locale);
  const pending = await unseal<PendingLogin>(auth.secret, "login", req.cookies.get(LOGIN_COOKIE)?.value);
  if (!pending) return messagePage(t.signInExpiredTitle, t.signInExpiredBody, 400, true, locale);

  let email: string;
  try {
    const oidc = await oidcClient(auth);
    // Rebuild the URL on the public origin so it matches the registered redirect URI behind proxies.
    const current = new URL(req.nextUrl.pathname + req.nextUrl.search, auth.publicUrl);
    const tokens = await client.authorizationCodeGrant(oidc, current, {
      pkceCodeVerifier: pending.verifier,
      expectedState: pending.state,
      expectedNonce: pending.nonce,
      idTokenExpected: true,
    });
    const claims: Record<string, unknown> = tokens.claims() ?? {};
    email = String(claims.email ?? claims.preferred_username ?? "").toLowerCase();
    if (!email.includes("@")) throw new Error("the provider did not share an email address");
    if (claims.email_verified === false) throw new Error(`${email} is not verified`);
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e);
    return messagePage(t.signInFailedTitle, t.signInFailedBody(reason), 400, true, locale);
  }
  if (!isAllowed(auth, email)) {
    return messagePage(t.notAllowedTitle, t.notAllowedBody(email), 403, true, locale);
  }

  const res = NextResponse.redirect(new URL(pending.returnTo, auth.publicUrl));
  res.cookies.set(SESSION_COOKIE, await seal(auth.secret, "session", { email }, sessionTtl), cookieOptions(auth, sessionTtl));
  res.cookies.delete(LOGIN_COOKIE);
  return res;
}
