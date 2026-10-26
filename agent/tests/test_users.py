"""User accounts: password hashing, sign-in, the administrator API and the chat check, against the
user directory in the test database (db/init/05_users.sh) as the pms_app role."""

import os
import secrets

import httpx2
import psycopg
import pytest

from fakes import FakeClient, text_reply
from pms_agent.app import create_app
from pms_agent.config import Settings
from pms_agent.users import UserDirectory, check_password, hash_password
from test_loop import toy_server

APP_DSN = os.environ.get("PMS_TEST_APP_DATABASE_URL")
needs_db = pytest.mark.skipif(not APP_DSN, reason="PMS_TEST_APP_DATABASE_URL not set")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_passwords():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert check_password("correct horse battery", stored)
    assert not check_password("correct horse batterY", stored)
    assert not check_password("anything", None) and not check_password("anything", "garbage")
    assert hash_password("same password") != hash_password("same password")  # salted


@pytest.fixture
async def site():
    """The agent with accounts on, an administrator, and a client; test accounts removed after."""
    tag = secrets.token_hex(4)
    email = lambda name: f"{name}-{tag}@agent.test"  # noqa: E731
    admin = await UserDirectory(APP_DSN).upsert_admin(email("boss"), "Boss", "boss-password-1")
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:", app_database_url=APP_DSN),
                     FakeClient(text_reply("Hi."), text_reply("Hi again.")), toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as http:
        try:
            yield http, email, {"x-pms-user": admin.email}
        finally:
            with psycopg.connect(APP_DSN, autocommit=True) as c:
                c.execute("DELETE FROM app.users WHERE email LIKE %s", (f"%-{tag}@agent.test",))


async def hotel_ids(http, as_admin) -> dict[str, int]:
    return {h["code"]: h["id"] for h in (await http.get("/api/admin/hotels", headers=as_admin)).json()["hotels"]}


@needs_db
@pytest.mark.anyio
async def test_administrators_manage_accounts(site):
    http, email, as_admin = site
    hotels = await hotel_ids(http, as_admin)
    assert set(hotels) == {"LIS", "BCN", "OPO"}

    new = {"name": "Ann Lee", "email": email("Ann").upper(), "phone": "+351 912 345 678", "notes": "Front office",
           "uniqueid": f"EMP-{email('x')}", "password": "ann-password-1", "hotel_ids": [hotels["LIS"]]}
    r = await http.post("/api/admin/users", json=new, headers=as_admin)
    assert r.status_code == 201, r.text
    ann = r.json()
    assert ann["email"] == email("ann") and ann["hotel_ids"] == [hotels["LIS"]] and not ann["is_admin"]
    assert ann["has_password"] and "password" not in ann and "password_hash" not in ann

    # Only administrators, checked against the directory each time.
    assert (await http.get("/api/admin/users")).status_code == 403
    assert (await http.get("/api/admin/users", headers={"x-pms-user": ann["email"]})).status_code == 403
    assert ann["email"] in {u["email"] for u in (await http.get("/api/admin/users", headers=as_admin)).json()["users"]}

    # Validation and duplicates.
    bad = [({**new, "password": "short"}, 422), ({**new, "email": "not-an-email"}, 422),
           ({**new, "phone": "call me"}, 422), ({**new, "email": email("h"), "uniqueid": None, "hotel_ids": [999999]}, 400),
           ({**new, "uniqueid": None}, 409),  # same email
           ({**new, "email": email("other")}, 409)]  # same uniqueid
    for body, status in bad:
        r = await http.post("/api/admin/users", json=body, headers=as_admin)
        assert r.status_code == status, (body, r.text)

    # Changing hotels, details and the password; fields not sent stay as they were.
    r = await http.patch(f"/api/admin/users/{ann['id']}", headers=as_admin,
                         json={"hotel_ids": [hotels["LIS"], hotels["OPO"]], "phone": "+351 000", "password": "new-password-22"})
    assert r.status_code == 200, r.text
    assert r.json()["hotel_ids"] == sorted([hotels["LIS"], hotels["OPO"]]) and r.json()["notes"] == "Front office"

    # Sign-in by email or unique ID.
    assert (await http.post("/api/auth/verify", json={"login": ann["email"], "password": "ann-password-1"})).status_code == 401
    ok = await http.post("/api/auth/verify", json={"login": ann["email"].upper(), "password": "new-password-22"})
    assert ok.status_code == 200 and ok.json()["email"] == ann["email"]
    assert (await http.post("/api/auth/verify", json={"login": new["uniqueid"], "password": "new-password-22"})).status_code == 200

    # Deactivated accounts can't sign in; deleted ones are gone.
    await http.patch(f"/api/admin/users/{ann['id']}", headers=as_admin, json={"active": False})
    assert (await http.post("/api/auth/verify", json={"login": ann["email"], "password": "new-password-22"})).status_code == 401
    assert (await http.get("/api/me", headers={"x-pms-user": ann["email"]})).json()["user"] is None
    assert (await http.delete(f"/api/admin/users/{ann['id']}", headers=as_admin)).status_code == 204
    assert (await http.patch(f"/api/admin/users/{ann['id']}", headers=as_admin, json={"name": "x"})).status_code == 404


@needs_db
@pytest.mark.anyio
async def test_administrators_keep_their_access(site):
    http, _, as_admin = site
    me = (await http.get("/api/me", headers=as_admin)).json()["user"]
    assert me["is_admin"]
    for change in ({"is_admin": False}, {"active": False}):
        r = await http.patch(f"/api/admin/users/{me['id']}", headers=as_admin, json=change)
        assert r.status_code == 400 and "yourself" in r.json()["detail"]
    assert (await http.delete(f"/api/admin/users/{me['id']}", headers=as_admin)).status_code == 400


@needs_db
@pytest.mark.anyio
async def test_sign_in_lockout(site):
    http, email, as_admin = site
    r = await http.post("/api/admin/users", headers=as_admin,
                        json={"name": "Bo", "email": email("bo"), "password": "bo-password-123"})
    assert r.status_code == 201
    for _ in range(10):
        assert (await http.post("/api/auth/verify", json={"login": email("bo"), "password": "wrong-wrong"})).status_code == 401
    r = await http.post("/api/auth/verify", json={"login": email("bo"), "password": "bo-password-123"})
    assert r.status_code == 429  # even the right password, until the window passes


@needs_db
@pytest.mark.anyio
async def test_hotel_ids(site):
    http, _, as_admin = site
    before = {h["code"]: h for h in (await http.get("/api/admin/hotels", headers=as_admin)).json()["hotels"]}
    lis, bcn = before["LIS"], before["BCN"]
    try:
        assert (await http.patch(f"/api/admin/hotels/{lis['id']}", headers=as_admin, json={"pms_id": 0})).status_code == 422
        assert (await http.patch(f"/api/admin/hotels/{lis['id']}", headers=as_admin,
                                 json={"alojamiento_id": -5})).status_code == 422
        r = await http.patch(f"/api/admin/hotels/{lis['id']}", headers=as_admin, json={"pms_id": bcn["pms_id"]})
        assert r.status_code == 409 and "pms_id" in r.json()["detail"]
        r = await http.patch(f"/api/admin/hotels/{lis['id']}", headers=as_admin, json={"alojamiento_id": 777001})
        assert r.status_code == 200 and r.json()["alojamiento_id"] == 777001 and r.json()["pms_id"] == lis["pms_id"]
        assert (await http.patch("/api/admin/hotels/999999", headers=as_admin, json={"pms_id": 9})).status_code == 404
    finally:
        await http.patch(f"/api/admin/hotels/{lis['id']}", headers=as_admin,
                         json={"alojamiento_id": lis["alojamiento_id"], "pms_id": lis["pms_id"]})


@needs_db
@pytest.mark.anyio
async def test_chat_needs_an_active_account(site):
    http, email, as_admin = site
    assert (await http.post("/api/chat", json={"message": "Hi"})).status_code == 401
    assert (await http.post("/api/chat", json={"message": "Hi"},
                            headers={"x-pms-user": email("stranger")})).status_code == 403
    r = await http.post("/api/admin/users", headers=as_admin,
                        json={"name": "Cy", "email": email("cy"), "password": "cy-password-123"})
    cy = {"x-pms-user": email("cy")}
    assert (await http.post("/api/chat", json={"message": "Hi"}, headers=cy)).status_code == 200
    await http.patch(f"/api/admin/users/{r.json()['id']}", headers=as_admin, json={"active": False})
    r = await http.post("/api/chat", json={"message": "Hi", "language": "es"}, headers=cy)
    assert r.status_code == 403 and "no está activa" in r.json()["detail"]


@pytest.mark.anyio
async def test_accounts_off_by_default():
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:", app_database_url=None),
                     FakeClient(text_reply("Hi.")), toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/api/me")).json() == {"directory": False, "user": None}
        assert (await http.get("/api/admin/users", headers={"x-pms-user": "a@b.c"})).status_code == 404
        assert (await http.post("/api/auth/verify", json={"login": "a", "password": "b"})).status_code == 404
        assert (await http.post("/api/chat", json={"message": "Hi"})).status_code == 200
