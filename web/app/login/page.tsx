import { redirect } from "next/navigation";
import { GoliattWordmark } from "@/components/Logo";
import { LoginForm } from "@/components/LoginForm";
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
      <div className="flex justify-center rounded-2xl bg-accent px-6 py-7 text-white">
        <GoliattWordmark className="h-12" />
      </div>
      <h1 className="mt-6 text-xl font-semibold">{t.signInTitle}</h1>
      <p className="mt-1 text-sm text-stone-500">{t.signInIntro}</p>
      {error && (
        <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}
      <LoginForm
        returnTo={returnTo}
        t={{
          loginLabel: t.loginLabel,
          passwordLabel: t.passwordLabel,
          showPassword: t.showPassword,
          hidePassword: t.hidePassword,
          rememberMe: t.rememberMe,
          signInButton: t.signInButton,
        }}
      />
    </main>
  );
}
