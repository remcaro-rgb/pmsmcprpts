// The signed-in user's saved conversations (everyone's when sign-in is off), newest first.

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

export function GET(req: Request): Promise<Response> {
  return relay(req, "/api/conversations");
}
