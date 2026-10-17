// Proxies downloads of generated files (charts, spreadsheets, decks, reports) from the agent.

export const dynamic = "force-dynamic";

const AGENT_URL = process.env.AGENT_URL ?? "http://localhost:8001";
const PASS_HEADERS = ["content-type", "content-disposition", "content-length"];

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  if (!/^[0-9a-f]{32}$/.test(id)) return new Response("Not found", { status: 404 });
  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_URL}/files/${id}`);
  } catch {
    return new Response("The assistant service is not reachable.", { status: 502 });
  }
  if (!upstream.ok) return new Response("File not found or expired.", { status: upstream.status });
  const headers = new Headers({ "cache-control": "private, max-age=3600" });
  for (const h of PASS_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new Response(upstream.body, { status: 200, headers });
}
