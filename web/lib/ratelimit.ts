/** In-memory sliding-window limiter (one Next.js server process). */
export class SlidingWindowLimiter {
  private hits = new Map<string, number[]>();
  private checks = 0;

  constructor(
    readonly limit: number,
    readonly windowMs: number,
    private now: () => number = Date.now,
  ) {}

  /** Records a hit for `key`; returns seconds to wait when over the limit, else 0. */
  check(key: string): number {
    const now = this.now();
    const hits = (this.hits.get(key) ?? []).filter((t) => t > now - this.windowMs);
    if (hits.length >= this.limit) {
      this.hits.set(key, hits);
      return Math.ceil((hits[0] + this.windowMs - now) / 1000);
    }
    hits.push(now);
    this.hits.set(key, hits);
    if (++this.checks % 1000 === 0) {
      for (const [k, v] of this.hits) if (!v.length || v[v.length - 1] <= now - this.windowMs) this.hits.delete(k);
    }
    return 0;
  }
}

/** Parses "20/600" (messages per seconds). */
export function parseLimit(spec: string | undefined, fallback = "20/600"): { limit: number; windowMs: number } {
  const [limit, seconds] = (spec || fallback).split("/").map(Number);
  if (!(limit > 0) || !(seconds > 0)) return parseLimit(undefined, fallback);
  return { limit, windowMs: seconds * 1000 };
}

/** Who a request counts against: the signed-in user, else the client IP (proxy header only if trusted). */
export function clientKey(headers: Headers, user: string | null, trustProxy: boolean): string {
  if (user) return `user:${user}`;
  const forwarded = trustProxy ? headers.get("x-forwarded-for")?.split(",")[0]?.trim() : undefined;
  return `ip:${forwarded || "local"}`;
}
