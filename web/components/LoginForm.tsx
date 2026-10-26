"use client";

import { useEffect, useState } from "react";

const REMEMBER_KEY = "pms_login";

export type LoginLabels = Record<
  "loginLabel" | "passwordLabel" | "showPassword" | "hidePassword" | "rememberMe" | "signInButton",
  string
>;

/** The password sign-in form: show/hide password, and "remember me" keeps the email or ID on this
 * device. The password itself is never stored here; the browser's password manager offers to save
 * it (the fields carry the standard autocomplete hints). */
export function LoginForm({ returnTo, t }: { returnTo: string; t: LoginLabels }) {
  const [login, setLogin] = useState("");
  const [remember, setRemember] = useState(false);
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(REMEMBER_KEY);
      if (saved) {
        setLogin(saved);
        setRemember(true);
      }
    } catch {}
  }, []);

  function onSubmit() {
    try {
      if (remember) localStorage.setItem(REMEMBER_KEY, login.trim());
      else localStorage.removeItem(REMEMBER_KEY);
    } catch {}
  }

  const field =
    "mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900";
  return (
    <form action="/auth/password" method="post" onSubmit={onSubmit} className="mt-5 space-y-4">
      <input type="hidden" name="returnTo" value={returnTo} />
      <label className="block text-sm">
        <span className="font-medium">{t.loginLabel}</span>
        <input name="login" required autoComplete="username" autoFocus value={login}
          onChange={(e) => setLogin(e.target.value)} className={field} />
      </label>
      <div className="text-sm">
        <label htmlFor="password" className="font-medium">{t.passwordLabel}</label>
        <div className="relative">
          <input id="password" name="password" type={show ? "text" : "password"} required
            autoComplete="current-password" className={`${field} pr-10`} />
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? t.hidePassword : t.showPassword}
            aria-pressed={show}
            title={show ? t.hidePassword : t.showPassword}
            className="absolute inset-y-0 right-0 mt-1 flex w-10 items-center justify-center text-stone-500 hover:text-stone-800 dark:hover:text-stone-200"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5" fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
              <circle cx="12" cy="12" r="3" />
              {show && <path d="M4 4l16 16" />}
            </svg>
          </button>
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}
          className="size-4 accent-accent" />
        {t.rememberMe}
      </label>
      <button className="w-full rounded-lg bg-accent px-4 py-2 font-medium text-white hover:opacity-90">{t.signInButton}</button>
    </form>
  );
}
