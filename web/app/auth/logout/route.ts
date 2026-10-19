import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, authConfig, siteOrigin } from "@/lib/auth";

export const dynamic = "force-dynamic";

/** POST only, so other sites can't sign people out with a link or image. */
export async function POST(req: NextRequest): Promise<Response> {
  const auth = authConfig();
  const res = NextResponse.redirect(new URL("/signed-out", auth ? siteOrigin(auth, req) : req.url), 303);
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
