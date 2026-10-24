"""FastAPI service: POST /api/chat streams a Claude answer as server-sent events."""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .conversations import ConversationStore
from .digest import Digest
from .prompts import MESSAGES
from .loop import ChatAgent
from .recommend import DailyRecommendations, Overviews
from .users import MIN_PASSWORD, User, UserDirectory, UserError

log = logging.getLogger(__name__)

FILE_ID = re.compile(r"^[0-9a-f]{32}$")


HOTEL_CODE = r"^[A-Za-z0-9_-]{1,12}$"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=64)
    # Website language: "es" answers in Latin American Spanish.
    language: Literal["en", "es"] = "en"
    # The hotel picked in the website's header (a code), assumed unless the question names others.
    hotel: str | None = Field(default=None, pattern=HOTEL_CODE)


class ConversationChange(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None


class Prefs(BaseModel):
    digest: bool | None = None
    language: Literal["en", "es"] | None = None
    hotel: str | None = Field(default=None, pattern=HOTEL_CODE)


class DigestTest(BaseModel):
    language: Literal["en", "es"] = "en"
    hotel: str | None = Field(default=None, pattern=HOTEL_CODE)


class Feedback(BaseModel):
    kind: Literal["answer", "recommendation"]
    ref: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_:.\-]+$")
    value: Literal["up", "down", "done"] | None = None
    note: str = Field(default="", max_length=1000)


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^[0-9+()\-.\s]{3,40}$")


class UserFields(BaseModel):
    """Fields an administrator sets on an account; on update, only the ones sent change."""
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    uniqueid: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=200)
    is_admin: bool | None = None
    active: bool | None = None
    hotel_ids: list[int] | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and v.strip() and not EMAIL.match(v.strip()):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is not None and v.strip() and not PHONE.match(v.strip()):
            raise ValueError("Use digits, spaces and + ( ) - . only.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        if v and len(v) < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters.")
        return v


class NewUser(UserFields):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class HotelIds(BaseModel):
    alojamiento_id: int | None = Field(default=None, gt=0, le=2_147_483_647)
    pms_id: int | None = Field(default=None, gt=0, le=2_147_483_647)


class SignIn(BaseModel):
    login: str = Field(min_length=1, max_length=254)  # email or unique ID
    password: str = Field(min_length=1, max_length=200)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _user(header: str | None) -> str | None:
    """The signed-in website user. The website sets this header from its session and strips it from
    browser requests; the agent is only reachable from the website, so it can be trusted here."""
    return header.strip().lower() if header and header.strip() else None


def create_app(settings: Settings | None = None, client: Any = None, mcp_target: Any = None) -> FastAPI:
    settings = settings or Settings()
    agent = ChatAgent(settings, client or anthropic.AsyncAnthropic(), mcp_target)
    store = ConversationStore(settings.conversations_db)
    daily = DailyRecommendations(agent, settings.timezone)
    overviews = Overviews(agent)
    directory = UserDirectory(settings.app_database_url) if settings.app_database_url else None
    failures: dict[str, list[float]] = {}  # sign-in failures per login, for a simple lockout

    def need_directory() -> UserDirectory:
        if directory is None:
            raise HTTPException(404, "User accounts are not enabled (set PMS_APP_DATABASE_URL).")
        return directory

    async def admin(x_pms_user: str | None = Header(default=None)) -> User:
        """The signed-in administrator, checked against the directory on every request."""
        directory = need_directory()
        email = _user(x_pms_user)
        account = await directory.get_by_email(email) if email else None
        if account is None or not account.active or not account.is_admin:
            raise HTTPException(403, "Only administrators can do this.")
        return account

    def user_error(e: UserError) -> HTTPException:
        return HTTPException(e.status, str(e))

    async def display_name(email: str) -> str | None:
        account = await directory.get_by_email(email) if directory else None
        return account.name if account else None

    digest = Digest(settings, store, overviews, daily, names=display_name)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(digest.run()) if digest.available else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="PMS Reports agent", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": settings.model}

    @app.get("/files/{file_id}")
    async def download(file_id: str) -> FileResponse:
        """Files generated by the MCP server's document tools (shared artifacts directory)."""
        root = Path(settings.artifacts_dir)
        if not FILE_ID.match(file_id) or not (root / file_id).is_file():
            raise HTTPException(404, "File not found or expired.")
        meta = json.loads((root / f"{file_id}.json").read_text())
        inline = meta["mime"].startswith("image/")
        return FileResponse(root / file_id, media_type=meta["mime"], filename=meta["filename"],
                            content_disposition_type="inline" if inline else "attachment")

    @app.post("/api/auth/verify")
    async def verify(body: SignIn) -> dict[str, Any]:
        """Password sign-in for the website. At most 10 failures per login in 15 minutes."""
        directory = need_directory()
        key, now = body.login.strip().lower(), time.monotonic()
        recent = [t for t in failures.get(key, []) if now - t < 900]
        if len(recent) >= 10:
            raise HTTPException(429, "Too many failed sign-ins. Try again in 15 minutes.")
        account = await directory.verify(body.login, body.password)
        if account is None:
            failures[key] = [*recent, now]
            raise HTTPException(401, "Wrong email or password.")
        failures.pop(key, None)
        return account.public()

    @app.get("/api/me")
    async def me(x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        """The signed-in user's account, when the user directory is on."""
        email = _user(x_pms_user)
        if directory is None or not email:
            return {"directory": directory is not None, "user": None}
        account = await directory.get_by_email(email)
        return {"directory": True, "user": account.public() if account and account.active else None}

    @app.get("/api/admin/users")
    async def list_users(_: User = Depends(admin)) -> dict[str, Any]:
        return {"users": [u.public() for u in await need_directory().list_users()]}

    @app.post("/api/admin/users", status_code=201)
    async def create_user(body: NewUser, _: User = Depends(admin)) -> dict[str, Any]:
        try:
            return (await need_directory().create(body.model_dump(exclude_none=True))).public()
        except UserError as e:
            raise user_error(e) from None

    @app.patch("/api/admin/users/{user_id}")
    async def update_user(user_id: int, body: UserFields, acting: User = Depends(admin)) -> dict[str, Any]:
        try:
            return (await need_directory().update(user_id, body.model_dump(exclude_unset=True), acting.email)).public()
        except UserError as e:
            raise user_error(e) from None

    @app.delete("/api/admin/users/{user_id}", status_code=204)
    async def delete_user(user_id: int, acting: User = Depends(admin)) -> None:
        try:
            await need_directory().delete(user_id, acting.email)
        except UserError as e:
            raise user_error(e) from None

    @app.get("/api/admin/hotels")
    async def list_hotels(_: User = Depends(admin)) -> dict[str, Any]:
        return {"hotels": await need_directory().list_hotels()}

    @app.patch("/api/admin/hotels/{hotel_id}")
    async def update_hotel(hotel_id: int, body: HotelIds, _: User = Depends(admin)) -> dict[str, Any]:
        try:
            return await need_directory().update_hotel(hotel_id, body.model_dump(exclude_none=True))
        except UserError as e:
            raise user_error(e) from None

    async def active_user(header: str | None, language: str) -> str | None:
        """With accounts on, only active users get answers; the database limits them to their hotels."""
        user = _user(header)
        if directory is not None:
            if user is None:
                raise HTTPException(401, MESSAGES[language]["sign_in"])
            account = await directory.get_by_email(user)
            if account is None or not account.active:
                raise HTTPException(403, MESSAGES[language]["no_account"])
        return user

    @app.get("/api/recommendations")
    async def recommendations(language: Literal["en", "es"] = Query(default="en"),
                              hotel: str | None = Query(default=None, pattern=HOTEL_CODE),
                              x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        """Today's three recommendations for the user's hotels, or one of them (made on the first
        request of the day), with the user's feedback on each."""
        user = await active_user(x_pms_user, language)
        try:
            result = await daily.get(user, language, hotel)
        except Exception:
            log.exception("recommendations failed")
            raise HTTPException(503, MESSAGES[language]["no_recommendations"]) from None
        prefix = f"{result['date']}:{result['hotel'] or 'ALL'}:"
        votes = store.feedback(user, "recommendation", prefix)
        # A vote (up or down) and "done" are kept apart: the vote under the item's ref, done under ref:done.
        items = [{**r, "ref": f"{prefix}{i}", "feedback": votes.get(f"{prefix}{i}"),
                  "done": votes.get(f"{prefix}{i}:done") == "done"}
                 for i, r in enumerate(result["recommendations"])]
        return {**result, "recommendations": items}

    @app.get("/api/overview")
    async def overview(hotel: str | None = Query(default=None, pattern=HOTEL_CODE),
                       x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        """The home screen's key figures for the user's hotels, or one of them."""
        user = await active_user(x_pms_user, "en")
        try:
            return await overviews.get(user, hotel)
        except Exception:
            log.exception("overview failed")
            raise HTTPException(503, "The key figures aren't available right now.") from None

    @app.get("/api/prefs")
    async def get_prefs(x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        """The signed-in user's settings: the daily email (available when SMTP is set up)."""
        user = await active_user(x_pms_user, "en")
        prefs = store.prefs(user) if user else {"digest": False, "language": "en", "hotel": None}
        return {"digest": prefs["digest"], "language": prefs["language"], "hotel": prefs["hotel"],
                "digest_available": digest.available and bool(user), "digest_time": settings.digest_time}

    @app.put("/api/prefs")
    async def put_prefs(body: Prefs, x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        user = await active_user(x_pms_user, body.language or "en")
        if not user:
            raise HTTPException(400, "Sign in to keep settings.")
        store.set_prefs(user, digest=body.digest, language=body.language,
                        hotel=body.hotel.upper() if body.hotel else None)
        return await get_prefs(x_pms_user)

    @app.post("/api/digest/test", status_code=204)
    async def digest_test(body: DigestTest, x_pms_user: str | None = Header(default=None)) -> None:
        """Sends the signed-in user today's email now, to check it arrives."""
        user = await active_user(x_pms_user, body.language)
        if not user or not digest.available:
            raise HTTPException(503, MESSAGES[body.language]["no_digest"])
        try:
            await digest.send_to(user, body.language, body.hotel)
        except Exception:
            log.exception("test email failed")
            raise HTTPException(502, MESSAGES[body.language]["digest_failed"]) from None

    @app.post("/api/feedback", status_code=204)
    async def feedback(body: Feedback, x_pms_user: str | None = Header(default=None)) -> None:
        """A thumbs up or down on an answer or a recommendation, or a recommendation marked done."""
        user = await active_user(x_pms_user, "en")
        store.set_feedback(user, body.kind, body.ref, body.value, body.note)

    @app.post("/api/chat")
    async def chat(req: ChatRequest, x_pms_user: str | None = Header(default=None)) -> StreamingResponse:
        user = await active_user(x_pms_user, req.language)
        try:
            conv = store.get_or_create(req.conversation_id, user)
        except LookupError:
            raise HTTPException(404, MESSAGES[req.language]["not_found"]) from None
        if conv.lock.locked():
            raise HTTPException(409, MESSAGES[req.language]["busy"])

        async def stream() -> AsyncIterator[str]:
            async with conv.lock:
                yield _sse("conversation", {"id": conv.id})
                events = []
                async for ev in agent.run_turn(conv, req.message, user, req.language, req.hotel):
                    events.append(ev)
                    yield _sse(ev["event"], ev["data"])
                # Only completed turns are kept, matching the history (failed turns are rolled back).
                if events and events[-1]["event"] == "done":
                    store.save_turn(conv, req.message, events)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/conversations")
    async def list_conversations(x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        return {"conversations": store.list(_user(x_pms_user))}

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        conv = store.load(conversation_id, _user(x_pms_user))
        if conv is None:
            raise HTTPException(404, "Conversation not found.")
        return conv

    @app.patch("/api/conversations/{conversation_id}")
    async def change_conversation(conversation_id: str, body: ConversationChange,
                                  x_pms_user: str | None = Header(default=None)) -> dict[str, Any]:
        """Renames or pins a conversation."""
        if not store.update(conversation_id, _user(x_pms_user), body.title, body.pinned):
            raise HTTPException(404, "Conversation not found.")
        return {"id": conversation_id}

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(conversation_id: str, x_pms_user: str | None = Header(default=None)) -> None:
        try:
            deleted = store.delete(conversation_id, _user(x_pms_user))
        except RuntimeError:
            raise HTTPException(409, "This conversation is answering a message; try again when it's done.") from None
        if not deleted:
            raise HTTPException(404, "Conversation not found.")

    return app
