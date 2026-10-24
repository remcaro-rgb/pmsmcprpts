"use client";

import { useEffect, useRef, useState } from "react";
import { isLocale } from "@/lib/i18n";
import { THEME_COOKIE, type Theme } from "@/lib/theme";
import { Icon } from "./Icons";
import { useI18n } from "./I18n";

function initials(name: string): string {
  const words = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase();
}

/** The account menu in the header: colors, language, administration and sign-out. */
export default function UserMenu({
  name,
  user,
  isAdmin,
  theme: initialTheme,
}: {
  name: string | null;
  user: string | null; // signed-in email; null when sign-in is off
  isAdmin: boolean;
  theme: Theme;
}) {
  const { locale, t, setLocale } = useI18n();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const ref = useRef<HTMLDivElement>(null);
  const label = name ?? user;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
  }

  const item = "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-stone-100 dark:hover:bg-stone-800";
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={t.accountMenu}
        className="flex items-center gap-2 rounded-full border border-stone-200 p-0.5 pr-0.5 hover:bg-stone-100 sm:pr-3 dark:border-stone-700 dark:hover:bg-stone-900"
      >
        <span className="flex size-8 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200">
          {label ? initials(label) : <Icon name="user" />}
        </span>
        {label && <span className="hidden max-w-40 truncate text-sm font-medium sm:inline">{name ?? user}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-40 w-64 rounded-xl border border-stone-200 bg-white p-1.5 shadow-lg dark:border-stone-700 dark:bg-stone-900">
          {user && <p className="truncate px-3 pb-2 pt-1 text-xs text-stone-500" title={user}>{user}</p>}
          <button onClick={toggleTheme} className={item}>
            {theme === "dark" ? t.lightMode : t.darkMode}
            <span aria-hidden="true">{theme === "dark" ? "☀️" : "🌙"}</span>
          </button>
          <label className={item}>
            {t.language}
            <select
              value={locale}
              onChange={(e) => isLocale(e.target.value) && setLocale(e.target.value)}
              aria-label={t.language}
              className="cursor-pointer rounded-md border border-stone-200 bg-transparent px-1.5 py-0.5 text-sm dark:border-stone-700"
            >
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </label>
          {isAdmin && (
            <a href="/admin" className={item}>
              {t.admin}
            </a>
          )}
          {user && (
            <form action="/auth/logout" method="post">
              <button className={`${item} text-red-700 dark:text-red-400`}>{t.signOut}</button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
