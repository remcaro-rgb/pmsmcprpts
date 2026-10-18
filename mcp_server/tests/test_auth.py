"""Remote sign-in, end to end over HTTP: an MCP client registers, signs in through a fake OIDC
provider, gets tokens and calls tools; users' data is kept apart; download links are signed.

Needs a seeded database: PMS_TEST_DATABASE_URL=postgresql://pms_readonly:...@localhost:5432/pms
"""

import asyncio
import base64
import hashlib
import os
import secrets
import socket
import time
from urllib.parse import parse_qs, urlparse

import httpx2
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from pms_mcp.auth import SERVICE_USER, AuthConfig, service_token_user
from pms_mcp.server import build_server

DSN = os.environ.get("PMS_TEST_DATABASE_URL")
pytestmark = [pytest.mark.anyio, pytest.mark.skipif(not DSN, reason="PMS_TEST_DATABASE_URL not set")]

ISSUER = "https://login.example.test"
CLIENT_ID = "pms-oidc-client"
REDIRECT = "http://localhost:6274/callback"  # the MCP client's (e.g. Claude's) redirect URI
SERVICE_TOKEN = "s" * 40


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeOIDC:
    """Discovery, JWKS and token endpoint of an OIDC provider, as an httpx2 mock transport."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.logins: dict[str, tuple[str, str]] = {}  # upstream code -> (email, nonce)

    def sign_in(self, email: str, nonce: str) -> str:
        code = secrets.token_urlsafe(8)
        self.logins[code] = (email, nonce)
        return code

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx2.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks"})
        if path == "/jwks":
            jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return httpx2.Response(200, json={"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]})
        if path == "/token":
            form = parse_qs(request.content.decode())
            assert form["client_secret"] == ["oidc-secret"] and form["code_verifier"][0]
            email, nonce = self.logins.pop(form["code"][0])
            now = int(time.time())
            id_token = jwt.encode({"iss": ISSUER, "aud": CLIENT_ID, "sub": email, "email": email,
                                   "email_verified": True, "nonce": nonce, "iat": now, "exp": now + 300},
                                  self.key, algorithm="RS256", headers={"kid": "k1"})
            return httpx2.Response(200, json={"id_token": id_token, "access_token": "upstream"})
        return httpx2.Response(404)


@pytest.fixture
async def server(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    oidc = FakeOIDC()
    config = AuthConfig(public_url=base, oidc_issuer=ISSUER, oidc_client_id=CLIENT_ID,
                        oidc_client_secret="oidc-secret", allowed_emails={"alice@gmail.com"},
                        allowed_domains={"hotel.example"}, db_path=str(tmp_path / "auth.sqlite"),
                        service_token=SERVICE_TOKEN)
    mcp = build_server(DSN, artifacts_dir=str(tmp_path / "files"), auth=config,
                       oidc_http_client=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(oidc.handler)))
    app = mcp.streamable_http_app(host="127.0.0.1")
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(uv.serve())
    while not uv.started:
        await asyncio.sleep(0.05)
    async with httpx2.AsyncClient(base_url=base) as http:
        yield http, oidc, base
    uv.should_exit = True
    await task


async def sign_in(http, oidc, email: str) -> dict:
    """Run the connector flow a client like Claude performs; returns the token response."""
    reg = (await http.post("/register", json={
        "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none", "client_name": "test",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})).json()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = await http.get("/authorize", params={
        "response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT, "state": "client-state",
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": "pms"})
    assert r.status_code == 302
    upstream = urlparse(r.headers["location"])
    assert f"{upstream.scheme}://{upstream.netloc}{upstream.path}" == f"{ISSUER}/authorize"
    q = parse_qs(upstream.query)
    assert q["client_id"] == [CLIENT_ID] and q["code_challenge_method"] == ["S256"]

    r = await http.get("/oauth/callback", params={"code": oidc.sign_in(email, q["nonce"][0]), "state": q["state"][0]})
    if r.status_code != 302:
        return {"status": r.status_code, "body": r.text}
    back = urlparse(r.headers["location"])
    assert back.geturl().startswith(REDIRECT)
    params = parse_qs(back.query)
    assert params["state"] == ["client-state"]
    r = await http.post("/token", data={
        "grant_type": "authorization_code", "code": params["code"][0], "redirect_uri": REDIRECT,
        "client_id": reg["client_id"], "code_verifier": verifier})
    assert r.status_code == 200, r.text
    return {**r.json(), "client_id": reg["client_id"]}


async def test_confidential_client_without_scope(server):
    """The way ChatGPT connects: a confidential client (client_secret_post) that registers and
    authorizes without a scope and names the resource; tokens still carry the pms scope."""
    http, oidc, base = server
    redirect = "https://chatgpt.example/connector/oauth_redirect"
    reg = (await http.post("/register", json={
        "redirect_uris": [redirect], "token_endpoint_auth_method": "client_secret_post",
        "client_name": "ChatGPT-like", "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"]})).json()
    assert reg.get("client_secret")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = await http.get("/authorize", params={
        "response_type": "code", "client_id": reg["client_id"], "redirect_uri": redirect, "state": "s1",
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": f"{base}/mcp"})
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    r = await http.get("/oauth/callback", params={"code": oidc.sign_in("alice@gmail.com", q["nonce"][0]),
                                                  "state": q["state"][0]})
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    token = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
             "client_id": reg["client_id"], "code_verifier": verifier, "resource": f"{base}/mcp"}
    assert (await http.post("/token", data=token)).status_code == 401  # the secret is required
    r = await http.post("/token", data={**token, "client_secret": reg["client_secret"]})
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["scope"] == "pms" and tokens["refresh_token"]
    async with mcp_client(base, tokens["access_token"]) as c:
        assert not (await c.call_tool("describe_schema", {"table": "hotels"})).is_error
    r = await http.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                        "client_id": reg["client_id"], "client_secret": reg["client_secret"]})
    assert r.status_code == 200, r.text


def mcp_client(base: str, token: str) -> Client:
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    return Client(streamable_http_client(f"{base}/mcp", http_client=http))


async def test_requires_sign_in(server):
    http, _, _ = server
    r = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert "resource_metadata" in r.headers["www-authenticate"]
    r = await http.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    meta = (await http.get("/.well-known/oauth-authorization-server")).json()
    assert meta["registration_endpoint"].endswith("/register")
    assert "S256" in meta["code_challenge_methods_supported"]


async def test_signed_in_user_calls_tools_and_downloads(server):
    http, oidc, base = server
    tokens = await sign_in(http, oidc, "Alice@Gmail.com")
    assert tokens["token_type"].lower() == "bearer" and tokens["refresh_token"]
    async with mcp_client(base, tokens["access_token"]) as c:
        r = await c.call_tool("run_sql", {"query": "SELECT code, total_rooms FROM hotels ORDER BY id"})
        assert not r.is_error and r.structured_content["row_count"] == 3
        chart = await c.call_tool("make_chart", {"dataset_id": r.structured_content["dataset_id"], "x": "code",
                                                 "y": "total_rooms", "chart_type": "bar", "title": "Rooms"})
        assert not chart.is_error, chart.content[0].text
        assert [b.type for b in chart.content] == ["text", "image"]
        url = chart.structured_content["file"]["download_url"]
        assert url.startswith(f"{base}/files/") and "download_url" in chart.content[0].text

    png = await http.get(url)
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert png.headers["content-disposition"].startswith("inline")
    assert (await http.get(url.replace("sig=", "sig=0"))).status_code == 403
    expired = url.split("?")[0] + "?exp=1&sig=" + url.split("sig=")[1]
    assert (await http.get(expired)).status_code == 403


async def test_users_cannot_see_each_others_data(server):
    http, oidc, base = server
    alice = await sign_in(http, oidc, "alice@gmail.com")
    bob = await sign_in(http, oidc, "bob@hotel.example")  # allowed by domain
    async with mcp_client(base, alice["access_token"]) as c:
        ds = (await c.call_tool("run_sql", {"query": "SELECT 1 AS x"})).structured_content["dataset_id"]
        assert not (await c.call_tool("get_dataset", {"dataset_id": ds})).is_error
    async with mcp_client(base, bob["access_token"]) as c:
        r = await c.call_tool("get_dataset", {"dataset_id": ds})
        assert r.is_error and "Unknown or expired" in r.content[0].text


async def test_unlisted_user_is_refused(server):
    http, oidc, _ = server
    result = await sign_in(http, oidc, "eve@gmail.com")
    assert result["status"] == 403 and "not allowed" in result["body"]


async def test_refresh_rotates_tokens_and_revoke(server):
    http, oidc, base = server
    first = await sign_in(http, oidc, "alice@gmail.com")
    r = await http.post("/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"],
                                        "client_id": first["client_id"]})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["access_token"] != first["access_token"]
    # The old refresh token and its access token are gone.
    again = await http.post("/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"],
                                            "client_id": first["client_id"]})
    assert again.status_code == 400
    assert (await http.post("/mcp", json={}, headers={"Authorization": f"Bearer {first['access_token']}"})
            ).status_code == 401
    async with mcp_client(base, second["access_token"]) as c:
        assert not (await c.call_tool("describe_schema", {"table": "hotels"})).is_error


async def test_service_token_for_the_website(server):
    _, _, base = server
    async with mcp_client(base, SERVICE_TOKEN) as c:
        r = await c.call_tool("get_kpis", {"start": "2026-01-01", "end": "2026-01-31", "by_hotel": False})
        assert not r.is_error
    # Acting for a website user: their own dataset store, and other users can't read it.
    ann = SERVICE_TOKEN + ":" + base64.urlsafe_b64encode(b"ann@hotel.example").decode().rstrip("=")
    bob = SERVICE_TOKEN + ":" + base64.urlsafe_b64encode(b"bob@hotel.example").decode().rstrip("=")
    async with mcp_client(base, ann) as c:
        r = await c.call_tool("run_sql", {"query": "SELECT code FROM pms.hotels ORDER BY code"})
        dataset_id = r.structured_content["dataset_id"]
        assert not (await c.call_tool("get_dataset", {"dataset_id": dataset_id})).is_error
    async with mcp_client(base, bob) as c:
        assert (await c.call_tool("get_dataset", {"dataset_id": dataset_id})).is_error


def test_service_token_user():
    token = "s" * 40
    assert service_token_user(token, token) == SERVICE_USER
    assert service_token_user(token + ":YW5uQGhvdGVsLmV4YW1wbGU", token) == "ann@hotel.example"
    assert service_token_user("x" * 40, token) is None
    assert service_token_user(token + "extra", token) is None
    assert service_token_user(token[:-1], token) is None
    assert service_token_user(token + ":bm90LWFuLWVtYWls", token) is None  # "not-an-email"
    assert service_token_user(token + ":%%%", token) is None


def test_config_from_env():
    assert AuthConfig.from_env({}) is None
    base = {"PMS_PUBLIC_URL": "https://pms.example.com/", "PMS_OIDC_ISSUER": ISSUER,
            "PMS_OIDC_CLIENT_ID": "id", "PMS_OIDC_CLIENT_SECRET": "secret"}
    with pytest.raises(ValueError, match="PMS_ALLOWED_EMAILS"):
        AuthConfig.from_env(base)
    with pytest.raises(ValueError, match="PMS_OIDC_CLIENT_SECRET"):
        AuthConfig.from_env({**base, "PMS_OIDC_CLIENT_SECRET": ""})
    with pytest.raises(ValueError, match="at least 32"):
        AuthConfig.from_env({**base, "PMS_ALLOW_ANY_USER": "true", "PMS_MCP_SERVICE_TOKEN": "short"})
    config = AuthConfig.from_env({**base, "PMS_ALLOWED_DOMAINS": "Hotel.Example, other.example"})
    assert config.public_url == "https://pms.example.com"
    assert config.callback_url == "https://pms.example.com/oauth/callback"
    assert config.allows("Ann@hotel.example") and not config.allows("ann@evil.example")
