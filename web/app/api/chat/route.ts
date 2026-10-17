// Proxies chat requests to the agent service and streams its server-sent events back,
// so the browser only talks to this origin.

export const dynamic = "force-dynamic";

const AGENT_URL = process.env.AGENT_URL ?? "http://localhost:8001";

export async function POST(req: Request): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_URL}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
      // Aborting the browser request closes the agent stream, which discards the turn.
      signal: req.signal,
    });
  } catch {
    return Response.json({ detail: "The assistant service is not reachable." }, { status: 502 });
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
