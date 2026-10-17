import * as client from "openid-client";
import type { AuthConfig } from "./auth";

let cached: { key: string; config: Promise<client.Configuration> } | null = null;

/** Provider metadata (discovery), fetched once per process. */
export function oidcClient(auth: AuthConfig): Promise<client.Configuration> {
  const key = `${auth.issuer}|${auth.clientId}`;
  if (!cached || cached.key !== key) {
    const config = client.discovery(new URL(auth.issuer), auth.clientId, auth.clientSecret, undefined,
      auth.allowHttp ? { execute: [client.allowInsecureRequests] } : undefined);
    config.catch(() => { cached = null; }); // retry discovery on the next login
    cached = { key, config };
  }
  return cached.config;
}

export const redirectUri = (auth: AuthConfig) => `${auth.publicUrl}/auth/callback`;
