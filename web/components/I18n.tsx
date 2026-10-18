"use client";

import { createContext, useContext, useState } from "react";
import { LOCALE_COOKIE, messages, type Locale, type Messages } from "@/lib/i18n";

type I18n = { locale: Locale; t: Messages; setLocale: (locale: Locale) => void };

const Context = createContext<I18n>({ locale: "en", t: messages("en"), setLocale: () => {} });

/** Website language: starts from the server's choice; switching remembers it in a cookie. */
export function I18nProvider({ initial, children }: { initial: Locale; children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initial);
  function setLocale(next: Locale) {
    setLocaleState(next);
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.lang = next === "es" ? "es-419" : "en";
  }
  return <Context.Provider value={{ locale, t: messages(locale), setLocale }}>{children}</Context.Provider>;
}

export const useI18n = () => useContext(Context);
