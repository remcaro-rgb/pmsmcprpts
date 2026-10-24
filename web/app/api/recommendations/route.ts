// Today's recommendations for the signed-in user's hotels (made by the agent once a day).

import { relay } from "@/lib/agent";
import { isLocale } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export function GET(req: Request): Promise<Response> {
  const language = new URL(req.url).searchParams.get("language");
  return relay(req, `/api/recommendations?language=${isLocale(language) ? language : "en"}`);
}
