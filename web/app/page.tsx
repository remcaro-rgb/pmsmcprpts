import { headers } from "next/headers";
import Chat from "@/components/Chat";
import { I18nProvider } from "@/components/I18n";
import { USER_HEADER } from "@/lib/auth";
import { serverLocale } from "@/lib/locale-server";

export default async function Home() {
  // Set by proxy.ts when sign-in is on.
  const user = (await headers()).get(USER_HEADER);
  return (
    <I18nProvider initial={await serverLocale()}>
      <Chat user={user} />
    </I18nProvider>
  );
}
