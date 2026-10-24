// One saved report: rename it, change its schedule, or delete it.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };
const REPORT_ID = /^rep_[0-9a-f]{16}$/;
const notFound = () => Response.json({ detail: "Report not found." }, { status: 404 });

export async function PATCH(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!REPORT_ID.test(id)) return notFound();
  return relay(req, `/api/reports/${id}`, "PATCH", await req.text());
}

export async function DELETE(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!REPORT_ID.test(id)) return notFound();
  return relay(req, `/api/reports/${id}`, "DELETE");
}
