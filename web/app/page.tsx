import { headers } from "next/headers";
import Chat from "@/components/Chat";
import { I18nProvider } from "@/components/I18n";
import { currentAccount } from "@/lib/agent";
import { USER_HEADER } from "@/lib/auth";
import { serverLocale, serverTheme } from "@/lib/request-prefs";

export const dynamic = "force-dynamic";

export default async function Home() {
  // Set by proxy.ts when sign-in is on.
  const user = (await headers()).get(USER_HEADER);
  const account = await currentAccount(user);
  return (
    <I18nProvider initial={await serverLocale()}>
      <Chat user={user} isAdmin={!!account?.is_admin} theme={await serverTheme()} />
    </I18nProvider>
  );
}
