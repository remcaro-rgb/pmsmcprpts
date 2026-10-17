import { messages } from "@/lib/i18n";
import { serverLocale } from "@/lib/locale-server";

export default async function SignedOut() {
  const t = messages(await serverLocale());
  return (
    <main className="mx-auto mt-[15vh] max-w-md px-4">
      <h1 className="text-xl font-semibold">{t.signedOutTitle}</h1>
      <p className="mt-2 text-stone-500">{t.signedOutBody}</p>
      <p className="mt-4">
        <a href="/auth/login" className="text-accent underline">{t.signInAgain}</a>
      </p>
    </main>
  );
}
