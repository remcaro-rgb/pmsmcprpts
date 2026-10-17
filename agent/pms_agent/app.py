"""FastAPI service: POST /api/chat streams a Claude answer as server-sent events."""

import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .conversations import ConversationStore
from .loop import ChatAgent


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=64)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def create_app(settings: Settings | None = None, client: Any = None, mcp_target: Any = None) -> FastAPI:
    settings = settings or Settings()
    agent = ChatAgent(settings, client or anthropic.AsyncAnthropic(), mcp_target)
    store = ConversationStore()

    app = FastAPI(title="PMS Reports agent")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": settings.model}

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        conv = store.get_or_create(req.conversation_id)
        if conv.lock.locked():
            raise HTTPException(409, "This conversation is already answering a message.")

        async def stream() -> AsyncIterator[str]:
            async with conv.lock:
                yield _sse("conversation", {"id": conv.id})
                async for ev in agent.run_turn(conv, req.message):
                    yield _sse(ev["event"], ev["data"])

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
