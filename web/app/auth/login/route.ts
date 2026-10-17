import * as client from "openid-client";
import { NextResponse, type NextRequest } from "next/server";
import { LOGIN_COOKIE, authConfig, cookieOptions, loginTtl, safeReturnTo, seal } from "@/lib/auth";
import { oidcClient, redirectUri } from "@/lib/oidc";
import { messagePage } from "@/lib/pages";

export const dynamic = "force-dynamic";

/** Starts sign-in: remembers state, nonce and PKCE verifier in a short-lived encrypted cookie. */
export async function GET(req: NextRequest): Promise<Response> {
  const auth = authConfig();
  if (!auth) return NextResponse.redirect(new URL("/", req.url));
  let oidc: client.Configuration;
  try {
    oidc = await oidcClient(auth);
  } catch {
    return messagePage("Sign-in unavailable", "The sign-in provider can't be reached right now. Try again shortly.", 503);
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
