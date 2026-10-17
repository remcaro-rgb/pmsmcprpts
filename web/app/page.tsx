import { headers } from "next/headers";
import Chat from "@/components/Chat";
import { USER_HEADER } from "@/lib/auth";

export default async function Home() {
  // Set by proxy.ts when sign-in is on.
  const user = (await headers()).get(USER_HEADER);
  return <Chat user={user} />;
}
