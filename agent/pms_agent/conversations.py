"""In-memory conversation store (demo scope; history is lost on restart)."""

import asyncio
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Conversation:
    id: str
    # Messages API history. Append-only: earlier turns are never edited, which keeps the
    # prompt cache warm and keeps replayed thinking blocks valid.
    messages: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConversationStore:
    def __init__(self, max_conversations: int = 500):
        self.max_conversations = max_conversations
        self._items: OrderedDict[str, Conversation] = OrderedDict()

    def get_or_create(self, conversation_id: str | None) -> Conversation:
        if conversation_id and conversation_id in self._items:
            self._items.move_to_end(conversation_id)
            return self._items[conversation_id]
        conv = Conversation(conversation_id or f"conv_{secrets.token_hex(8)}")
        self._items[conv.id] = conv
        while len(self._items) > self.max_conversations:
            self._items.popitem(last=False)
        return conv
