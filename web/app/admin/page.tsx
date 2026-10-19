import { headers } from "next/headers";
import AdminPanel from "@/components/AdminPanel";
import { I18nProvider } from "@/components/I18n";
import { currentAccount } from "@/lib/agent";
import { USER_HEADER } from "@/lib/auth";
import { messages } from "@/lib/i18n";
import { serverLocale } from "@/lib/request-prefs";

export const dynamic = "force-dynamic";

/** Users and hotels, for administrators. The agent checks again on every change. */
export default async function Admin() {
  const locale = await serverLocale();
  const account = await currentAccount((await headers()).get(USER_HEADER));
  if (!account?.is_admin) {
    const t = messages(locale);
    return (
      <main className="mx-auto mt-[12vh] w-full max-w-md px-4">
        <h1 className="text-xl font-semibold">{t.adminOnlyTitle}</h1>
        <p className="mt-2 text-sm text-stone-500">{t.adminOnlyBody}</p>
        <a href="/" className="mt-6 inline-block text-sm text-accent hover:underline">{t.backToChat}</a>
      </main>
    );
  }
  return (
    <I18nProvider initial={locale}>
      <AdminPanel me={account} />
    </I18nProvider>
  );
}
