// Proxies chat requests to the agent service and streams its server-sent events back,
// so the browser only talks to this origin.

import { USER_HEADER } from "@/lib/auth";
import { messages, requestLocale } from "@/lib/i18n";
import { SlidingWindowLimiter, clientKey, parseLimit } from "@/lib/ratelimit";

export const dynamic = "force-dynamic";

const AGENT_URL = process.env.AGENT_URL ?? "http://localhost:7001";
const { limit, windowMs } = parseLimit(process.env.CHAT_RATE_LIMIT);
const limiter = new SlidingWindowLimiter(limit, windowMs);
const TRUST_PROXY = process.env.TRUST_PROXY === "true";

export async function POST(req: Request): Promise<Response> {
  // Set by proxy.ts from the session when sign-in is on (and always stripped from the browser request).
  const user = req.headers.get(USER_HEADER);
  const t = messages(requestLocale(req));
  const wait = limiter.check(clientKey(req.headers, user, TRUST_PROXY));
  if (wait > 0) {
    return Response.json(
      { detail: t.rateLimited(wait) },
      { status: 429, headers: { "retry-after": String(wait) } },
    );
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_URL}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json", ...(user ? { [USER_HEADER]: user } : {}) },
      body: await req.text(),
      // Aborting the browser request closes the agent stream, which discards the turn.
      signal: req.signal,
    });
  } catch {
    return Response.json({ detail: t.serviceUnreachable }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
