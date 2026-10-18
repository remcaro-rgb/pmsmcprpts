"""Per-client-IP rate limiting for the public HTTP endpoints (ASGI middleware, in memory).

Sliding window per (rule, client IP). Requests carrying the website's service token are exempt:
the website applies its own per-user limit before calling the agent.
"""

import hmac
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    prefixes: tuple[str, ...]
    limit: int
    window: float  # seconds


DEFAULT_RULES = (
    # Sign-in and registration: a person needs a handful of these per connection.
    Rule("auth", ("/register", "/authorize", "/token", "/revoke", "/oauth/"), limit=30, window=300),
    Rule("files", ("/files/",), limit=120, window=300),
    # Tool calls: one answer can take ~10 requests.
    Rule("mcp", ("/mcp",), limit=600, window=300),
)


class RateLimitMiddleware:
    def __init__(self, app, rules=DEFAULT_RULES, trust_proxy: bool = False, service_token: str | None = None,
                 clock=time.monotonic):
        self.app, self.rules, self.trust_proxy = app, rules, trust_proxy
        self.exempt = f"Bearer {service_token}".encode() if service_token else None
        self.clock = clock
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.checks = 0

    def _client(self, scope) -> str:
        headers = dict(scope.get("headers") or [])
        if self.trust_proxy and b"x-forwarded-for" in headers:
            # The proxy appends the address it saw; the left-most entry is the original client.
            return headers[b"x-forwarded-for"].decode().split(",")[0].strip()
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        rule = next((r for r in self.rules if path.startswith(r.prefixes)), None)
        if rule is None:
            return await self.app(scope, receive, send)
        auth = dict(scope.get("headers") or []).get(b"authorization", b"")
        # The website's agent: the service token, optionally followed by ":<user>".
        if (self.exempt and hmac.compare_digest(auth[: len(self.exempt)], self.exempt)
                and auth[len(self.exempt):len(self.exempt) + 1] in (b"", b":")):
            return await self.app(scope, receive, send)

        now = self.clock()
        hits = self.hits[(rule.name, self._client(scope))]
        while hits and hits[0] <= now - rule.window:
            hits.popleft()
        if len(hits) >= rule.limit:
            retry = int(hits[0] + rule.window - now) + 1
            body = json.dumps({"error": "rate_limited",
                               "error_description": f"Too many requests; try again in {retry} seconds."}).encode()
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", str(retry).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        hits.append(now)
        self.checks += 1
        if self.checks % 1000 == 0:  # drop idle clients so memory stays bounded
            for key in [k for k, q in self.hits.items() if not q or q[-1] <= now - 3600]:
                del self.hits[key]
        return await self.app(scope, receive, send)
