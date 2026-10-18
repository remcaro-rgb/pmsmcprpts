// Runs before every request. With WEB_PASSWORD set, asks for that user name and password first.
// With sign-in on (WEB_AUTH=oidc), requires a valid session and passes the signed-in email to route
// handlers in the x-pms-user header. With neither, does nothing.

import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, USER_HEADER, authConfig, isAllowed, unseal, type AuthConfig, type Session } from "@/lib/auth";
import { messages, requestLocale } from "@/lib/i18n";
import { messagePage } from "@/lib/pages";
import { passwordAccepted, passwordChallenge, passwordGate, type PasswordGate } from "@/lib/password";

const PUBLIC_PATHS = ["/auth/", "/signed-out"];

export async function proxy(req: NextRequest): Promise<Response> {
  // Never trust an identity header sent by the browser.
  const headers = new Headers(req.headers);
  headers.delete(USER_HEADER);

  let auth: AuthConfig | null;
  let gate: PasswordGate | null;
  try {
    gate = passwordGate();
    auth = authConfig();
  } catch (e) {
    const locale = requestLocale(req);
    return messagePage(messages(locale).misconfiguredTitle, e instanceof Error ? e.message : String(e), 500, false, locale);
  }
  if (gate && !passwordAccepted(gate, req.headers.get("authorization"))) return passwordChallenge();

  const { pathname, search } = req.nextUrl;
  if (!auth || PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next({ request: { headers } });
  }

  const session = await unseal<Session>(auth.secret, "session", req.cookies.get(SESSION_COOKIE)?.value);
  // Re-check the allowlist so removing someone takes effect without waiting for their cookie to expire.
  if (!session?.email || !isAllowed(auth, session.email)) {
    if (pathname.startsWith("/api/")) {
      return Response.json({ detail: messages(requestLocale(req)).signInToContinue }, { status: 401 });
    }
    const login = new URL("/auth/login", auth.publicUrl);
    login.searchParams.set("returnTo", pathname + search);
    return NextResponse.redirect(login);
  }
  headers.set(USER_HEADER, session.email);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
