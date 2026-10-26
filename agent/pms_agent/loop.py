"""The Claude tool-use loop: streams one chat turn and runs tool calls on the MCP server."""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from .config import Settings
from .conversations import Conversation
from .prompts import HOTEL_PROMPT, LANGUAGE_PROMPTS, MESSAGES, PERIOD_PROMPT, PERIODS, SYSTEM_PROMPT

log = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 60_000
PREVIEW_ROWS_FOR_UI = 50
MAX_JSON_RETRIES = 2
# Blocks a declining model produced before a mid-output fallback; they must not be echoed back.
DROP_BEFORE_FALLBACK = {"thinking", "redacted_thinking", "tool_use"}

Event = dict[str, Any]


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _event(kind: str, /, **data: Any) -> Event:
    return {"event": kind, "data": data}


def service_bearer(token: str, user: str | None) -> str:
    """The MCP service token, plus the signed-in website user it acts for (base64url email)."""
    if not user:
        return token
    return f"{token}:{base64.urlsafe_b64encode(user.encode()).decode().rstrip('=')}"


def _error_message(e: BaseException) -> str:
    while isinstance(e, BaseExceptionGroup) and len(e.exceptions) == 1:
        e = e.exceptions[0]
    if isinstance(e, anthropic.APIError):
        return f"Claude API error: {e.message}"
    if isinstance(e, TypeError) and "authentication" in str(e):
        return "No Anthropic credentials configured: set ANTHROPIC_API_KEY for the agent service."
    return f"{type(e).__name__}: {e}"


def echo_content(content: list[Any]) -> list[dict[str, Any]]:
    """Assistant content to append to history, as plain dicts.

    Everything is kept unchanged, except that after a mid-output fallback the declined
    model's thinking and tool_use blocks before the last `fallback` marker are dropped.
    """
    blocks = [b.model_dump(exclude_none=True) for b in content]
    boundary = max((i for i, b in enumerate(blocks) if b["type"] == "fallback"), default=-1)
    return [b for i, b in enumerate(blocks)
            if b["type"] != "fallback" and not (i < boundary and b["type"] in DROP_BEFORE_FALLBACK)]


def tool_definitions(mcp_tools) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.input_schema,
            # Stream tool inputs as generated; the MCP server validates them.
            "eager_input_streaming": True,
        }
        for t in mcp_tools
    ]


def _ui_result(structured: Any) -> Any:
    """Trim a tool's structured result for the browser (tables get a short preview)."""
    if isinstance(structured, dict) and isinstance(structured.get("rows"), list):
        return {**structured, "rows": structured["rows"][:PREVIEW_ROWS_FOR_UI]}
    return structured


class ChatAgent:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic, mcp_target: Any = None):
        self.settings = settings
        self.client = client
        # A URL, or an in-process MCPServer (tests).
        self.mcp_target = mcp_target or settings.mcp_url

    def _mcp(self, user: str | None = None) -> Client:
        target = self.mcp_target
        if isinstance(target, str) and self.settings.mcp_token:
            http = create_mcp_http_client(headers={"Authorization": f"Bearer {service_bearer(self.settings.mcp_token, user)}"})
            target = streamable_http_client(target, http_client=http)
        return Client(target)

    def _request(self, system: str, tools: list[dict], messages: list[dict]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.settings.effort},
            "cache_control": {"type": "ephemeral"},
        }
        # Haiku models have no server-side refusal fallback; the parameter would be rejected.
        if self.settings.server_fallbacks and not self.settings.model.startswith("claude-haiku"):
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        return params

    async def run_turn(self, conv: Conversation, user_text: str, user: str | None = None,
                       language: str = "en", hotel: str | None = None,
                       period: str | None = None) -> AsyncIterator[Event]:
        """Run one user turn, yielding UI events. The caller must hold conv.lock.

        History is only kept when the turn completes; on refusal, error or disconnect it is
        rolled back to where the turn started (only the tail is removed, never earlier turns).
        """
        start = len(conv.messages)
        conv.messages.append({"role": "user", "content": user_text})
        completed = False
        try:
            async with self._mcp(user) as mcp:
                # Errors are caught inside the client's context: raised through it they
                # would arrive wrapped in an ExceptionGroup by its task group.
                try:
                    tools = tool_definitions((await mcp.list_tools()).tools)
                    system = (SYSTEM_PROMPT + LANGUAGE_PROMPTS[language]
                              + ("\n" + mcp.instructions if mcp.instructions else "")
                              + (HOTEL_PROMPT.format(hotel=hotel.upper()) if hotel else "")
                              + (PERIOD_PROMPT.format(period=PERIODS.get(period, period)) if period else ""))
                    async for event in self._loop(conv, mcp, system, tools, MESSAGES[language]):
                        if event["event"] == "done":
                            completed = True
                        yield event
                except Exception as e:
                    log.exception("turn failed")
                    yield _event("error", message=_error_message(e))
        except Exception as e:  # could not connect to the MCP server
            log.exception("MCP connection failed")
            yield _event("error", message=MESSAGES[language]["unreachable"].format(error=_error_message(e)))
        finally:
            if not completed:
                del conv.messages[start:]

    async def _loop(self, conv: Conversation, mcp: Client, system: str, tools: list[dict],
                    text: dict[str, str]) -> AsyncIterator[Event]:
        json_retries = 0
        step = 0
        # Usage summed over every API request in the turn (the done event reports the turn).
        totals = dict.fromkeys(USAGE_FIELDS, 0)
        requests = 0
        while step < self.settings.max_tool_steps:
            try:
                async with self.client.beta.messages.stream(**self._request(system, tools, conv.messages)) as stream:
                    async for ev in stream:
                        if ev.type == "text":
                            yield _event("text", text=ev.text)
                        elif ev.type == "thinking":
                            yield _event("thinking", text=ev.thinking)
                        elif ev.type == "content_block_start" and ev.content_block.type == "tool_use":
                            yield _event("tool_start", id=ev.content_block.id, name=ev.content_block.name)
                    message = await stream.get_final_message()
                json_retries = 0
                requests += 1
                for f in USAGE_FIELDS:
                    totals[f] += getattr(message.usage, f, None) or 0
            except ValueError:
                # Tool input the SDK could not parse at all (eager input streaming). There is no
                # complete tool_use block to answer, so re-issue the request.
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise
                yield _event("retry", reason="unparseable tool input")
                continue

            if message.stop_reason == "refusal":
                details = getattr(message, "stop_details", None)
                yield _event("refusal", category=getattr(details, "category", None),
                             message=text["refusal"])
                return

            content = echo_content(message.content)
            conv.messages.append({"role": "assistant", "content": content})
            if message.stop_reason == "pause_turn":
                continue

            tool_uses = [b for b in content if b["type"] == "tool_use"]
            if not tool_uses:
                yield _event("done", stop_reason=message.stop_reason, usage=totals, requests=requests,
                             model=getattr(message, "model", None) or self.settings.model)
                return
            if message.stop_reason == "max_tokens":
                # A truncated tool input can parse as a valid partial object; don't run it.
                yield _event("error", message=text["max_tokens"], usage=totals, requests=requests)
                return

            for b in tool_uses:
                yield _event("tool_call", id=b["id"], name=b["name"], input=b["input"])
            results = await asyncio.gather(*(self._call_tool(mcp, b) for b in tool_uses))
            for b, (result, ui) in zip(tool_uses, results):
                yield _event("tool_result", id=b["id"], name=b["name"], is_error=result.get("is_error", False),
                             result=ui)
            # All results for one assistant turn go back in a single user message.
            conv.messages.append({"role": "user", "content": [r for r, _ in results]})
            step += 1

        # The turn failed, but its requests were billed: report them like done does.
        yield _event("error", message=text["max_steps"].format(steps=self.settings.max_tool_steps),
                     usage=totals, requests=requests)

    async def _call_tool(self, mcp: Client, block: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        args = block["input"]
        if not isinstance(args, dict):
            text = json.dumps({"INVALID_JSON": json.dumps(args)})
            return {"type": "tool_result", "tool_use_id": block["id"], "is_error": True, "content": text}, text
        result = await mcp.call_tool(block["name"], args)
        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "\n[truncated: request fewer preview rows or aggregate more]"
        tool_result = {"type": "tool_result", "tool_use_id": block["id"], "content": text}
        if result.is_error:
            tool_result["is_error"] = True
        ui = text if result.is_error or result.structured_content is None else _ui_result(result.structured_content)
        return tool_result, ui
