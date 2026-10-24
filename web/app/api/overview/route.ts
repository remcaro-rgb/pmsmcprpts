// The home screen's key figures for the signed-in user's hotels (or one of them), for a period.

import { relay } from "@/lib/agent";
import { PERIODS } from "@/lib/home";

export const dynamic = "force-dynamic";

const HOTEL = /^[A-Za-z0-9_-]{1,12}$/;

export function GET(req: Request): Promise<Response> {
  const params = new URL(req.url).searchParams;
  const hotel = params.get("hotel");
  const period = params.get("period");
  const query = new URLSearchParams();
  if (hotel && HOTEL.test(hotel)) query.set("hotel", hotel);
  if (period && (PERIODS as readonly string[]).includes(period)) query.set("period", period);
  return relay(req, `/api/overview${query.size ? `?${query}` : ""}`);
}
