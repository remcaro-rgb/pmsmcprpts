import { cookies, headers } from "next/headers";
import { LOCALE_COOKIE, pickLocale, type Locale } from "./i18n";

/** The locale of the current request, for server components. */
export async function serverLocale(): Promise<Locale> {
  return pickLocale((await cookies()).get(LOCALE_COOKIE)?.value, (await headers()).get("accept-language"));
}
