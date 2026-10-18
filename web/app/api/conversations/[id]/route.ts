// One saved conversation: load it to show again, or delete it.

import { relay } from "@/lib/agent";
import { messages, requestLocale } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };
const ID = /^conv_[0-9a-f]{16}$/;
const notFound = (req: Request) =>
  Response.json({ detail: messages(requestLocale(req)).conversationNotFound }, { status: 404 });

export async function GET(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!ID.test(id)) return notFound(req);
  return relay(req, `/api/conversations/${id}`);
}

export async function DELETE(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!ID.test(id)) return notFound(req);
  return relay(req, `/api/conversations/${id}`, "DELETE");
}
