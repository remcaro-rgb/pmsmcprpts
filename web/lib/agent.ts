import { USER_HEADER } from "./auth";
import { messages, requestLocale } from "./i18n";

export const AGENT_URL = process.env.AGENT_URL ?? "http://localhost:7001";

/** JSON request to the agent on behalf of the signed-in user (set by proxy.ts), relayed as-is. */
export async function relay(req: Request, path: string, method = "GET", body?: string): Promise<Response> {
  const user = req.headers.get(USER_HEADER);
  const headers: Record<string, string> = user ? { [USER_HEADER]: user } : {};
  if (body !== undefined) headers["content-type"] = "application/json";
  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_URL}${path}`, { method, headers, body });
  } catch {
    return Response.json({ detail: messages(requestLocale(req)).serviceUnreachable }, { status: 502 });
  }
  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
  });
}

/** The signed-in user's account in the user directory, or null (accounts off, or not a user). */
export async function currentAccount(user: string | null): Promise<Account | null> {
  if (!user) return null;
  try {
    const r = await fetch(`${AGENT_URL}/api/me`, { headers: { [USER_HEADER]: user }, cache: "no-store" });
    return r.ok ? ((await r.json()).user ?? null) : null;
  } catch {
    return null;
  }
}

export type Account = {
  id: number;
  uniqueid: string | null;
  name: string;
  email: string;
  phone: string | null;
  notes: string | null;
  is_admin: boolean;
  active: boolean;
  has_password: boolean;
  hotel_ids: number[];
  created_at: string;
};

export type Hotel = {
  id: number;
  code: string;
  name: string;
  city: string;
  country: string;
  alojamiento_id: number;
  pms_id: number;
};
