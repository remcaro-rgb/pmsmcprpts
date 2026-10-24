// A thumbs up or down on an answer or a recommendation, or a recommendation marked done.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  return relay(req, "/api/feedback", "POST", await req.text());
}
