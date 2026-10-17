// One saved conversation: load it to show again, or delete it.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };
const ID = /^conv_[0-9a-f]{16}$/;

export async function GET(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!ID.test(id)) return Response.json({ detail: "Conversation not found." }, { status: 404 });
  return relay(req, `/api/conversations/${id}`);
}

export async function DELETE(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!ID.test(id)) return Response.json({ detail: "Conversation not found." }, { status: 404 });
  return relay(req, `/api/conversations/${id}`, "DELETE");
}
