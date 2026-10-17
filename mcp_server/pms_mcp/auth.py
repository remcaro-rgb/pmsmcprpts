"""Sign-in for remote users, e.g. people adding this server as a custom connector in Claude.

The MCP server is its own OAuth 2.1 authorization server (dynamic client registration, PKCE),
as MCP clients expect, and delegates the actual login to an OpenID Connect provider (Google,
Microsoft Entra, Auth0, Okta, Keycloak, ...). Only users on an allowlist get in.

    Claude --/authorize--> this server --redirect--> OIDC provider (login)
    OIDC provider --/oauth/callback--> this server (checks the allowlist) --code--> Claude
    Claude --/token--> this server --access token (subject = user's email)--> Claude

Clients, codes and tokens live in a small SQLite file; codes and tokens are stored hashed.
"""

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx2
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

SCOPE = "pms"
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
CODE_TTL = 300
LOGIN_TTL = 600
LINK_TTL = 24 * 3600
ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
LOCAL_USER = "local"  # stdio / unauthenticated deployments
SERVICE_USER = "website"  # the website's agent, via the service token


def current_user() -> str:
    """Who is calling the current tool: the signed-in user's email, or a fixed owner."""
    token = get_access_token()
    return token.subject if token and token.subject else LOCAL_USER


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _csv(value: str | None) -> set[str]:
    return {v.strip().lower() for v in (value or "").split(",") if v.strip()}


@dataclass
class AuthConfig:
    public_url: str  # e.g. https://pms.example.com; the MCP endpoint is {public_url}/mcp
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    allowed_emails: set[str] = field(default_factory=set)
    allowed_domains: set[str] = field(default_factory=set)
    allow_any_user: bool = False
    db_path: str = "pms-auth.sqlite"
    service_token: str | None = None  # lets the website's agent call the server
    signing_key: str | None = None  # for download links; generated and stored if unset

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AuthConfig | None":
        """None when PMS_PUBLIC_URL is unset (local use without sign-in)."""
        public_url = env.get("PMS_PUBLIC_URL", "").rstrip("/")
        if not public_url:
            return None
        missing = [k for k in ("PMS_OIDC_ISSUER", "PMS_OIDC_CLIENT_ID", "PMS_OIDC_CLIENT_SECRET") if not env.get(k)]
        if missing:
            raise ValueError(f"PMS_PUBLIC_URL is set, so sign-in is on; also set {', '.join(missing)}.")
        config = cls(
            public_url=public_url,
            oidc_issuer=env["PMS_OIDC_ISSUER"].rstrip("/"),
            oidc_client_id=env["PMS_OIDC_CLIENT_ID"],
            oidc_client_secret=env["PMS_OIDC_CLIENT_SECRET"],
            allowed_emails=_csv(env.get("PMS_ALLOWED_EMAILS")),
            allowed_domains=_csv(env.get("PMS_ALLOWED_DOMAINS")),
            allow_any_user=env.get("PMS_ALLOW_ANY_USER", "").lower() == "true",
            db_path=env.get("PMS_AUTH_DB", "pms-auth.sqlite"),
            service_token=env.get("PMS_MCP_SERVICE_TOKEN") or None,
            signing_key=env.get("PMS_SIGNING_KEY") or None,
        )
        if not (config.allowed_emails or config.allowed_domains or config.allow_any_user):
            raise ValueError("Set PMS_ALLOWED_EMAILS and/or PMS_ALLOWED_DOMAINS to say who may connect "
                             "(or PMS_ALLOW_ANY_USER=true to accept any account the provider signs in).")
        if config.service_token is not None and len(config.service_token) < 32:
            raise ValueError("PMS_MCP_SERVICE_TOKEN must be at least 32 characters (openssl rand -hex 32).")
        return config

    @property
    def callback_url(self) -> str:
        return f"{self.public_url}/oauth/callback"

    def allows(self, email: str) -> bool:
        email = email.lower()
        return (self.allow_any_user or email in self.allowed_emails
                or email.rsplit("@", 1)[-1] in self.allowed_domains)


class AuthStore:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logins (state TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS codes (code_hash TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, pair_hash TEXT, client_id TEXT NOT NULL,
                subject TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()

    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        cur = self.db.execute(sql, args)
        self.db.commit()
        return cur

    def setting(self, key: str, default: Callable[[], str]) -> str:
        row = self.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row:
            return row[0]
        value = default()
        self.execute("INSERT INTO settings VALUES (?, ?)", (key, value))
        return value

    def purge(self) -> None:
        now = time.time()
        for table in ("logins", "codes", "tokens"):
            self.execute(f"DELETE FROM {table} WHERE expires < ?", (now,))


class OIDCAuthProvider:
    """OAuthAuthorizationServerProvider that signs users in through an OIDC provider."""

    def __init__(self, config: AuthConfig, http_client: Callable[[], httpx2.AsyncClient] | None = None):
        self.config = config
        self.store = AuthStore(config.db_path)
        self.signing_key = (config.signing_key or self.store.setting("signing_key", lambda: secrets.token_hex(32))).encode()
        self._http = http_client or (lambda: httpx2.AsyncClient(timeout=15))
        self._discovery: dict | None = None
        self._jwks: jwt.PyJWKSet | None = None

    # ---------- OIDC provider metadata ----------

    async def discovery(self) -> dict:
        if self._discovery is None:
            async with self._http() as http:
                r = await http.get(f"{self.config.oidc_issuer}/.well-known/openid-configuration")
                r.raise_for_status()
                self._discovery = r.json()
        return self._discovery

    async def _signing_key(self, kid: str | None) -> jwt.PyJWK:
        for attempt in range(2):
            if self._jwks is None or attempt:
                async with self._http() as http:
                    r = await http.get((await self.discovery())["jwks_uri"])
                    r.raise_for_status()
                    self._jwks = jwt.PyJWKSet.from_dict(r.json())
            for key in self._jwks.keys:
                if kid is None or key.key_id == kid:
                    return key
        raise ValueError("The ID token was signed with an unknown key.")

    # ---------- client registration ----------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.store.execute("SELECT data FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.store.execute("INSERT OR REPLACE INTO clients VALUES (?, ?)",
                           (client_info.client_id, client_info.model_dump_json()))

    # ---------- authorization: hand off to the OIDC provider ----------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        try:
            meta = await self.discovery()
        except httpx2.HTTPError as e:
            raise AuthorizeError("temporarily_unavailable", "The sign-in provider is unreachable.") from e
        self.store.purge()
        state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(16)
        login = {"client_id": client.client_id, "params": params.model_dump(mode="json"),
                 "verifier": verifier, "nonce": nonce}
        self.store.execute("INSERT INTO logins VALUES (?, ?, ?)", (state, json.dumps(login), time.time() + LOGIN_TTL))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return meta["authorization_endpoint"] + "?" + urlencode({
            "response_type": "code",
            "client_id": self.config.oidc_client_id,
            "redirect_uri": self.config.callback_url,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    async def handle_callback(self, request: Request) -> Response:
        """GET /oauth/callback: the OIDC provider returns here after the user signs in."""
        state = request.query_params.get("state", "")
        row = self.store.execute("SELECT data, expires FROM logins WHERE state = ?", (state,)).fetchone()
        self.store.execute("DELETE FROM logins WHERE state = ?", (state,))
        if not row or row[1] < time.time():
            return _page("Sign-in expired", "This sign-in link has expired. Start connecting again from Claude.", 400)
        login = json.loads(row[0])
        params = AuthorizationParams.model_validate(login["params"])

        def back_to_client(**query: str | None) -> Response:
            return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), state=params.state, **query), 302)

        if request.query_params.get("error"):
            return back_to_client(error="access_denied", error_description="Sign-in was cancelled or failed.")
        try:
            email = await self._verified_email(request.query_params.get("code", ""), login)
        except (httpx2.HTTPError, jwt.PyJWTError, ValueError, KeyError) as e:
            return _page("Sign-in failed", f"We could not verify your sign-in: {e}", 400)
        if not self.config.allows(email):
            return _page("Access not allowed",
                         f"{email} is not allowed to use this hotel reporting server. Ask the administrator "
                         "to add your account, then connect again.", 403)

        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code, scopes=params.scopes or [SCOPE], expires_at=time.time() + CODE_TTL,
            client_id=login["client_id"], code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri, redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource, subject=email,
        )
        self.store.execute("INSERT INTO codes VALUES (?, ?, ?)",
                           (_hash(code), auth_code.model_dump_json(), auth_code.expires_at))
        return back_to_client(code=code)

    async def _verified_email(self, code: str, login: dict) -> str:
        meta = await self.discovery()
        async with self._http() as http:
            r = await http.post(meta["token_endpoint"], data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.callback_url,
                "client_id": self.config.oidc_client_id,
                "client_secret": self.config.oidc_client_secret,
                "code_verifier": login["verifier"],
            }, headers={"Accept": "application/json"})
            r.raise_for_status()
        id_token = r.json()["id_token"]
        key = await self._signing_key(jwt.get_unverified_header(id_token).get("kid"))
        # Asymmetric algorithms only, so a forged HS256 token can't use the public key as a secret.
        claims = jwt.decode(id_token, key, algorithms=ID_TOKEN_ALGORITHMS, audience=self.config.oidc_client_id,
                            issuer=meta["issuer"], options={"require": ["exp", "iat", "sub"]})
        if not hmac.compare_digest(claims.get("nonce", ""), login["nonce"]):
            raise ValueError("nonce mismatch")
        email = claims.get("email") or claims.get("preferred_username")
        if not email or "@" not in email:
            raise ValueError("the provider did not share an email address")
        if claims.get("email_verified") is False:
            raise ValueError(f"the email address {email} is not verified")
        return email.lower()

    # ---------- codes and tokens ----------

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        row = self.store.execute("SELECT data, expires FROM codes WHERE code_hash = ?",
                                 (_hash(authorization_code),)).fetchone()
        if not row or row[1] < time.time():
            return None
        code = AuthorizationCode.model_validate_json(row[0])
        return code if code.client_id == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        deleted = self.store.execute("DELETE FROM codes WHERE code_hash = ?", (_hash(authorization_code.code),))
        if deleted.rowcount != 1:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.subject or "", authorization_code.scopes,
                           authorization_code.resource)

    def _issue(self, client_id: str, subject: str, scopes: list[str], resource: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        rows = [(_hash(access), "access", _hash(refresh), client_id, subject, json.dumps(scopes), resource,
                 now + ACCESS_TTL),
                (_hash(refresh), "refresh", _hash(access), client_id, subject, json.dumps(scopes), resource,
                 now + REFRESH_TTL)]
        self.store.db.executemany("INSERT INTO tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.store.db.commit()
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL,
                          refresh_token=refresh, scope=" ".join(scopes))

    def _load(self, token: str, kind: str) -> tuple | None:
        row = self.store.execute(
            "SELECT client_id, subject, scopes, resource, expires FROM tokens WHERE token_hash = ? AND kind = ?",
            (_hash(token), kind)).fetchone()
        if not row or row[4] < time.time() or not self.config.allows(row[1]):
            return None
        return row

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = self._load(refresh_token, "refresh")
        if not row or row[0] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=row[0], subject=row[1], scopes=json.loads(row[2]),
                            resource=row[3], expires_at=int(row[4]))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        await self.revoke_token(refresh_token)  # rotate
        return self._issue(client.client_id, refresh_token.subject or "", scopes or refresh_token.scopes,
                           refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if self.config.service_token and hmac.compare_digest(token, self.config.service_token):
            return AccessToken(token=token, client_id=SERVICE_USER, scopes=[SCOPE], subject=SERVICE_USER,
                               resource=f"{self.config.public_url}/mcp")
        row = self._load(token, "access")
        if not row:
            return None
        return AccessToken(token=token, client_id=row[0], subject=row[1], scopes=json.loads(row[2]),
                           resource=row[3], expires_at=int(row[4]))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        h = _hash(token.token)
        row = self.store.execute("SELECT pair_hash FROM tokens WHERE token_hash = ?", (h,)).fetchone()
        self.store.execute("DELETE FROM tokens WHERE token_hash IN (?, ?)", (h, row[0] if row else h))

    # ---------- signed download links ----------

    def _signature(self, file_id: str, expires: int) -> str:
        return hmac.new(self.signing_key, f"{file_id}:{expires}".encode(), hashlib.sha256).hexdigest()[:40]

    def download_url(self, file_id: str) -> str:
        expires = int(time.time()) + LINK_TTL
        return f"{self.config.public_url}/files/{file_id}?exp={expires}&sig={self._signature(file_id, expires)}"

    def link_is_valid(self, file_id: str, expires: str, signature: str) -> bool:
        if not expires.isdigit() or int(expires) < time.time():
            return False
        return hmac.compare_digest(self._signature(file_id, int(expires)), signature)


def _page(title: str, message: str, status: int) -> HTMLResponse:
    from html import escape

    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><body style='font-family:system-ui,sans-serif;max-width:32rem;"
        f"margin:15vh auto;padding:0 1rem;color:#0b0b0b'><h1 style='font-size:1.4rem'>{escape(title)}</h1>"
        f"<p style='color:#52514e;line-height:1.5'>{escape(message)}</p></body>",
        status_code=status)
