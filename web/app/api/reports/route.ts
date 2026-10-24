// The signed-in user's saved reports: list them, or save a new one.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

export function GET(req: Request): Promise<Response> {
  return relay(req, "/api/reports");
}

export async function POST(req: Request): Promise<Response> {
  return relay(req, "/api/reports", "POST", await req.text());
}
