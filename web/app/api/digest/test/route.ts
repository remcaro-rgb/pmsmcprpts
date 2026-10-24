// Sends the signed-in user today's daily email now.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  return relay(req, "/api/digest/test", "POST", await req.text());
}
