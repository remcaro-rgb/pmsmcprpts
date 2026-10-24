// Runs a saved report and emails it now.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!/^rep_[0-9a-f]{16}$/.test(id)) return Response.json({ detail: "Report not found." }, { status: 404 });
  return relay(req, `/api/reports/${id}/send`, "POST", "{}");
}
