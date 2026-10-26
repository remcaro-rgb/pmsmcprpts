// Today's recommendations for the signed-in user's hotels, or one of them (made by the agent once a day).

import { relay } from "@/lib/agent";
import { isLocale } from "@/lib/i18n";

export const dynamic = "force-dynamic";

const HOTEL = /^[A-Za-z0-9_-]{1,12}$/;

export function GET(req: Request): Promise<Response> {
  const params = new URL(req.url).searchParams;
  const language = params.get("language");
  const hotel = params.get("hotel");
  const query = `language=${isLocale(language) ? language : "en"}${hotel && HOTEL.test(hotel) ? `&hotel=${hotel}` : ""}`;
  return relay(req, `/api/recommendations?${query}`);
}
