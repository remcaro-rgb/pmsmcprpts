"""A minimal OpenID Connect provider for browser tests of website sign-in.

    python web/e2e/fake_oidc.py --port 8102 --client-id web --client-secret secret

The sign-in page asks for an email address and signs in as whoever is typed; the ID token
(RS256, with the request's nonce) carries that email. Authorization codes need PKCE (S256).
"""

import argparse
import base64
import hashlib
import html
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "test", "use": "sig", "alg": "RS256"}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class Provider(BaseHTTPRequestHandler):
    issuer = client_id = client_secret = ""
    codes: dict[str, dict] = {}

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: str | dict, content_type="application/json", headers=None):
        data = (json.dumps(body) if isinstance(body, dict) else body).encode()
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _form(self) -> dict[str, str]:
        raw = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/.well-known/openid-configuration":
            return self._send(200, {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/jwks",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            })
        if url.path == "/jwks":
            return self._send(200, {"keys": [JWK]})
        if url.path == "/authorize":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if q.get("client_id") != self.client_id or q.get("code_challenge_method") != "S256":
                return self._send(400, {"error": "invalid_request"})
            hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in q.items())
            return self._send(200, f"""<!doctype html><title>Test provider</title><h1>Test provider</h1>
<form method="post" action="/authorize">{hidden}<label>Email <input name="email" type="email"></label>
<button>Continue</button></form>""", "text/html")
        self._send(404, {"error": "not_found"})

    def do_POST(self):
        url = urlparse(self.path)
        form = self._form()
        if url.path == "/authorize":
            code = secrets.token_urlsafe(16)
            self.codes[code] = form
            target = form["redirect_uri"] + "?" + urlencode({"code": code, "state": form.get("state", "")})
            return self._send(302, "", "text/plain", {"location": target})
        if url.path == "/token":
            client_id, secret = form.get("client_id"), form.get("client_secret")
            if auth := self.headers.get("authorization"):
                client_id, secret = (unquote(p) for p in base64.b64decode(auth.split()[1]).decode().split(":", 1))
            if (client_id, secret) != (self.client_id, self.client_secret):
                return self._send(401, {"error": "invalid_client"})
            req = self.codes.pop(form.get("code", ""), None)
            if (not req or form.get("redirect_uri") != req["redirect_uri"]
                    or b64url(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != req["code_challenge"]):
                return self._send(400, {"error": "invalid_grant"})
            now = int(time.time())
            id_token = jwt.encode({
                "iss": self.issuer, "sub": hashlib.sha256(req["email"].encode()).hexdigest()[:16],
                "aud": self.client_id, "iat": now, "exp": now + 300, "nonce": req.get("nonce"),
                "email": req["email"], "email_verified": True,
            }, KEY, algorithm="RS256", headers={"kid": "test"})
            return self._send(200, {"access_token": secrets.token_urlsafe(16), "token_type": "Bearer",
                                    "expires_in": 300, "id_token": id_token}, headers={"cache-control": "no-store"})
        self._send(404, {"error": "not_found"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8102)
    parser.add_argument("--client-id", default="web")
    parser.add_argument("--client-secret", default="web-secret")
    args = parser.parse_args()
    Provider.issuer = f"http://127.0.0.1:{args.port}"
    Provider.client_id, Provider.client_secret = args.client_id, args.client_secret
    ThreadingHTTPServer(("127.0.0.1", args.port), Provider).serve_forever()


if __name__ == "__main__":
    main()
