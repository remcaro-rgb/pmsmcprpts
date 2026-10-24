"""The day's recommendations on the chat's welcome screen: Claude reads the data with the read-only
tools and hands back the three actions most worth taking, for the hotels the user can see."""

import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .loop import ChatAgent, echo_content, tool_definitions
from .prompts import LANGUAGE_PROMPTS, RECOMMEND_ASK, RECOMMEND_PROMPT, SYSTEM_PROMPT

log = logging.getLogger(__name__)

COUNT = 3
# Tools that only read; the documents and charts aren't needed here.
DATA_TOOLS = {"describe_schema", "run_sql", "get_kpis", "get_dataset"}
SUBMIT = "give_recommendations"
SUBMIT_TOOL = {
    "name": SUBMIT,
    "description": f"Hand back the {COUNT} recommendations, most valuable first. Call it once, at the end.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "The action, in a few words."},
                        "detail": {"type": "string",
                                   "description": "One or two sentences: the evidence (with figures) and the expected effect."},
                        "hotel": {"type": "string", "description": "The hotel's name, or empty for all of them."},
                        "question": {"type": "string",
                                     "description": "A follow-up question the user can ask to see the analysis."},
                    },
                    "required": ["title", "detail", "hotel", "question"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["recommendations"],
        "additionalProperties": False,
    },
}
FIELDS = {"title": 120, "detail": 600, "hotel": 120, "question": 300}


class RecommendationError(RuntimeError):
    pass


def clean(raw: Any) -> list[dict[str, str]]:
    """The first COUNT well-formed recommendations, with lengths capped."""
    items = raw.get("recommendations") if isinstance(raw, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("title") or "").strip():
            out.append({k: str(item.get(k) or "").strip()[:n] for k, n in FIELDS.items()})
    if not out:
        raise RecommendationError("No recommendations came back.")
    return out[:COUNT]


async def recommend(agent: ChatAgent, user: str | None, language: str) -> list[dict[str, str]]:
    """Ask Claude for today's recommendations, as the signed-in user (the database limits the hotels)."""
    async with agent._mcp(user) as mcp:
        tools = [t for t in tool_definitions((await mcp.list_tools()).tools) if t["name"] in DATA_TOOLS]
        system = (SYSTEM_PROMPT + LANGUAGE_PROMPTS[language]
                  + ("\n" + mcp.instructions if mcp.instructions else "") + RECOMMEND_PROMPT)
        messages: list[dict[str, Any]] = [{"role": "user", "content": RECOMMEND_ASK[language]}]
        for _ in range(agent.settings.max_tool_steps):
            async with agent.client.beta.messages.stream(
                    **agent._request(system, [*tools, SUBMIT_TOOL], messages)) as stream:
                message = await stream.get_final_message()
            if message.stop_reason == "refusal":
                raise RecommendationError("The model declined.")
            content = echo_content(message.content)
            messages.append({"role": "assistant", "content": content})
            if message.stop_reason == "pause_turn":
                continue
            uses = [b for b in content if b["type"] == "tool_use"]
            submitted = next((b for b in uses if b["name"] == SUBMIT), None)
            if submitted is not None:
                return clean(submitted["input"])
            if not uses:
                messages.append({"role": "user", "content": f"Hand them back with {SUBMIT}."})
                continue
            results = await asyncio.gather(*(agent._call_tool(mcp, b) for b in uses))
            messages.append({"role": "user", "content": [r for r, _ in results]})
    raise RecommendationError("Too many steps.")


class DailyRecommendations:
    """Recommendations made once a day per user and language (the data changes overnight)."""

    def __init__(self, agent: ChatAgent, timezone: str):
        self.agent = agent
        try:
            self.zone = ZoneInfo(timezone)
        except Exception:
            log.warning("unknown PMS_TIMEZONE %r, using UTC", timezone)
            self.zone = ZoneInfo("UTC")
        self.cache: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        self.locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    async def get(self, user: str | None, language: str) -> dict[str, Any]:
        day = datetime.now(self.zone).date().isoformat()
        key = (user or "", language, day)
        async with self.locks.setdefault(key, asyncio.Lock()):
            if key not in self.cache:
                items = await recommend(self.agent, user, language)
                # Keep only today's.
                for old in [k for k in self.cache if k[2] != day]:
                    del self.cache[old]
                    self.locks.pop(old, None)
                self.cache[key] = items
        return {"date": day, "recommendations": self.cache[key]}
