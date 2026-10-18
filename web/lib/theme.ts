// Light or dark colors, chosen with the header toggle and remembered in a cookie so the server
// renders the right one (no flash). Light unless someone picks dark.

export type Theme = "light" | "dark";
export const THEME_COOKIE = "pms_theme";

export function parseTheme(value: string | null | undefined): Theme {
  return value === "dark" ? "dark" : "light";
}
