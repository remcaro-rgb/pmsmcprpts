"""In-memory conversation store (demo scope; history is lost on restart)."""

import asyncio
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Conversation:
    id: str
    owner: str | None = None  # signed-in website user; None when sign-in is off
    # Messages API history. Append-only: earlier turns are never edited, which keeps the
    # prompt cache warm and keeps replayed thinking blocks valid.
    messages: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConversationStore:
    def __init__(self, max_conversations: int = 500):
        self.max_conversations = max_conversations
        self._items: OrderedDict[str, Conversation] = OrderedDict()

    def get_or_create(self, conversation_id: str | None, owner: str | None = None) -> Conversation:
        """Raises LookupError for another user's conversation."""
        if conversation_id and conversation_id in self._items:
            conv = self._items[conversation_id]
            if conv.owner != owner:
                raise LookupError(conversation_id)
            self._items.move_to_end(conversation_id)
            return conv
        conv = Conversation(conversation_id or f"conv_{secrets.token_hex(8)}", owner)
        self._items[conv.id] = conv
        while len(self._items) > self.max_conversations:
            self._items.popitem(last=False)
        return conv
