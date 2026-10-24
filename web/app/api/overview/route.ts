// The home screen's key figures for the signed-in user's hotels (or one of them).

import { relay } from "@/lib/agent";

export const dynamic = "force-dynamic";

const HOTEL = /^[A-Za-z0-9_-]{1,12}$/;

export function GET(req: Request): Promise<Response> {
  const hotel = new URL(req.url).searchParams.get("hotel");
  return relay(req, `/api/overview${hotel && HOTEL.test(hotel) ? `?hotel=${hotel}` : ""}`);
}
