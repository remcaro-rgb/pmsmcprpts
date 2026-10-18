// Per-request preferences for server components: language and light/dark colors.

import { cookies, headers } from "next/headers";
import { LOCALE_COOKIE, pickLocale, type Locale } from "./i18n";
import { THEME_COOKIE, parseTheme, type Theme } from "./theme";

/** The locale of the current request. */
export async function serverLocale(): Promise<Locale> {
  return pickLocale((await cookies()).get(LOCALE_COOKIE)?.value, (await headers()).get("accept-language"));
}

/** The light/dark choice of the current request (light by default). */
export async function serverTheme(): Promise<Theme> {
  return parseTheme((await cookies()).get(THEME_COOKIE)?.value);
}
