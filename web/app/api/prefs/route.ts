// The signed-in user's settings (the daily email).

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

export function GET(req: Request): Promise<Response> {
  return relay(req, "/api/prefs");
}

export async function PUT(req: Request): Promise<Response> {
  return relay(req, "/api/prefs", "PUT", await req.text());
}
