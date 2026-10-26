import * as client from "openid-client";
import { NextResponse, type NextRequest } from "next/server";
import { LOGIN_COOKIE, authConfig, cookieOptions, loginTtl, safeReturnTo, seal, siteOrigin } from "@/lib/auth";
import { oidcClient, redirectUri } from "@/lib/oidc";
import { messages, requestLocale } from "@/lib/i18n";
import { messagePage } from "@/lib/pages";

export const dynamic = "force-dynamic";

/** Starts sign-in: remembers state, nonce and PKCE verifier in a short-lived encrypted cookie. */
export async function GET(req: NextRequest): Promise<Response> {
  const auth = authConfig();
  if (!auth) return NextResponse.redirect(new URL("/", req.url));
  if (auth.mode === "password") {
    const login = new URL("/login", siteOrigin(auth, req));
    login.searchParams.set("returnTo", safeReturnTo(req.nextUrl.searchParams.get("returnTo")));
    return NextResponse.redirect(login);
  }
  let oidc: client.Configuration;
  try {
    oidc = await oidcClient(auth);
  } catch {
    const locale = requestLocale(req);
    const t = messages(locale);
    return messagePage(t.signInUnavailableTitle, t.signInUnavailableBody, 503, false, locale);
  }
  const verifier = client.randomPKCECodeVerifier();
  const pending = {
    state: client.randomState(),
    nonce: client.randomNonce(),
    verifier,
    returnTo: safeReturnTo(req.nextUrl.searchParams.get("returnTo")),
  };
  const url = client.buildAuthorizationUrl(oidc, {
    redirect_uri: redirectUri(auth),
    scope: "openid email profile",
    code_challenge: await client.calculatePKCECodeChallenge(verifier),
    code_challenge_method: "S256",
    state: pending.state,
    nonce: pending.nonce,
  });
  const res = NextResponse.redirect(url);
  res.cookies.set(LOGIN_COOKIE, await seal(auth.secret, "login", pending, loginTtl), cookieOptions(auth, loginTtl));
  return res;
}
