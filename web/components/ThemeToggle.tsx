"use client";

import { useState } from "react";
import { THEME_COOKIE, type Theme } from "@/lib/theme";
import { useI18n } from "./I18n";

/** Switches between light and dark colors; the choice is kept in a cookie for a year. */
export default function ThemeToggle({ initial }: { initial: Theme }) {
  const { t } = useI18n();
  const [theme, setTheme] = useState<Theme>(initial);
  const label = theme === "dark" ? t.lightMode : t.darkMode;

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-stone-200 text-stone-600 hover:bg-stone-100 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-900"
    >
      {theme === "dark" ? (
        // Sun: switch to light
        <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4">
          <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.06 1.06M11.54 11.54l1.06 1.06M3.4 12.6l1.06-1.06M11.54 4.46l1.06-1.06"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        // Moon: switch to dark
        <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4">
          <path
            d="M13.5 9.6A5.75 5.75 0 0 1 6.4 2.5a5.75 5.75 0 1 0 7.1 7.1Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}
