"""The day's recommendations on the chat's welcome screen: Claude reads the data with the read-only
tools and hands back the three actions most worth taking, for the hotels the user can see."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .conversations import ConversationStore
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
                        "impact": {"type": "string",
                                   "description": "What's at stake, in a few words with a figure, e.g. "
                                                  "\"+COP 9.8 M estimated\" or \"-18 pp vs 2025\"."},
                        "kind": {"type": "string", "enum": ["money", "risk", "info"],
                                 "description": "money: an opportunity to earn more; risk: a loss to prevent; "
                                                "info: anything else."},
                    },
                    "required": ["title", "detail", "hotel", "question", "impact", "kind"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["recommendations"],
        "additionalProperties": False,
    },
}
FIELDS = {"title": 120, "detail": 600, "hotel": 120, "question": 300, "impact": 60, "kind": 10}
KINDS = {"money", "risk", "info"}


class RecommendationError(RuntimeError):
    pass


def clean(raw: Any) -> list[dict[str, str]]:
    """The first COUNT well-formed recommendations, with lengths capped."""
    items = raw.get("recommendations") if isinstance(raw, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("title") or "").strip():
            rec = {k: str(item.get(k) or "").strip()[:n] for k, n in FIELDS.items()}
            rec["kind"] = rec["kind"] if rec["kind"] in KINDS else "info"
            out.append(rec)
    if not out:
        raise RecommendationError("No recommendations came back.")
    return out[:COUNT]


async def recommend(agent: ChatAgent, user: str | None, language: str,
                    hotel: str | None = None) -> list[dict[str, str]]:
    """Ask Claude for today's recommendations, as the signed-in user (the database limits the hotels);
    with `hotel` (a code), for that hotel only."""
    async with agent._mcp(user) as mcp:
        tools = [t for t in tool_definitions((await mcp.list_tools()).tools) if t["name"] in DATA_TOOLS]
        system = (SYSTEM_PROMPT + LANGUAGE_PROMPTS[language]
                  + ("\n" + mcp.instructions if mcp.instructions else "") + RECOMMEND_PROMPT)
        ask = RECOMMEND_ASK[language] + (f" (hotel {hotel})" if hotel else "")
        messages: list[dict[str, Any]] = [{"role": "user", "content": ask}]
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
    """Recommendations made once a day per user, language and hotel (the data changes overnight),
    kept in the agent's database; `prepare` makes them early for the people who use them."""

    def __init__(self, agent: ChatAgent, timezone: str, store: ConversationStore | None = None):
        self.agent = agent
        self.store = store
        try:
            self.zone = ZoneInfo(timezone)
        except Exception:
            log.warning("unknown PMS_TIMEZONE %r, using UTC", timezone)
            self.zone = ZoneInfo("UTC")
        # (user, language, hotel, day) -> (recommendations, when they were made)
        self.cache: dict[tuple[str, str, str, str], tuple[list[dict[str, str]], str]] = {}
        self.locks: dict[tuple[str, str, str, str], asyncio.Lock] = {}

    async def get(self, user: str | None, language: str, hotel: str | None = None,
                  reader: bool = True) -> dict[str, Any]:
        """Today's, made now if nobody has yet; `reader` records who looked, for `prepare`."""
        now = datetime.now(self.zone)
        day = now.date().isoformat()
        key = (user or "", language, (hotel or "").upper(), day)
        if reader and self.store:
            self.store.saw_recommendations(*key[:3])
        async with self.locks.setdefault(key, asyncio.Lock()):
            if key not in self.cache and self.store and (saved := self.store.load_recommendations(*key)):
                self.cache[key] = saved
            if key not in self.cache:
                items = await recommend(self.agent, user, language, hotel)
                made = datetime.now(self.zone).isoformat(timespec="minutes")
                # Keep only today's.
                for old in [k for k in self.cache if k[3] != day]:
                    del self.cache[old]
                    self.locks.pop(old, None)
                self.cache[key] = (items, made)
                if self.store:
                    self.store.save_recommendations(*key, made, items)
        items, made = self.cache[key]
        return {"date": day, "hotel": key[2] or None, "generated_at": made, "recommendations": items}

    async def prepare(self) -> int:
        """Makes today's for everyone who looked at them in the last two weeks, one at a time."""
        made = 0
        for owner, language, hotel in self.store.recommendation_readers() if self.store else []:
            try:
                await self.get(owner or None, language, hotel or None, reader=False)
                made += 1
            except Exception:
                log.exception("preparing recommendations for %s failed", owner or "(no sign-in)")
        return made


class Overviews:
    """The home screen's key figures (the MCP server's get_overview), kept a few minutes per user."""

    TTL = 300.0

    def __init__(self, agent: ChatAgent):
        self.agent = agent
        self.cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    async def get(self, user: str | None, hotel: str | None = None) -> dict[str, Any]:
        key = (user or "", (hotel or "").upper())
        hit = self.cache.get(key)
        if hit and time.monotonic() - hit[0] < self.TTL:
            return hit[1]
        async with self.agent._mcp(user) as mcp:
            result = await mcp.call_tool("get_overview", {"hotel": hotel} if hotel else {})
        if result.is_error or result.structured_content is None:
            text = "".join(getattr(c, "text", "") for c in result.content)
            raise RecommendationError(text or "No key figures came back.")
        if len(self.cache) > 500:
            self.cache.clear()
        self.cache[key] = (time.monotonic(), result.structured_content)
        return result.structured_content
