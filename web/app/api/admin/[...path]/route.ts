// User and hotel administration, relayed to the agent, which checks that the signed-in user is an
// administrator on every request.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };
const PATH = /^(users|hotels)(\/[1-9][0-9]{0,9})?$/;
const MAX_BODY = 16_000;

async function forward(req: Request, ctx: Ctx, method: string): Promise<Response> {
  const path = (await ctx.params).path.join("/");
  if (!PATH.test(path)) return Response.json({ detail: "Not found." }, { status: 404 });
  let body: string | undefined;
  if (method === "POST" || method === "PATCH") {
    body = await req.text();
    if (body.length > MAX_BODY) return Response.json({ detail: "Request too large." }, { status: 413 });
  }
  return relay(req, `/api/admin/${path}`, method, body);
}

export const GET = (req: Request, ctx: Ctx) => forward(req, ctx, "GET");
export const POST = (req: Request, ctx: Ctx) => forward(req, ctx, "POST");
export const PATCH = (req: Request, ctx: Ctx) => forward(req, ctx, "PATCH");
export const DELETE = (req: Request, ctx: Ctx) => forward(req, ctx, "DELETE");
