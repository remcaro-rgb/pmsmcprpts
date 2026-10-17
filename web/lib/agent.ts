import { USER_HEADER } from "./auth";

export const AGENT_URL = process.env.AGENT_URL ?? "http://localhost:7001";

/** JSON request to the agent on behalf of the signed-in user (set by proxy.ts), relayed as-is. */
export async function relay(req: Request, path: string, method = "GET"): Promise<Response> {
  const user = req.headers.get(USER_HEADER);
  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_URL}${path}`, { method, headers: user ? { [USER_HEADER]: user } : {} });
  } catch {
    return Response.json({ detail: "The assistant service is not reachable." }, { status: 502 });
  }
  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
  });
}
