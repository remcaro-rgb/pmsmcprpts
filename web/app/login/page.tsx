import { redirect } from "next/navigation";
import { authConfig, safeReturnTo } from "@/lib/auth";
import { messages } from "@/lib/i18n";
import { serverLocale } from "@/lib/request-prefs";

export const dynamic = "force-dynamic";

/** Password sign-in (WEB_AUTH=password); the form posts to /auth/password. */
export default async function Login({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const params = await searchParams;
  const returnTo = safeReturnTo(params.returnTo ?? null);
  if (authConfig()?.mode !== "password") redirect(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
  const t = messages(await serverLocale());
  const error = params.error ? t.signInErrors[params.error] ?? t.signInErrors.invalid : null;
  return (
    <main className="mx-auto mt-[12vh] w-full max-w-sm px-4">
      <div className="flex size-10 items-center justify-center rounded-xl bg-accent text-lg font-bold text-white">P</div>
      <h1 className="mt-4 text-xl font-semibold">{t.signInTitle}</h1>
      <p className="mt-1 text-sm text-stone-500">{t.signInIntro}</p>
      {error && (
        <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}
      <form action="/auth/password" method="post" className="mt-5 space-y-4">
        <input type="hidden" name="returnTo" value={returnTo} />
        <label className="block text-sm">
          <span className="font-medium">{t.loginLabel}</span>
          <input name="login" required autoComplete="username" autoFocus
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900" />
        </label>
        <label className="block text-sm">
          <span className="font-medium">{t.passwordLabel}</span>
          <input name="password" type="password" required autoComplete="current-password"
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900" />
        </label>
        <button className="w-full rounded-lg bg-accent px-4 py-2 font-medium text-white hover:opacity-90">{t.signInButton}</button>
      </form>
    </main>
  );
}
